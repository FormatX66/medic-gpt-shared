#!/usr/bin/env python3
"""CLOCK TOWER AGENT — one resident watch agent for every Medic/Rivet lane.

v1.1 (2026-10-14) — amended per Rivet's source review of v1 commit ad729e0f
(Entry rivet-tower-review-20261014-1323-v1). Fixes, in her bounded order:
  1. Sanitized error paths: lane errors log operation + exception CLASS only;
     subprocess argv (which can carry Authorization headers) is never logged.
  2. Persistent monotonic Doc deadline (absolute due time, not per-loop t).
  3. Board event payload field renamed (entry_kind) — the duplicate-kind
     TypeError that dropped Board notifications is gone.
  4. Effects before cursor advance everywhere (Doc seen, Board seen, MQ
     next_seq, repo heads): events are appended + fsynced BEFORE any cursor
     moves, so a crash loses nothing silently.
  5. Atomic state writes (tmp + os.replace); corrupt state is set aside and
     rebuilt, never silently trusted.
  6. Tower quiet now has freshness gates: a knock requires every Rivet lane
     to have a SUCCESSFUL read inside its freshness window — a broken lane
     reads as "coverage unknown", never as silence. Mail from Rivet counts
     as Rivet activity.
  7. Board posts send the body via stdin — no credential-bearing temp file.
  8. Hub probe distinguishes 401 (probe fault) from failure, in that order.
  9. Bus watermark handles rotation/truncation and holds partial last lines.
 10. Slow lanes (keepawake, mail, stall checks) run in their own threads so
     a 90s probe can never starve the 20s lanes; shared state is lock-guarded.
 11. Doc dedup keys include a content hash, so an edited entry re-fires.

Lanes: doc 20s flat, board 20s, mq 20s, repos 120s, bus 120s, queue 60s,
keepawake 300s, mail 300s, awaiting 900s (slow three threaded).
Events -> hidden_files/clock-tower-events.jsonl (fsync per event).
State  -> hidden_files/clock-tower-state.json (atomic).
Run: nohup python3 clock_tower_agent.py >> hidden_files/clock-tower.log 2>&1 &
"""
import base64, hashlib, json, os, re, subprocess, sys, threading, time
from datetime import datetime
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
HID = os.path.normpath(os.path.join(HERE, "..", "hidden_files"))
STATE_F = os.path.join(HID, "clock-tower-state.json")
EVENTS_F = os.path.join(HID, "clock-tower-events.jsonl")
DOC_ID = "1gHVGrWSbuWGPNca8-lO8K9hAWv6gBesRmapOCoi-fP8"
GWS = "/opt/hatch/bin/hatch_gws_cli"
MQ_URL = "https://madmorrigan.com/prymortal-api/api.php?action=mq"
BOARD_URL = "https://madmorrigan.com/prymortal-api/api.php?action=board"
ET = ZoneInfo("America/New_York")
sys.path.insert(0, HERE)
import comms_log_watch as W

SHARED_CLONE = os.path.join(ROOT, "shared", "medic-gpt-shared")
LOCK = threading.Lock()


def now():
    return int(time.time())


def log(msg):
    print("[%s] %s" % (datetime.now(ET).strftime("%H:%M:%S"), msg), flush=True)


def save_json_atomic(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def emit(kind, **kw):
    ev = {"ts": now(), "kind": kind}
    ev.update(kw)
    with LOCK:
        with open(EVENTS_F, "a") as f:
            f.write(json.dumps(ev) + "\n")
            f.flush()
            os.fsync(f.fileno())
    log("event %s" % kind)


def load_state():
    if os.path.exists(STATE_F):
        try:
            return json.load(open(STATE_F))
        except Exception:
            bad = STATE_F + ".corrupt-%d" % now()
            try:
                os.replace(STATE_F, bad)
            except Exception:
                pass
            log("state corrupt; set aside, rebuilding")
    return {"lanes": {}, "rivet_activity": {}, "lane_health": {},
            "tower": {"reported": False, "boot": now()},
            "mq_next_seq": 0, "mq_init": False, "reported_missed": [],
            "down": {}, "doc": {}, "doc_due": 0}


def save_state(s):
    with LOCK:
        save_json_atomic(STATE_F, s)


def touch_rivet(state, lane):
    with LOCK:
        state.setdefault("rivet_activity", {})[lane] = now()
        if state.get("tower", {}).get("reported"):
            state["tower"]["reported"] = False
            log("tower re-armed (rivet active on %s)" % lane)


def lane_ok(state, lane):
    with LOCK:
        state.setdefault("lane_health", {})[lane] = {"last_ok": now(), "last_err": 0}


def lane_err(state, lane):
    with LOCK:
        h = state.setdefault("lane_health", {}).setdefault(lane, {"last_ok": 0, "last_err": 0})
        h["last_err"] = now()


def sh(args, timeout=60, cwd=None, input_text=None):
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                       cwd=cwd, input=input_text)
    return r.returncode, r.stdout, r.stderr


