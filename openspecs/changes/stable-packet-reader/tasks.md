# Tasks: stable-packet-reader

## Implementation

- [x] Add project-local OpenSpec files.
- [x] Add packet parser and protocol decoder.
- [x] Add raw tile mapping store with runtime correction persistence.
- [x] Add packet state tracker that can produce `BattleState`.
- [x] Add stable version UI tab.
- [x] Connect tcpdump thread and strategy analysis flow in `MainWindow`.

## Verification

- [x] Add unit tests for protocol reassembly, mapping persistence, and baida analysis blocking.
- [x] Add regression tests for 2026-05-17 trusted opening-hand decoding (first 13 tiles).
- [x] Add protocol tests for untrusted `0x0003 deal` and concealed draw marker handling.
- [x] Verify replay helper re-decodes from `raw_hex` for historical jsonl records.
- [x] Run unit tests.
- [x] Run Python compile check.
