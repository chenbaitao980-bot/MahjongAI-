"""AES-256-CFB128 encryption for the SRS protocol.

Ground truth from static reversing of `apk_research/native/libcocos2dlua.so`
(2026-06-11). Full evidence:
  .trellis/tasks/06-11-srs-client-finish/research/srs-key-derivation.md

Key facts (each backed by disassembly in the research report):
  - Default key   = 32 bytes (AES-256), hardcoded in .rodata @0x11f660c:
        f362120513e389ff2311d7360123100705a210007acc023c3901da2ecb12448b
    Loaded by Encryption::setDefaultAesKey @0x8f53d8 (mov w9,#0x20 -> len=32).
  - IV            = 16 bytes, fixed, .rodata @0x11f662c:
        15ff010034ab4cd355fea122084f1307
  - Mode          = AES-CFB128 (OpenSSL AES_cfb128_encrypt; confirmed via
    GOT/.rela.plt relocation in Encryption::encrypt @0x8f5400). NOT CTR.
    `CFB` in the `cryptography` lib IS CFB128 (full-block feedback);
    do NOT use `CFB8`.
  - Session key   = whatever the server's RespKey message carries: payload is
    len(1B) + key(len B). GuoPengFei::onRespKey @0x907b9c copies it verbatim
    into setAesKey with NO KDF/XOR/transform. key length (16/24/32) picks
    AES-128/192/256.

The previously-recorded "AES-192 / 24-byte all-zero key, Frida-confirmed" was
WRONG: the zero key is anti-tamper scrubbed bytes, not the real key. The mode
"AES-CTR" was also WRONG. Both are fixed here.
"""
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms

try:
    # cryptography >= 48 relocated CFB here (decrepit). Prefer it to avoid the
    # CryptographyDeprecationWarning; it is removed from `primitives.ciphers.modes`
    # in 49.0. CFB == CFB128 (full-block feedback) either way.
    from cryptography.hazmat.decrepit.ciphers.modes import CFB
except ImportError:  # older cryptography
    from cryptography.hazmat.primitives.ciphers.modes import CFB

# Hardcoded default key — 32 bytes (AES-256), .rodata @0x11f660c.
SRS_DEFAULT_KEY = bytes.fromhex(
    "f362120513e389ff2311d7360123100705a210007acc023c3901da2ecb12448b"
)

# Backwards-compat alias (older code imports SRS_KEY).
SRS_KEY = SRS_DEFAULT_KEY

# Fixed IV, .rodata @0x11f662c.
SRS_IV = bytes.fromhex("15ff010034ab4cd355fea122084f1307")


class SRSCrypto:
    """AES-CFB128 encrypt/decrypt for the SRS protocol.

    Defaults to the 32-byte (AES-256) hardcoded key used during the early
    handshake. Once the server's RespKey message arrives, call ``set_key()``
    with the downloaded session key (length 16/24/32 selects AES-128/192/256).

    CFB is a *stateful stream cipher*: each Encryption cycle starts from the IV
    with num=0, and successive ``update`` calls keep the feedback chain going.
    Switching keys (RespKey arrival) must rebuild the cipher, so ``set_key``
    calls ``_reset`` — matching the native code, which re-seeds from the IV
    each Encryption cycle.
    """

    def __init__(self, key: bytes = SRS_DEFAULT_KEY, iv: bytes = SRS_IV):
        self.key = bytes(key)
        self.iv = bytes(iv)
        self._reset()

    def _reset(self) -> None:
        # AES algorithm auto-selects 128/192/256 from key length (16/24/32).
        self._encryptor = Cipher(
            algorithms.AES(self.key), CFB(self.iv)
        ).encryptor()
        self._decryptor = Cipher(
            algorithms.AES(self.key), CFB(self.iv)
        ).decryptor()

    def set_key(self, key: bytes) -> None:
        """Install a new session key (from RespKey) and reset the CFB state.

        Key length must be 16/24/32 (AES-128/192/256). The IV is unchanged.
        """
        key = bytes(key)
        if len(key) not in (16, 24, 32):
            raise ValueError(
                f"SRS session key must be 16/24/32 bytes, got {len(key)}"
            )
        self.key = key
        self._reset()

    def encrypt_payload(self, plaintext: bytes) -> bytes:
        """AES-CFB128 encrypt (no hex transform)."""
        return self._encryptor.update(plaintext)

    def decrypt_payload(self, ciphertext: bytes) -> bytes:
        """AES-CFB128 decrypt (no hex transform)."""
        return self._decryptor.update(ciphertext)

    def transform_and_encrypt(self, plaintext: bytes) -> bytes:
        """hex_encode(plaintext) -> AES-CFB128 encrypt.

        ``transformStr`` (Encryption::transformStr @0x8f5794) is confirmed to
        be lowercase-hex encoding (snprintf "%02x", out_len = in_len*2).

        TODO (待真实样本验证): static analysis confirmed `transformStr` and
        `encrypt` are two *independent* functions — the encrypt() body does NOT
        call transformStr internally. Whether the hex step runs BEFORE AES
        (this method's assumption) or AFTER is not yet pinned down. The CFB key
        bytes are right; only the hex/AES ordering is open. See research
        report §transformStr.
        """
        hex_encoded = plaintext.hex().encode("ascii")
        return self._encryptor.update(hex_encoded)

    def decrypt_and_untransform(self, ciphertext: bytes) -> bytes:
        """AES-CFB128 decrypt -> hex_decode -> original bytes.

        Inverse of ``transform_and_encrypt`` (hex-before-AES assumption).
        See the TODO in ``transform_and_encrypt`` — ordering待真实样本验证.
        """
        decrypted = self._decryptor.update(ciphertext)
        return bytes.fromhex(decrypted.decode("ascii"))
