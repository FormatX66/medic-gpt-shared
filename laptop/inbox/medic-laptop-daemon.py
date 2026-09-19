#!/usr/bin/env python3
"""
Medic laptop daemon — always-on hands for Medic's dispatches. Stdlib only.

Polls bin B every 20s for `exec` packets from Medic, verifies the shared
secret, runs the packet body as PowerShell, streams output to bin A with
__START__/__END__ markers, and posts __ACK__.

The daemon never thinks — it only executes. All judgment stays with Medic.
Standing rules apply to every packet: read-only unless the packet authorizes
a write, never submit QPU hardware jobs, secrets never enter the repo.

Install: 2026-09-19-medic-laptop-setup.ps1 does it (scheduled task at logon).
Stop:   create a file named STOP next to this script, or disable the
         'MedicLaptopDaemon' scheduled task. Logs to daemon.log beside it.
"""
import json
import subprocess
import sys
import time
import uuid
import pathlib
import datetime

BIN_B = "da708c88-feb6-4fae-a0ef-4ef3ed3bbcc4"  # inbound: Medic -> laptop
BIN_A = "947df846-f999-43e4-bf9c-fdac4577ef89"  # outbound: laptop -> Medic
BASE = pathlib.Path(__file__).resolve().parent
POLL_SECONDS = 20
CMD_TIMEOUT = 600  # seconds per exec packet


def log(msg):
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(BASE / "daemon.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def curl_get(url):
    # curl.exe: webhook.site's bot protection drops Python's TLS fingerprint.
    r = subprocess.run(["curl.exe", "-s", "--max-time", "25", url],
                       capture_output=True, text=True, timeout=30)
    return r.stdout if r.returncode == 0 else ""


def curl_post(url, data):
    r = subprocess.run(["curl.exe", "-s", "--max-time", "25", "-X", "POST", url,
                        "-H", "Content-Type: application/json", "--data", data],
                       capture_output=True, text=True, timeout=30)
    return r.returncode == 0


def bin_a_post(text):
    curl_post(f"https://webhook.site/{BIN_A}", text)


def load_secret():
    p = BASE / "daemon-secret.txt"
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def load_seen():
    p = BASE / "seen.json"
    try:
        return set(json.loads(p.read_text(encoding="utf-8")))
    except OSError:
        return set()


def save_seen(seen):
    try:
        (BASE / "seen.json").write_text(json.dumps(sorted(seen)), encoding="utf-8")
    except OSError:
        pass


def handle(req, secret):
    try:
        pkt = json.loads(req.get("content") or "")
    except Exception:
        return
    if not isinstance(pkt, dict) or pkt.get("secret") != secret:
        return  # junk or wrong secret: ignore silently
    pid = pkt.get("id") or str(uuid.uuid4())
    ptype = pkt.get("type")
    if ptype == "ping":
        bin_a_post(f"__ACK__ {pid} daemon alive")
        return
    if ptype != "exec":
        return  # GPT-app dispatches etc. — not this daemon's to run
    body = pkt.get("body") or ""
    log(f"exec {pid}: {len(body)} chars")
    bin_a_post(f"__START__ {pid}")
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", body],
            capture_output=True, text=True, timeout=CMD_TIMEOUT)
        out = (r.stdout or "") + (r.stderr or "")
        n = 0
        for i in range(0, len(out), 1800):
            bin_a_post(out[i:i + 1800])
            n += 1
        bin_a_post(f"__END__ {pid} exit={r.returncode} chunks={n}")
        bin_a_post(f"__ACK__ {pid} exit={r.returncode}")
        log(f"exec {pid} done exit={r.returncode}")
    except subprocess.TimeoutExpired:
        bin_a_post(f"__END__ {pid} TIMEOUT after {CMD_TIMEOUT}s")
        bin_a_post(f"__ACK__ {pid} timeout")
        log(f"exec {pid} TIMEOUT")
    except Exception as e:
        bin_a_post(f"__END__ {pid} ERROR {e}")
        bin_a_post(f"__ACK__ {pid} error")
        log(f"exec {pid} ERROR {e}")


def main():
    secret = load_secret()
    if not secret:
        log("FATAL: daemon-secret.txt missing next to script. "
            "Paste the daemon secret from Medic into it, then restart.")
        return 2
    seen = load_seen()
    log(f"daemon up. polling every {POLL_SECONDS}s. base={BASE}")
    bin_a_post("__STATUS__ medic-daemon online")
    while True:
        if (BASE / "STOP").exists():
            log("STOP file present — exiting.")
            return 0
        try:
            raw = curl_get(f"https://webhook.site/token/{BIN_B}/requests")
            items = json.loads(raw).get("data", []) if raw else []
            for req in items:
                rid = req.get("uuid")
                if not rid or rid in seen:
                    continue
                seen.add(rid)
                save_seen(seen)
                handle(req, secret)
        except Exception as e:
            log(f"poll error: {e}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
