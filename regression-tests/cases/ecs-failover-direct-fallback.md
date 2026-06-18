# ECS Failover Direct Fallback (Path Y) -- Manual Regression Cases

PRD: `.trellis/tasks/06-17-ecs-failover-direct-fallback/prd.md`

This file is a manual checklist. Real-device verification is the only way to
sign off on Path Y because all four pieces interact at runtime:
NetConf 5045 list, NetConf `_50` 5067/5167 list, NetEngine fail-count rotation,
and NetEngine FAIL link-state hook.

## Prereqs

- ECS reachable from the lab phone (default network: lab WiFi or LAN).
- PC is **not** required to be co-located -- Path Y runs entirely on the phone.
- Phone has been through a hotspot setup-period at least once so that
  NetConf.luac and NetEngine.luac are persisted in the on-device harbor (i.e.
  the patched bytes from `setup_mitm` have landed via `forge_manifest_full`).
- ECS public IP: 8.136.37.136 (override via env if running against a staging IP).

## Cases

Fill `result` with `PASS` / `FAIL` / `BLOCKED` plus a one-line note + log
pointer. Append the run timestamp + tester initials.

| # | Scenario | Steps | Expected | Result |
|---|----------|-------|----------|--------|
| 1 | Hotspot setup pushes patched NetConf + NetEngine | 1. Phone connects to PC hotspot. 2. Open game; let it complete one hot-update round. 3. Login normally. | Lobby + at least one room loads. Relay (`/state` on :8002) shows tiles. | |
| 2 | ECS down -> 4G lobby + friends room reachable | 1. On PC, run `stop_ecs_services.bat` (verify the port probes report ECS unreachable). 2. Phone switches to 4G. 3. Force-close & reopen game. | Lobby loads within ~30s. Friends room creates and joins. NetEngine fail-count rotation lands on real-server entry of `LOCAL_TCP_LIST[5045]`. | |
| 3 | ECS down -> 4G coin game (wenzhou-jingu / `_50` 5067) reachable | After Case 2 succeeds, enter coin game (`_50[5067]`). | Coin game table loads; first deal is dealt. NetEngine `_50` rotation evaluates `(_failCount % 2) + 1` and reaches `list[2]` = `srs-zj.tt2kj.com:7777`. | |
| 4 | ECS recovery -> next session re-routes to ECS | 1. Run `start_ecs_services.bat` and confirm port probes succeed. 2. On phone, force-close & reopen game. 3. Open lobby on either coin or friends room. | Relay (`/state` on ECS:8002) shows the phone's hand again, proving the spectator pipeline (= ECS chain) re-engaged. | |

## Sign-off

Each row above must reach `PASS` once before this task is marked Done. Attach:
- A screenshot of `stop_ecs_services.bat` output (port probes failing).
- A screenshot of the in-game lobby on 4G during the ECS-down window.
- A screenshot of `start_ecs_services.bat` output (port probes succeeding).
- The relevant timestamps from `journalctl -u mahjong-relay-noconfig` or the
  on-PC capture log (whichever applies for that scenario).

## Open questions / known caveats

- NetEngine `_50` rotation depends on `_srsConnFailCount` being incremented at
  least once before the game requests the coin-game list. If the phone's first
  coin-game attempt happens **before** any failed connect, the user may hit
  ECS first and see the coin game stall briefly. Document the actual delay
  observed during testing and decide whether a pre-warm probe is needed.
- ECS-stop drill should never be run on a production user. Always coordinate
  with anyone using the ECS chain before flipping `stop_ecs_services.bat`.
