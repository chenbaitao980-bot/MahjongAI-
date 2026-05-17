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
- Unknown tile values are recorded and displayed, not guessed.
- Baida must come from protocol fields; until such a field is decoded, analysis remains blocked.

## Rollback

The change is additive. Removing the stable tab import/build call and the `stable/` package restores the previous application behavior.

