# stable-reader Spec

## Requirements

### Packet Capture

The stable reader shall run `adb exec-out` with tcpdump against the configured device, interface, and server port.

### Protocol Decoding

The stable reader shall decode pcap bytes into TCP payloads, reassemble Mahjong protocol frames, and emit structured game events for deal, hand update, draw, discard, kong, and win.

### Mapping Correction

When a raw tile value cannot be resolved, the stable reader shall display it as an unknown mapping candidate. When the user binds it to a standard MahjongAI tile id, the binding shall be saved and replayed against current history.

### Analysis Gating

The stable reader shall not run strategy analysis unless baida is known, the current turn is self, and the self effective hand count is 14.

