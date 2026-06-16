# Fix No-Config Resource Loading

## Goal

Make no-config mode reliable for real phone use: the phone should require no manual configuration, resource loading should complete when first connected through the PC hotspot and later on the phone's own 4G/WiFi network, and the cloud path should keep reading hand data regardless of the phone network.

## What I Already Know

* User is currently stuck at the game loading screen at 0%, with text indicating local resource validation.
* Recent logs show the hot-update MITM is active and handles `hotfix_update`, `version.manifest`, `project.manifest`, CDN file passthrough, NetConf injection, and ResEnsure injection.
* `logs/run_hijack.log` includes successful origin file passthroughs and also previous `project.manifest origin fetch status=404 -> 502` failures.
* `.trellis/spec/backend/remote-access.md` explicitly lists mobile-network resource validation and no-config hand display as open issues.
* The desired no-config architecture is: setup-period MITM patches NetConf to ECS, then ECS lobby/game proxy rewrites SRS addresses and taps hand data.

## Requirements

* First-time setup over PC hotspot must complete game resource loading instead of staying at 0%.
* After setup, the phone must load resources normally on its own 4G/WiFi network.
* No phone-side configuration is allowed: no manual DNS, VPN, certificate install, proxy setting, or app install.
* Cloud relay must receive and expose hand data regardless of whether the phone is on PC hotspot, 4G, or normal WiFi after setup.
* Hot-update MITM must not make the game download a stale APK manifest that causes broad file diffs.
* Failure modes must be visible in logs without breaking unrelated passthrough resources.

## Acceptance Criteria

* [ ] `setup_mitm` self-test passes.
* [ ] A regression test covers the project-manifest fallback/matching behavior that caused 0% resource validation stalls.
* [ ] Local relay/proxy tests pass where available.
* [ ] On a real phone connected to PC hotspot, the loading screen advances past resource validation and reaches the lobby/game.
* [ ] After switching the phone to 4G/WiFi, resource loading remains normal and cloud `:8002/state` continues receiving hand data.

## Definition of Done

* Tests added or updated for the fixed behavior.
* Relevant lint/type/test commands run.
* Logs remain useful for diagnosing DNS, manifest, CDN passthrough, and hand-data proxy stages.
* Trellis specs updated if the fix captures a new durable convention.

## Technical Approach

Start by tracing `remote/noconfig/hijack/setup_mitm.py`, `manifest_forge.py`, `netconf_patch.py`, `dns_divert.py`, `run_hijack.py`, and `tcp_proxy.py`. Focus first on the loading blocker, especially project-manifest identification, origin fetch fallback, injected `file_url`, and ResEnsure delivery. Then verify the cloud proxy/hand-data path from NetConf rewrite to ECS proxy to relay push.

## Open Questions

* None blocking yet. Real-phone verification will be needed after code-level fixes.

## Out of Scope

* Building a new phone app.
* Requiring user-visible phone configuration.
* Replacing the no-config design with VPN as the primary solution.

## Technical Notes

* Relevant spec: `.trellis/spec/backend/remote-access.md`.
* Relevant code: `remote/noconfig/hijack/setup_mitm.py`, `remote/noconfig/hijack/manifest_forge.py`, `remote/noconfig/hijack/netconf_patch.py`, `remote/noconfig/hijack/dns_divert.py`, `remote/noconfig/hijack/tcp_proxy.py`, `remote/noconfig/hijack/run_hijack.py`.
* Relevant logs: `logs/run_hijack.log`, `hijack_live.err`, `logs/dns_divert.log`.
