"""AES-192-CTR encryption for SRS protocol.

Key finding from Frida (2026-06-11):
- setDefaultAesKey sets hardcoded 32-byte key, then setAesKey overwrites with:
- AES-192: 24-byte ALL-ZERO key
- Default IV: 15ff010034ab4cd355fea122084f1307 (16 bytes)
- transformStr = hex encoding (sprintf("%02x", byte))
"""
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# Frida-confirmed: all-zero 24-byte key
SRS_KEY = bytes(24)  # 24 bytes of 0x00

# Default IV from libcocos2dlua.so
SRS_IV = bytes.fromhex("15ff010034ab4cd355fea122084f1307")


class SRSCrypto:
    """AES-CTR encrypt/decrypt for SRS protocol.

    Uses AES-192 (24-byte all-zero key) + hex-encoding transform.
    """

    def __init__(self, key: bytes = SRS_KEY, iv: bytes = SRS_IV):
        self.key = bytes(key)
        self.iv = bytes(iv)
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
        self.key = bytes(key)
        self._reset()

    def encrypt_payload(self, plaintext: bytes) -> bytes:
        """Encrypt with AES-CTR directly (for post-handshake, when m_key is set)."""
        return self._encryptor.update(plaintext)

    def decrypt_payload(self, ciphertext: bytes) -> bytes:
        return self._decryptor.update(ciphertext)

    def transform_and_encrypt(self, plaintext: bytes) -> bytes:
        """hex_encode(plaintext) → AES-CTR encrypt.

        This is the encryptStr flow used by GuoPengFei::sendMessage.
        """
        hex_encoded = plaintext.hex().encode("ascii")
        encrypted = self._encryptor.update(hex_encoded)
        return encrypted

    def decrypt_and_untransform(self, ciphertext: bytes) -> bytes:
        """AES-CTR decrypt → hex_decode → original bytes."""
        decrypted = self._decryptor.update(ciphertext)
        return bytes.fromhex(decrypted.decode("ascii"))
