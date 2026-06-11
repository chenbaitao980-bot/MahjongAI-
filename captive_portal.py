#!/usr/bin/env python3
# =====================================================================
# DEPRECATED (Option A 不需要)
# 纯 PSK 系统 VPN 方案（场景C / Option A）首次在手机上手填 3 个字段即可，
# 不需要热点 + captive portal 自动投送配置。本文件仅为旧的软路由/热点
# 方案保留，逻辑未动，不在 Option A 部署路径中使用。
# =====================================================================
"""
captive_portal.py — DNS + HTTP captive portal for Windows hotspot.

When phone connects to PC hotspot:
  1. Phone tries http://connectivitycheck.gstatic.com/generate_204
  2. DNS server redirects to this PC (192.168.137.1)
  3. HTTP server catches request → redirects to VPN setup page
  4. Phone shows "Sign in to network" → tap → see VPN credentials

Run as Administrator (DNS server needs port 53).
"""
import http.server
import os
import socket
import struct
import sys
import threading
import time

HOTSPOT_IP = "192.168.137.1"
VPN_PAGE_URL = "http://8.136.37.136:8000/vpn-setup"
LOCAL_VPN_PAGE = "http://{}/vpn-setup".format(HOTSPOT_IP)
REDIRECT_PORT = 80  # Captive portal HTTP
DNS_PORT = 53


# ─── DNS Server ──────────────────────────────────────────────
# Intercepts connectivitycheck.gstatic.com and redirects to HOTSPOT_IP
# All other queries forwarded to upstream DNS (8.8.8.8)

TARGET_DOMAIN = b"connectivitycheck.gstatic.com"


def build_dns_response(query_data, answer_ip):
    """Build a minimal DNS response pointing domain to answer_ip."""
    # query[0:2] = transaction ID
    transaction_id = query_data[:2]
    # Build response: flags (standard response, no error), 1 question, 1 answer
    flags = struct.pack(">H", 0x8180)  # QR=1, RA=1
    questions = struct.pack(">H", 1)
    answers = struct.pack(">H", 1)
    authority = struct.pack(">H", 0)
    additional = struct.pack(">H", 0)

    header = transaction_id + flags + questions + answers + authority + additional

    # Copy question section from query (skip header = 12 bytes)
    question = query_data[12:]

    # Build answer: pointer to name (0xc00c), type A (1), class IN (1),
    # TTL 60, data length 4, IP address
    answer = b"\xc0\x0c"  # pointer to name at offset 12
    answer += struct.pack(">H", 1)   # type A
    answer += struct.pack(">H", 1)   # class IN
    answer += struct.pack(">I", 60)  # TTL
    answer += struct.pack(">H", 4)   # data length
    answer += socket.inet_aton(answer_ip)

    return header + question + answer


def forward_dns(query_data):
    """Forward DNS query to upstream server."""
    try:
        upstream = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        upstream.settimeout(3)
        upstream.sendto(query_data, ("8.8.8.8", 53))
        response, _ = upstream.recvfrom(1024)
        upstream.close()
        return response
    except Exception:
        return None


def dns_thread():
    """DNS server: intercept gstatic.com, forward everything else."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", DNS_PORT))
    except PermissionError:
        print("[DNS] Port 53 requires Administrator. Run as admin.")
        return

    print("[DNS] Listening on port 53, intercepting gstatic.com")
    while True:
        try:
            data, addr = sock.recvfrom(512)
            if TARGET_DOMAIN in data:
                response = build_dns_response(data, HOTSPOT_IP)
                sock.sendto(response, addr)
                print("[DNS] Intercepted gstatic.com from {}".format(addr[0]))
            else:
                forwarded = forward_dns(data)
                if forwarded:
                    sock.sendto(forwarded, addr)
        except Exception as e:
            print("[DNS] Error:", e)


# ─── Captive Portal HTTP ─────────────────────────────────────

CAPTIVE_RESPONSE = """HTTP/1.1 302 Found
Location: {vpn_url}
Content-Length: 0
Connection: close

""".format(vpn_url=VPN_PAGE_URL).encode()


class CaptiveHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        # Android captive portal check: redirect to VPN setup
        if "generate_204" in self.path or "gen_204" in self.path:
            self.send_response(302)
            self.send_header("Location", VPN_PAGE_URL)
            self.end_headers()
            print("[Portal] Captive portal triggered for {}".format(self.client_address[0]))
            return
        # Apple captive portal check: return success (don't block)
        if any(x in self.path for x in ["hotspot-detect", "success.txt", "captive.apple"]):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>")
            return
        # Everything else → redirect to VPN setup
        self.send_response(302)
        self.send_header("Location", VPN_PAGE_URL)
        self.end_headers()

    def log_message(self, fmt, *args):
        print("[Portal] {} - {}".format(self.client_address[0], args[0]))


# ─── Raw Socket Captive (catches requests before they go to relay) ──

def raw_captive_thread():
    """Serve captive portal redirects on port 80 via raw HTTP.
    Redirect everything to VPN setup page."""
    host = "0.0.0.0"
    port = REDIRECT_PORT
    server = http.server.HTTPServer((host, port), CaptiveHandler)
    print("[Portal] Captive portal on port {}".format(port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


# ─── Main ────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("Hotspot Captive Portal for Mahjong VPN")
    print("=" * 55)
    print("When phone connects to hotspot (192.168.137.x):")
    print("  → DNS: intercepts gstatic.com → {}".format(HOTSPOT_IP))
    print("  → HTTP: redirects to {}".format(VPN_PAGE_URL))
    print("")

    # Start DNS in background
    dns = threading.Thread(target=dns_thread, daemon=True)
    dns.start()
    time.sleep(0.5)

    # Start HTTP captive portal
    raw_captive_thread()


if __name__ == "__main__":
    main()
