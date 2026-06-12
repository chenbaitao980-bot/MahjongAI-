"""Attach to the gadget-injected game and load hook_lobby_key.js (no TUI).

The game APK embeds a Frida gadget in listen mode (unix:frida:com.xm.zjgamecenter).
The `frida` CLI needs a console (fails here), so this uses the frida Python API
to attach + inject the hook and stream its send() logs.

Flow:
  1. START THE GAME on the phone first (so the gadget is listening).
  2. python frida/run_lobby_hook.py
  3. Do a full login on the phone (into the lobby).
  4. Ctrl-C here, then: adb pull /data/local/tmp/.lobby_dump.jsonl
"""
from __future__ import annotations

import json
import os
import sys
import time

import frida

GAME = "com.xm.zjgamecenter"
# optional arg: hook script filename (in frida/). default = hook_lobby_key.js
_SCRIPT_NAME = sys.argv[1] if len(sys.argv) > 1 else "hook_lobby_key.js"
SCRIPT = _SCRIPT_NAME if os.path.isabs(_SCRIPT_NAME) else os.path.join(os.path.dirname(__file__), _SCRIPT_NAME)
_tag = os.path.splitext(os.path.basename(SCRIPT))[0].replace("hook_", "")
OUT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "_%s_dump.jsonl" % _tag)

_counts = {}
_pids = {}
_out_fh = None


def on_message(msg, data):
    global _out_fh
    if msg.get("type") == "error":
        print("[ERROR]", msg.get("stack") or msg.get("description"), flush=True)
        return
    if msg.get("type") != "send":
        return
    p = msg.get("payload")
    if isinstance(p, dict) and p.get("_rec"):
        # a captured record -> write to local jsonl, tally
        if _out_fh is None:
            _out_fh = open(OUT, "a", encoding="utf-8")
        _out_fh.write(json.dumps(p, ensure_ascii=False) + "\n")
        _out_fh.flush()
        t = p.get("type", "?")
        _counts[t] = _counts.get(t, 0) + 1
        if t == "packMsg":
            pid = p.get("pid")
            _pids[pid] = _pids.get(pid, 0) + 1
        # surface the interesting ones live
        if t == "aes_set_key":
            print(f"[KEY] AES-{p.get('bits')} {p.get('key')}", flush=True)
        elif t == "packMsg" and p.get("pid") == 1147:
            print(f"[LOBBY pid=1147] msgid={p.get('msgid')} plain={p.get('payload')}", flush=True)
        elif t == "unzip":
            d = p.get("data", "")
            print(f"[UNZIP {p.get('fn')}] outLen={p.get('outLen')} head={d[:80]}", flush=True)
        # periodic tally
        total = sum(_counts.values())
        if total % 25 == 0:
            print(f"  ... {total} records  types={_counts}  pids={_pids}", flush=True)
    else:
        print("[hook]", p, flush=True)


def pick_target(dev):
    """Find the MAIN game process (the one the gadget is embedded in).

    Must be the exact package process (name == GAME), NOT sub-processes like
    `com.xm.zjgamecenter:GuardService` — the embedded gadget can only act on its
    own host process, which is the main app process.
    """
    try:
        procs = dev.enumerate_processes()
    except Exception as e:
        print("enumerate_processes failed:", e)
        procs = []
    # 1) exact main process name
    for p in procs:
        if p.name == GAME:
            print(f"found MAIN target: pid={p.pid} name={p.name}")
            return p.pid
    # 2) any zjgame process that is NOT a ':'-suffixed sub-process
    for p in procs:
        if "zjgame" in p.name and ":" not in p.name:
            print(f"found target: pid={p.pid} name={p.name}")
            return p.pid
    print("main game process not found; trying name 'Gadget'")
    return "Gadget"


def main():
    dev = frida.get_usb_device(timeout=15)
    print("device:", dev.id, dev.name)
    target = pick_target(dev)
    session = dev.attach(target)
    print("attached to:", target)
    with open(SCRIPT, "r", encoding="utf-8") as f:
        code = f.read()
    script = session.create_script(code)
    script.on("message", on_message)
    script.load()
    print("=== hook loaded. DO THE LOGIN ON THE PHONE NOW (into the lobby). ===")
    print("=== capturing to /data/local/tmp/.lobby_dump.jsonl ; Ctrl-C / stop to end ===")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("stopping")
    finally:
        try:
            session.detach()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except frida.ServerNotRunningError as e:
        print("Frida not reachable:", e)
        print("Make sure the GAME IS RUNNING (gadget listens only while game runs).")
        sys.exit(1)
    except Exception as e:
        print("fatal:", type(e).__name__, e)
        sys.exit(1)
