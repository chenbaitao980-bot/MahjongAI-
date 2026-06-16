import json
import unittest

from remote.noconfig.hijack.setup_mitm import (
    MitmAssets,
    RESCHECKER_FILE_KEY,
    RESENSURE_FILE_KEY,
)


class SetupMitmManifestPatchTest(unittest.TestCase):
    def make_assets(self):
        assets = object.__new__(MitmAssets)
        assets.bump_version = "9.9.9.103"
        assets.version = "9.9.9.103"
        assets.served_md5 = "netconf-md5"
        assets.served_size = 100
        assets.served_name = "aa/netconf.luac"
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
        # 真实版未捕获 → 下发静态兜底支配版本（每分量远大于现实版本）
        self.assertEqual(patched["version"], "99999.99999.99999.99999")
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
        """断言下发版本在每个分量上都 >= 真实版本（绕过游戏 versionLessThan 的 bug）。"""
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
        self.assertIn("/yj/proj/project_10001.manifest", assets.real_manifest_paths)
        self.assertIn(
            "/yj/manifests/1073/1.0.0.16/198/project-1.0.0.16.manifest",
            assets.real_manifest_paths,
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
        """支配版本：每分量 >= 真实版（4G 判 NOUPDATE）且首分量远大（热点必触发）。"""
        assets = self.make_assets()
        # 真实版未知 → 静态兜底支配版本
        self.assertEqual(assets._served_version(), "99999.99999.99999.99999")
        # 真实版已知 → 每分量 +偏移，仍支配
        assets.real_online_version = "1.0.1.1776"
        self.assert_dominates(assets._served_version(), "1.0.1.1776")
        # 关键回归：末段必须 > 真实 build，否则 versionLessThan bug 会在 4G 误触发
        self.assertGreater(int(assets._served_version().split(".")[-1]), 1776)


if __name__ == "__main__":
    unittest.main()
