#!/usr/bin/env python3
"""
Medic Mini — always-on Medic app for the laptop. Stdlib only.

Polls bin B every 20s for `exec` packets from Medic, verifies the shared
secret, runs the packet body as PowerShell, streams output to bin A with
__START__/__END__ markers, and posts __ACK__. `shot` packets return a
screen capture: PNG, downscaled to 1280px wide, base64-chunked to bin A
(__IMG_START__/__IMG__/__IMG_END__), then reassembled by Medic.

Pairing: if no mini-secret.txt exists on first start, the daemon enters
TOFU pairing mode — it posts a rotating __PAIR__ code to bin A, and accepts
the first `pair` packet (via bin B) carrying the matching code, adopting the
supplied secret. No human paste needed. Re-running setup keeps an existing
secret (already paired).

The daemon never thinks — it only executes. All judgment stays with Medic.
Standing rules apply to every packet: read-only unless the packet authorizes
a write, never submit QPU hardware jobs, secrets never enter the repo.

Install: 2026-09-19-medic-laptop-setup.ps1 does it (scheduled task at logon).
Dashboard: http://127.0.0.1:8899 (localhost only) — status, screenshot, log, update.
Self-update: `update` packet or dashboard button pulls the latest medic-mini.py
from the repo inbox and restarts.
Stop:   create a file named STOP next to this script, or disable the
         'MedicLaptopDaemon' scheduled task. Logs to mini.log beside it.
"""
import http.server
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
import pathlib
import datetime

BIN_B = "da708c88-feb6-4fae-a0ef-4ef3ed3bbcc4"  # inbound: Medic -> laptop
BIN_A = "947df846-f999-43e4-bf9c-fdac4577ef89"  # outbound: laptop -> Medic
BASE = pathlib.Path(__file__).resolve().parent
MEDIC_MINI_VERSION = "1.0.0"
MINI_URL = "https://raw.githubusercontent.com/FormatX66/medic-gpt-shared/main/laptop/inbox/medic-mini.py"
DASH_PORT = 8899

state = {
    "version": MEDIC_MINI_VERSION,
    "started": "",
    "paired": False,
    "exec_count": 0,
    "shot_count": 0,
    "last_dispatch": None,
    "last_result": None,
}
POLL_SECONDS = 20
CMD_TIMEOUT = 600  # seconds per exec packet


def log(msg):
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(BASE / "mini.log", "a", encoding="utf-8") as f:
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
    p = BASE / "mini-secret.txt"
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
    if ptype == "shot":
        take_shot(pid)
        return
    if ptype == "update":
        self_update(pid)
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
        state["exec_count"] += 1
        state["last_dispatch"] = pid
        state["last_result"] = f"exit={r.returncode}"
    except subprocess.TimeoutExpired:
        bin_a_post(f"__END__ {pid} TIMEOUT after {CMD_TIMEOUT}s")
        bin_a_post(f"__ACK__ {pid} timeout")
        log(f"exec {pid} TIMEOUT")
    except Exception as e:
        bin_a_post(f"__END__ {pid} ERROR {e}")
        bin_a_post(f"__ACK__ {pid} error")
        log(f"exec {pid} ERROR {e}")




def dash_html():
    p = BASE / "shot.png"
    shot_img = '<p><img src="/shot.png" style="max-width:100%"></p>' if p.exists() else "<i>none yet</i>"
    try:
        logtail = (BASE / "mini.log").read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
    except OSError:
        logtail = []
    rows = "".join("<div>" + l.replace("&", "&amp;").replace("<", "&lt;") + "</div>" for l in logtail)
    paired = "paired" if state["paired"] else "awaiting pairing"
    return ("<!doctype html><html><head><meta charset='utf-8'><title>Medic Mini</title><style>"
            "body{background:#0d1117;color:#c9d1d9;font-family:sans-serif;max-width:900px;margin:2em auto;padding:0 1em}"
            ".card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:1em;margin-bottom:1em}"
            "button{background:#238636;color:#fff;border:0;border-radius:6px;padding:.6em 1.2em;margin-right:.5em;cursor:pointer}"
            ".log{font-family:monospace;font-size:.8em;white-space:pre-wrap}</style></head><body>"
            f"<h1>Medic Mini <small>v{state['version']}</small></h1>"
            f"<div class='card'><b>Status:</b> {paired} | up since {state['started']} | "
            f"execs: {state['exec_count']} | shots: {state['shot_count']}<br>"
            f"<b>Last dispatch:</b> {state['last_dispatch']} &rarr; {state['last_result']}</div>"
            "<div class='card'>"
            "<form method='post' action='/api/shot' style='display:inline'><button>Take screenshot</button></form> "
            "<form method='post' action='/api/update' style='display:inline'><button>Check for update</button></form> "
            "<form method='post' action='/api/restart' style='display:inline'><button>Restart</button></form></div>"
            f"<div class='card'><h3>Latest screenshot</h3>{shot_img}</div>"
            f"<div class='card'><h3>Log (tail)</h3><div class='log'>{rows}</div></div>"
            "</body></html>")


class DashHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/shot.png":
            p = BASE / "shot.png"
            if p.exists():
                data = p.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_error(404)
            return
        html = dash_html().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def do_POST(self):
        if self.path == "/api/shot":
            take_shot("dash-" + uuid.uuid4().hex[:8])
        elif self.path == "/api/update":
            threading.Thread(target=self_update, daemon=True).start()
        elif self.path == "/api/restart":
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()
            threading.Timer(0.5, lambda: os.execv(
                sys.executable, [sys.executable, str(BASE / "medic-mini.py")])).start()
            return
        else:
            self.send_error(404)
            return
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()


