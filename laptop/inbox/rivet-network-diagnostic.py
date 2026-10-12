#!/usr/bin/env python3
"""
Rivet Broad Network Diagnostic - tests if the environment is filtered/restricted.
Tests DNS + TCP for multiple hosts to identify patterns.
"""
import socket

HOSTS = [
    ("github.com", "GitHub - repo packets (known working)"),
    ("madmorrigan.com", "Bluehost - MQ queue (known failing)"),
    ("google.com", "Google - general connectivity"),
    ("api.github.com", "GitHub API"),
    ("raw.githubusercontent.com", "GitHub raw content"),
    ("bluehost.com", "Bluehost main site"),
]

print("=== Broad Network Diagnostic ===")
print()

results = {}
for host, desc in HOSTS:
    # DNS test
    try:
        ip = socket.gethostbyname(host)
        dns = f"OK ({ip})"
        dns_ok = True
    except Exception as e:
        dns = f"FAIL ({type(e).__name__})"
        dns_ok = False
        results[host] = "DNS_FAIL"
        print(f"{host}")
        print(f"  {desc}")
        print(f"  DNS: {dns}")
        print(f"  TCP: SKIP (no IP)")
        print()
        continue

    # TCP test
    try:
        s = socket.create_connection((host, 443), timeout=10)
        s.close()
        tcp = "OK (port 443 reachable)"
        results[host] = "OK"
    except Exception as e:
        tcp = f"FAIL ({type(e).__name__}: {e})"
        results[host] = "TCP_FAIL"

    print(f"{host}")
    print(f"  {desc}")
    print(f"  DNS: {dns}")
    print(f"  TCP: {tcp}")
    print()

print("=== Summary ===")
ok = [h for h, r in results.items() if r == "OK"]
dns_fail = [h for h, r in results.items() if r == "DNS_FAIL"]
tcp_fail = [h for h, r in results.items() if r == "TCP_FAIL"]

print(f"Working: {', '.join(ok) if ok else 'none'}")
if dns_fail:
    print(f"DNS blocked: {', '.join(dns_fail)}")
if tcp_fail:
    print(f"TCP blocked: {', '.join(tcp_fail)}")

print()
if dns_fail and not tcp_fail:
    print("Pattern: DNS filtering — specific hosts are blocked at DNS level.")
    print("This suggests a filtering proxy or DNS policy, not a general outage.")
elif tcp_fail:
    print("Pattern: TCP blocking — DNS works but connections are refused.")
    print("This suggests a firewall blocking outbound HTTPS to specific hosts.")
elif not dns_fail and not tcp_fail:
    print("Pattern: All hosts reachable — network is fine, issue is application-level.")