def run_lane(state, name, fn):
    """Sanitized: never log exception text — argv may carry credentials."""
    try:
        fn(state)
        lane_ok(state, name)
    except subprocess.TimeoutExpired:
        lane_err(state, name)
        log("lane %s timeout" % name)
    except Exception as e:
        lane_err(state, name)
        log("lane %s error (%s)" % (name, type(e).__name__))


# ---------------- doc lane ----------------

def board_pointer(topics):
    try:
        key = open(os.path.expanduser("~/.config/board/medic-key")).read().strip()
        body = {"key": key, "kind": "work-status",
                "body": {"msg": "COMMS LOG: new Rivet entry picked up + acked in-doc (%s)." % topics,
                         "ref": "comms-log"}}
        rc, out, _ = sh(["curl", "-sS", "--max-time", "30", "-X", "POST", BOARD_URL,
                         "-H", "Content-Type: application/json", "-d", "@-"],
                        timeout=45, input_text=json.dumps(body))
        return '"ok":true' in out.replace(" ", "")
    except Exception:
        log("board pointer failed")
        return False


def entry_key(e):
    h = hashlib.sha1(e["text"].encode("utf-8", "replace")).hexdigest()[:8]
    return e["ts"] + "|" + e["author"] + "|" + e["topic"] + "|" + h


def doc_poll(state):
    dstate_f = os.path.join(HID, "comms-log-watch-state.json")
    ds = {"seen": [], "last_modified": None}
    if os.path.exists(dstate_f):
        try:
            ds = json.load(open(dstate_f))
        except Exception:
            pass
    mod = W.doc_modified()
    if mod == ds.get("last_modified"):
        return []
    entries = W.doc_entries()
    seen = set(ds.get("seen", []))
    new = [e for e in entries if entry_key(e) not in seen]
    rivet = [e for e in new if e["author"] != "MEDIC"]
    if rivet:
        # EFFECTS FIRST (ack, pointer, event); cursor advance last.
        now_edt = datetime.now(ET).strftime("%Y-%m-%d %H:%M EDT")
        lines = ["\n---\n[%s] MEDIC - ack" % now_edt]
        for e in rivet:
            m = re.search(r"Entry ID:\s*(\S+)", e["text"])
            lines.append("Picked up new RIVET entry: Entry ID %s" % m.group(1) if m
                         else "Picked up new RIVET entry: [%s] %s - %s" % (e["ts"], e["author"], e["topic"]))
        rc, _, _ = sh([GWS, "docs", "+write", "--document", DOC_ID, "--text", "\n".join(lines)])
        board_pointer("; ".join(e["topic"] for e in rivet))
        emit("DOC_NEW", entries=[{"ts": e["ts"], "author": e["author"], "topic": e["topic"],
                                  "text": e["text"]} for e in rivet], ack_ok=(rc == 0))
        touch_rivet(state, "doc")
    ds["seen"] = [entry_key(e) for e in entries]
    ds["last_modified"] = mod
    save_json_atomic(dstate_f, ds)
    return rivet


# ---------------- board lane ----------------

def board_poll(state):
    rc, out, _ = sh(["curl", "-sS", "--max-time", "30", BOARD_URL + "&format=json"], timeout=45)
    if rc != 0:
        raise RuntimeError("board GET failed")
    entries = json.loads(out).get("entries", [])
    sf = os.path.join(HID, "board-watch-state.json")
    bs = {"seen": [], "rivet_receipted": True}
    if os.path.exists(sf):
        try:
            bs = json.load(open(sf))
        except Exception:
            pass
    seen = set(bs.get("seen", []))
    new = []
    for e in entries:
        k = "%s:%s:%s" % (e.get("ts"), e.get("agent"), e.get("kind"))
        if k not in seen:
            new.append((k, e))
    # EFFECTS FIRST: emit/touch for every new entry, then advance the cursor.
    for k, e in new:
        if e.get("agent") == "rivet":
            touch_rivet(state, "board")
        if e.get("agent") != "medic":
            body = e.get("body") or {}
            emit("BOARD_ENTRY", agent=e.get("agent"), entry_kind=e.get("kind"),
                 msg=str(body.get("msg", ""))[:400], ref=str(body.get("ref", ""))[:120])
    for k, e in new:
        seen.add(k)
    bs["seen"] = sorted(seen)
    save_json_atomic(sf, bs)
    return len(new)


