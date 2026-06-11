"""SRS ciphertext decryption validator — close the loop on one real capture.

Once you have ONE real SRS ciphertext sample on the wire, this tool brute-tries
the plausible (key, hex-order) combinations and prints each candidate plaintext
so you can eyeball which combination decrypted correctly. It reuses the verified
AES-CFB128 parameters from crypto.py (default key, fixed IV) — no AES is
re-implemented here.

------------------------------------------------------------------------------
How to obtain a sample to feed in
------------------------------------------------------------------------------
The Frida hook `frida/hook_srs.js` writes /data/local/tmp/.srs_dump.jsonl on the
phone. Useful record types:
  - {"type":"wire_send", ...,"data":"<hex>"}  -> encrypted bytes the client SENT
  - {"type":"tcp_recv",  ...,"data":"<hex>"}  -> raw bytes RECEIVED from server
  - {"type":"encrypt",   "plaintext":"<hex>"} -> the PLAINTEXT before encrypt()
        (use this to confirm a wire_send decrypts back to it)
  - {"type":"setAesKey", "key":"<hex>","len":N} -> the session key (may be the
        anti-tamper-scrubbed all-zero value; the REAL key comes from RespKey).

Pull it off the device, then:
  1. Strip the 12-byte frame header (see frame.py) if you want to decrypt just
     the payload, or feed the whole frame — the heuristic looks for the 0x4001
     flag either way.
  2. Pass the hex via positional arg, --hex, or --file.
  3. If you captured a RespKey session key, pass it via --session-key <hex>.

Examples:
  python remote/srs_spectator/decrypt_validate.py 01400a00...
  python remote/srs_spectator/decrypt_validate.py --hex 01400a00... \
      --session-key f362120513e389ff...
  python remote/srs_spectator/decrypt_validate.py --file sample.hex
------------------------------------------------------------------------------
"""
import argparse
import string
import sys

try:
    # When run as a module: python -m remote.srs_spectator.decrypt_validate
    from .crypto import SRSCrypto, SRS_DEFAULT_KEY, SRS_IV
except ImportError:
    # When run as a script: python remote/srs_spectator/decrypt_validate.py
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from crypto import SRSCrypto, SRS_DEFAULT_KEY, SRS_IV  # type: ignore


_PRINTABLE = set(bytes(string.printable, "ascii"))
SRS_FRAME_FLAG_LE = b"\x01\x40"  # 0x4001 little-endian on the wire


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _clean_hex(s: str) -> str:
    """Strip whitespace/0x prefixes/colons so loose pasted hex still parses."""
    s = s.strip().replace("0x", "").replace("0X", "")
    for ch in (" ", "\n", "\r", "\t", ":", ",", "-"):
        s = s.replace(ch, "")
    return s


def _ascii_preview(data: bytes, limit: int = 64) -> str:
    out = []
    for b in data[:limit]:
        out.append(chr(b) if 32 <= b < 127 else ".")
    tail = "..." if len(data) > limit else ""
    return "".join(out) + tail


def _printable_ratio(data: bytes) -> float:
    if not data:
        return 0.0
    good = sum(1 for b in data if b in _PRINTABLE)
    return good / len(data)


def _looks_like_srs_frame(data: bytes) -> bool:
    """0x4001 flag at the very start (decrypted a full frame)."""
    return data[:2] == SRS_FRAME_FLAG_LE


def _has_frame_flag_anywhere(data: bytes) -> bool:
    return SRS_FRAME_FLAG_LE in data


def _looks_like_protobuf(data: bytes) -> bool:
    """Very loose protobuf sniff: first byte is a plausible field tag and at
    least the first couple of varint fields parse without running off the end.
    """
    if len(data) < 2:
        return False
    pos = 0
    fields = 0
    while pos < len(data) and fields < 3:
        tag = data[pos]
        pos += 1
        field_no = tag >> 3
        wire = tag & 0x07
        if field_no == 0 or wire in (6, 7):
            return False
        if wire == 0:  # varint
            shift = 0
            while pos < len(data) and (data[pos] & 0x80):
                pos += 1
                shift += 1
                if shift > 9:
                    return False
            pos += 1
        elif wire == 2:  # length-delimited
            if pos >= len(data):
                return False
            ln = data[pos]
            pos += 1
            if ln & 0x80:  # multi-byte length varint — give up cheaply
                return False
            pos += ln
        elif wire == 5:  # 32-bit
            pos += 4
        elif wire == 1:  # 64-bit
            pos += 8
        else:
            return False
        fields += 1
    return fields >= 1 and pos <= len(data) + 1


def _score(data: bytes) -> tuple:
    """Heuristic score: higher = more likely correct. Returns (score, reasons)."""
    score = 0.0
    reasons = []
    if _looks_like_srs_frame(data):
        score += 100
        reasons.append("starts with 0x4001 frame flag")
    elif _has_frame_flag_anywhere(data):
        score += 30
        reasons.append("contains 0x4001 flag")
    pr = _printable_ratio(data)
    score += pr * 20
    if pr > 0.7:
        reasons.append(f"high ascii ratio {pr:.0%}")
    if _looks_like_protobuf(data):
        score += 15
        reasons.append("plausible protobuf varint structure")
    return score, reasons


