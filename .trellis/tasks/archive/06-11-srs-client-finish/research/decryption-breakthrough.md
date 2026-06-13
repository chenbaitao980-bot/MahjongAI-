# Decryption Breakthrough — 2026-06-11 23:30

## Confirmed Encryption Flow

1. **EncryptVer**: `AES_CFB128(default_key, iv).encrypt(b'\x01\x00\x00\x00')` → `fa60a522`
2. **HandshakeRsp**: Server sends encrypted with default key (S2C direction, CFB from IV).
   - Decrypt with default key → `[version_byte(1B)][session_key(16B)]`
   - `_crypto.set_key(session_key)` resets CFB state
3. **PlayerConnect**: `AES_CFB128(session_key, iv).encrypt(raw_binary)` — **NO hex encoding!**
4. **PlayerData / RespPlusData**: Decrypted with session key

## PlayerConnect Binary Format

From `SRSProtocol.lua:PlayerConnect:bostream()` + wire capture verification:

```
offset  size  field
0       1     clienttype (2=MOBILE)
1       1     usertype (7=SESSION)
2       4     areaid (LE uint32)
6       1     uid_len + uid string
7+uidlen 16   pwd (raw 16-byte session token)
...     1+12  identify (1B len "020000000000" = RC4-encrypted hardware fingerprint)
...     4     ver
...     4     channelid
...     4     osver
...     1+12  identify (repeated)
...     4     nGameID
```

IStream.writeString = 1-byte length + string (NOT uint16 BE!)

## Identified Blocker

**pwd / sessionid (16B)**: The server rejects PlayerConnect with wrong pwd. The pwd is a session token obtained from the HTTPS login flow (before TCP connection). Our emulator-captured pwd may have expired.

## Tests Completed

- ✅ EncryptVer encryption/decryption confirmed correct
- ✅ HandshakeRsp decryption + session key extraction confirmed correct
- ✅ PlayerConnect binary format matches 80B capture
- ✅ AES-CFB128 with session key produces correct decrypt of captured PlayerConnect
- ❌ Live connection: server closes immediately after PlayerConnect (likely expired session token)

## Next Steps

1. **Fresh capture**: Run emulator again, capture NEW session immediately, test within seconds
2. **Try identify variants**: Test with empty identify (once worked?)
3. **Try MJ protocol direct**: Skip SRS layer, send MJ init+handshake+auth directly after connection
