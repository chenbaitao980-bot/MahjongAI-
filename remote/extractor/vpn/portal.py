#!/usr/bin/env python3
# =====================================================================
# DEPRECATED (Option A 不需要)
# 纯 PSK 系统 VPN 方案（场景C / Option A）首次在手机上手填 3 个字段即可，
# 不需要 portal 页面自动投送配置。本文件仅为旧方案保留，逻辑未动。
# =====================================================================
"""
portal.py — Simple HTTP server showing VPN setup instructions for phone.

No external dependencies (stdlib only, Python 3.6+).
Phone opens this page to get step-by-step setup guide with credentials.

Usage:
    python portal.py [--port 8080]
"""
from __future__ import print_function
import argparse
import http.server
import os
import sys
import signal

_HERE = os.path.dirname(os.path.abspath(__file__))


def _read_phone_setup():
    """Read phone-setup.txt from current dir or script dir."""
    for d in [".", _HERE]:
        path = os.path.join(d, "phone-setup.txt")
        if os.path.isfile(path):
            with open(path, "r") as f:
                return f.read()
    return None


def _build_html():
    setup = _read_phone_setup()
    if not setup:
        setup = ("phone-setup.txt not found.\n"
                 "Run vpn_configure.py --server-ip <ip> first.")

    # Parse credentials from setup text
    lines = setup.split("\n")
    creds = {}
    for line in lines:
        stripped = line.strip()
        for key in ("Server:", "pre-shared key:", "Username:", "Password:"):
            if key in stripped:
                val = stripped.split(":", 1)[-1].strip()
                if "pre-shared" in key:
                    creds["PSK"] = val
                elif key == "Server:":
                    creds["Server"] = val
                elif key == "Username:":
                    creds["Username"] = val
                elif key == "Password:":
                    creds["Password"] = val
                break

    server = creds.get("Server", "?")
    psk = creds.get("PSK", "?")
    username = creds.get("Username", "?")
    password = creds.get("Password", "?")

    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VPN Setup — Mahjong</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system,"Segoe UI",Roboto,sans-serif;
         max-width: 500px; margin: 20px auto; padding: 0 15px;
         background: #0f0f23; color: #ccc; line-height: 1.6; }}
  h1 {{ color: #fff; text-align: center; font-size: 22px; margin-bottom: 5px; }}
  .sub {{ text-align: center; color: #4f8; font-size: 13px; margin-bottom: 20px; }}
  .step {{ background: #1a1a2e; padding: 14px; margin: 10px 0;
           border-radius: 8px; border-left: 3px solid #4f8; }}
  .step b {{ color: #4f8; }}
  .cred {{ background: #0a0a15; padding: 12px; border-radius: 6px;
           font-family: monospace; font-size: 13px; word-break: break-all;
           margin: 8px 0; }}
  .cred span {{ color: #888; }}
  .note {{ font-size: 12px; color: #666; text-align: center; margin: 20px 0; }}
  .copy-btn {{ background: #2a2a4e; color: #ccc; border: 1px solid #4f8;
               padding: 4px 10px; border-radius: 4px; cursor: pointer;
               font-size: 11px; float: right; }}
  .copy-btn:hover {{ background: #3a3a5e; }}
</style>
</head>
<body>
<h1>Mahjong VPN Setup</h1>
<div class="sub">System VPN — no app needed, 1 minute setup</div>

<div class="step">
  <b>1.</b> Open Settings > Network & internet > VPN<br>
  <b>2.</b> Tap <b>+</b> (Add VPN), fill in:
  <div class="cred">
    <span>Name:</span> Mahjong<br>
    <span>Type:</span> IPSec IKEv2 PSK<br>
    <span>Server:</span> {server}<br>
    <span>IPSec identifier:</span> (leave empty)<br>
    <span>IPSec pre-shared key:</span> {psk}<br>
    <span>Username:</span> {username}<br>
    <span>Password:</span> {password}
  </div>
  <b>3.</b> Tap <b>Save</b>
</div>

<div class="step">
  <b>4.</b> Tap Settings icon next to Mahjong VPN<br>
  <b>5.</b> Enable <b>Always-on VPN</b> = ON<br>
  <b>6.</b> Done! VPN auto-connects on any network.
</div>

<div class="note">
  Split tunnel: only game server traffic through VPN. WeChat/browser use 4G directly.<br>
  After first setup, you never need to touch this again.
</div>
</body>
</html>""".format(server=server, psk=psk, username=username, password=password)


class PortalHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        html = _build_html().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def log_message(self, fmt, *args):
        print("[portal] {} - {}".format(self.client_address[0], args[0]))


def main():
    ap = argparse.ArgumentParser(description="VPN setup portal")
    ap.add_argument("--port", type=int, default=8080, help="Listen port")
    ap.add_argument("--host", default="0.0.0.0", help="Listen address")
    args = ap.parse_args()

    print("[portal] Starting on http://{}:{}/".format(args.host, args.port))
    if not _read_phone_setup():
        print("[portal] WARNING: phone-setup.txt not found. Run vpn_configure.py first.")
        print("[portal]          python vpn_configure.py --server-ip <public_ip>")

    server = http.server.HTTPServer((args.host, args.port), PortalHandler)

    def shutdown(sig, frame):
        print("\n[portal] Shutting down...")
        server.shutdown()
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