# ---------------- mq lane ----------------

def mq_call(op_fields, token):
    rc, out, _ = sh(["curl", "-sS", "--max-time", "30", "-X", "POST", MQ_URL,
                     "-H", "Content-Type: application/json",
                     "-H", "Authorization: Bearer " + token, "-d", json.dumps(op_fields)],
                    timeout=45)
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
    # EFFECTS FIRST: emit + ack each message; cursor advances only after.
    for m in msgs:
        if m.get("sender") == "rivet":
            touch_rivet(state, "mq")
        emit("MQ_MSG", sender=m.get("sender"), type=m.get("type"), key=m.get("key"),
             id=m.get("id"), seq=m.get("seq"), payload=str(m.get("payload"))[:400])
        try:
            mq_call({"op": "ack", "id": m.get("id")}, token)
        except Exception:
            log("mq ack failed (sanitized)")
    if msgs and r.get("next_seq") is not None:
        state["mq_next_seq"] = r["next_seq"]
    return len(msgs)


# ---------------- repo lanes ----------------

def repo_poll(state, name, clone, outbox_prefix):
    if not os.path.isdir(os.path.join(clone, ".git")):
        return 0
    rc, _, _ = sh(["git", "fetch", "origin", "main"], timeout=90, cwd=clone)
    if rc != 0:
        raise RuntimeError("git fetch failed")
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
    new_files = [f for f in out.splitlines() if f.startswith(outbox_prefix)]
    for f in new_files:  # effects first
        touch_rivet(state, "repo-" + name)
        emit("REPO_PACKET", repo=name, file=f)
    state[key] = head
    return len(new_files)


def repo_api_poll(state, name, repo, outbox_prefix):
    key = "repoapi_" + name
    if key not in state:
        sf = os.path.join(HID, "private-mailbox-watch-state.json")
        seed = []
        if os.path.exists(sf):
            try:
                seed = json.load(open(sf)).get("seen_outbox", [])
            except Exception:
                pass
        state[key] = seed
        log("repo %s: seeded %d known outbox files" % (name, len(seed)))
        return 0
    token = open(os.path.expanduser("~/.config/github/token")).read().strip()
    rc, out, _ = sh(["curl", "-sS", "--max-time", "30",
                     "https://api.github.com/repos/%s/contents/%s" % (repo, outbox_prefix.rstrip("/")),
                     "-H", "Authorization: token " + token,
                     "-H", "Accept: application/vnd.github+json"], timeout=45)
    if rc != 0:
        raise RuntimeError("repo API list failed")
    try:
        names = [e["name"] for e in json.loads(out) if isinstance(e, dict) and e.get("type") == "file"]
    except Exception:
        raise RuntimeError("repo API list unparseable")
    seen = set(state[key])
    new = [n for n in names if n not in seen]
    for n in new:  # effects first
        touch_rivet(state, "repo-" + name)
        emit("REPO_PACKET", repo=name, file=outbox_prefix + n)
    state[key] = sorted(seen | set(names))
    return len(new)


# ---------------- sftp helpers ----------------

def proxy_cmd():
    hp = os.environ.get("HTTPS_PROXY", "")
    base = hp.split("@")[-1]
    auth = hp.replace("http://", "").split("@")[0]
    host = base.split(":")[0]
    return "socat - PROXY:%s:100.89.69.54:22,proxyport=3130,proxyauth=%s" % (host, auth)


def sftp_get(remote, local):
    batch = os.path.join(HID, ".sftp.batch")
    open(batch, "w").write("get %s %s\n" % (remote, local))
    try:
        rc, _, _ = sh(["sftp", "-b", batch, "-o", "StrictHostKeyChecking=no",
                       "-o", "ProxyCommand=" + proxy_cmd(), "-i",
                       os.path.expanduser("~/.ssh/id_ed25519"), "bruce@100.89.69.54"], timeout=60)
        return rc == 0 and os.path.exists(local)
    finally:
        try:
            os.remove(batch)
        except Exception:
            pass


