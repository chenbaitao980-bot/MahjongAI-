"""Safety self-check: scan the emulator for detectable artifacts.

Usage:
    python scripts/check_detection.py [--adb PATH] [--device SERIAL]
"""

from __future__ import annotations

import argparse
import subprocess
import sys

DEFAULT_ADB = r"D:\Program Files\Netease\MuMu\nx_main\adb.exe"
DEFAULT_DEVICE = "127.0.0.1:16384"

SUSPICIOUS_PROCESSES = [
    "tcpdump", "frida", "frida-server", "capture", "hook", "inject",
    "xposed", "magisk", "riru", "lsposed",
]

SUSPICIOUS_PORTS = [27042, 27043, 8080, 8888, 9090]

EMULATOR_PROPS = [
    ("ro.kernel.qemu", "1"),
    ("ro.hardware.chipname", "ranchu"),
    ("ro.product.model", "sdk_gphone"),
    ("ro.build.flavor", "sdk_gphone"),
    ("init.svc.qemud", "running"),
]


def adb_shell(adb_path: str, device: str, cmd: str) -> str:
    full = [adb_path, "-s", device, "shell", cmd]
    try:
        result = subprocess.run(
            full, capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip()
    except Exception as exc:
        return f"[ERROR] {exc}"


def check_processes(adb: str, device: str) -> list[dict]:
    findings = []
    output = adb_shell(adb, device, "ps -A")
    for line in output.splitlines():
        lower = line.lower()
        for name in SUSPICIOUS_PROCESSES:
            if name in lower:
                findings.append({
                    "level": "CRITICAL",
                    "category": "process",
                    "detail": f"Suspicious process found: {line.strip()}",
                })
    return findings


def check_ports(adb: str, device: str) -> list[dict]:
    findings = []
    output = adb_shell(adb, device, "netstat -tlnp 2>/dev/null || ss -tlnp 2>/dev/null")
    for line in output.splitlines():
        for port in SUSPICIOUS_PORTS:
            if f":{port}" in line:
                findings.append({
                    "level": "CRITICAL",
                    "category": "port",
                    "detail": f"Suspicious port {port} open: {line.strip()}",
                })
    return findings


def check_emulator_fingerprint(adb: str, device: str) -> list[dict]:
    findings = []
    for prop, bad_value in EMULATOR_PROPS:
        value = adb_shell(adb, device, f"getprop {prop}")
        if bad_value.lower() in value.lower() and value:
            findings.append({
                "level": "WARNING",
                "category": "fingerprint",
                "detail": f"Emulator fingerprint: {prop}={value}",
            })
    return findings


def check_frida_maps(adb: str, device: str) -> list[dict]:
    findings = []
    output = adb_shell(adb, device, "cat /proc/self/maps 2>/dev/null")
    for line in output.splitlines():
        lower = line.lower()
        if "frida" in lower or "gadget" in lower:
            findings.append({
                "level": "CRITICAL",
                "category": "memory",
                "detail": f"Frida memory mapping: {line.strip()}",
            })
    return findings


def check_tmp_binaries(adb: str, device: str) -> list[dict]:
    findings = []
    output = adb_shell(adb, device, "ls -la /data/local/tmp/ 2>/dev/null")
    for line in output.splitlines():
        lower = line.lower()
        for name in ["frida", "tcpdump", "gadget", "hook", "inject"]:
            if name in lower:
                findings.append({
                    "level": "WARNING",
                    "category": "file",
                    "detail": f"Suspicious file in /data/local/tmp/: {line.strip()}",
                })
    return findings


def main():
    parser = argparse.ArgumentParser(description="Emulator safety self-check")
    parser.add_argument("--adb", default=DEFAULT_ADB, help="ADB path")
    parser.add_argument("--device", default=DEFAULT_DEVICE, help="Device serial")
    args = parser.parse_args()

    print(f"[*] Checking device {args.device} via {args.adb}")
    print()

    all_findings: list[dict] = []
    checks = [
        ("Process scan", check_processes),
        ("Port scan", check_ports),
        ("Emulator fingerprint", check_emulator_fingerprint),
        ("Frida memory maps", check_frida_maps),
        ("Temp directory scan", check_tmp_binaries),
    ]

    for name, fn in checks:
        print(f"[*] {name}...")
        findings = fn(args.adb, args.device)
        all_findings.extend(findings)
        if not findings:
            print(f"    CLEAN")
        for f in findings:
            print(f"    [{f['level']}] {f['detail']}")

    print()
    critical = sum(1 for f in all_findings if f["level"] == "CRITICAL")
    warnings = sum(1 for f in all_findings if f["level"] == "WARNING")

    if critical > 0:
        score = "DANGER"
        color = "\033[91m"
    elif warnings > 0:
        score = "WARNING"
        color = "\033[93m"
    else:
        score = "SAFE"
        color = "\033[92m"

    print(f"{'=' * 40}")
    print(f"  Score: {color}{score}\033[0m  ({critical} critical, {warnings} warnings)")
    print(f"{'=' * 40}")

    return 1 if critical > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
