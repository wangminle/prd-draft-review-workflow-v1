"""API Key 加密/解密/脱敏工具"""

import base64
import hashlib

from cryptography.fernet import Fernet


def _derive_key(secret: str) -> bytes:
    """从 secret 派生 32-byte Fernet 密钥"""
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_key(plain_key: str, secret: str) -> str:
    """加密 API Key，返回 base64 密文"""
    f = Fernet(_derive_key(secret))
    return f.encrypt(plain_key.encode()).decode()


def decrypt_key(cipher_key: str, secret: str) -> str:
    """解密 API Key，返回明文"""
    f = Fernet(_derive_key(secret))
    return f.decrypt(cipher_key.encode()).decode()


def mask_key(key: str) -> str:
    """脱敏显示：sk-****xxxx（仅显示后4位）"""
    if not key or len(key) <= 8:
        return "****"
    return key[:3] + "****" + key[-4:]
