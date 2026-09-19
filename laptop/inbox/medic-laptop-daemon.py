#!/usr/bin/env python3
"""
Medic laptop daemon — always-on hands for Medic's dispatches. Stdlib only.

Polls bin B every 20s for `exec` packets from Medic, verifies the shared
secret, runs the packet body as PowerShell, streams output to bin A with
__START__/__END__ markers, and posts __ACK__. `shot` packets return a
screen capture: PNG, downscaled to 1280px wide, base64-chunked to bin A
(__IMG_START__/__IMG__/__IMG_END__), then reassembled by Medic.

Pairing: if no daemon-secret.txt exists on first start, the daemon enters
TOFU pairing mode — it posts a rotating __PAIR__ code to bin A, and accepts
the first `pair` packet (via bin B) carrying the matching code, adopting the
supplied secret. No human paste needed. Re-running setup keeps an existing
secret (already paired).

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
    if ptype == "shot":
        take_shot(pid)
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
                            (BASE / "daemon-secret.txt").write_text(
                                secret, encoding="utf-8")
                            bin_a_post("__PAIRED__ medic-daemon paired")
                            log("paired successfully")
                            return secret
                        log("pair packet with too-short secret ignored")
            except Exception as e:
                log(f"pairing poll error: {e}")
            time.sleep(10)


def main():
    secret = load_secret()
    if not secret:
        log("no daemon-secret.txt — entering TOFU pairing mode")
        secret = pairing_mode()
    if not secret:
        log("pairing failed or STOP requested — exiting.")
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
