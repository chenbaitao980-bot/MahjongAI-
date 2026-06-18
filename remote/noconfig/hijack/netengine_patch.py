"""netengine_patch.py -- decrypt / patch / re-encrypt the game's NetEngine.luac.

Same XXTEA + SIGN format as NetConf.luac (see netconf_patch.py for the crypto
write-up). NetEngine.luac uses the inc=True wrapping (4-byte length tail),
which unwrap_luac/wrap_luac in netconf_patch already handle correctly.

Goal: ECS failover Path Y. When ECS goes down the phone (4G or strange WiFi)
must still be able to reach the real lobby / coin-game servers without any
PC-side intervention. Three injections:

  1. Inject a global counter `XH._srsConnFailCount = XH._srsConnFailCount or 0`
     near the top of the file (idempotent, safe re-init).

  2. Replace the `_50` branch hard-coded `return list[1]` inside
     `getTcpConnectInfoByGroupId` with
         `return list[(XH._srsConnFailCount % #list) + 1]`
     so the coin-game group (5067/5167), whose list NetConf now writes as
     `{ECS_entry, real_entry}`, picks ECS by default and switches to the real
     server once `_srsConnFailCount` advances.

  3. In every TcpConnection link-state callback inside `connect()` call sites,
     append a FAIL branch that bumps `XH._srsConnFailCount` and triggers a
     fresh `NetEngine:startTcp(groupId, protocolData)` so the next selection
     points at the alternate IP without depending on the UI to retry.

The patch is idempotent: re-applying on an already-patched source is a no-op
(detected via a sentinel comment marker).

Pure offline tool. Does not depend on the noconfig runtime.
"""
from __future__ import annotations

import argparse
import logging
import re
import zipfile
from dataclasses import dataclass

# Reuse the XXTEA + luac wrap helpers from netconf_patch.
from remote.noconfig.hijack.netconf_patch import (
    KEY,
    SIGN,
    PatchResult,
    unwrap_luac,
    wrap_luac,
    xxtea_decrypt,
    xxtea_encrypt,
)

logger = logging.getLogger(__name__)

# APK entry for NetEngine.luac
APK_NETENGINE_ENTRY = "assets/src/app/Net/NetEngine.luac"

# Sentinel used to detect "already patched" -- placed right after the counter init.
_SENTINEL = "-- [path-y] netengine fail-count rotation injected"

# The global init line we inject at the very top of the file.
_COUNTER_INIT = (
    "XH = XH or {}\n"
    "XH._srsConnFailCount = XH._srsConnFailCount or 0\n"
    + _SENTINEL + "\n"
)


def _inject_counter(source: str) -> tuple[str, int]:
    """Prepend `XH._srsConnFailCount = XH._srsConnFailCount or 0` (idempotent).

    NetEngine.lua starts with `local NetEngine = class("NetEngine")`. We insert
    the counter init **before** that line so it runs once at module load time.
    """
    if _SENTINEL in source:
        return source, 0
    # Insert at file start; keep original content right after.
    return _COUNTER_INIT + source, 1


# Match the `_50` branch: capture the leading whitespace + `return list[1]` line.
_RETURN_LIST1_RE = re.compile(
    r"(?P<indent>[ \t]*)return\s+list\s*\[\s*1\s*\]"
)

_NEW_RETURN_EXPR = "return list[(XH._srsConnFailCount % #list) + 1]"


def _patch_50_return(source: str) -> tuple[str, int]:
    """Replace the `_50` branch's `return list[1]` with the rotation expression.

    Locate `function NetEngine:getTcpConnectInfoByGroupId(...)` and rewrite the
    first `return list[1]` we find inside its body (which is the _50 branch --
    the body's only `return list[1]`; the abroad / fallback paths use random or
    `return nil`). Idempotent: if the rotation expression is already present we
    return 0.
    """
    fn = re.search(
        r"function\s+NetEngine\s*:\s*getTcpConnectInfoByGroupId\b", source
    )
    if not fn:
        return source, 0
    # Find the matching `end` for this function (top-level `end` at column 0
    # following the `function` line). We do not strictly need brace-matching
    # because Lua functions are terminated by `end` keywords, but a robust
    # heuristic is "the next `\nend\n` after the function header".
    body_start = fn.end()
    end_match = re.search(r"\nend\b", source[body_start:])
    if not end_match:
        return source, 0
    body_end = body_start + end_match.start()
    body = source[body_start:body_end]

    if _NEW_RETURN_EXPR in body:
        return source, 0

    new_body, count = _RETURN_LIST1_RE.subn(
        lambda m: m.group("indent") + _NEW_RETURN_EXPR,
        body,
        count=1,
    )
    if count == 0:
        return source, 0
    return source[:body_start] + new_body + source[body_end:], count


