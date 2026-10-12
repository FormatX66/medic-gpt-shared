#!/usr/bin/env python3
"""
Rivet MQ Diagnostic - run this to isolate the connection failure.
Tests each layer independently: DNS -> TCP -> TLS -> HTTP -> Auth -> Queue ops.
"""
import socket, ssl, json, urllib.request, sys

HOST = "madmorrigan.com"
URL = f"https://{HOST}/prymortal-api/api.php?action=mq"
# Rivet: paste your token here (do not share this file)
TOKEN = "PASTE_YOUR_TOKEN_HERE"

def test(name, fn):
    try:
        result = fn()
        print(f"  [PASS] {name}: {result}")
        return True
    except Exception as e:
        print(f"  [FAIL] {name}: {type(e).__name__}: {e}")
        return False

print("=== MQ Connection Diagnostic ===")
print(f"Target: {URL}")
print()

# Layer 1: DNS
def dns_test():
    ip = socket.gethostbyname(HOST)
    return f"resolved to {ip}"
dns_ok = test("DNS resolution", dns_test)

# Layer 2: TCP
def tcp_test():
    s = socket.create_connection((HOST, 443), timeout=10)
    s.close()
    return "port 443 reachable"
tcp_ok = test("TCP connect", tcp_test) if dns_ok else print("  [SKIP] TCP connect (DNS failed)")

# Layer 3: TLS
def tls_test():
    ctx = ssl.create_default_context()
    s = socket.create_connection((HOST, 443), timeout=10)
    ss = ctx.wrap_socket(s, server_hostname=HOST)
    cert = ss.getpeercert()
    ss.close()
    return f"TLS OK, cert for {cert.get('subject', 'unknown')}"
tls_ok = test("TLS handshake", tls_test) if dns_ok else print("  [SKIP] TLS (DNS failed)")

# Layer 4: HTTP (no auth)
def http_test():
    req = urllib.request.Request(URL, data=b'{}', method='POST',
        headers={'Content-Type': 'application/json', 'User-Agent': 'rivet-diag/1.0'})
    try:
        urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code} (server responding)"
    return "unexpected success without auth"
test("HTTP reachability", http_test) if tls_ok else print("  [SKIP] HTTP (TLS failed)")

# Layer 5: Auth
def auth_test():
    body = json.dumps({'op': 'poll', 'since_seq': 0, 'limit': 1}).encode()
    req = urllib.request.Request(URL, data=body, method='POST',
        headers={'Content-Type': 'application/json',
                 'Authorization': f'Bearer {TOKEN}',
                 'User-Agent': 'rivet-diag/1.0'})
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.loads(r.read().decode())
        return f"authenticated, {len(d.get('messages', []))} messages"
if TOKEN != "PASTE_YOUR_TOKEN_HERE":
    test("Auth + poll", auth_test)
else:
    print("  [SKIP] Auth (paste your token in TOKEN variable)")

print()
print("=== Diagnosis ===")
if not dns_ok:
    print("DNS FAILED: Your machine cannot resolve madmorrigan.com.")
    print("  - Check: can you open https://madmorrigan.com in a browser?")
    print("  - Try: nslookup madmorrigan.com")
    print("  - Possible: corporate VPN, DNS filtering, or hosts file issue")
elif not tcp_ok:
    print("TCP FAILED: DNS works but port 443 is blocked.")
    print("  - Check firewall / antivirus (Defender has flagged our tooling before)")
else:
    print("Network layers OK. Issue is in application code or token.")
