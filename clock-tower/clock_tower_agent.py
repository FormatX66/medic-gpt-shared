#!/usr/bin/env python3
"""CLOCK TOWER AGENT — one unified poller for every Medic/Rivet lane (Bruce 2026-10-14:
"combine clocktower and stepping poll. And whatever other polls we have running.
Make it all work.")

One resident daemon, one state file, one event queue. Lanes:
  doc        COMMS LOG stepping poll (Bruce's two-part spec) + ack + Board pointer
  board      Board of Directors new-entry watch (relay stays with board-watch cron)
  mq         MQ poll + ack-on-sight
  repos      shared + private repo outbox packet watch (git fetch + tree diff)
  bus        laptop bus rivet-to-medic.jsonl + heartbeat checks
  mail       medic@ email bridge poll
  queue      crew-queue ETA watchdog (report-once per missed item — v2 fix built in)
  keepawake  laptop / Pi / Hub / MQ liveness (transition-only alerts)
  awaiting   work-stall vs delivery-failure checks (15m scripts)
  tower      ALL-LANE quiet detection: a knock only when EVERY Rivet lane has
             been quiet past threshold — the tower finally sees all the places.
             Detection + report only; no wake actuation (Bruce's freeze stands).

Events -> hidden_files/clock-tower-events.jsonl (drained to Bruce by the 2m cron).
State  -> hidden_files/clock-tower-state.json (daemon-owned).
Run: nohup python3 crew_pulse.py >> hidden_files/clock-tower.log 2>&1 &
     python3 crew_pulse.py --once   (run every lane once, print results, exit)
"""
import base64, json, os, re, subprocess, sys, time
from datetime import datetime
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
HID = os.path.normpath(os.path.join(HERE, "..", "hidden_files"))
STATE_F = os.path.join(HID, "clock-tower-state.json")
EVENTS_F = os.path.join(HID, "clock-tower-events.jsonl")
EXPECT_F = os.path.join(HID, "comms-log-expect.json")
DOC_ID = "1gHVGrWSbuWGPNca8-lO8K9hAWv6gBesRmapOCoi-fP8"
GWS = "/opt/hatch/bin/hatch_gws_cli"
MQ_URL = "https://madmorrigan.com/prymortal-api/api.php?action=mq"
BOARD_URL = "https://madmorrigan.com/prymortal-api/api.php?action=board"
ET = ZoneInfo("America/New_York")
LADDER = [20, 30, 60, 180, 300, 600]
sys.path.insert(0, HERE)
import comms_log_watch as W

SHARED_CLONE = os.path.join(ROOT, "shared", "medic-gpt-shared")
PRIVATE_CLONE = os.path.join(ROOT, "private", "poetry-project-9th-grade")


def now():
    return int(time.time())


def log(msg):
    print("[%s] %s" % (datetime.now(ET).strftime("%H:%M:%S"), msg), flush=True)


def emit(kind, **kw):
    ev = {"ts": now(), "kind": kind}
    ev.update(kw)
    with open(EVENTS_F, "a") as f:
        f.write(json.dumps(ev) + "\n")
    log("event %s %s" % (kind, {k: v for k, v in kw.items() if k != 'entries'}))


def load_state():
    if os.path.exists(STATE_F):
        return json.load(open(STATE_F))
    return {"lanes": {}, "rivet_activity": {}, "tower": {"reported": False, "boot": now()},
            "mq_next_seq": 0, "reported_missed": [], "down": {}, "doc": {}}


def save_state(s):
    json.dump(s, open(STATE_F, "w"), indent=1)


def touch_rivet(state, lane):
    state.setdefault("rivet_activity", {})[lane] = now()
    if state.get("tower", {}).get("reported"):
        state["tower"]["reported"] = False
        log("tower re-armed (rivet active on %s)" % lane)


def sh(args, timeout=60, cwd=None):
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    return r.returncode, r.stdout, r.stderr


# ---------------- doc lane (stepping) ----------------

def board_pointer(topics):
    try:
        key = open(os.path.expanduser("~/.config/board/medic-key")).read().strip()
        body = {"key": key, "kind": "work-status",
                "body": {"msg": "COMMS LOG: new Rivet entry picked up + acked in-doc (%s)." % topics,
                         "ref": "comms-log"}}
        p = os.path.join(HID, ".boardpost.tmp.json")
        open(p, "w").write(json.dumps(body))
        rc, out, _ = sh(["curl", "-sS", "--max-time", "30", "-X", "POST", BOARD_URL,
                         "-H", "Content-Type: application/json", "-d", "@" + p], timeout=45)
        os.remove(p)
        return '"ok":true' in out.replace(" ", "")
    except Exception as e:
        log("board pointer failed: %s" % e)
        return False


