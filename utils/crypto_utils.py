"""
Solana keypair management, transaction signing, and wallet utilities.
Handles key generation, storage, and cryptographic operations for testnet.
"""

import json
import base64
from pathlib import Path
from typing import Optional, Tuple
import base58

try:
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey
    from solders.signature import Signature
    from solders.transaction import Transaction
    from solders.message import Message
    HAS_SOLDERS = True
except ImportError:
    HAS_SOLDERS = False

try:
    from nacl.signing import SigningKey, VerifyKey
    from nacl.encoding import RawEncoder
    HAS_NACL = True
except ImportError:
    HAS_NACL = False

from utils.logger import log


class SolanaWallet:
    """
    Manages a Solana keypair for signing transactions.
    Supports generation, loading from file, and loading from base58 private key.
    """

    def __init__(self):
        self._keypair: Optional[Keypair] = None
        self._signing_key: Optional[SigningKey] = None
        self._private_key_bytes: Optional[bytes] = None
        self._public_key_bytes: Optional[bytes] = None

    @property
    def public_key(self) -> str:
        """Base58-encoded public key."""
        if self._keypair and HAS_SOLDERS:
            return str(self._keypair.pubkey())
        if self._public_key_bytes:
            return base58.b58encode(self._public_key_bytes).decode()
        return ""

    @property
    def private_key_base58(self) -> str:
        """Base58-encoded private key (full 64-byte keypair)."""
        if self._keypair and HAS_SOLDERS:
            return base58.b58encode(bytes(self._keypair)).decode()
        if self._private_key_bytes:
            return base58.b58encode(self._private_key_bytes).decode()
        return ""

    @property
    def private_key_bytes_raw(self) -> bytes:
        """Raw 64-byte keypair bytes for JS wallet injection."""
        if self._keypair and HAS_SOLDERS:
            return bytes(self._keypair)
        if self._private_key_bytes:
            return self._private_key_bytes
        return b""

    def generate(self) -> "SolanaWallet":
        """Generate a fresh random keypair."""
        if HAS_SOLDERS:
            self._keypair = Keypair()
            log.info(f"Generated new Solana keypair: {self.public_key}")
        elif HAS_NACL:
            self._signing_key = SigningKey.generate()
            self._private_key_bytes = (
                self._signing_key.encode(encoder=RawEncoder)
                + self._signing_key.verify_key.encode(encoder=RawEncoder)
            )
            self._public_key_bytes = self._signing_key.verify_key.encode(encoder=RawEncoder)
            log.info(f"Generated new keypair (nacl): {self.public_key}")
        else:
            # Pure Python fallback using os.urandom
            import os
            import hashlib
            seed = os.urandom(32)
            # Use ed25519 seed to derive keypair
            # This is a simplified fallback — for production, install solders
            self._private_key_bytes = seed + seed  # Placeholder
            self._public_key_bytes = seed
            log.warning("Generated keypair using fallback (install solders for proper crypto)")
        return self

    def from_base58(self, private_key: str) -> "SolanaWallet":
        """Load keypair from a base58-encoded private key string."""
        try:
            key_bytes = base58.b58decode(private_key)
            if HAS_SOLDERS:
                self._keypair = Keypair.from_bytes(key_bytes)
            else:
                self._private_key_bytes = key_bytes
                self._public_key_bytes = key_bytes[32:] if len(key_bytes) == 64 else key_bytes
            log.info(f"Loaded wallet from base58: {self.public_key}")
        except Exception as e:
            log.error(f"Failed to load wallet from base58: {e}")
            raise
        return self

    def from_file(self, filepath: Path) -> "SolanaWallet":
        """Load keypair from a JSON file (Solana CLI format: array of bytes)."""
        try:
            with open(filepath, "r") as f:
                key_array = json.load(f)
            key_bytes = bytes(key_array)
            if HAS_SOLDERS:
                self._keypair = Keypair.from_bytes(key_bytes)
            else:
                self._private_key_bytes = key_bytes
                self._public_key_bytes = key_bytes[32:] if len(key_bytes) == 64 else key_bytes
            log.info(f"Loaded wallet from {filepath}: {self.public_key}")
        except Exception as e:
            log.error(f"Failed to load wallet from file {filepath}: {e}")
            raise
        return self

    def save_to_file(self, filepath: Path) -> Path:
        """Save keypair to a JSON file (Solana CLI format)."""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        key_bytes = self.private_key_bytes_raw
        key_array = list(key_bytes)
        with open(filepath, "w") as f:
            json.dump(key_array, f)
        log.info(f"Saved wallet to {filepath}")
        return filepath

    def sign_message(self, message: bytes) -> bytes:
        """Sign an arbitrary message with the private key."""
        if self._keypair and HAS_SOLDERS:
            sig = self._keypair.sign_message(message)
            return bytes(sig)
        elif self._signing_key and HAS_NACL:
            signed = self._signing_key.sign(message)
            return signed.signature
        else:
            log.error("No signing key available")
            raise RuntimeError("No signing key loaded — cannot sign")

    def to_js_keypair_array(self) -> list:
        """
        Return the keypair as a JS-compatible Uint8Array.
        Used for injecting into browser context for wallet provider mock.
        """
        return list(self.private_key_bytes_raw)


def load_or_create_wallet(
    private_key: str = "",
    auto_generate: bool = True,
    keypair_dir: Optional[Path] = None,
) -> SolanaWallet:
    """
    Smart wallet loader:
    1. If private_key provided, load from that
    2. If existing keypair file found, load it
    3. If auto_generate, create a new one and save it
    """
    wallet = SolanaWallet()

    # Option 1: Load from provided key
    if private_key:
        return wallet.from_base58(private_key)

    # Option 2: Load from existing file
    if keypair_dir:
        keypair_file = keypair_dir / "default_keypair.json"
        if keypair_file.exists():
            return wallet.from_file(keypair_file)

    # Option 3: Auto-generate
    if auto_generate:
        wallet.generate()
        if keypair_dir:
            wallet.save_to_file(keypair_dir / "default_keypair.json")
        return wallet

    raise RuntimeError("No wallet available: provide a private key or enable auto_generate")
