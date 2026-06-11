"""AES-256-CTR encryption/decryption for SRS protocol.

Uses the hardcoded default key extracted from libcocos2dlua.so.
"""
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

DEFAULT_KEY = bytes.fromhex(
    "f362120513e389ff2311d73601231007"
    "05a210007acc023c3901da2ecb12448b"
)  # 32 bytes

DEFAULT_IV = bytes.fromhex(
    "15ff010034ab4cd355fea122084f1307"
)  # 16 bytes


class SRSCrypto:
    """AES-256-CTR encrypt/decrypt for SRS protocol."""

    def __init__(self, key: bytes = DEFAULT_KEY, iv: bytes = DEFAULT_IV):
        self.key = bytes(key)
        self.iv = bytes(iv)
        self._encryptor = None
        self._decryptor = None
        self._reset()

    def _reset(self) -> None:
        self._encryptor = Cipher(
            algorithms.AES(self.key), modes.CTR(self.iv)
        ).encryptor()
        self._decryptor = Cipher(
            algorithms.AES(self.key), modes.CTR(self.iv)
        ).decryptor()

    def set_key(self, key: bytes) -> None:
        """Set a new AES key (e.g., m_key from RespPlayerPlusData)."""
        if len(key) not in (16, 24, 32):
            raise ValueError(f"Invalid key length: {len(key)}")
        self.key = bytes(key)
        self._reset()

    def encrypt(self, data: bytes) -> bytes:
        return self._encryptor.update(data)

    def decrypt(self, data: bytes) -> bytes:
        return self._decryptor.update(data)

    def encrypt_frame_payload(self, payload: bytes) -> bytes:
        """Encrypt only the payload portion (msgid=5 PlayerConnect)."""
        return self.encrypt(payload)