# Match a link-state callback we want to extend. The callback shape (consistent
# across `startTcpPB`, `sendRawData`, `startTcp`):
#
#     (newTcp|tcp):addLinkStateScriptFunc(function(linkState)
#         if linkState == XH.SRS_LINK_STATE.LINK_STATE_SUCCESS then
#             ... reissue the original send ...
#         end
#         self:dispatchEvent({name = NetEngine.EVENT_NET_ENGINE_LINKSTATUS_CHANGED})
#     end)
#
# We append a FAIL branch right before the closing `end)` that:
#   - bumps the global counter on any non-SUCCESS state,
#   - calls `NetEngine.startTcp(self, groupId, protocolData)` to re-trigger
#     connection selection (which now picks the next IP via the counter).
#
_CALLBACK_RE = re.compile(
    r"(?P<head>(newTcp|tcp)\s*:\s*addLinkStateScriptFunc\s*\(\s*function\s*\(\s*linkState\s*\)\s*\n)"
    r"(?P<body>.*?)"
    r"(?P<tail>\n[ \t]*end\s*\)\s*\n)",
    re.DOTALL,
)

_FAIL_MARK = "-- [path-y] failover bump"

_FAIL_BLOCK_TEMPLATE = (
    "{indent}if linkState ~= XH.SRS_LINK_STATE.LINK_STATE_SUCCESS then  {mark}\n"
    "{indent}    XH._srsConnFailCount = (XH._srsConnFailCount or 0) + 1\n"
    "{indent}    if protocolData then\n"
    "{indent}        NetEngine.startTcp(self, groupId, protocolData)\n"
    "{indent}    end\n"
    "{indent}end\n"
)


def _patch_link_state_callbacks(source: str) -> tuple[str, int]:
    """Append FAIL bump + auto reconnect to every addLinkStateScriptFunc body.

    Idempotent: skip blocks that already contain the fail-mark sentinel.
    Returns the count of callbacks rewritten.
    """
    count = 0

    def _replace(match: re.Match) -> str:
        nonlocal count
        body = match.group("body")
        if _FAIL_MARK in body:
            return match.group(0)
        # Extract the indent of the first non-empty body line so the FAIL block
        # aligns with the existing `if linkState == ... then` block.
        indent = ""
        for line in body.splitlines():
            stripped = line.lstrip(" \t")
            if stripped:
                indent = line[: len(line) - len(stripped)]
                break
        if not indent:
            indent = "        "
        fail_block = _FAIL_BLOCK_TEMPLATE.format(indent=indent, mark=_FAIL_MARK)
        # Insert FAIL block right before the closing `end)` (i.e. between body
        # and tail). The dispatchEvent line is part of the body and runs on
        # every state change, including FAIL -- we keep that ordering.
        new_body = body.rstrip("\n") + "\n" + fail_block.rstrip("\n")
        count += 1
        return match.group("head") + new_body + match.group("tail")

    new_source = _CALLBACK_RE.sub(_replace, source)
    return new_source, count


