# Design: stable-packet-reader

## Current State

`BattlePanel` and `BattleService` are built around visual hand capture, manual battle editing, and the existing strategy engine. The strategy engine can already analyze a `BattleState` without image recognition through `analyze_state_only()` and `analyze_state_with_ai()`.

## Approach

- Keep the old battle tab unchanged.
- Add a stable tab that owns packet capture and packet state display.
- Use `StableCaptureThread` to run `adb exec-out` with tcpdump and feed bytes into `PcapParser` and `MJProtocol`.
- Use `PacketStateTracker` to convert protocol messages into a `BattleState`.
- Use `MappingStore` to combine built-in raw-code mappings and user-saved corrections.
- Reuse `BattleAnalysisThread` in `state_only` or `state_with_ai` mode so stable analysis cannot call screenshot recognition.

## Data Rules

- Built-in linear mapping: `1-9 -> 1m-9m`, `11-19 -> 1p-9p`, `21-29 -> 1s-9s`, `31-37 -> 1z-7z`.
- Built-in nibble mapping: high nibble `0/1/2/3` maps to `m/p/s/z`.
- Built-in stable mapping for trusted live packets:
  - `0x11-0x19 -> 1m-9m`
  - `0x21-0x29 -> 1s-9s`
  - `0x31-0x39 -> 1p-9p`
  - `0x41-0x44 -> 1z-4z` (east/south/west/north)
  - `0x51-0x53 -> 5z-7z` (red/green/white)
- Unknown tile values are recorded and displayed, not guessed.
- Baida must come from protocol fields; until such a field is decoded, analysis remains blocked.
- `0x0003 deal` is untrusted and only used as round marker; candidate hand/baida bytes are kept for debugging only.
- `0x0216 hand_update` is trusted for hand updates and only consumes the first `count` bytes after offset 3; tail bytes are metadata.
- `0x021A draw` with `0x72` marker is treated as concealed draw and must not produce a visible tile.

## Replay and Regression

- Offline replay supports both `.pcap` and saved `events_*.jsonl`.
- For saved events, replay re-decodes `raw_hex` using current parser to avoid stale decoded fields after protocol fixes.

## Rollback

The change is additive. Removing the stable tab import/build call and the `stable/` package restores the previous application behavior.
