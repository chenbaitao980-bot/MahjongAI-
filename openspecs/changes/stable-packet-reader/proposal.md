# stable-packet-reader

## Why

The current formal battle flow depends on image recognition and manual correction, which is unstable in live play. The stable version must read structured game data directly from packets and only use the existing decision engine once packet data is complete.

## What Changes

- Add a project-local `openspecs/` change for this work.
- Add `stable/` packet protocol, mapping, and state tracking modules.
- Add a new "stable version" tab after the existing formal battle tab.
- Stream game packets through `adb exec-out + tcpdump`, decode protocol events, and display live state.
- Persist manual raw-code tile mappings under writable runtime data.
- Trigger existing strategy analysis only when it is self discard turn, self effective hand count is 14, and baida has been parsed.
- Make `0x0003 deal` non-authoritative: it is a round marker only and must not initialize hand/baida.
- Decode trusted `0x0216 hand_update` with stable nibble encoding and consume only the first `count` tiles (opening uses `count=13`).
- Treat `0x021A draw` with `0x72` concealed marker as hidden draw (no visible tile mapping).
- Replay historical `events_*.jsonl` by re-decoding `raw_hex` with current parser so regressions can be validated after protocol fixes.

## Non-Goals

- No Frida backend.
- No changes to discard strategy algorithms.
- No screenshot, region setup, hand setup, manual baida, or turn toggle controls in the stable tab.

## Success Criteria

- Stable tab can start and stop packet reading without touching the vision pipeline.
- Unknown raw tile values can be mapped during runtime and reused after restart.
- Missing baida prevents analysis and shows an explicit blocked reason.
- Existing formal battle tab remains available.
- Stable tab must not show false opening hands from `0x0003` payloads.
- For 2026-05-17 records, first 13 trusted tiles from `0x0216` must match known opening-hand truth sets.
