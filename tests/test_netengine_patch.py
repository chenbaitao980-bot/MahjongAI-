"""Unit tests for remote.noconfig.hijack.netengine_patch.

Coverage matrix (per task PRD):
  (a) XXTEA roundtrip: decrypt(encrypt(x)) == x for synthetic + real APK source
  (b) Counter injection: `XH._srsConnFailCount = ... or 0` lands at the top once,
      idempotent on re-application.
  (c) `_50` rotation: replaces `return list[1]` inside getTcpConnectInfoByGroupId
      with the rotation expression; leaves the abroad/fallback `return list[1]`
      alone.
  (d) Link-state FAIL hook: every addLinkStateScriptFunc callback gains a
      `linkState ~= LINK_STATE_SUCCESS` branch that bumps the counter and
      reissues startTcp.
"""
from __future__ import annotations

import unittest

from remote.noconfig.hijack import netengine_patch
from remote.noconfig.hijack.netconf_patch import unwrap_luac, wrap_luac
from remote.noconfig.hijack.netengine_patch import (
    _FAIL_MARK,
    _NEW_RETURN_EXPR,
    _SENTINEL,
    patch_from_apk,
    patch_netengine,
)


REAL_APK = "apk/game_base.apk"


# A trimmed-down synthetic NetEngine.lua used for fast structural tests;
# mirrors apk/_dump_NetEngine.lua but only the lines we transform.
SYNTHETIC_NETENGINE = """\
local NetEngine = class("NetEngine")

NetEngine.EVENT_NET_ENGINE_LINKSTATUS_CHANGED = "EVENT_NET_ENGINE_LINKSTATUS_CHANGED"

function NetEngine:startTcpPB(groupId, protocolData)
    local newTcp = require("app.Net.TcpConnection").new(groupId)
    newTcp:addLinkStateScriptFunc(function(linkState)
        if linkState == XH.SRS_LINK_STATE.LINK_STATE_SUCCESS then
            self:sendProtoBuf(protocolData.reqData, protocolData.processID, protocolData.appID, protocolData.groupId)
        end
        self:dispatchEvent({name = NetEngine.EVENT_NET_ENGINE_LINKSTATUS_CHANGED})
    end)
    newTcp:connect(connectInfo.id, connectInfo.ip, tostring(connectInfo.port), 10000)
end

function NetEngine:sendRawData(XY_ID, protocol, processID, appID, groupId)
    local tcp = require("app.Net.TcpConnection").new(groupId)
    tcp:addLinkStateScriptFunc(function(linkState)
        if linkState == XH.SRS_LINK_STATE.LINK_STATE_SUCCESS then
            NetEngine.sendRawData(self, XY_ID, protocol, processID, appID, groupId)
        end
        self:dispatchEvent({name = NetEngine.EVENT_NET_ENGINE_LINKSTATUS_CHANGED})
    end)
    tcp:connect(connectInfo.id, connectInfo.ip, tostring(connectInfo.port), 10000)
end

function NetEngine:startTcp(groupId, protocolData)
    local newTcp = require("app.Net.TcpConnection").new(groupId)
    newTcp:addLinkStateScriptFunc(function(linkState)
        if linkState == XH.SRS_LINK_STATE.LINK_STATE_SUCCESS then
            self:sendProtocol(protocolData.protocol, protocolData.processID, protocolData.appID, protocolData.groupId)
        end
        self:dispatchEvent({name = NetEngine.EVENT_NET_ENGINE_LINKSTATUS_CHANGED})
    end)
    newTcp:connect(connectInfo.id, connectInfo.ip, tostring(connectInfo.port), 10000)
end

function NetEngine:getTcpConnectInfoByGroupId(groupId)
    local list = XH.LOCAL_TCP_LIST[groupId] or {}
    if XH.areaData:isSupportSRS50() then
        for k,v in pairs(XH.LOCAL_TCP_LIST_50) do
            if k == groupId then
                list = XH.LOCAL_TCP_LIST_50[groupId]
                if list and #list > 0 then
                    return list[1]
                end
            end
        end
    end
    self:getSRSConfigListFromFile(groupId, list)
    if list then
        local len = #list
        if len > 1 then
            local randomNum = math.random(1, len)
            return list[randomNum]
        else
            return list[1]
        end
    else
        return nil
    end
end

return NetEngine
"""


def _wrap_synthetic() -> bytes:
    """Encrypt SYNTHETIC_NETENGINE the same way the APK ships NetEngine.luac."""
    return wrap_luac(SYNTHETIC_NETENGINE)