def doc_poll(state):
    """Returns new RIVET entries; handles ack/pointer/event itself."""
    dstate_f = os.path.join(HID, "comms-log-watch-state.json")
    ds = json.load(open(dstate_f)) if os.path.exists(dstate_f) else {"seen": [], "last_modified": None}
    mod = W.doc_modified()
    if mod == ds.get("last_modified"):
        return []
    entries = W.doc_entries()
    seen = set(ds.get("seen", []))
    new = [e for e in entries if (e["ts"] + "|" + e["author"] + "|" + e["topic"]) not in seen]
    ds["seen"] = [e["ts"] + "|" + e["author"] + "|" + e["topic"] for e in entries]
    ds["last_modified"] = mod
    json.dump(ds, open(dstate_f, "w"), indent=1)
    rivet = [e for e in new if e["author"] != "MEDIC"]
    if rivet:
        touch_rivet(state, "doc")
        now_edt = datetime.now(ET).strftime("%Y-%m-%d %H:%M EDT")
        lines = ["\n---\n[%s] MEDIC - ack" % now_edt]
        for e in rivet:
            m = re.search(r"Entry ID:\s*(\S+)", e["text"])
            lines.append("Picked up new RIVET entry: Entry ID %s" % m.group(1) if m
                         else "Picked up new RIVET entry: [%s] %s - %s" % (e["ts"], e["author"], e["topic"]))
        rc, _, err = sh([GWS, "docs", "+write", "--document", DOC_ID, "--text", "\n".join(lines)])
        board_pointer("; ".join(e["topic"] for e in rivet))
        emit("DOC_NEW", entries=[{"ts": e["ts"], "author": e["author"], "topic": e["topic"],
                                  "text": e["text"]} for e in rivet], ack_ok=(rc == 0))
    return rivet


def doc_next_wait(state, exp):
    """Doc lane pinned at 20s flat (Bruce 2026-10-14 09:08 EDT): the cheap
    read-only lanes (doc gate, Board, MQ) poll at 20s indefinitely; the
    stepping ladder / ETA-relative checks no longer add anything at that
    cadence and are retired for this lane. Stepping remains for the rest."""
    return 20, ("ladder", 0)


# ---------------- board lane ----------------

def board_poll(state):
    rc, out, _ = sh(["curl", "-sS", "--max-time", "30", BOARD_URL + "&format=json"], timeout=45)
    if rc != 0:
        raise RuntimeError("board GET failed")
    entries = json.loads(out).get("entries", [])
    sf = os.path.join(HID, "board-watch-state.json")
    bs = json.load(open(sf)) if os.path.exists(sf) else {"seen": [], "rivet_receipted": True}
    seen = set(bs.get("seen", []))
    new = []
    for e in entries:
        k = "%s:%s:%s" % (e.get("ts"), e.get("agent"), e.get("kind"))
        if k not in seen:
            seen.add(k)
            new.append(e)
    bs["seen"] = sorted(seen)
    json.dump(bs, open(sf, "w"), indent=1)
    for e in new:
        if e.get("agent") == "rivet":
            touch_rivet(state, "board")
        if e.get("agent") != "medic":
            body = e.get("body") or {}
            emit("BOARD_ENTRY", agent=e.get("agent"), kind=e.get("kind"),
                 msg=str(body.get("msg", ""))[:400], ref=str(body.get("ref", ""))[:120])
    return len(new)


# ---------------- mq lane ----------------

def mq_call(op_fields, token):
    body = json.dumps(op_fields)
    rc, out, _ = sh(["curl", "-sS", "--max-time", "30", "-X", "POST", MQ_URL,
                     "-H", "Content-Type: application/json",
                     "-H", "Authorization: Bearer " + token, "-d", body], timeout=45)
    try:
        return json.loads(out)
    except Exception:
        return {}


def mq_poll(state):
    tokens = json.load(open(os.path.expanduser("~/.config/mq/production-tokens.json")))
    token = tokens["medic"]
    if not state.get("mq_init"):
        r = mq_call({"op": "poll", "since_seq": 0, "limit": 1}, token)
        if r.get("next_seq") is not None:
            state["mq_next_seq"] = r["next_seq"]
        state["mq_init"] = True
        log("mq lane initialized at next_seq=%s (history not replayed)" % state.get("mq_next_seq"))
        return 0
    r = mq_call({"op": "poll", "since_seq": state.get("mq_next_seq", 0), "limit": 50}, token)
    msgs = r.get("messages", [])
    if r.get("next_seq") is not None:
        state["mq_next_seq"] = r["next_seq"]
    for m in msgs:
        if m.get("sender") == "rivet":
            touch_rivet(state, "mq")
        emit("MQ_MSG", sender=m.get("sender"), type=m.get("type"), key=m.get("key"),
             id=m.get("id"), seq=m.get("seq"),
             payload=str(m.get("payload"))[:400])
        try:
            mq_call({"op": "ack", "id": m.get("id")}, token)
        except Exception as e:
            log("mq ack failed for %s: %s" % (m.get("id"), e))
    return len(msgs)