def sftp_put(local, remote):
    batch = os.path.join(HID, ".sftp.batch")
    open(batch, "w").write("put %s %s\n" % (local, remote))
    try:
        rc, _, _ = sh(["sftp", "-b", batch, "-o", "StrictHostKeyChecking=no",
                       "-o", "ProxyCommand=" + proxy_cmd(), "-i",
                       os.path.expanduser("~/.ssh/id_ed25519"), "bruce@100.89.69.54"], timeout=60)
        return rc == 0
    finally:
        try:
            os.remove(batch)
        except Exception:
            pass


def bus_poll(state):
    tmp = os.path.join(HID, ".bus-inbox.jsonl")
    if not sftp_get("/C:/Users/bruce/memscan/bus/rivet-to-medic.jsonl", tmp):
        raise RuntimeError("bus fetch failed")
    data = open(tmp, "rb").read()
    prev = state.get("bus_seen_bytes", 447)
    if len(data) < prev:
        prev = 0  # rotation/truncation: re-read from the start
    chunk = data[prev:]
    last_nl = chunk.rfind(b"\n")
    if last_nl < 0:
        return 0  # only a partial line so far; hold the watermark
    complete = chunk[:last_nl + 1]
    n = 0
    for line in complete.decode("utf-8", "replace").splitlines():
        if line.strip():
            touch_rivet(state, "bus")
            emit("BUS_MAIL", line=line[:500])
            n += 1
    state["bus_seen_bytes"] = prev + len(complete)
    return n


# ---------------- keepawake (threaded) ----------------

def keepawake_poll(state):
    down = state.setdefault("down", {})

    def alert(name, is_down, msg):
        with LOCK:
            was = down.get(name)
            down[name] = is_down
        if is_down and not was:
            emit("LANE_DOWN", lane=name, msg=msg)

    hb = os.path.join(HID, ".hb-medic.json")
    open(hb, "w").write(json.dumps({"ts": now(), "agent": "medic", "state": "live", "via": "clock-tower"}))
    sftp_put(hb, "/C:/Users/bruce/memscan/bus/heartbeat-medic.json")
    tmp = os.path.join(HID, ".hb-laptop.json")
    ok = sftp_get("/C:/Users/bruce/memscan/bus/laptop-heartbeat.json", tmp)
    fresh = False
    if ok:
        try:
            fresh = now() - int(json.load(open(tmp)).get("ts", 0)) < 720
        except Exception:
            fresh = False
    alert("laptop", not fresh, "laptop heartbeat stale — laptop may be asleep or offline")

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
        rc, out, _ = sh(["timeout", "40", os.path.join(ROOT, "ssh-pi.sh"),
                         "cat ~/crew/state/heartbeat-pi.json"], timeout=60)
        pi_fresh = False
        try:
            pi_fresh = now() - int(json.loads(out).get("ts", 0)) < 720
        except Exception:
            pi_fresh = False
        alert("pi", not pi_fresh, "BBPI4 heartbeat stale — Pi may be down or unreachable")
        ps = ("$k=(Get-Content 'C:\\Users\\bruce\\MedicHub\\hub\\.env' | "
              "Where-Object {$_ -match '^HUB_API_KEY='} | ForEach-Object {$_.Split('=',2)[1]}); "
              "$o = curl.exe -s -m 6 -w \"`nHTTP:%{http_code}\" -H \"Authorization: Bearer $k\" "
              "http://127.0.0.1:8090/health; "
              "if ($o -match 'HTTP:401') { 'HUB_401' } "
              "elseif ($o -match 'HTTP:200' -and $o -match '\"ok\": true') { 'HUB_OK' } "
              "else { 'HUB_FAIL ' + $o }")
        enc = base64.b64encode(ps.encode("utf-16le")).decode()
        rc, out, _ = sh([os.path.join(ROOT, "ssh-laptop.sh"),
                         "powershell -NoProfile -EncodedCommand " + enc], timeout=60)
        if "HUB_401" in out:
            log("hub probe broken (401) — probe fault, not Hub")
        elif "HUB_OK" in out:
            alert("hub", False, "")
        else:
            time.sleep(30)
            rc, out, _ = sh([os.path.join(ROOT, "ssh-laptop.sh"),
                             "powershell -NoProfile -EncodedCommand " + enc], timeout=60)
            if "HUB_401" in out:
                log("hub probe broken (401) — probe fault, not Hub")
            else:
                alert("hub", "HUB_OK" not in out, "Model Hub health check FAILED on the laptop")
    return 0


# ---------------- mail / queue / awaiting ----------------

