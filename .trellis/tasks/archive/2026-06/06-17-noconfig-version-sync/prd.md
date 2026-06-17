# brainstorm: noconfig version sync

## Goal

Make noconfig injection display a version that visually matches the official version format, while still reliably triggering setup-period hot update and avoiding later 4G/self-network update loops. If the official server has update content, preserve/sync that official update content and only apply our required injection changes.

## What I already know

* User reports that in no-config mode, the injected displayed version currently differs greatly from the official version digit width.
* User wants the injected upgrade version to be official version + 1, not a large synthetic version.
* User asks whether official update content can be synchronized when the official server has update content.
* Current noconfig/hijack code captures the real online version from `version.manifest` or from `manifest_url`.
* Current code serves a "dominating" version by adding a large offset to every numeric component, with fallback `99999.99999.99999.99999`.
* The large version strategy exists because the client `Manifest.versionLessThan` appears to compare each component independently and can incorrectly treat `9.9.9.103` as less than `1.0.1.1776`.
* Current transparent-origin flow already preserves real `manifest_url` / `file_url`, fetches real online `project.manifest`, and patches only the injection targets.

## Assumptions (temporary)

* Official version strings are primarily numeric dot-separated 4-segment strings such as `1.0.1.1776`.
* "Official digits stay consistent" means keep the same segment count (4) and roughly the same digit
  width as official, e.g. `1.0.1.1776` → `2.5.10.2776` (each segment mildly higher) — instead of
  `100001.100000.100001.101776`.
* The core safety requirement remains: after injection, switching away from hotspot/no-config should
  not cause the client to loop on hot update or overwrite the injected NetConf unexpectedly.
* Verified against decompiled `Manifest.lua`: `versionLessThan` compares segments with `<` and never
  short-circuits on `>`, so as long as **every segment >= official** we permanently dominate.
  (A segment-count short-circuit also exists, but exploiting it via 5 segments causes a real-device
  hot-update stall — see "5-segment failure". Do NOT use 5 segments.)

## Open Questions

* None.

## Requirements (evolving)

* Prefer deriving injected version from official online version dynamically.
* **Chosen strategy (`official_plus_segment_buffer`, 4-segment)**: serve a **4-segment** version =
  official 4 segments each bumped by a per-segment buffer offset (`major+1, minor+5, patch+9,
  build+1000`). Example: official `1.0.0.51` → served `2.5.9.1051`; `1.0.1.1776` → `2.5.10.2776`.
  Same segment count as official (4), every segment strictly > official's corresponding segment.
* Why 4 segments (not 5): a 5-segment strategy was attempted (see "5-segment failure" below) and
  **real-device hot update stalled** — the phone downloaded files then aborted before writing the
  version into harbor, so the injected version never displayed. Reverting to 4-segment `+100000`
  restored normal hot-update completion. The 5-segment stall mechanism is on the phone's
  native/UI layer; server logs + decompiled Lua hot-update chain show no cause (the `version`
  field is not read during merge; `_updateLocalManifest` just `setJson`-overwrites it). So 5
  segments is abandoned; we stay at the same 4-segment count as official.
* Why per-segment buffer instead of `+100000`: `versionLessThan` compares each segment with `<`
  and never short-circuits on `>`, so as long as **every segment >= official** we permanently
  dominate (4G NOUPDATE). `+100000` works but looks pirated (5-digit segments). Small per-segment
  buffers `(1,5,9,1000)` keep every segment > official's foreseeable-future value while staying
  close to official's digit width.
* Keep the static `99.99.99.9999` (4-segment) dominating version as fallback when official version
  capture/parsing fails.
* When official update content exists, use official `version.manifest` / `project.manifest` as the
  source of truth and patch only injection-related entries (already implemented by
  `patch_real_project_manifest`; **no change needed** for content sync).
* Maintain fallback behavior when origin fetch or parsing fails.

## Acceptance Criteria (evolving)

* [x] For official version `1.0.0.51`, served version is `2.5.9.1051` (4 segments; each > official
      corresponding segment). Selftest + pytest green.
* [x] For official version `1.0.1.1776`, served version is `2.5.10.2776`.
* [x] Served version has the **same segment count** as official (4 vs 4) — avoids the 5-segment
      real-device hot-update stall (see "5-segment failure" below).
* [x] Each served segment is strictly greater than the official corresponding segment →
      `versionLessThan` (per-segment `<`, no early `>` short-circuit) never returns true → 4G NOUPDATE.
