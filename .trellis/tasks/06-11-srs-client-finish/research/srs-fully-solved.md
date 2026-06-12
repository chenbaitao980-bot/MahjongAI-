# SRS Decryption — Fully Solved (2026-06-12)

## Complete Encryption Chain

### EncryptVer
```
Client: AES_CFB128(default_key, IV).encrypt(b'\x01\x00\x00\x00') → fa60a522
Server: Sends back fa60a522 (echo, plain text)
```

### HandshakeRsp → Session Key
```
Server: AES_CFB128(default_key, IV).encrypt([key_len(1B)][session_key(key_len B)])
        sent S2C direction, CFB from IV
Client: AES_CFB128(default_key, IV).decrypt → [key_len(1B)][session_key(key_len B)]
        key_len ∈ {16, 24, 32} → AES-128/192/256

setAesKey(session_key) — CFB state RESETS to IV (confirmed by decrypting captured PC from IV)
```

### PlayerConnect
```
Format: per SRSProtocol.lua PlayerConnect:bostream()
  IStream.writeString = 1-byte length + data
  IStream.writeUInt32 = 4 bytes LE + 1 byte padding (!)
  Total: 81 bytes for the default PlayerConnect

Encryption: AES_CFB128(session_key, IV).encrypt(raw_binary)
           NO hex encoding at this stage

Server response: PlayerData (msg=6), encrypted with session key
```

### PlayerData / RespPlusData
```
Both encrypted with session key, CFB continues from previous state
RespPlusData contains m_key → setAesKey(m_key) for subsequent traffic
```

## Critical Fixes Made

1. **AES-CFB128** mode (not CTR)
2. **Default key**: 32 bytes `f362120513e389ff...` (not 24-byte zeros)
3. **Variable key length**: HandshakeRsp[0] = key_len ∈ {16,24,32}
4. **NO hex encoding** for PlayerConnect (raw binary encryption)
5. ~~**IStream alignment**: areaid has extra 00 padding byte after writeUInt32~~
   **WRONG — see 2026-06-12 correction below. There is NO padding byte.**
6. **String encoding**: 1-byte length (writeString uses compact format)

---

## ★ 2026-06-12 BREAKTHROUGH — flag=41 root cause found, protocol fully validated live

Validated against the LIVE server `47.96.0.227:7777` AND cross-checked by
decrypting two independent pcaps. The earlier "flag=41 = stale credential"
diagnosis was **WRONG**.

### Offline proof (no phone needed)
`data/phone_srs.pcap` and `data/phone_full.pcap` BOTH decrypt cleanly with the
SRS chain — HandshakeRsp(S→C,msg=4)→session_key, PlayerConnect(C→S,msg=5)→pwd —
and yield the **same** 16-byte sessionid `a269e12a1ca5442db00ec625a0d0e619`.
Offsets + AES params are therefore correct (`scripts/diag_srs_sample.py`).

### Real PlayerConnect plaintext (80 bytes, decoded from phone_srs.pcap)
```
02 07 | c51b0000 (areaid=7109) | 0f "newpt1084306678" (uid, 1-byte len!)
| a269e12a1ca5442db00ec625a0d0e619 (pwd=16B) | 0c "020000000000" (identify)
| ver=0 | channelid=70900 | osver=10160 | 0c "020000000000" | nGameID=900535
```
Total = exactly 80 bytes. **NO padding byte after areaid.** writeUInt32 = 4 bytes.

### Two real bugs that caused flag=41 (NOT credential staleness)
1. `player_connect.py:build_player_connect_raw` adds a spurious `bos.append(0)`
   padding byte after areaid → 81 bytes, everything after pwd misaligned → the
   server can't resolve the account → **flag=41 ACCOUNT_ERR**.
2. `client.py` builds PlayerConnect with `userid=b""` (empty) instead of the real
   uid → server can't find the account → **flag=41**.

### Live confirmation (`scripts/diag_srs_live.py`)
Sending the byte-perfect 80B plaintext (re-encrypted with a fresh session key)
to the live server:
```
-> EncryptVer fa60a522
<- EncryptVer (echo)
-> ReqKey
<- HandshakeRsp 17B → session_key 6ae3e08a... (AES-128)
-> PlayerConnect 80B
<- PlayerData 88B → flag=72, areaid=7109, numid=1084306678
```
- **numid=1084306678 resolved** = uid "newpt**1084306678**" → server FOUND the account.
- **flag=72 = INVALID_SESSIONID (令牌错误)** — SRSProtocol.lua:199. Pure token error.
  NOT 75 (token+machinecode) → our identify `020000000000` was accepted too.

### Conclusion
Protocol is **fully solved and live-validated**. Only the pwd (session token) is
stale. A **fresh, currently-online sessionid** in this exact code path → **flag=0
SUCCESS**. No protocol unknowns remain.

## Remaining work
1. **Fix format bugs**: remove padding byte in `player_connect.py`; stop passing
   empty uid in `client.py`. Robust design: have `SRSSessionExtractor` capture the
   FULL decrypted PlayerConnect plaintext (80B template) and have the spectator
   just re-encrypt it with its fresh session key (no field reconstruction).
2. **Fresh-credential live test**: capture one fresh PlayerConnect (phone online),
   splice its pwd into the 80B template (or capture full template), run
   `diag_srs_live.py` → expect flag=0.

## Files Modified
- `remote/srs_spectator/crypto.py` — AES-CFB128 + real key (already fixed in a90a11d)
- `remote/srs_spectator/player_connect.py` — has padding-byte bug (to fix)
- `remote/srs_spectator/client.py` — uses empty uid (to fix)
- `scripts/diag_srs_sample.py` — NEW: offline pcap scan for decryptable handshake
- `scripts/diag_srs_live.py` — NEW: live byte-perfect PlayerConnect replay
