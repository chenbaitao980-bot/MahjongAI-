import json
import os
import sys
import unittest
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from remote.noconfig.hijack import setup_mitm
from remote.noconfig.hijack.setup_mitm import (
    MitmAssets,
    RESCHECKER_FILE_KEY,
    RESENSURE_FILE_KEY,
)


class SetupMitmManifestPatchTest(unittest.TestCase):
    def make_assets(self, file_url_mode="official"):
        assets = object.__new__(MitmAssets)
        assets.bump_version = "9.9.9.103"
        assets.version = "9.9.9.103"
        assets.self_host = "8.136.37.136"
        assets.ecs_ip = "8.136.37.136"
        assets.tls_port = 443
        assets.file_url_mode = file_url_mode
        assets.served_md5 = "netconf-md5"
        assets.served_size = 100
        assets.served_name = "aa/netconf.luac"
        assets.netengine_md5 = "netengine-md5"
        assets.netengine_size = 400
        assets.netengine_name = "dd/netengine.luac"
        assets.resensure_md5 = "resensure-md5"
        assets.resensure_size = 200
        assets.resensure_name = "bb/resensure.luac"
        assets.reschecker_md5 = "reschecker-md5"
        assets.reschecker_size = 300
        assets.reschecker_name = "cc/reschecker.luac"
        assets.real_manifest_path = None
        assets.real_manifest_host = None
        assets.real_manifest_paths = set()
        assets.real_manifest_hosts_by_path = {}
        assets._inferred_manifest_url = None
        assets.hotfix_only_manifest = True
        assets.real_online_version = None
        return assets

    def test_project_manifest_patches_netconf_only_and_preserves_full_file_list(self):
        """默认 INJECT_LOBBY_CHECKER=False：只改写 NetConf，保留完整 file_list，
        ResEnsure/ResChecker 保持线上原版（手机从 CDN 取回原版以正常 clean_res，
        避免热更后黑屏）。file_list 不得被裁剪——否则游戏找不到其他资源会黑屏。"""
        assets = self.make_assets()
        manifest = {
            "version": "1.0.0.1",
            "file_url": ["https://cdn.example/files/"],
            "file_list": {
                "src/app/config/NetConf.luac": {"md5": "old", "size": 1, "name": "old/net.luac"},
                RESENSURE_FILE_KEY: {"md5": "old", "size": 2, "name": "old/resensure.luac"},
                RESCHECKER_FILE_KEY: {"md5": "old", "size": 3, "name": "old/reschecker.luac"},
                "subgame/main.luac": {"md5": "keep", "size": 4, "name": "keep/main.luac"},
            },
        }

        patched = json.loads(
            assets.patch_real_project_manifest(json.dumps(manifest).encode("utf-8")).decode("utf-8")
        )

        file_list = patched["file_list"]
        # 真实版未捕获 → 静态兜底 4 段支配版本（每分量远大于现实版本）
        self.assertEqual(patched["version"], "99.99.99.9999")
        self.assertTrue(patched["forbid_zip"])
        # 完整 file_list 必须保留（含非大厅资源）
        self.assertEqual(
            sorted(file_list.keys()),
            sorted(
                [
                    "src/app/config/NetConf.luac",
                    RESENSURE_FILE_KEY,
                    RESCHECKER_FILE_KEY,
                    "subgame/main.luac",
                ]
            ),
        )
        # 只有 NetConf 被改写
        self.assertEqual(file_list["src/app/config/NetConf.luac"]["md5"], assets.served_md5)
        # ResEnsure/ResChecker 保持原版（未注入），subgame 原样
        self.assertEqual(file_list[RESENSURE_FILE_KEY]["md5"], "old")
        self.assertEqual(file_list[RESCHECKER_FILE_KEY]["md5"], "old")
        self.assertEqual(file_list["subgame/main.luac"]["md5"], "keep")

    def _lobby_manifest_with_update_url(self):
        return {
            "version": "1.0.0.1",
            "file_url": ["https://gxb-oss.hzxuanming.com/yj/files/",
                         "https://gxb-cos.hzxuanming.com/yj/files/"],
            "update_url": [
                "https://gxb-api.hzxuanming.com/hotfix_update?env=1&appid=1073&version=1.0.0.59",
                "https://gxb-api-tx.hzxuanming.com/hotfix_update?env=1&appid=1073&version=1.0.0.59",
            ],
            "file_list": {
                "src/app/config/NetConf.luac": {"md5": "old", "size": 1, "name": "old/net.luac"},
                "subgame/main.luac": {"md5": "keep", "size": 4, "name": "keep/main.luac"},
            },
        }

    def test_project_manifest_rewrites_update_url_to_ecs(self):
        """★PR2：project.manifest 的 update_url host 改写为 ECS、path=/hotfix_update、
        保留原 query（appid/version 等），原 list 条数保持。"""
        from urllib.parse import urlsplit
        assets = self.make_assets()
        manifest = self._lobby_manifest_with_update_url()
        patched = json.loads(
            assets.patch_real_project_manifest(json.dumps(manifest).encode("utf-8")).decode("utf-8")
        )

        ecs_base = assets._ecs_base()
        uu = patched["update_url"]
        # 原 list 条数保持
        self.assertEqual(len(uu), 2)
        for orig, new in zip(manifest["update_url"], uu):
            # host=ECS、path=/hotfix_update
            self.assertTrue(new.startswith(ecs_base + "/hotfix_update"), new)
            self.assertEqual(urlsplit(new).hostname, "8.136.37.136")
            # 保留原 query 参数
            self.assertEqual(urlsplit(new).query, urlsplit(orig).query)
            self.assertIn("appid=1073", new)
            self.assertIn("version=1.0.0.59", new)

    def test_project_manifest_file_url_official_mode_preserved(self):
        """official 模式（默认）：file_url 保持官方原样（官方文件 4G 直连官方 CDN）。"""
        assets = self.make_assets(file_url_mode="official")
        manifest = self._lobby_manifest_with_update_url()
        patched = json.loads(
            assets.patch_real_project_manifest(json.dumps(manifest).encode("utf-8")).decode("utf-8")
        )
        self.assertEqual(patched["file_url"], manifest["file_url"])

    def test_project_manifest_file_url_ecs_mode_rewritten(self):
        """ecs 模式（验收）：file_url 改写为 ECS file base。"""
        from urllib.parse import urlsplit
        assets = self.make_assets(file_url_mode="ecs")
        manifest = self._lobby_manifest_with_update_url()
        patched = json.loads(
            assets.patch_real_project_manifest(json.dumps(manifest).encode("utf-8")).decode("utf-8")
        )
        ecs_base = assets._ecs_base()
        self.assertEqual(len(patched["file_url"]), 1)
        self.assertTrue(patched["file_url"][0].startswith(ecs_base), patched["file_url"])
        self.assertEqual(urlsplit(patched["file_url"][0]).hostname, "8.136.37.136")

    def test_non_lobby_manifest_passes_through_unchanged(self):
        assets = self.make_assets()
        manifest_bytes = json.dumps({
            "version": "1.0.0.1",
            "file_list": {
                "subgame/main.luac": {"md5": "keep", "size": 4, "name": "keep/main.luac"},
            },
        }).encode("utf-8")

        self.assertEqual(assets.patch_real_project_manifest(manifest_bytes), manifest_bytes)

    def assert_dominates(self, served: str, real: str):
        """断言下发版本（4 段缓冲）在每个分量上都 >= 真实官方版本（绕过 versionLessThan 逐段 bug）。

        与官方同段数（4 段），每段加缓冲偏移 → 每段都 >= 官方对应段，至少一段严格更大。
        """
        sv = [int(x) for x in served.split(".")]
        rv = [int(x) for x in real.split(".")]
        self.assertEqual(len(sv), len(rv), (served, real))
        for s, r in zip(sv, rv):
            self.assertGreaterEqual(s, r, (served, real))
        # 且至少有一个分量严格更大（确保热点端触发）
        self.assertTrue(any(s > r for s, r in zip(sv, rv)), (served, real))

    def test_version_manifest_records_all_project_manifest_paths(self):
        assets = self.make_assets()
        version_bytes = json.dumps({
            "version": "1.0.0.51",
            "manifest_url": [
                "https://gxb-oss.hzxuanming.com/yj/proj/project_10001.manifest?appid=10001",
                "https://gxb-cos.hzxuanming.com/yj/manifests/1073/1.0.0.16/198/project-1.0.0.16.manifest",
            ],
            "file_url": ["https://gxb-oss.hzxuanming.com/yj/files/"],
            "project_md5": "deadbeef",
            "diff_zip": {"url": "x"},
            "zip_url": ["y"],
        }).encode("utf-8")

        patched = json.loads(assets.patch_real_version_manifest(version_bytes).decode("utf-8"))

        # 捕获真实线上版本，但下发的是「支配版本」（每分量 >= 真实版），而非真实版本本身
        self.assertEqual(assets.real_online_version, "1.0.0.51")
        self.assert_dominates(patched["version"], "1.0.0.51")
        self.assertEqual(patched["project_md5"], "")
        self.assertNotIn("diff_zip", patched)
        self.assertNotIn("zip_url", patched)
        # ★PR2：manifest_url 改写到 ECS（host 换 ECS、保留官方 path+query），原 list 条数不变
        ecs_base = assets._ecs_base()
        self.assertEqual(
            patched["manifest_url"],
            [
                ecs_base + "/yj/proj/project_10001.manifest?appid=10001",
                ecs_base + "/yj/manifests/1073/1.0.0.16/198/project-1.0.0.16.manifest",
            ],
        )
        # 同时仍记录真实官方 path（供 project handler 回源官方）
        self.assertIn("/yj/proj/project_10001.manifest", assets.real_manifest_paths)
        self.assertIn(
            "/yj/manifests/1073/1.0.0.16/198/project-1.0.0.16.manifest",
            assets.real_manifest_paths,
        )
        # 仍记录真实官方 host（按 path）
        self.assertEqual(
            assets.real_manifest_hosts_by_path["/yj/proj/project_10001.manifest"],
            "gxb-oss.hzxuanming.com",
        )

    def test_real_version_falls_back_to_manifest_url_filename(self):
        """vm 缺 version 字段时，从 manifest_url 文件名 project-<VER>.manifest 提取。"""
        assets = self.make_assets()
        version_bytes = json.dumps({
            "manifest_url": [
                "https://gxb-oss.hzxuanming.com/yj/manifests/1073/3.13/10001116_astc/"
                "project-1.0.1.1776.manifest?t=1781250429",
            ],
            "file_url": ["https://gxb-oss.hzxuanming.com/yj/files/"],
        }).encode("utf-8")

        patched = json.loads(assets.patch_real_version_manifest(version_bytes).decode("utf-8"))

        self.assertEqual(assets.real_online_version, "1.0.1.1776")
        # 下发支配版本：每分量 >= 1.0.1.1776（关键：末段 > 1776，规避 versionLessThan bug）
        self.assert_dominates(patched["version"], "1.0.1.1776")

    def test_served_version_dominates_and_triggers(self):
        """4 段缓冲支配版本：与官方同段数，每段 +缓冲(1,5,9,3001) > 官方对应段
        （4G 判 NOUPDATE）且首分量更大（热点必触发）。"""
        assets = self.make_assets()
        # 真实版未知 → 静态兜底 4 段支配版本
        self.assertEqual(assets._served_version(), "99.99.99.9999")
        # 真实版已知 → 每段 +缓冲偏移，4 段与官方一致
        assets.real_online_version = "1.0.1.1776"
        served = assets._served_version()
        self.assertEqual(served, "2.5.10.4777")  # 1.0.1.1776 → 2.5.10.4777 (offset +3001)
        self.assert_dominates(served, "1.0.1.1776")
        # 关键回归：每段都 > 官方对应段，否则 versionLessThan 逐段 bug 会在 4G 误触发
        sv = [int(x) for x in served.split(".")]
        rv = [1, 0, 1, 1776]
        for s, r in zip(sv, rv):
            self.assertGreater(s, r, (served, "1.0.1.1776"))

    def test_served_version_build_offset_env_override(self):
        """MITM_BUILD_OFFSET 覆盖 build 段偏移（仅第 4 段，前 3 段不变）。

        用途：临时设值使 served 比 harbor 高/低以触发或抑制更新检查
        （scenario 3 验证 NetConf 不被重下）。非法值回退默认 3001。
        """
        assets = self.make_assets()
        assets.real_online_version = "1.0.1.1782"
        # env 未设 → 默认 3001：1.0.1.1782 → 2.5.10.4783
        self.assertEqual(assets._served_version(), "2.5.10.4783")
        # MITM_BUILD_OFFSET=3001 → 仅 build 段 1782+3001，前 3 段不变（与默认一致）
        with mock.patch.dict(os.environ, {"MITM_BUILD_OFFSET": "3001"}):
            self.assertEqual(assets._served_version(), "2.5.10.4783")
        # 非法值 → 回退默认 3001
        with mock.patch.dict(os.environ, {"MITM_BUILD_OFFSET": "abc"}):
            self.assertEqual(assets._served_version(), "2.5.10.4783")
        # patch.dict 退出后自动还原 → 仍默认
        self.assertEqual(assets._served_version(), "2.5.10.4783")

    def make_hotspot_assets(self, file_url_mode="official"):
        """PC 热点设置形态：self_host=热点网关 IP（4G 够不着），ecs_ip=ECS 公网 IP。

        现有 make_assets 里 self_host==ecs_ip==8.136.37.136，掩盖了"_ecs_base 误用
        self_host"的 bug。这里构造 self_host≠ecs_ip 暴露它。
        """
        assets = self.make_assets(file_url_mode=file_url_mode)
        assets.self_host = "192.168.137.1"   # 热点网关 IP，4G 下手机够不着
        assets.ecs_ip = "8.136.37.136"        # ECS 公网 IP，永久重定向目标
        return assets

    def test_ecs_base_uses_ecs_ip_not_self_host(self):
        """★回归：写进 harbor 的永久重定向基址必须是 ECS 公网 IP（ecs_ip），
        而非设置期 serve manifest 的 self_host（PC 热点下=热点网关 192.168.137.1）。
        否则 4G 手机据热点网关 IP 直连够不着 → 永久重定向失效。"""
        assets = self.make_hotspot_assets()
        base = assets._ecs_base()
        self.assertIn("8.136.37.136", base)
        self.assertNotIn("192.168.137.1", base)

    def test_update_url_rewrite_targets_ecs_ip_under_hotspot(self):
        """★回归：PC 热点设置时 patch_real_project_manifest 写入的 update_url host
        必须是 ECS 公网 IP，不能是热点网关 IP。"""
        from urllib.parse import urlsplit
        assets = self.make_hotspot_assets()
        manifest = self._lobby_manifest_with_update_url()
        patched = json.loads(
            assets.patch_real_project_manifest(json.dumps(manifest).encode("utf-8")).decode("utf-8")
        )
        for new in patched["update_url"]:
            self.assertEqual(urlsplit(new).hostname, "8.136.37.136", new)
            self.assertNotEqual(urlsplit(new).hostname, "192.168.137.1", new)

    def test_manifest_url_rewrite_targets_ecs_ip_under_hotspot(self):
        """★回归：PC 热点设置时 patch_real_version_manifest 写入的 manifest_url host
        必须是 ECS 公网 IP，不能是热点网关 IP。"""
        from urllib.parse import urlsplit
        assets = self.make_hotspot_assets()
        version_bytes = json.dumps({
            "version": "1.0.0.51",
            "manifest_url": [
                "https://gxb-oss.hzxuanming.com/yj/proj/project_10001.manifest?appid=10001",
            ],
            "file_url": ["https://gxb-oss.hzxuanming.com/yj/files/"],
            "project_md5": "deadbeef",
        }).encode("utf-8")
        patched = json.loads(assets.patch_real_version_manifest(version_bytes).decode("utf-8"))
        for new in patched["manifest_url"]:
            self.assertEqual(urlsplit(new).hostname, "8.136.37.136", new)
            self.assertNotEqual(urlsplit(new).hostname, "192.168.137.1", new)


class SetupMitmOriginFetchTest(unittest.TestCase):
    def test_origin_fetch_ignores_proxy_env(self):
        session = mock.Mock()
        response = mock.Mock()
        response.status_code = 200
        response.content = b"body"
        response.headers = {"Content-Type": "application/test"}
        session.get.return_value = response

        with mock.patch.object(setup_mitm, "_resolve_real_ip", return_value="1.2.3.4"):
            with mock.patch("requests.Session", return_value=session) as session_cls:
                status, body, ctype = setup_mitm._origin_fetch(
                    "gxb-oss.hzxuanming.com",
                    "/yj/files/demo.bin?foo=1",
                )

        session_cls.assert_called_once_with()
        self.assertFalse(session.trust_env)
        session.get.assert_called_once_with(
            "https://1.2.3.4/yj/files/demo.bin?foo=1",
            headers={"Host": "gxb-oss.hzxuanming.com"},
            verify=False,
            timeout=setup_mitm.ORIGIN_TIMEOUT,
        )
        self.assertEqual((status, body, ctype), (200, b"body", "application/test"))


if __name__ == "__main__":
    unittest.main()
