# stable-reader Spec

## Requirements

### Packet Capture

The stable reader shall run `adb exec-out` with tcpdump against the configured device, interface, and server port.

### Protocol Decoding

The stable reader shall decode pcap bytes into TCP payloads, reassemble Mahjong protocol frames, and emit structured game events for deal, hand update, draw, discard, kong, and win.
The stable reader shall treat `0x0003 deal` as an untrusted round marker and shall not initialize hand or baida from this payload.
The stable reader shall decode trusted `0x0216 hand_update` tiles from the first `count` bytes only, and preserve trailing bytes as non-hand metadata.
The stable reader shall decode stable packet tile bytes with the stable nibble mapping (`0x1*` m, `0x2*` s, `0x3*` p, `0x4*` winds, `0x5*` dragons).
The stable reader shall treat `0x021A` packets containing `0x72` concealed marker as hidden draw and shall not emit a visible tile for that draw.

### Mapping Correction

When a raw tile value cannot be resolved, the stable reader shall display it as an unknown mapping candidate. When the user binds it to a standard MahjongAI tile id, the binding shall be saved and replayed against current history.

### Analysis Gating

The stable reader shall not run strategy analysis unless baida is known, the current turn is self, and the self effective hand count is 14.

### Replay Compatibility

Offline replay of saved `events_*.jsonl` shall prefer re-decoding from `raw_hex` so that historical captures can be validated against updated parser logic.
