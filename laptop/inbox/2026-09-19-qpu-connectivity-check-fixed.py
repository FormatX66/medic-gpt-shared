#!/usr/bin/env python3
"""IBM QPU connectivity check — read-only, spends zero QPU seconds.

Reads the API key ONLY from the IBM_API_KEY environment variable.
Performs: IAM token exchange -> backend listing -> usage read.
Makes NO job-submit calls. Never prints or stores the key or token.

Exit codes:
    0  success: key reached live IBM Quantum backends
    2  IBM_API_KEY is missing
    3  auth failure (bad/revoked key)
    4  network failure (endpoint unreachable)

Stdlib only — runs on any Python 3.6+.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

IAM_TOKEN_URL = "https://iam.cloud.ibm.com/identity/token"
API_BASE = "https://quantum.cloud.ibm.com/api/v1"

# urllib's default UA trips Cloudflare's bot check on IBM's API front;
# a browser-like UA is required for reliable reads.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")


def _get(url, bearer=None, timeout=30, service_crn=None):
    """GET url -> (status, parsed_json). Network errors raise."""
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if bearer:
        headers["Authorization"] = "Bearer " + bearer
    if service_crn:
        headers["Service-CRN"] = service_crn
        headers["IBM-API-Version"] = "2025-05-01"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            body = {}
        return e.code, body


def main():
    key = os.environ.get("IBM_API_KEY", "").strip()
    crn = os.environ.get("IBM_QUANTUM_CRN", "").strip()
    if not key:
        print("IBM_API_KEY is not set.")
        print("Set it on this machine first, e.g.:")
        print('  Windows (PowerShell):  $env:IBM_API_KEY = "paste-your-key-here"')
        print('  macOS/Linux (bash):    export IBM_API_KEY="paste-your-key-here"')
        print("Then run this script again. The key is read from the")
        print("environment only and is never stored or printed.")
        return 2

    # 1. IAM token exchange (no key or token ever printed).
    form = urllib.parse.urlencode({
        "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
        "apikey": key,
    }).encode()
    req = urllib.request.Request(
        IAM_TOKEN_URL, data=form, method="POST",
        headers={"User-Agent": UA,
                 "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        print("FAIL: IAM token exchange rejected the key "
              "(HTTP %s). The key may be bad or revoked." % e.code)
        return 3
    except Exception as e:
        print("FAIL: could not reach %s (%s: %s)"
              % (IAM_TOKEN_URL, type(e).__name__, e))
        return 4
    token = payload.get("access_token")
    if not token:
        print("FAIL: IAM exchange returned no access token.")
        return 3

    # 2. Backend listing (read-only).
    try:
        status, body = _get(API_BASE + "/backends", bearer=token, service_crn=crn)
    except Exception as e:
        print("FAIL: could not reach %s/backends (%s: %s)"
              % (API_BASE, type(e).__name__, e))
        return 4
    if status != 200:
        print("FAIL: backend listing returned HTTP %s." % status)
        return 3
    backends = body.get("backends") or body.get("devices") or []

    # 3. Usage read (read-only).
    try:
        ustatus, ubody = _get(API_BASE + "/usage", bearer=token, service_crn=crn)
    except Exception as e:
        print("FAIL: could not reach %s/instances/usage (%s: %s)"
              % (API_BASE, type(e).__name__, e))
        return 4

    print("PASS: IBM key reached live IBM Quantum backends.")
    print("Backends (%d):" % len(backends))
    for b in backends:
        name = b.get("name") or b.get("backend_name") or "?"
        oper = b.get("operational")
        status_txt = "operational" if oper else ("offline" if oper is False else "?")
        print("  - %s  [%s]" % (name, status_txt))
    if ustatus == 200 and isinstance(ubody, dict):
        used = ubody.get("usage_seconds", ubody.get("seconds_used", "?"))
        remaining = ubody.get("usage_remaining_seconds", "?")
        print("QPU seconds used: %s | remaining: %s" % (used, remaining))
        if ubody.get("usage_limit_reached"):
            print("Note: IBM reports the usage limit is reached.")
    else:
        print("Usage read returned HTTP %s (backends listing still passed)."
              % ustatus)
    print("Zero QPU seconds were spent by this check.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