# ---------------- repo lanes ----------------

def repo_api_poll(state, name, repo, outbox_prefix):
    """Private repo has no local clone — watch its outbox via the Contents API."""
    key = "repoapi_" + name
    if key not in state:
        sf = os.path.join(HID, "private-mailbox-watch-state.json")
        seed = []
        if os.path.exists(sf):
            seed = json.load(open(sf)).get("seen_outbox", [])
        state[key] = seed
        log("repo %s: seeded %d known outbox files" % (name, len(seed)))
        return 0
    token = open(os.path.expanduser("~/.config/github/token")).read().strip()
    rc, out, _ = sh(["curl", "-sS", "--max-time", "30",
                     "https://api.github.com/repos/%s/contents/%s" % (repo, outbox_prefix.rstrip("/")),
                     "-H", "Authorization: token " + token,
                     "-H", "Accept: application/vnd.github+json"], timeout=45)
    try:
        names = [e["name"] for e in json.loads(out) if isinstance(e, dict) and e.get("type") == "file"]
    except Exception:
        log("repo %s: API list failed" % name)
        return 0
    seen = set(state[key])
    new = [n for n in names if n not in seen]
    for n in new:
        touch_rivet(state, "repo-" + name)
        emit("REPO_PACKET", repo=name, file=outbox_prefix + n)
    state[key] = sorted(seen | set(names))
    return len(new)



def repo_poll(state, name, clone, outbox_prefix):
    if not os.path.isdir(os.path.join(clone, ".git")):
        log("repo %s: clone missing at %s — lane skipped" % (name, clone))
        return 0
    sh(["git", "fetch", "origin", "main"], timeout=90, cwd=clone)
    key = "repo_" + name
    prev = state.get(key)
    rc, head, _ = sh(["git", "rev-parse", "origin/main"], cwd=clone)
    head = head.strip()
    if prev is None:
        state[key] = head
        return 0
    if prev == head:
        return 0
    rc, out, _ = sh(["git", "diff", "--name-only", prev, head], cwd=clone)
    state[key] = head
    new_files = [f for f in out.splitlines() if f.startswith(outbox_prefix)]
    for f in new_files:
        touch_rivet(state, "repo-" + name)
        emit("REPO_PACKET", repo=name, file=f)
    return len(new_files)


# ---------------- sftp helpers (laptop bus / keepawake) ----------------

def proxy_cmd():
    hp = os.environ.get("HTTPS_PROXY", "")
    base = hp.split("@")[-1]           # host:port of egress proxy
    auth = hp.replace("http://", "").split("@")[0]
    host = base.split(":")[0]
    return "socat - PROXY:%s:100.89.69.54:22,proxyport=3130,proxyauth=%s" % (host, auth)


def sftp_get(remote, local):
    batch = os.path.join(HID, ".sftp.batch")
    open(batch, "w").write("get %s %s\n" % (remote, local))
    rc, _, err = sh(["sftp", "-b", batch, "-o", "StrictHostKeyChecking=no",
                     "-o", "ProxyCommand=" + proxy_cmd(), "-i",
                     os.path.expanduser("~/.ssh/id_ed25519"), "bruce@100.89.69.54"], timeout=60)
    os.remove(batch)
    return rc == 0 and os.path.exists(local)


def sftp_put(local, remote):
    batch = os.path.join(HID, ".sftp.batch")
    open(batch, "w").write("put %s %s\n" % (local, remote))
    rc, _, _ = sh(["sftp", "-b", batch, "-o", "StrictHostKeyChecking=no",
                   "-o", "ProxyCommand=" + proxy_cmd(), "-i",
                   os.path.expanduser("~/.ssh/id_ed25519"), "bruce@100.89.69.54"], timeout=60)
    os.remove(batch)
    return rc == 0


def bus_poll(state):
    tmp = os.path.join(HID, ".bus-inbox.jsonl")
    if not sftp_get("/C:/Users/bruce/memscan/bus/rivet-to-medic.jsonl", tmp):
        return 0
    data = open(tmp, "rb").read()
    prev = state.get("bus_seen_bytes", 447)
    n = 0
    if len(data) > prev:
        for line in data[prev:].decode("utf-8", "replace").splitlines():
            if line.strip():
                touch_rivet(state, "bus")
                emit("BUS_MAIL", line=line[:500])
                n += 1
        state["bus_seen_bytes"] = len(data)
    return n