# --------------------------------------------------------------------------- #
# candidate generators (each returns bytes or None on failure)
# --------------------------------------------------------------------------- #
def _cfb_decrypt(key: bytes, iv: bytes, ct: bytes) -> bytes:
    return SRSCrypto(key=key, iv=iv).decrypt_payload(ct)


def _combo_direct(key, iv, ct):
    """CFB128 decrypt, use the plaintext as-is."""
    return _cfb_decrypt(key, iv, ct)


def _combo_hex_after(key, iv, ct):
    """hex-after-AES: decrypt, then the plaintext is ascii-hex -> hex-decode."""
    pt = _cfb_decrypt(key, iv, ct)
    return bytes.fromhex(pt.decode("ascii"))


def _combo_hex_before(key, iv, ct):
    """hex-before: the CIPHERTEXT is ascii-hex -> hex-decode it, then CFB decrypt."""
    raw_ct = bytes.fromhex(ct.decode("ascii"))
    return _cfb_decrypt(key, iv, raw_ct)


_COMBOS = [
    ("CFB128, direct decrypt", _combo_direct),
    ("CFB128, hex-decode AFTER decrypt (hex-after-AES)", _combo_hex_after),
    ("CFB128, hex-decode ciphertext BEFORE decrypt (hex-before)", _combo_hex_before),
]


def _run_key(label: str, key: bytes, iv: bytes, ct: bytes):
    results = []
    print(f"\n=== {label} (AES-{len(key) * 8}, key={key.hex()[:16]}...) ===")
    for name, fn in _COMBOS:
        try:
            pt = fn(key, iv, ct)
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"  [{name}]")
            print(f"      -> FAILED: {type(exc).__name__}: {exc}")
            continue
        score, reasons = _score(pt)
        results.append((score, label, name, pt, reasons))
        print(f"  [{name}]")
        print(f"      hex   : {pt.hex()}")
        print(f"      ascii : {_ascii_preview(pt)}")
        tag = ", ".join(reasons) if reasons else "(no positive signals)"
        print(f"      score : {score:.1f}  ({tag})")
    return results


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Brute-try SRS AES-CFB128 (key, hex-order) combos on one "
                    "ciphertext sample and rank candidate plaintexts.",
    )
    parser.add_argument("hex_pos", nargs="?", help="ciphertext hex (positional)")
    parser.add_argument("--hex", dest="hex_opt", help="ciphertext hex")
    parser.add_argument("--file", help="read ciphertext hex from a file")
    parser.add_argument("--session-key", help="RespKey session key hex (16/24/32 bytes)")
    parser.add_argument("--iv", help="override the default IV (hex, 16 bytes)")
    args = parser.parse_args(argv)

    raw = args.hex_pos or args.hex_opt
    if args.file:
        with open(args.file, "r", encoding="utf-8") as fh:
            raw = fh.read()
    if not raw:
        parser.error("provide ciphertext hex via positional arg, --hex, or --file")

    try:
        ct = bytes.fromhex(_clean_hex(raw))
    except ValueError as exc:
        parser.error(f"invalid ciphertext hex: {exc}")
    if not ct:
        parser.error("empty ciphertext")

    iv = SRS_IV
    if args.iv:
        try:
            iv = bytes.fromhex(_clean_hex(args.iv))
        except ValueError as exc:
            parser.error(f"invalid IV hex: {exc}")
        if len(iv) != 16:
            parser.error(f"IV must be 16 bytes, got {len(iv)}")

    print(f"ciphertext : {len(ct)} bytes")
    print(f"IV         : {iv.hex()}")

    all_results = []
    all_results += _run_key("default key", SRS_DEFAULT_KEY, iv, ct)

    if args.session_key:
        try:
            skey = bytes.fromhex(_clean_hex(args.session_key))
        except ValueError as exc:
            parser.error(f"invalid session key hex: {exc}")
        if len(skey) not in (16, 24, 32):
            parser.error(f"session key must be 16/24/32 bytes, got {len(skey)}")
        all_results += _run_key("session key (RespKey)", skey, iv, ct)

    # verdict
    print("\n" + "=" * 60)
    if not all_results:
        print("No candidate produced output (all combos failed to decode).")
        return 0
    all_results.sort(key=lambda r: r[0], reverse=True)
    best_score, best_key, best_combo, best_pt, best_reasons = all_results[0]
    if best_score >= 50:
        print(f"LIKELY MATCH: '{best_key}' + '{best_combo}'  (score {best_score:.1f})")
        print(f"  reasons: {', '.join(best_reasons)}")
        print(f"  ascii  : {_ascii_preview(best_pt)}")
    else:
        print("No combination looks clearly correct (best score "
              f"{best_score:.1f} < 50).")
        print("  Likely wrong session key, wrong sample boundaries, or the "
              "hex/AES ordering differs. Best guess below:")
        print(f"  '{best_key}' + '{best_combo}' -> {_ascii_preview(best_pt)}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