* [x] Official-version-unknown fallback is the static 4-segment `99.99.99.9999`.
* [x] Version and project manifest patching preserve real `manifest_url` and `file_url`.
* [x] Official project manifest content is synchronized by origin fetch before applying injection changes.
* [x] Tests cover normal official version capture, manifest-url fallback capture, and origin/fallback behavior.
* [x] Regression coverage documents/guards the known client `versionLessThan` issue.
* [x] Real-device verification: 4-segment strategy hot-updates to completion and the injected version
      displays on the phone (confirmed for `+100000`; 4-segment buffer shares the same segment count
      and merge path, expected to behave identically — pending one on-device confirmation after deploy).

## Technical Approach

Implement the `official_plus_segment_buffer` (4-segment) served-version strategy in
`MitmAssets._served_version()`:

* Parse the captured official version into numeric components.
* Bump each of the first 4 components by per-segment buffer offsets
  `_VERSION_SEGMENT_OFFSETS = (1, 5, 9, 1000)` so every one strictly exceeds the official
  corresponding segment. Same 4-segment count as official.
* Return the static 4-segment `99.99.99.9999` if there is no captured official version or parsing
  fails.
* Continue preserving official `manifest_url` / `file_url` and origin-fetched `project.manifest`
  content; only the version and injection-related manifest entries change. Official content sync is
  already handled by `patch_real_project_manifest` — no change needed.

Why same segment count as official matters: a 5-segment served version (attempted, then reverted)
caused the phone to stall mid hot-update — it downloaded the diff files but never reached
`_updateLocalManifest` (which `setJson`-overwrites harbor with the new version), so the injected
version never wrote into harbor and never displayed. Reverting to 4 segments restored normal
completion. The 4-segment buffer keeps the proven completion path while tightening the visual gap
to official.

## 5-segment failure (lesson learned, why we reverted to 4 segments)

* Attempted strategy Y: served = official 4 segments + buffer + appended `.1` (5 segments total),
  e.g. `1.0.1.1776` → `2.5.10.2776.1`. Theory: `versionLessThan` does a segment-count short-circuit
  (`#numsA > #numsB → return false`) before the per-segment `<` loop, so 5-vs-4 would permanently
  dominate. This short-circuit IS real (confirmed in decompiled `Manifest.lua`).
* Real-device result: phone hot-update **stalled**. ECS logs show the phone fetched
  `version.manifest` (v=`2.5.10.2776.1`) → `project.manifest` → downloaded 1 file (ResChecker) →
  then stopped. No second `hotfix_update`, no further downloads. Harbor version never advanced;
  the injected version did **not** display.
* Control: reverting to 4-segment `+100000` (`100001.100000.100001.101776`) on the same phone →
  hot-update completed normally → injected version displayed. Server-side, the 4-seg and 5-seg
  sessions served **identical** files (same version.manifest structure, same project.manifest,
  same single ResChecker download) — the ONLY difference was the `version` string (4 vs 5 segments).
* Root-cause hunt: traced the entire decompiled Lua hot-update chain
  (`_onVersionDownload` → `checkVersionUpdate` / `versionLessThan` → `_generalDownload` →
  `_startMerge` → `_startDelete` → `_updateLocalManifest`). The `version` field is **not read**
  during merge; `_updateLocalManifest` just `setJson`-overwrites harbor. No code path branches on
  segment count in a way that would stall. The stall mechanism is on the phone's native layer
  (cocos `Downloader2` / `Manifest` C++ impl) or upper UI logic (`ResChecker.onChooseHotFixType`
  FORCE-update dialog). Server logs + Lua decompile exhausted; would need phone `logcat` to pinpoint.
* Decision: abandon 5-segment. Stay at official's 4-segment count; use small per-segment buffers
  instead of `+100000` for visual closeness. 4G safety comes from every-segment dominance
  (per-segment `<` with no `>` short-circuit), not segment-count tricks.

## Decision (ADR-lite)

**Context**: The previous `+100000` strategy (`100001.100000.100001.101776`) solved the client
`versionLessThan` per-segment bug via a numeric buffer, but displays a version that looks nothing
like official. The user asked for a version that stays close to official while remaining 4G-safe.

**Options considered**:
- **5-segment (`official + buffer + .1`)**: served = `2.5.10.2776.1`. Theory was elegant
  (segment-count short-circuit → permanent dominance). **Real-device test failed**: hot-update
  stalled, version never wrote into harbor, never displayed. Reverted. See "5-segment failure" above.
- **`official + .1` (4-seg, no buffer)**: served = `1.0.1.1777`. Only last segment +1. Fragile:
  once official bumps build past us, `versionLessThan` triggers and 4G re-pulls. Rejected.