class XXTEARoundtripTest(unittest.TestCase):
    """(a) XXTEA encrypt/decrypt roundtrip is bytes-faithful for the patched source."""

    def test_synthetic_source_roundtrip(self):
        raw = _wrap_synthetic()
        decoded = unwrap_luac(raw)
        # Roundtrip-tolerant: pad NUL is stripped via length tail; allow trailing \n.
        self.assertEqual(decoded.rstrip("\n"), SYNTHETIC_NETENGINE.rstrip("\n"))

    def test_patch_roundtrip_keeps_decryption_lossless(self):
        raw = _wrap_synthetic()
        result = patch_netengine(raw)
        # The roundtrip assertion is also done internally; here we re-verify by
        # decrypting again and checking text equality with source_after.
        decoded = unwrap_luac(result.new_luac)
        self.assertEqual(decoded.rstrip("\n"), result.source_after.rstrip("\n"))


class CounterInjectionTest(unittest.TestCase):
    """(b) Global `_srsConnFailCount` is injected and the patch is idempotent."""

    def test_counter_present_after_patch(self):
        raw = _wrap_synthetic()
        result = patch_netengine(raw)
        self.assertIn(_SENTINEL, result.source_after)
        self.assertIn(
            "XH._srsConnFailCount = XH._srsConnFailCount or 0",
            result.source_after,
        )

    def test_counter_only_injected_once(self):
        raw = _wrap_synthetic()
        result = patch_netengine(raw)
        # Sentinel appears exactly once.
        self.assertEqual(result.source_after.count(_SENTINEL), 1)
        # Re-running on patched bytes is a no-op.
        result2 = patch_netengine(result.new_luac)
        self.assertEqual(result2.replacements, 0)
        self.assertEqual(result2.source_after, result.source_after)


class FiftyBranchRotationTest(unittest.TestCase):
    """(c) `_50` branch rewrites `return list[1]` to fail-count rotation."""

    def test_50_branch_uses_rotation_expression(self):
        raw = _wrap_synthetic()
        result = patch_netengine(raw)
        self.assertIn(_NEW_RETURN_EXPR, result.source_after)
        # The exact rewritten expression appears once.
        self.assertEqual(result.source_after.count(_NEW_RETURN_EXPR), 1)

    def test_fallback_return_list_one_preserved(self):
        """The trailing `return list[1]` (fallback when len <= 1) is untouched."""
        raw = _wrap_synthetic()
        result = patch_netengine(raw)
        # Synthetic source has exactly one fallback `return list[1]` outside the
        # _50 branch (in the `else` branch of `if len > 1 then ... else ...`).
        self.assertEqual(result.source_after.count("return list[1]"), 1)


class LinkStateCallbackInjectionTest(unittest.TestCase):
    """(d) Every addLinkStateScriptFunc callback gains a FAIL bump branch."""

    def test_each_callback_gets_fail_branch(self):
        raw = _wrap_synthetic()
        result = patch_netengine(raw)
        src = result.source_after
        self.assertIn(_FAIL_MARK, src)
        # Synthetic source has 3 connect callbacks (startTcpPB/sendRawData/startTcp).
        self.assertEqual(src.count(_FAIL_MARK), 3)
        # Each FAIL branch performs the bump + reconnect.
        self.assertEqual(
            src.count("XH._srsConnFailCount = (XH._srsConnFailCount or 0) + 1"), 3
        )
        self.assertEqual(
            src.count("NetEngine.startTcp(self, groupId, protocolData)"), 3
        )

    def test_fail_branch_only_runs_when_state_not_success(self):
        raw = _wrap_synthetic()
        result = patch_netengine(raw)
        # The injected guard uses the `~=` comparison against LINK_STATE_SUCCESS.
        self.assertIn(
            "if linkState ~= XH.SRS_LINK_STATE.LINK_STATE_SUCCESS then",
            result.source_after,
        )

    def test_idempotent_when_already_patched(self):
        raw = _wrap_synthetic()
        first = patch_netengine(raw)
        second = patch_netengine(first.new_luac)
        self.assertEqual(second.replacements, 0)
        self.assertEqual(second.source_after, first.source_after)


class RealApkPatchTest(unittest.TestCase):
    """End-to-end: applying to the real APK NetEngine.luac succeeds + roundtrips."""

    def test_real_apk_patch_roundtrips_and_keeps_signals(self):
        import os

        if not os.path.exists(REAL_APK):
            self.skipTest("apk/game_base.apk not present in this environment")
        result = patch_from_apk(REAL_APK)
        src = result.source_after
        # All three signals present.
        self.assertIn(_SENTINEL, src)
        self.assertIn(_NEW_RETURN_EXPR, src)
        self.assertIn(_FAIL_MARK, src)
        # Re-decrypt new luac; must equal patched source.
        self.assertEqual(unwrap_luac(result.new_luac).rstrip("\n"), src.rstrip("\n"))
        # Real dump has 3 connect callbacks (startTcpPB/sendRawData/startTcp).
        self.assertEqual(src.count(_FAIL_MARK), 3)
        # The original `return list[1]` count: one in `_50` branch (now rewritten)
        # plus one fallback `return list[1]`. Post-patch only the fallback remains.
        self.assertEqual(src.count("return list[1]"), 1)


if __name__ == "__main__":
    unittest.main()