def keepawake_poll(state):
    down = state.setdefault("down", {})
    def alert(name, is_down, msg):
        if is_down and not down.get(name):
            down[name] = True
            emit("LANE_DOWN", lane=name, msg=msg)
        elif not is_down:
            down[name] = False
    # medic heartbeat refresh
    hb = os.path.join(HID, ".hb-medic.json")
    open(hb, "w").write(json.dumps({"ts": now(), "agent": "medic", "state": "live", "via": "clock-tower"}))
    sftp_put(hb, "/C:/Users/bruce/memscan/bus/heartbeat-medic.json")
    # laptop heartbeat freshness
    tmp = os.path.join(HID, ".hb-laptop.json")
    ok = sftp_get("/C:/Users/bruce/memscan/bus/laptop-heartbeat.json", tmp)
    fresh = False
    if ok:
        try:
            fresh = now() - int(json.load(open(tmp)).get("ts", 0)) < 720
        except Exception:
            fresh = False
    alert("laptop", not fresh, "laptop heartbeat stale — laptop may be asleep or offline")
    # MQ health (unauthenticated op) — one confirm-retry; the host is flaky
    def mq_ok():
        rc, out, _ = sh(["curl", "-sS", "--max-time", "15", "-X", "POST", MQ_URL,
                         "-H", "Content-Type: application/json", "-d", '{"op":"health"}'], timeout=30)
        return '"ok":true' in out.replace(" ", "")
    mq_healthy = mq_ok()
    if not mq_healthy:
        time.sleep(20)
        mq_healthy = mq_ok()
    alert("mq", not mq_healthy, "MQ health check FAILED")
    if fresh:
        # Pi heartbeat via laptop route
        rc, out, _ = sh(["timeout", "40", os.path.join(ROOT, "ssh-pi.sh"),
                         "cat ~/crew/state/heartbeat-pi.json"], timeout=60)
        pi_fresh = False
        try:
            pi_fresh = now() - int(json.loads(out).get("ts", 0)) < 720
        except Exception:
            pi_fresh = False
        alert("pi", not pi_fresh, "BBPI4 heartbeat stale — Pi may be down or unreachable")
        # Hub probe (laptop-side key; EncodedCommand pattern)
        ps = ("$k=(Get-Content 'C:\\Users\\bruce\\MedicHub\\hub\\.env' | "
              "Where-Object {$_ -match '^HUB_API_KEY='} | ForEach-Object {$_.Split('=',2)[1]}); "
              "$o = curl.exe -s -m 6 -w \"`nHTTP:%{http_code}\" -H \"Authorization: Bearer $k\" "
              "http://127.0.0.1:8090/health; "
              "if ($o -match 'HTTP:200' -and $o -match '\"ok\": true') { 'HUB_OK' } else { 'HUB_FAIL ' + $o }")
        enc = base64.b64encode(ps.encode("utf-16le")).decode()
        rc, out, _ = sh([os.path.join(ROOT, "ssh-laptop.sh"),
                         "powershell -NoProfile -EncodedCommand " + enc], timeout=60)
        if "HUB_OK" in out:
            alert("hub", False, "")
        elif "HTTP:000" in out or "HUB_FAIL" in out:
            time.sleep(30)
            rc, out, _ = sh([os.path.join(ROOT, "ssh-laptop.sh"),
                             "powershell -NoProfile -EncodedCommand " + enc], timeout=60)
            alert("hub", "HUB_OK" not in out, "Model Hub health check FAILED on the laptop")
        elif "401" in out:
            log("hub probe broken (401) — probe fault, not Hub")
    return 0


# ---------------- mail / queue / awaiting lanes ----------------

def mail_poll(state):
    rc, out, err = sh(["python3", os.path.join(ROOT, "email-bridge", "mail_poll.py"), "--once"],
                      timeout=120)
    if rc != 0:
        log("mail poll failed rc=%d (transient pattern known)" % rc)
        return 0
    for line in out.splitlines():
        if line.strip().startswith(("NEW", "MAIL", "FROM")) or "rivet@arkmatx.com" in line:
            emit("MAIL", line=line[:400])
    return 0