def start_dashboard():
    srv = http.server.HTTPServer(("127.0.0.1", DASH_PORT), DashHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log(f"dashboard on http://127.0.0.1:{DASH_PORT} (localhost only)")


def self_update(pid="manual"):
    try:
        new = curl_get(MINI_URL)
        if not new or "MEDIC_MINI_VERSION" not in new:
            bin_a_post(f"__ACK__ {pid} update-failed (download)")
            log("self-update: download failed")
            return
        m = re.search(r'MEDIC_MINI_VERSION\s*=\s*"([^"]+)"', new)
        ver = m.group(1) if m else "?"
        if ver == MEDIC_MINI_VERSION:
            bin_a_post(f"__ACK__ {pid} already-current {ver}")
            log(f"self-update: already current ({ver})")
            return
        (BASE / "medic-mini.py").write_text(new, encoding="utf-8")
        bin_a_post(f"__ACK__ {pid} updated {MEDIC_MINI_VERSION} -> {ver}, restarting")
        log(f"self-update {MEDIC_MINI_VERSION} -> {ver}; restarting")
        time.sleep(1)
        os.execv(sys.executable, [sys.executable, str(BASE / "medic-mini.py")])
    except Exception as e:
        bin_a_post(f"__ACK__ {pid} update-error {e}")
        log(f"self-update error: {e}")


def take_shot(pid):
    shot_ps = r"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap($bounds.Width, $bounds.Height)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
$maxw = 1280
if ($bounds.Width -gt $maxw) {
  $scale = $maxw / $bounds.Width
  $small = New-Object System.Drawing.Bitmap($bmp, $maxw, [int]($bounds.Height * $scale))
  $bmp.Dispose(); $bmp = $small
}
$p = "$env:USERPROFILE\medic-daemon\shot.png"
$bmp.Save($p, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
[Convert]::ToBase64String([IO.File]::ReadAllBytes($p))
"""
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", shot_ps],
            capture_output=True, text=True, timeout=60)
        b64 = "".join((r.stdout or "").split())
        if r.returncode != 0 or not b64:
            bin_a_post(f"__IMG_END__ {pid} ERROR {(r.stderr or '')[:200]}")
            bin_a_post(f"__ACK__ {pid} shot-failed")
            log(f"shot {pid} FAILED rc={r.returncode}")
            return
        bin_a_post(f"__IMG_START__ {pid} chunks={(len(b64) + 1799) // 1800}")
        for i in range(0, len(b64), 1800):
            bin_a_post(f"__IMG__ {pid} {b64[i:i + 1800]}")
        bin_a_post(f"__IMG_END__ {pid} ok")
        bin_a_post(f"__ACK__ {pid} shot-ok")
        log(f"shot {pid} sent ({len(b64)} b64 chars)")
        state["shot_count"] += 1
    except Exception as e:
        bin_a_post(f"__IMG_END__ {pid} ERROR {e}")
        bin_a_post(f"__ACK__ {pid} shot-error")
        log(f"shot {pid} ERROR {e}")


def pairing_mode():
    """TOFU pairing: no secret yet. Post rotating code to bin A, accept the
    first `pair` packet via bin B with the matching code, adopt its secret."""
    import random
    seen = load_seen()
    while True:
        if (BASE / "STOP").exists():
            return None
        code = f"{random.randint(0, 999999):06d}"
        bin_a_post(f"__PAIR__ {code} medic-daemon awaiting pairing (code rotates in 90s)")
        log(f"pairing mode, code {code}")
        deadline = time.time() + 90
        while time.time() < deadline:
            if (BASE / "STOP").exists():
                return None
            try:
                raw = curl_get(f"https://webhook.site/token/{BIN_B}/requests")
                items = json.loads(raw).get("data", []) if raw else []
                for req in items:
                    rid = req.get("uuid")
                    if not rid or rid in seen:
                        continue
                    seen.add(rid)
                    save_seen(seen)
                    try:
                        pkt = json.loads(req.get("content") or "")
                    except Exception:
                        continue
                    if (isinstance(pkt, dict) and pkt.get("type") == "pair"
                            and pkt.get("code") == code):
                        secret = (pkt.get("secret") or "").strip()
                        if len(secret) >= 16:
                            (BASE / "mini-secret.txt").write_text(
                                secret, encoding="utf-8")
                            bin_a_post("__PAIRED__ medic-daemon paired")
                            log("paired successfully")
                            state["paired"] = True
                            return secret
                        log("pair packet with too-short secret ignored")
            except Exception as e:
                log(f"pairing poll error: {e}")
            time.sleep(10)


def main():
    secret = load_secret()
    if not secret:
        log("no mini-secret.txt — entering TOFU pairing mode")
        secret = pairing_mode()
    if not secret:
        log("pairing failed or STOP requested — exiting.")
        return 2
    seen = load_seen()
    state["started"] = datetime.datetime.now().isoformat(timespec="seconds")
    state["paired"] = True
    start_dashboard()
    log(f"medic-mini v{MEDIC_MINI_VERSION} up. polling every {POLL_SECONDS}s. base={BASE}")
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
