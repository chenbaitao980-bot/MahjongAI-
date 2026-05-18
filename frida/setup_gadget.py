"""Deploy Frida Gadget to emulator in stealth mode.

Prerequisites (user must do manually):
  1. Enable Root in MuMu (Settings -> Other -> Root)
  2. Download frida-gadget-{ver}-android-x86_64.so from GitHub releases
  3. pip install frida-tools (version must match gadget)

Usage:
    python frida/setup_gadget.py --gadget path/to/frida-gadget.so [--adb PATH] [--device SERIAL]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

DEFAULT_ADB = r"D:\Program Files\Netease\MuMu\nx_main\adb.exe"
DEFAULT_DEVICE = "127.0.0.1:16384"
DISGUISED_GADGET = ".libsys_perf.so"
DISGUISED_HOOK = ".hook_payload.js"
DEVICE_TMP = "/data/local/tmp"
GAME_PACKAGE = "com.xm.zjgamecenter"


def adb_cmd(adb: str, device: str, *args: str) -> int:
    cmd = [adb, "-s", device] + list(args)
    print(f"  $ {' '.join(cmd)}")
    return subprocess.call(cmd)


def adb_shell(adb: str, device: str, shell_cmd: str) -> str:
    result = subprocess.run(
        [adb, "-s", device, "shell", shell_cmd],
        capture_output=True, text=True, timeout=10,
    )
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description="Deploy Frida Gadget (stealth)")
    parser.add_argument("--gadget", required=True, help="Path to frida-gadget.so")
    parser.add_argument("--adb", default=DEFAULT_ADB, help="ADB path")
    parser.add_argument("--device", default=DEFAULT_DEVICE, help="Device serial")
    args = parser.parse_args()

    if not os.path.isfile(args.gadget):
        print(f"[ERROR] Gadget file not found: {args.gadget}")
        return 1

    hook_js = os.path.join(os.path.dirname(__file__), "hook_recv.js")
    gadget_config = os.path.join(os.path.dirname(__file__), "gadget_config.json")

    print(f"[1/5] Pushing gadget as {DISGUISED_GADGET}...")
    adb_cmd(args.adb, args.device, "push", args.gadget, f"{DEVICE_TMP}/{DISGUISED_GADGET}")

    print(f"\n[2/5] Pushing hook script as {DISGUISED_HOOK}...")
    adb_cmd(args.adb, args.device, "push", hook_js, f"{DEVICE_TMP}/{DISGUISED_HOOK}")

    print(f"\n[3/5] Pushing gadget config...")
    config_name = DISGUISED_GADGET.replace(".so", ".config.so")
    adb_cmd(args.adb, args.device, "push", gadget_config, f"{DEVICE_TMP}/{config_name}")

    print(f"\n[4/5] Setting permissions...")
    adb_shell(args.adb, args.device, f"su -c 'chmod 755 {DEVICE_TMP}/{DISGUISED_GADGET}'")

    print(f"\n[5/5] Deployment complete.")
    print()
    print("=" * 50)
    print("To launch the game with Gadget injection:")
    print()
    print(f"  adb -s {args.device} shell")
    print(f"  su -c 'setprop wrap.{GAME_PACKAGE} LD_PRELOAD={DEVICE_TMP}/{DISGUISED_GADGET}'")
    print(f"  am force-stop {GAME_PACKAGE}")
    print(f"  monkey -p {GAME_PACKAGE} 1")
    print()
    print("Captured data will be written to:")
    print(f"  {DEVICE_TMP}/.game_capture.jsonl")
    print("=" * 50)
    return 0


if __name__ == "__main__":
    sys.exit(main())