def queue_poll(state):
    rc, out, _ = sh(["python3", os.path.join(HERE, "crew_queue.py")], timeout=60)
    try:
        d = json.loads(out.strip().splitlines()[-1])
    except Exception:
        log("crew_queue unparseable: %s" % out[:120])
        return 0
    missed = d.get("missed", []) if isinstance(d, dict) else []
    ids = [m.get("id") for m in missed if isinstance(m, dict)]
    reported = set(state.get("reported_missed", []))
    for m in missed:
        if isinstance(m, dict) and m.get("id") not in reported:
            emit("ETA_MISSED", id=m.get("id"), title=m.get("title"), owner=m.get("owner"),
                 late_s=m.get("late_s"))
            reported.add(m.get("id"))
    state["reported_missed"] = sorted(reported & set(ids)) if ids else []
    return len(ids)


def awaiting_poll(state):
    for script in ("check-awaiting-reply.py", "check-inbound-delivery.py"):
        rc, out, _ = sh(["python3", os.path.join(HID, script)], timeout=120)
        for line in out.splitlines():
            if line.startswith("ESCALATE"):
                emit("WORK_STALL", line=line[:400])
            elif line.startswith("DELIVERY_FAIL"):
                emit("DELIVERY_FAIL", line=line[:400])
    return 0


# ---------------- tower (all-lane quiet) ----------------

TOWER_THRESHOLD = 1800

def tower_eval(state):
    t = state.setdefault("tower", {"reported": False, "boot": now()})
    act = state.get("rivet_activity", {})
    if not act:
        return
    last = max(act.values())
    quiet = now() - last
    if quiet > TOWER_THRESHOLD and not t.get("reported") and now() - t.get("boot", 0) > TOWER_THRESHOLD:
        t["reported"] = True
        ages = {k: now() - v for k, v in sorted(act.items())}
        emit("ALL_QUIET", quiet_s=quiet, lane_ages_s=ages,
             note="Every Rivet lane quiet past threshold. Detection only — no wake action (freeze).")
    save_state(state)


# ---------------- main loop ----------------

LANES = [
    ("board", 20, board_poll),
    ("mq", 20, mq_poll),
    ("repos", 120, lambda s: repo_poll(s, "shared", SHARED_CLONE, "laptop/outbox/")
                             + repo_api_poll(s, "private", "FormatX66/poetry-project-9th-grade", "laptop/outbox/")),
    ("bus", 120, bus_poll),
    ("mail", 300, mail_poll),
    ("queue", 60, queue_poll),
    ("keepawake", 300, keepawake_poll),
    ("awaiting", 900, awaiting_poll),
]


def run_lane(state, name, fn):
    try:
        fn(state)
    except Exception as e:
        log("lane %s error: %s" % (name, e))


def main():
    state = load_state()
    once = "--once" in sys.argv
    due = {name: 0 for name, _, _ in LANES}
    exp, exp_mtime = None, None
    log("clock tower agent start (once=%s)" % once)
    while True:
        t = time.time()
        # doc stepping runs on its own schedule within the loop
        wait, mode_stage = doc_next_wait(state, exp)
        # expectation pickup
        if os.path.exists(EXPECT_F):
            mt = os.path.getmtime(EXPECT_F)
            if exp_mtime != mt:
                try:
                    j = json.load(open(EXPECT_F))
                    exp = {"eta_s": int(j.get("eta_s", 600)), "set_ts": now(), "stage": 0}
                    exp_mtime = mt
                    log("expectation set eta_s=%s" % exp["eta_s"])
                except Exception:
                    pass
        for name, interval, fn in LANES:
            if t >= due[name]:
                run_lane(state, name, fn)
                due[name] = t + interval
        save_state(state)
        tower_eval(state)
        if once:
            try:
                doc_poll(state)
            except Exception as e:
                log("doc lane error: %s" % e)
            save_state(state)
            log("once complete")
            return
        # sleep until the nearest due event or the doc step, max 5s granularity
        next_due = min(list(due.values()) + [t + wait])
        sleep_s = max(1, min(5, next_due - t))
        # doc step handling: if the doc wait elapsed within this sleep window, poll doc
        time.sleep(sleep_s)
        if time.time() >= t + wait:
            try:
                new = doc_poll(state)
            except Exception as e:
                log("doc lane error: %s" % e)
                new = []
            d = state.setdefault("doc", {})
            if new:
                d["ladder_i"] = 0
                exp = None
            elif mode_stage[0] == "part1" and exp:
                exp["stage"] = mode_stage[1] + 1
                if exp["stage"] >= 3:
                    exp = None
                    d["ladder_i"] = 0
            elif mode_stage[0] == "ladder":
                d["ladder_i"] = min(mode_stage[1] + 1, len(LADDER) - 1)
            save_state(state)


if __name__ == "__main__":
    main()
