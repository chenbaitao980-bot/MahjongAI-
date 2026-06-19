# ECS log sweep — 加好友→看对手手牌 路径证据

## L1.A friend-table-info 协议 ID 出现频次（all-time + last hour）

```
[total]
0
[last 1h]
0
```

## L1.B 实时观战协议（搜可能的常量名 + 任何 RealtimeGameRecord 字面）

```

```

## L1.C SEEGAME / 旁观 join action 字段

```

```

## L2 0x2BC0 deal 帧 sub_cmd=0x0003 在 noconfig pcap 历史里出现的次数（必须有，否则 stable 解码器都没活）

```
---
```

## L3.A 找曾经记录到的 hand_raw / 0x3c 占位符字段（dump 哪局是 obscured 的）

```

```

## L3.B noconfig 抓过的 0x2BC0 game_event sub 类型分布

```

```

## L4 m_SeeRule 字面量（如果你抓过 TableInfo/CreateTable 的服务端响应）

```

```

## L5.A nManagerRight / nUserRight 字面

```

```

## L5.B teahouse summary 在日志里出现过吗（有就有 nTeaOwnerNumid 的 dump）

```

```

## L6 mitm hotupdate 服务最近 200 行（看是不是有 manifest/NetConf 注入相关的迹象）

```
Jun 19 13:30:20 iZbp1byz8uirlnmgo650z5Z python3[32829]: 2026-06-19 13:30:20,995 INFO remote.noconfig.hijack.netconf_patch [netconf] _50 真服游服改写 2 个 -> ECS 单点 8.136.37.136
Jun 19 13:30:21 iZbp1byz8uirlnmgo650z5Z python3[32829]: 2026-06-19 13:30:21,056 INFO remote.noconfig.hijack.netconf_patch [netconf] patched (ECS-only): LOCAL_TCP_LIST[5045] in-place x2 + _50 ECS 单点x2 -> 8.136.37.136
Jun 19 13:30:21 iZbp1byz8uirlnmgo650z5Z python3[32829]: 2026-06-19 13:30:21,059 INFO remote.noconfig.hijack.setup_mitm Lobby ResEnsure/ResChecker injection DISABLED (INJECT_LOBBY_CHECKER=False); serving original from CDN to keep clean_res — avoids post-hotfix black screen
Jun 19 13:30:21 iZbp1byz8uirlnmgo650z5Z python3[32829]: 2026-06-19 13:30:21,091 INFO remote.noconfig.hijack.setup_mitm [patch] project.manifest: NetConf=src/app/config/NetConf.luac inject_checker=False ResEnsure=False ResChecker=False keys=915
Jun 19 13:30:21 iZbp1byz8uirlnmgo650z5Z python3[32829]: 2026-06-19 13:30:21,094 INFO remote.noconfig.hijack.setup_mitm MITM assets built: version=9.9.9.103 netconf=13477B md5=5e5ce0e3016569c29bd547d228655f95 inject_checker=False resensure=0B md5=None reschecker=0B md5=None
Jun 19 13:30:21 iZbp1byz8uirlnmgo650z5Z python3[32829]: 2026-06-19 13:30:21,116 INFO remote.noconfig.hijack.setup_mitm HTTPS MITM server on 0.0.0.0:443
Jun 19 13:30:21 iZbp1byz8uirlnmgo650z5Z python3[32829]: 2026-06-19 13:30:21,117 INFO remote.noconfig.hijack.setup_mitm DNS responder on 0.0.0.0:53 -> hijack ['gxb-api-tx.hzxuanming.com', 'gxb-api.hzxuanming.com', 'gxb-cos.hzxuanming.com', 'gxb-cos.imeete.com', 'gxb-oss.hzxuanming.com', 'gxb-oss.imeete.com'] as 8.136.37.136
Jun 19 13:30:21 iZbp1byz8uirlnmgo650z5Z python3[32829]: 2026-06-19 13:30:21,117 INFO remote.noconfig.hijack.setup_mitm MITM 设置期服务已启动；手机连热点开游戏触发热更即可。Ctrl+C 退出。
Jun 19 13:30:23 iZbp1byz8uirlnmgo650z5Z python3[32829]: 2026-06-19 13:30:23,068 INFO remote.noconfig.hijack.setup_mitm [mitm] 127.0.0.1 host=gxb-api.hzxuanming.com path=/hotfix_update?env=1&appid=1073&engine_ver=3.13&channel=10001116_astc&version=1.0.0.59 → version.manifest (origin fetch...)
Jun 19 13:30:23 iZbp1byz8uirlnmgo650z5Z python3[32829]: 2026-06-19 13:30:23,068 INFO remote.noconfig.hijack.setup_mitm [infer] manifest_url from query: https://gxb-oss.hzxuanming.com/yj/manifests/1073/3.13/10001116_astc/project-1.0.0.59.manifest (appid=1073 engine=3.13 channel=10001116_astc ver=1.0.0.59)
Jun 19 13:30:23 iZbp1byz8uirlnmgo650z5Z python3[32829]: 2026-06-19 13:30:23,105 INFO remote.noconfig.hijack.setup_mitm [origin] resolved gxb-api.hzxuanming.com -> 121.40.48.133 (via 119.29.29.29)
Jun 19 13:30:23 iZbp1byz8uirlnmgo650z5Z python3[32829]: 2026-06-19 13:30:23,183 INFO remote.noconfig.hijack.setup_mitm [mitm] 127.0.0.1 host=gxb-api.hzxuanming.com version.manifest origin body(200B): b'{"manifest_url":["https://gxb-oss.hzxuanming.com/yj/manifests/1073/3.13/10001116_astc/project-1.0.1.1780.manifest?t=1781761911","https://gxb-cos.hzxuanming.com/yj/manifests/1073/3.13/10001116_astc/pro'
Jun 19 13:30:23 iZbp1byz8uirlnmgo650z5Z python3[32829]: 2026-06-19 13:30:23,184 INFO remote.noconfig.hijack.setup_mitm [origin] captured real online version=1.0.1.1780 → served dominating version=2.5.10.3780
Jun 19 13:30:23 iZbp1byz8uirlnmgo650z5Z python3[32829]: 2026-06-19 13:30:23,184 INFO remote.noconfig.hijack.setup_mitm [patch] 注入 file_url (API 未返回)
Jun 19 13:30:23 iZbp1byz8uirlnmgo650z5Z python3[32829]: 2026-06-19 13:30:23,185 INFO remote.noconfig.hijack.setup_mitm [origin] real version.manifest manifest_url=https://gxb-oss.hzxuanming.com/yj/manifests/1073/3.13/10001116_astc/project-1.0.1.1780.manifest?t=1781761911 (host=gxb-oss.hzxuanming.com path=/yj/manifests/1073/3.13/10001116_astc/project-1.0.1.1780.manifest?t=1781761911 all=2)
Jun 19 13:30:23 iZbp1byz8uirlnmgo650z5Z python3[32829]: 2026-06-19 13:30:23,185 INFO remote.noconfig.hijack.setup_mitm [mitm] 127.0.0.1 host=gxb-api.hzxuanming.com → version.manifest (origin-patched, v=2.5.10.3780, 420B) real_manifest_url host=gxb-oss.hzxuanming.com
Jun 19 13:30:23 iZbp1byz8uirlnmgo650z5Z python3[32829]: 2026-06-19 13:30:23,281 INFO remote.noconfig.hijack.setup_mitm [origin] resolved gxb-oss.hzxuanming.com -> 122.228.79.41 (via 119.29.29.29)
Jun 19 13:30:23 iZbp1byz8uirlnmgo650z5Z python3[32829]: 2026-06-19 13:30:23,443 INFO remote.noconfig.hijack.setup_mitm [patch] project.manifest: NetConf=src/app/Config/NetConf.luac inject_checker=False ResEnsure=False ResChecker=False keys=6138
Jun 19 13:30:23 iZbp1byz8uirlnmgo650z5Z python3[32829]: 2026-06-19 13:30:23,466 INFO remote.noconfig.hijack.setup_mitm [mitm] 127.0.0.1 host=gxb-oss.hzxuanming.com → project.manifest (origin-patched, 1072449B)
Jun 19 13:30:23 iZbp1byz8uirlnmgo650z5Z python3[32829]: 2026-06-19 13:30:23,589 INFO remote.noconfig.hijack.setup_mitm [mitm] 127.0.0.1 host=gxb-oss.hzxuanming.com → /yj/files/12/1282cf26ec386cfd13dfe72c4db5cdbaa09d3b0f.luac (origin 200, 13034B)
Jun 19 13:55:09 iZbp1byz8uirlnmgo650z5Z python3[32829]: 2026-06-19 13:55:09,506 WARNING remote.noconfig.hijack.setup_mitm [origin] resolve 8.136.37.136: no A record in response
Jun 19 13:55:09 iZbp1byz8uirlnmgo650z5Z python3[32829]: 2026-06-19 13:55:09,506 WARNING remote.noconfig.hijack.setup_mitm [mitm] 34.140.126.150 host=8.136.37.136 → / (origin failed status=502, 404)
Jun 19 13:55:57 iZbp1byz8uirlnmgo650z5Z systemd[1]: Stopping MahjongAI Hot-Update MITM (DNS hijack + HTTPS manifest) for 4G/any-network...
Jun 19 13:55:57 iZbp1byz8uirlnmgo650z5Z systemd[1]: mahjong-mitm-hotupdate.service: Deactivated successfully.
Jun 19 13:55:57 iZbp1byz8uirlnmgo650z5Z systemd[1]: Stopped MahjongAI Hot-Update MITM (DNS hijack + HTTPS manifest) for 4G/any-network.
Jun 19 13:55:57 iZbp1byz8uirlnmgo650z5Z systemd[1]: Started MahjongAI Hot-Update MITM (DNS hijack + HTTPS manifest) for 4G/any-network.
Jun 19 13:55:57 iZbp1byz8uirlnmgo650z5Z python3[33711]: 2026-06-19 13:55:57,310 INFO remote.noconfig.hijack.netconf_patch [netconf] _50 注入 [5045]=ECS x1 -> 8.136.37.136
Jun 19 13:55:57 iZbp1byz8uirlnmgo650z5Z python3[33711]: 2026-06-19 13:55:57,311 INFO remote.noconfig.hijack.netconf_patch [netconf] _50 真服游服改写 2 个 -> ECS 单点 8.136.37.136
Jun 19 13:55:57 iZbp1byz8uirlnmgo650z5Z python3[33711]: 2026-06-19 13:55:57,342 INFO remote.noconfig.hijack.netconf_patch [netconf] patched (ECS-only): LOCAL_TCP_LIST[5045] in-place x2 + _50 注入x1 + _50 真服游服x2 -> 8.136.37.136
Jun 19 13:55:57 iZbp1byz8uirlnmgo650z5Z python3[33711]: 2026-06-19 13:55:57,343 INFO remote.noconfig.hijack.setup_mitm Lobby ResEnsure/ResChecker injection DISABLED (INJECT_LOBBY_CHECKER=False); serving original from CDN to keep clean_res — avoids post-hotfix black screen
Jun 19 13:55:57 iZbp1byz8uirlnmgo650z5Z python3[33711]: 2026-06-19 13:55:57,361 INFO remote.noconfig.hijack.setup_mitm [patch] project.manifest: NetConf=src/app/config/NetConf.luac inject_checker=False ResEnsure=False ResChecker=False keys=915
Jun 19 13:55:57 iZbp1byz8uirlnmgo650z5Z python3[33711]: 2026-06-19 13:55:57,363 INFO remote.noconfig.hijack.setup_mitm MITM assets built: version=9.9.9.103 netconf=13585B md5=831d55f02aec9da3fda4fe5f005751e4 inject_checker=False resensure=0B md5=None reschecker=0B md5=None
Jun 19 13:55:57 iZbp1byz8uirlnmgo650z5Z python3[33711]: 2026-06-19 13:55:57,372 INFO remote.noconfig.hijack.setup_mitm HTTPS MITM server on 0.0.0.0:443
Jun 19 13:55:57 iZbp1byz8uirlnmgo650z5Z python3[33711]: 2026-06-19 13:55:57,373 INFO remote.noconfig.hijack.setup_mitm DNS responder on 0.0.0.0:53 -> hijack ['gxb-api-tx.hzxuanming.com', 'gxb-api.hzxuanming.com', 'gxb-cos.hzxuanming.com', 'gxb-cos.imeete.com', 'gxb-oss.hzxuanming.com', 'gxb-oss.imeete.com'] as 8.136.37.136
Jun 19 13:55:57 iZbp1byz8uirlnmgo650z5Z python3[33711]: 2026-06-19 13:55:57,373 INFO remote.noconfig.hijack.setup_mitm MITM 设置期服务已启动；手机连热点开游戏触发热更即可。Ctrl+C 退出。
Jun 19 13:59:27 iZbp1byz8uirlnmgo650z5Z systemd[1]: Stopping MahjongAI Hot-Update MITM (DNS hijack + HTTPS manifest) for 4G/any-network...
Jun 19 13:59:27 iZbp1byz8uirlnmgo650z5Z systemd[1]: mahjong-mitm-hotupdate.service: Deactivated successfully.
Jun 19 13:59:27 iZbp1byz8uirlnmgo650z5Z systemd[1]: Stopped MahjongAI Hot-Update MITM (DNS hijack + HTTPS manifest) for 4G/any-network.
Jun 19 13:59:27 iZbp1byz8uirlnmgo650z5Z systemd[1]: Started MahjongAI Hot-Update MITM (DNS hijack + HTTPS manifest) for 4G/any-network.
Jun 19 13:59:27 iZbp1byz8uirlnmgo650z5Z python3[33801]: 2026-06-19 13:59:27,848 INFO remote.noconfig.hijack.netconf_patch [netconf] _50 注入 [5045]=ECS x1 -> 8.136.37.136
Jun 19 13:59:27 iZbp1byz8uirlnmgo650z5Z python3[33801]: 2026-06-19 13:59:27,849 INFO remote.noconfig.hijack.netconf_patch [netconf] _50 真服游服改写 2 个 -> ECS 单点 8.136.37.136
Jun 19 13:59:27 iZbp1byz8uirlnmgo650z5Z python3[33801]: 2026-06-19 13:59:27,890 INFO remote.noconfig.hijack.netconf_patch [netconf] patched (ECS-only): LOCAL_TCP_LIST[5045] in-place x2 + _50 注入x1 + _50 真服游服x2 -> 8.136.37.136
Jun 19 13:59:27 iZbp1byz8uirlnmgo650z5Z python3[33801]: 2026-06-19 13:59:27,893 INFO remote.noconfig.hijack.setup_mitm Lobby ResEnsure/ResChecker injection DISABLED (INJECT_LOBBY_CHECKER=False); serving original from CDN to keep clean_res — avoids post-hotfix black screen
Jun 19 13:59:27 iZbp1byz8uirlnmgo650z5Z python3[33801]: 2026-06-19 13:59:27,927 INFO remote.noconfig.hijack.setup_mitm [patch] project.manifest: NetConf=src/app/config/NetConf.luac inject_checker=False ResEnsure=False ResChecker=False keys=915
Jun 19 13:59:27 iZbp1byz8uirlnmgo650z5Z python3[33801]: 2026-06-19 13:59:27,931 INFO remote.noconfig.hijack.setup_mitm MITM assets built: version=9.9.9.103 netconf=13585B md5=831d55f02aec9da3fda4fe5f005751e4 inject_checker=False resensure=0B md5=None reschecker=0B md5=None
Jun 19 13:59:27 iZbp1byz8uirlnmgo650z5Z python3[33801]: 2026-06-19 13:59:27,951 INFO remote.noconfig.hijack.setup_mitm HTTPS MITM server on 0.0.0.0:443
Jun 19 13:59:27 iZbp1byz8uirlnmgo650z5Z python3[33801]: 2026-06-19 13:59:27,952 INFO remote.noconfig.hijack.setup_mitm DNS responder on 0.0.0.0:53 -> hijack ['gxb-api-tx.hzxuanming.com', 'gxb-api.hzxuanming.com', 'gxb-cos.hzxuanming.com', 'gxb-cos.imeete.com', 'gxb-oss.hzxuanming.com', 'gxb-oss.imeete.com'] as 8.136.37.136
Jun 19 13:59:27 iZbp1byz8uirlnmgo650z5Z python3[33801]: 2026-06-19 13:59:27,952 INFO remote.noconfig.hijack.setup_mitm MITM 设置期服务已启动；手机连热点开游戏触发热更即可。Ctrl+C 退出。
Jun 19 13:59:29 iZbp1byz8uirlnmgo650z5Z python3[33801]: 2026-06-19 13:59:29,937 INFO remote.noconfig.hijack.setup_mitm [mitm] 127.0.0.1 host=gxb-api.hzxuanming.com path=/hotfix_update?env=1&appid=1073&engine_ver=3.13&channel=10001116_astc&version=1.0.0.59 → version.manifest (origin fetch...)
Jun 19 13:59:29 iZbp1byz8uirlnmgo650z5Z python3[33801]: 2026-06-19 13:59:29,937 INFO remote.noconfig.hijack.setup_mitm [infer] manifest_url from query: https://gxb-oss.hzxuanming.com/yj/manifests/1073/3.13/10001116_astc/project-1.0.0.59.manifest (appid=1073 engine=3.13 channel=10001116_astc ver=1.0.0.59)
Jun 19 13:59:29 iZbp1byz8uirlnmgo650z5Z python3[33801]: 2026-06-19 13:59:29,967 INFO remote.noconfig.hijack.setup_mitm [origin] resolved gxb-api.hzxuanming.com -> 121.40.48.133 (via 119.29.29.29)
Jun 19 13:59:30 iZbp1byz8uirlnmgo650z5Z python3[33801]: 2026-06-19 13:59:30,021 INFO remote.noconfig.hijack.setup_mitm [mitm] 127.0.0.1 host=gxb-api.hzxuanming.com version.manifest origin body(200B): b'{"manifest_url":["https://gxb-oss.hzxuanming.com/yj/manifests/1073/3.13/10001116_astc/project-1.0.1.1780.manifest?t=1781761911","https://gxb-cos.hzxuanming.com/yj/manifests/1073/3.13/10001116_astc/pro'
Jun 19 13:59:30 iZbp1byz8uirlnmgo650z5Z python3[33801]: 2026-06-19 13:59:30,022 INFO remote.noconfig.hijack.setup_mitm [origin] captured real online version=1.0.1.1780 → served dominating version=2.5.10.4780
Jun 19 13:59:30 iZbp1byz8uirlnmgo650z5Z python3[33801]: 2026-06-19 13:59:30,022 INFO remote.noconfig.hijack.setup_mitm [patch] 注入 file_url (API 未返回)
Jun 19 13:59:30 iZbp1byz8uirlnmgo650z5Z python3[33801]: 2026-06-19 13:59:30,022 INFO remote.noconfig.hijack.setup_mitm [origin] real version.manifest manifest_url=https://gxb-oss.hzxuanming.com/yj/manifests/1073/3.13/10001116_astc/project-1.0.1.1780.manifest?t=1781761911 (host=gxb-oss.hzxuanming.com path=/yj/manifests/1073/3.13/10001116_astc/project-1.0.1.1780.manifest?t=1781761911 all=2)
Jun 19 13:59:30 iZbp1byz8uirlnmgo650z5Z python3[33801]: 2026-06-19 13:59:30,022 INFO remote.noconfig.hijack.setup_mitm [mitm] 127.0.0.1 host=gxb-api.hzxuanming.com → version.manifest (origin-patched, v=2.5.10.4780, 420B) real_manifest_url host=gxb-oss.hzxuanming.com
Jun 19 13:59:30 iZbp1byz8uirlnmgo650z5Z python3[33801]: 2026-06-19 13:59:30,088 INFO remote.noconfig.hijack.setup_mitm [origin] resolved gxb-oss.hzxuanming.com -> 117.24.169.66 (via 119.29.29.29)
Jun 19 13:59:30 iZbp1byz8uirlnmgo650z5Z python3[33801]: 2026-06-19 13:59:30,390 INFO remote.noconfig.hijack.setup_mitm [patch] project.manifest: NetConf=src/app/Config/NetConf.luac inject_checker=False ResEnsure=False ResChecker=False keys=6138
Jun 19 13:59:30 iZbp1byz8uirlnmgo650z5Z python3[33801]: 2026-06-19 13:59:30,413 INFO remote.noconfig.hijack.setup_mitm [mitm] 127.0.0.1 host=gxb-oss.hzxuanming.com → project.manifest (origin-patched, 1072449B)
Jun 19 13:59:30 iZbp1byz8uirlnmgo650z5Z python3[33801]: 2026-06-19 13:59:30,552 INFO remote.noconfig.hijack.setup_mitm [mitm] 127.0.0.1 host=gxb-oss.hzxuanming.com → /yj/files/12/1282cf26ec386cfd13dfe72c4db5cdbaa09d3b0f.luac (origin 200, 13034B)
```

## L7 pcap 文件清单（拿来本地用 stable 解一遍）

```

```

## L8 7777 协议 ID 全分布（最近 50000 条匹配）

```

```

## L9 端口 5045/5067/5167/5748/5749/5747/7777 的连接拓扑（看有没有第三方旁观者连接）

```

```

## L10 现在跑着的服务清单

```
  mahjong-mitm-hotupdate.service loaded active running MahjongAI Hot-Update MITM (DNS hijack + HTTPS manifest) for 4G/any-network
  mahjong-relay-cloud.service    loaded active running MahjongAI Relay - Cloud Player Mode (Port 8003)
  mahjong-relay-hotspot.service  loaded active running MahjongAI Relay - Hotspot Mode (Port 8000)
  mahjong-relay-noconfig.service loaded active running MahjongAI Relay - No-Config Mode (Port 8002)
  mahjong-relay-vpn.service      loaded active running MahjongAI Relay - VPN Mode (Port 8001)
  mahjong-tcp-proxy.service      loaded active running MahjongAI TCP Proxy - Hijack Mode (Lobby + Game)
```

