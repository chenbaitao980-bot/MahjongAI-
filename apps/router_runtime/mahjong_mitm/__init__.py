"""mahjong_mitm — setup-period 热更 MITM（路由器/PC 双模）。

抽取自 remote/noconfig/hijack/ 的最小子集，只保留 setup-period 一刀：
  - DNS 响应器（劫持热更域名 → 本机）
  - 自签 HTTPS server（回源真实 manifest + 只改 NetConf 一条）
  - NetConf XXTEA 解密改 IP（台州 5045 → ECS）

不含 ECS 侧 tcp_proxy / 多用户后台 / relay；那些单独部署。

入口：`python -m mahjong_mitm --host-ip <网关IP> --ecs-ip <ECS公网IP>`
"""
from __future__ import annotations

__all__ = ["run", "main", "DEFAULT_ECS_IP", "DEFAULT_APK"]

from .setup_mitm import DEFAULT_APK, DEFAULT_ECS_IP, main, run
