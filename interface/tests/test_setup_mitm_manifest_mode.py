from __future__ import annotations

import json
import os
import sys
from urllib.parse import urlsplit


_RUNTIME_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RUNTIME_ROOT not in sys.path:
    sys.path.insert(0, _RUNTIME_ROOT)

from mahjong_mitm.setup_mitm import (
    FILE_URL_MODE_OFFICIAL,
    MANIFEST_URL_MODE_ECS,
    MANIFEST_URL_MODE_LOCAL,
    MitmAssets,
)


def _make_assets(*, manifest_url_mode: str) -> MitmAssets:
    assets = object.__new__(MitmAssets)
    assets.bump_version = "9.9.9.103"
    assets.version = "9.9.9.103"
    assets.self_host = "192.168.137.1"
    assets.ecs_ip = "8.136.32.137"
    assets.tls_port = 443
    assets.file_url_mode = FILE_URL_MODE_OFFICIAL
    assets.manifest_url_mode = manifest_url_mode
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


def test_manifest_url_stays_official_in_local_hotspot_mode():
    assets = _make_assets(manifest_url_mode=MANIFEST_URL_MODE_LOCAL)
    version_bytes = json.dumps(
        {
            "version": "1.0.0.51",
            "manifest_url": [
                "https://gxb-oss.hzxuanming.com/yj/proj/project_10001.manifest?appid=10001",
                "https://gxb-cos.hzxuanming.com/yj/manifests/1073/3.13/10001116_astc/project-1.0.1.1782.manifest",
            ],
            "file_url": ["https://gxb-oss.hzxuanming.com/yj/files/"],
            "project_md5": "deadbeef",
        }
    ).encode("utf-8")

    patched = json.loads(assets.patch_real_version_manifest(version_bytes).decode("utf-8"))

    assert patched["manifest_url"] == [
        "https://gxb-oss.hzxuanming.com/yj/proj/project_10001.manifest?appid=10001",
        "https://gxb-cos.hzxuanming.com/yj/manifests/1073/3.13/10001116_astc/project-1.0.1.1782.manifest",
    ]
    assert assets.real_manifest_hosts_by_path["/yj/proj/project_10001.manifest"] == "gxb-oss.hzxuanming.com"


def test_manifest_url_rewrites_to_ecs_in_ecs_mode():
    assets = _make_assets(manifest_url_mode=MANIFEST_URL_MODE_ECS)
    version_bytes = json.dumps(
        {
            "version": "1.0.0.51",
            "manifest_url": [
                "https://gxb-oss.hzxuanming.com/yj/proj/project_10001.manifest?appid=10001",
            ],
            "file_url": ["https://gxb-oss.hzxuanming.com/yj/files/"],
            "project_md5": "deadbeef",
        }
    ).encode("utf-8")

    patched = json.loads(assets.patch_real_version_manifest(version_bytes).decode("utf-8"))

    assert len(patched["manifest_url"]) == 1
    assert urlsplit(patched["manifest_url"][0]).hostname == "8.136.32.137"


def test_project_manifest_still_rewrites_update_url_to_ecs():
    assets = _make_assets(manifest_url_mode=MANIFEST_URL_MODE_LOCAL)
    manifest = {
        "version": "1.0.0.1",
        "file_url": ["https://gxb-oss.hzxuanming.com/yj/files/"],
        "update_url": [
            "https://gxb-api.hzxuanming.com/hotfix_update?env=1&appid=1073&version=1.0.0.59",
        ],
        "file_list": {
            "src/app/config/NetConf.luac": {"md5": "old", "size": 1, "name": "old/net.luac"},
        },
    }

    patched = json.loads(
        assets.patch_real_project_manifest(json.dumps(manifest).encode("utf-8")).decode("utf-8")
    )

    assert urlsplit(patched["update_url"][0]).hostname == "8.136.32.137"