def mail_poll(state):
    rc, out, err = sh(["python3", os.path.join(ROOT, "email-bridge", "mail_poll.py"), "--once"],
                      timeout=120)
    if rc != 0:
        raise RuntimeError("mail bridge fetch failed")
    for line in out.splitlines():
        if "rivet@arkmatx.com" in line:
            touch_rivet(state, "mail")
            emit("MAIL", line=line[:400])
        elif line.strip().startswith(("NEW", "MAIL", "FROM")):
            emit("MAIL", line=line[:400])
    return 0


def queue_poll(state):
    rc, out, _ = sh(["python3", os.path.join(HERE, "crew_queue.py")], timeout=60)
    try:
        d = json.loads(out.strip().splitlines()[-1])
    except Exception:
        raise RuntimeError("crew_queue unparseable")
    missed = d.get("missed", []) if isinstance(d, dict) else []
    ids = [m.get("id") for m in missed if isinstance(m, dict)]
    with LOCK:
        reported = set(state.get("reported_missed", []))
    for m in missed:
        if isinstance(m, dict) and m.get("id") not in reported:
            emit("ETA_MISSED", id=m.get("id"), title=m.get("title"), owner=m.get("owner"),
                 late_s=m.get("late_s"))
            reported.add(m.get("id"))
    with LOCK:
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


# ---------------- tower (all-lane quiet, freshness-gated) ----------------

TOWER_THRESHOLD = 1800
FRESHNESS = {"doc": 300, "board": 300, "mq": 300, "repo-shared": 600,
             "repo-private": 600, "bus": 600, "mail": 1200}


def tower_eval(state):
    t = state.setdefault("tower", {"reported": False, "boot": now()})
    act = state.get("rivet_activity", {})
    if not act:
        return
    health = state.get("lane_health", {})
    # Coverage gate: every lane must have read successfully within its
    # window, otherwise quiet is UNPROVEN, not true.
    for lane, window in FRESHNESS.items():
        last_ok = health.get(lane, {}).get("last_ok", 0)
        if now() - last_ok > window:
            return
    last = max(act.values())
    quiet = now() - last
    if quiet > TOWER_THRESHOLD and not t.get("reported") and now() - t.get("boot", 0) > TOWER_THRESHOLD:
        t["reported"] = True
        ages = {k: now() - v for k, v in sorted(act.items())}
        emit("ALL_QUIET", quiet_s=quiet, lane_ages_s=ages,
             note="Every Rivet lane quiet past threshold, all lanes read-verified fresh. Detection only — no wake action (freeze).")
    save_state(state)


# ---------------- main loop ----------------

FAST_LANES = [
    ("board", 20, board_poll),
    ("mq", 20, mq_poll),
    ("repos", 120, None),  # wired in main (two sub-lanes + health mirror)
    ("bus", 120, bus_poll),
    ("queue", 60, queue_poll),
]
SLOW_LANES = [
    ("keepawake", 300, keepawake_poll),
    ("mail", 300, mail_poll),
    ("awaiting", 900, awaiting_poll),
]


def repos_lane(state):
    n = repo_poll(state, "shared", SHARED_CLONE, "laptop/outbox/")
    lane_ok(state, "repo-shared")
    n += repo_api_poll(state, "private", "FormatX66/poetry-project-9th-grade", "laptop/outbox/")
    lane_ok(state, "repo-private")
    return n


def slow_lane_thread(state, name, interval, fn):
    while True:
        run_lane(state, name, fn)
        save_state(state)
        time.sleep(interval)


def main():
    state = load_state()
    once = "--once" in sys.argv
    for name, interval, fn in SLOW_LANES:
        if not once:
            th = threading.Thread(target=slow_lane_thread, args=(state, name, interval, fn),
                                  daemon=True, name=name)
            th.start()
    due = {name: 0 for name, _, _ in FAST_LANES}
    log("clock tower agent start (once=%s)" % once)
    while True:
        t = time.time()
        if t >= state.get("doc_due", 0):
            run_lane(state, "doc", doc_poll)
            state["doc_due"] = time.time() + 20  # absolute deadline; loop never resets it
        for name, interval, fn in FAST_LANES:
            if t >= due[name]:
                run_lane(state, name, repos_lane if name == "repos" else fn)
                due[name] = t + interval
        save_state(state)
        tower_eval(state)
        if once:
            for name, interval, fn in SLOW_LANES:
                run_lane(state, name, fn)
            save_state(state)
            log("once complete")
            return
        next_due = min(list(due.values()) + [state.get("doc_due", 0)])
        time.sleep(max(0.2, min(5, next_due - time.time())))


if __name__ == "__main__":
    main()
