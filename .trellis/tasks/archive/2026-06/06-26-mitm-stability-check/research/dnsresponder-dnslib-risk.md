# Research: DnsResponder dnslib Exception Risk Analysis

- **Query**: Find DnsResponder class and analyze what happens if dnslib.DNSRecord.parse() replaces custom parsing
- **Scope**: Internal + External (dnslib knowledge)
- **Date**: 2026-06-26

## Findings

### Files Found

| File Path | Description |
|---|---|
| `remote/noconfig/hijack/setup_mitm.py:1156-1270` | DnsResponder class (noconfig version) |
| `interface/mahjong_mitm/setup_mitm.py:1167-1270` | DnsResponder class (interface version) |

### Current Implementation Details

#### Custom Parsing Code (`_parse_qname`)

Both files have identical `_parse_qname` at:
- noconfig: lines 1200-1213
- interface: lines 1211-1224

```python
@staticmethod
def _parse_qname(data: bytes) -> tuple[str, int]:
    off = 12  # header
    labels = []
    while True:
        length = data[off]; off += 1
        if length == 0:
            break
        labels.append(data[off:off + length].decode("ascii", errors="replace"))
        off += length
    name = ".".join(labels)
    off += 4  # qtype(2) + qclass(2)
    return name, off
```

**Current exception handling in `_loop()`:**

noconfig line 1197, interface line 1208:
```python
try:
    resp = self._handle(data)
    if resp:
        self._sock.sendto(resp, addr)
except Exception as e:
    logger.debug("DNS handle error: %s", e)
```

The `_handle()` method is at noconfig line 1215-1225, interface line 1226-1236. It calls `_parse_qname()` and `struct.unpack_from()` without internal try/catch.

### dnslib Status in Project

- **dnslib is NOT installed**: Not in requirements.txt, not in pip list
- **dnslib is NOT imported**: No `import dnslib` or `from dnslib` anywhere in codebase
- **Current implementation**: Uses custom byte parsing + struct module only

### dnslib.DNSRecord.parse() Exception Profile

Based on dnslib source code knowledge (https://github.com/paulc/dnslib):

`dnslib.DNSRecord.parse(data)` can raise these exceptions:

1. **`IndexError`** - Truncated packets, buffer over-read during label parsing
2. **`ValueError`** - Malformed domain names, invalid compression pointers
3. **`struct.error`** - Header unpack failures from `struct.unpack`
4. **`UnicodeDecodeError`** - Non-ASCII labels in IDN variants
5. **`TypeError`** - Non-bytes input passed to parse()
6. **General `Exception` subclasses** - Various parsing edge cases

### Current Exception Handling Coverage

The `_loop()` method has a **broad `except Exception as e`** handler around the entire `_handle()` call:

- This catches **ALL** standard Python exceptions including:
  - `IndexError` ✓
  - `ValueError` ✓
  - `struct.error` ✓ (subclass of Exception)
  - `UnicodeDecodeError` ✓
  - `TypeError` ✓

**Risk Level**: LOW - No unhandled exceptions would escape

### What Would Happen If dnslib Replaced Custom Parsing

1. **Server crash risk**: NONE. The broad `Exception` catch in `_loop()` would catch any parsing error and log it at DEBUG level.

2. **Behavior change**: dnslib is a full DNS parser, so it would:
   - Validate the entire DNS packet structure
   - Handle DNS compression pointers properly
   - Reject malformed packets earlier than the current minimalist parser
   - Raise exceptions on packet formats the current code silently accepts

3. **Logging**: Exceptions would be logged via `logger.debug("DNS handle error: %s", e)` - same as current failures.

### Custom vs dnslib Parsing Exception Safety Comparison

| Aspect | Custom Parsing | dnslib Parsing |
|---|---|---|
| `IndexError` on short data | `len(data) < 12` check at line 1216 only; `data[off]` at line 1206 can raise if packet malformed after header | Full validation; can raise on any malformed offset |
| `struct.error` | Raised by `struct.unpack_from()` at line 1219 if `qend - 4` out of bounds | Raised by internal struct calls on header/fields |
| Compression pointers | NOT handled; `_parse_qname` does not follow DNS compression (`0xC0` pointers) → can produce wrong names or infinite loops | Fully handled per RFC 1035 |
| Exception type coverage | Broad `Exception` catch covers all | Same broad catch covers all dnslib exceptions |
| Crash risk | Low (caught) | Same low (caught) |
| Silent failures | Can silently produce malformed responses on weird packets | Fails fast (raises → logged → ignored) |

## Caveats / Not Found

1. dnslib is not currently a project dependency - this analysis is based on public dnslib library behavior
2. The broad `except Exception` in `_loop()` is both a strength (no crashes) and a potential debugging issue (DEBUG level logging may not be visible)
3. Current custom parsing has known limitations with DNS compression pointers that dnslib would solve, but at the cost of rejecting more malformed packets
