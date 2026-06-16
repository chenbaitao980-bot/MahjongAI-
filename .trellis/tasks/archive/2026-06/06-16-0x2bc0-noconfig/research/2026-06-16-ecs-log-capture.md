# ECS Log Capture Notes (2026-06-16)

## What was verified on ECS

- Host: `root@8.136.37.136`
- Services are active:
  - `mahjong-tcp-proxy`
  - `mahjong-relay-noconfig`
  - `mahjong-mitm-hotupdate`
- Listening ports include:
  - lobby: `5748`, `5749`
  - fixed gold proxy: `5767`, `5768`
  - dynamic game ports: `5700`, `5701`, `5702`, `5707`, `5708`, `5722`, `5723`
  - relay: `8002`
  - MITM TLS: `443`

## Current 4G link state

Latest live sample around `2026-06-16 10:18` shows:

- `[proxy 5748] + 223.104.166.229 -> 47.96.101.155:5748`
- `[lobby] session key learned from HandshakeRsp`
- multiple `RespSRSAddr` rewrites to `8.136.37.136:*`
- dynamic game proxies created for `5700/5701/5702/5707/5708/5722/5723`
- fixed gold proxy connection reached:
  - `[proxy 5767] + 223.104.166.229 -> srs-zj.tt2kj.com:7777`

But the same window did **not** produce:

- `[game-decrypt] session key learned ... KEYHEX=...`
- `[game-decrypt][dbg] 0x2bc0 flag=... sub=... extra=... ENC=...`
- relay `/push` lines

Interpretation: the newest reproduced 4G attempt reached ECS and the fixed gold proxy, but did not progress far enough on the game-server side to emit the new decryption diagnostics.

## Historical 0x2bc0 sample status

Historical logs around `2026-06-16 10:08` and `10:09` do contain many `0x2bc0` samples, for example:

- `17B head=654fafe9272232e2f6688d16de30372bec`
- `17B head=2e639f8db1b994bda77d56377c5fde684a`
- `53B head=2c26fd4a33f0dcc4533961377db736e1168b886227ecffa278db8cc6fa3860a10ec8c3934a5ddc6477a90f9385c6d5cc`
- `307B head=c9a72d8d8eee2e795f2b3f2ae435e78d0074ee4ea06cda20b7ec46b80a6de81113823880e14d5ece24e1c00b4282ce11`

However, those historical lines are in the **old** log format:

- `[game-decrypt][dbg] 0x2bc0 HAND frame: ... head=...`

and do **not** include the newer fields needed for offline cracking:

- `KEYHEX`
- `flag`
- `sub`
- `extra`
- `ENC`

## Remote code vs observed logs

The remote file `/opt/mahjong-remote/remote/noconfig/hijack/tcp_proxy.py` currently contains the newer diagnostics:

- `session key learned ... KEYHEX=%s`
- `new msg=0x... flag=0x... sub=0x... extra=%d plain_head=%s`
- `0x2bc0 flag=0x... sub=0x... extra=%d ENC=%s`

So there is a drift between:

- the diagnostic code currently deployed on disk
- the historical journal entries that were captured before the service restart / before a fresh full game-side session happened

## Practical conclusion

We now know the blocker is not "ECS service dead" or "ports not listening".

The real remaining blocker is: we still need **one fresh full game-side session after the diagnostic version is active** so the journal emits:

1. `KEYHEX`
2. at least one `0x2bc0 flag/sub/extra/ENC`
3. ideally a nearby successful `new msg=0x0006` or `0x0018` line for comparison

Without that fresh sample, the repository has only old-format `HAND frame` ciphertext snippets, which are useful as evidence but insufficient for the intended offline variant analysis described in `prd.md`.

## Recommended next action

1. Keep ECS on the current diagnostic `tcp_proxy.py`.
2. Reproduce one real 4G gold-game session until `journalctl -u mahjong-tcp-proxy` prints `KEYHEX` and `0x2bc0 flag=... ENC=...`.
3. Save that sample pair into a follow-up research note, then implement an offline decrypt-variant brute-force script locally.