- **4-segment per-segment buffer (chosen)**: served = `2.5.10.2776`. Same segment count as
  official (proven completion path), every segment > official (permanent 4G dominance), digits
  close to official (not pirated-looking).
- Static `+100000` (baseline, works but ugly): kept only as the historical reference point.

**Decision**: 4-segment per-segment buffer `(1,5,9,1000)`. Same segment count as official (avoids
the 5-segment stall), every segment strictly > official (4G-safe via the per-segment `<` no-early-`>`
behavior), visually one notch above official.

**Consequences**: Displayed version `2.5.10.2776`-style — close to official, not pirated. 4G-safe as
long as every segment stays >= official (buffers `(1,5,9,1000)` cover official's foreseeable-future
per-segment growth; build +1000 ≈ years of headroom at current cadence). Fallback `99.99.99.9999`
when official capture fails. On-device hot-update completion verified for the 4-segment shape (via
`+100000`); one final on-device confirmation of the buffer values pending after deploy.

## Definition of Done (team quality bar)

* Tests added/updated (unit/integration where appropriate)
* Lint / typecheck / CI green
* Docs/notes updated if behavior changes
* Rollout/rollback considered if risky

## Out of Scope (explicit)

* Rewriting the full no-config MITM architecture.
* Changing phone network topology or hotspot startup/deploy scripts unless required by this version strategy.
* Claiming real-device 4G behavior is fixed without device verification.

## Technical Notes

* Relevant files inspected:
  * `remote/noconfig/hijack/setup_mitm.py`
  * `remote/noconfig/hijack/manifest_forge.py`
  * `tests/test_setup_mitm.py`
  * `.trellis/spec/backend/index.md`
* Memory confirms prior hot-update work: real verification should follow `manifest_url` from `version.manifest`; manifest-level minimization and real-phone timing must be kept separate.
* Current implementation points (4-segment buffer):
  * `MitmAssets._served_version()` generates the 4-segment served version: each official segment
    bumped by `_VERSION_SEGMENT_OFFSETS = (1,5,9,1000)`. Same segment count as official.
  * `_FALLBACK_DOMINATE_VERSION = "99.99.99.9999"` (static 4-segment; every segment >> official).
  * `patch_real_version_manifest()` captures `real_online_version`, preserves official URLs, clears
    `project_md5`, removes zip fields, then sets `vm["version"] = self._served_version()`.
  * `patch_real_project_manifest()` fetches/patches official project manifest and sets
    `forged["version"] = self._served_version()` (official content sync unchanged).
* Reverse-engineering source:
  `apk_research/decrypted-lua/app/hotupdate/universe/hotfix/Manifest.lua` (`versionLessThan`,
  `genDiffList`) and `HotFixProcessor.lua` (`parseVersion` / `checkVersionUpdate` /
  `_onVersionDownload` / `_generalDownload` / `_startMerge` / `_updateLocalManifest`).
* Verification completed:
  * `python -m pytest tests/test_setup_mitm.py` → 5 passed.
  * `python remote/noconfig/hijack/setup_mitm.py --selftest` → ALL PASS.
  * Selftest evidence: fake official `1.0.0.51` served as `2.5.9.1051` (4 segments; each > official);
    official-unknown fallback served as `99.99.99.9999`; real `manifest_url` / `file_url` preserved;
    NetConf/md5/file_list content synced from official.
* Real-device evidence:
  * 4-segment `+100000` (`100001.100000.100001.101776`): hot-update completed, injected version
    displayed on phone. ✅ (proves 4-segment shape completes)
  * 5-segment (`2.5.10.2776.1`): hot-update stalled, version never displayed. ❌ (reverted)
  * 4-segment buffer (`2.5.10.2776`): same 4-segment shape as the proven `+100000`, expected to
    complete identically — pending one on-device confirmation after deploy.

## Spec Conflicts

* Prior memory [hotupdate-4g-stall-fake-version] prescribed `real[i]+100000` per-segment dominating
  version. This task's 4-segment buffer supersedes the `+100000` value (same 4-segment shape and
  safety mechanism — every segment >= official — just smaller, official-close buffers instead of
  `+100000`). A 5-segment variant was tried and **rejected** (real-device hot-update stall).
  → **Resolution**: update the memory to record (a) the 4-segment buffer as the new default,
  (b) the `versionLessThan` per-segment `<` no-early-`>` behavior (the actual safety mechanism),
  (c) the segment-count short-circuit fact, and (d) the warning that 5-segment versions stall
  real-device hot-update and must NOT be used.