def patch_netengine(raw_luac: bytes, *, key: bytes = KEY) -> PatchResult:
    """Main entrypoint: original NetEngine.luac bytes -> patched bytes (with roundtrip check).

    Three injections (see module docstring). All idempotent.
    """
    source = unwrap_luac(raw_luac, key)
    src, n_counter = _inject_counter(source)
    src, n_return = _patch_50_return(src)
    src, n_callbacks = _patch_link_state_callbacks(src)

    if n_return == 0 and _NEW_RETURN_EXPR not in src:
        raise ValueError(
            "Failed to locate `return list[1]` in NetEngine:getTcpConnectInfoByGroupId; "
            "verify the dump matches apk/_dump_NetEngine.lua"
        )
    if n_callbacks == 0 and _FAIL_MARK not in src:
        raise ValueError(
            "Failed to locate any addLinkStateScriptFunc callback; "
            "verify the dump matches apk/_dump_NetEngine.lua"
        )

    new_luac = wrap_luac(src, key)

    # Roundtrip check: decrypt new luac -> must equal `src` (allow trailing \n).
    roundtrip = unwrap_luac(new_luac, key)
    if roundtrip.rstrip("\n") != src.rstrip("\n"):
        raise AssertionError("XXTEA roundtrip mismatch on NetEngine.luac")
    # Sanity: all three signals present.
    if _SENTINEL not in roundtrip:
        raise AssertionError("counter init missing after roundtrip")
    if _NEW_RETURN_EXPR not in roundtrip:
        raise AssertionError("`_50` rotation expr missing after roundtrip")
    if _FAIL_MARK not in roundtrip:
        raise AssertionError("link-state FAIL hook missing after roundtrip")

    logger.info(
        "[netengine] patched: counter=%d return50=%d callbacks=%d",
        n_counter, n_return, n_callbacks,
    )

    return PatchResult(source, src, n_counter + n_return + n_callbacks, new_luac)


def patch_from_apk(apk_path: str, **kw) -> PatchResult:
    with zipfile.ZipFile(apk_path) as z:
        raw = z.read(APK_NETENGINE_ENTRY)
    return patch_netengine(raw, **kw)


# --- CLI / selftest ---------------------------------------------------------

def _selftest() -> None:
    import os

    apk = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "apk", "game_base.apk")
    )
    res = patch_from_apk(apk)
    src = res.source_after

    # Required textual signals.
    assert _SENTINEL in src, "counter sentinel missing"
    assert "XH._srsConnFailCount = XH._srsConnFailCount or 0" in src
    assert _NEW_RETURN_EXPR in src, "rotation expression missing"
    assert _FAIL_MARK in src, "fail-mark missing"
    # The original `return list[1]` (in the _50 branch) must be gone now.
    # Note: the abroad / fallback random path uses `return list[1]` only when
    # `len <= 1`; we did NOT touch that branch. Confirm by counting:
    # only one match should remain (the abroad/fallback `else return list[1]`).
    # The dump has exactly one `return list[1]` originally inside the _50 branch
    # plus one `return list[1]` in the trailing fallback branch.
    remaining = src.count("return list[1]")
    assert remaining == 1, f"expected 1 leftover `return list[1]` (fallback), got {remaining}"
    print(f"[OK] counter sentinel + rotation expr + FAIL hook injected")
    print(f"[OK] remaining `return list[1]` (fallback only): {remaining}")

    # Roundtrip already validated inside patch_netengine; double-check size.
    print(f"[OK] new luac size: {len(res.new_luac)} bytes (raw source: {len(src)} chars)")

    # Idempotence: run again on the patched bytes -> should be a no-op.
    res2 = patch_netengine(res.new_luac)
    assert res2.replacements == 0, f"second pass should be no-op, got {res2.replacements}"
    assert res2.source_after == src, "second-pass output diverged"
    print("[OK] idempotent: second pass produced 0 replacements")

    print("\n[PASS] netengine_patch selftest passed")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="decrypt/patch/re-encrypt NetEngine.luac for ECS failover Path Y"
    )
    ap.add_argument("--apk", help="game APK path (default: ./apk/game_base.apk)")
    ap.add_argument("--out", help="write patched NetEngine.luac to this path")
    ap.add_argument("--dump-source", help="optional: also write patched plain source for review")
    ap.add_argument("--selftest", action="store_true", help="run offline selftest and exit")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    if args.selftest:
        _selftest()
        return

    import os
    apk = args.apk or os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "apk", "game_base.apk")
    )
    res = patch_from_apk(apk)
    if args.out:
        with open(args.out, "wb") as f:
            f.write(res.new_luac)
        print(f"[OK] wrote {args.out} ({len(res.new_luac)} bytes)")
    if args.dump_source:
        with open(args.dump_source, "w", encoding="utf-8") as f:
            f.write(res.source_after)
        print(f"[OK] wrote source dump to {args.dump_source}")
    print(f"[OK] {res.replacements} injections applied")


if __name__ == "__main__":
    main()
