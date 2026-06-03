"""
SIMP Agent Wallet Generator
============================
Generates deterministic Solana wallets for SIMP agents using a master seed.
Each agent gets its own wallet for V1 ordinance and operations.

Usage:
    from tokens.agent_wallets import AgentWalletManager
    
    mgr = AgentWalletManager()
    mgr.generate_all_agent_wallets()  # Create wallet for each agent with V1 allocation
    mgr.get_wallet("quantumarb")      # Get agent's wallet
    
The master seed is derived from the whale keyfile + agent_id + domain salt.
This means: same seed = same wallet, always recoverable.
"""

import hashlib
import hmac
import json
import logging
import os
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("SIMP.AgentWallets")

# ── Constants ───────────────────────────────────────────────────────────────

WHALE_KEYFILE = os.environ.get(
    "SIMP_WHALE_KEYFILE",
    "/Users/kaseymarcelle/Downloads/simp_whale_private_key.json",
)

DEFAULT_WALLET_DIR = Path("data/agent_wallets")

DOMAIN_SALT = b"simp_v1_agent_wallet_ordinance_2026"

# Agent wallet derivation paths (BIP44-like)
# m/44'/501'/<agent_index>'/0'/0'
AGENT_INDICES: Dict[str, int] = {
    "projectx_native": 0,
    "gemma4_local": 1,
    "kashclaw": 2,
    "bullbear_predictor": 3,
    "quantumarb": 4,
    "kloutbot": 5,
    "orchestrator": 6,
    "claude_cowork": 7,
    "perplexity_research": 8,
    "financial_ops": 9,
    "security_auditor": 10,
    "mesh_routing": 11,
    "ptai_knowledge": 12,
    "hermes": 13,
    "goose": 14,
    "community_pool": 15,
}


@dataclass
class AgentWallet:
    """An agent's Solana wallet for V1 ordinance."""
    agent_id: str
    index: int
    derivation_path: str
    pubkey: str
    encrypted_keyfile: Optional[str] = None
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AgentWalletManager:
    """Manages deterministic agent wallets for V1 distribution.

    Wallets are derived deterministically from:
        master_seed = HMAC-SHA256(whale_seed, domain_salt)
        agent_seed = HMAC-SHA256(master_seed, agent_index)

    This means:
    - Same computer + same whale keyfile = same agent wallets
    - Wallets can always be recovered
    - No need to store private keys (derived on-demand)
    """

    def __init__(self, wallet_dir: Optional[Path] = None):
        self._lock = threading.Lock()
        self._wallet_dir = wallet_dir or DEFAULT_WALLET_DIR
        self._wallet_dir.mkdir(parents=True, exist_ok=True)
        self._derived_wallets: Dict[str, Dict[str, Any]] = {}
        self._master_seed: Optional[bytes] = None

    # ── Seed Derivation ───────────────────────────────────────────────

    def _load_master_seed(self) -> bytes:
        """Load or derive the master seed from the whale keyfile."""
        if self._master_seed:
            return self._master_seed

        keyfile = Path(WHALE_KEYFILE)
        if not keyfile.exists():
            raise FileNotFoundError(f"Whale keyfile not found: {WHALE_KEYFILE}")

        with open(keyfile) as f:
            data = json.load(f)

        if isinstance(data, list) and len(data) >= 32:
            whale_seed = bytes(data[:32])
        else:
            raise ValueError(f"Unexpected keyfile format: {type(data)}")

        # Derive master seed: HMAC-SHA256(whale_seed, domain_salt)
        self._master_seed = hmac.new(
            whale_seed, DOMAIN_SALT, hashlib.sha256
        ).digest()
        return self._master_seed

    def _derive_agent_seed(self, index: int) -> bytes:
        """Derive an agent's seed from the master seed + index."""
        master = self._load_master_seed()
        index_bytes = index.to_bytes(4, byteorder="big")
        return hmac.new(master, index_bytes, hashlib.sha256).digest()

    # ── Pubkey Derivation ──────────────────────────────────────────────

    def _seed_to_pubkey(self, seed: bytes) -> str:
        """Convert a 32-byte seed to a Solana pubkey using Ed25519.

        Uses a subprocess call to avoid the local simpa/solana/ shadowing issue.
        Falls back to PyNaCl if simpa/solana/ is not in path.
        """
        import sys as _sys
        _sys.path = [p for p in _sys.path if 'simp/solana' not in p.replace('\\', '/')
                     and not p.endswith('/simp/solana')]

        try:
            from solders.keypair import Keypair
            kp = Keypair.from_seed(seed)
            return str(kp.pubkey())
        except ImportError:
            pass

        try:
            import nacl.bindings
            import base58
            pk, _ = nacl.bindings.crypto_sign_seed_keypair(seed)
            return base58.b58encode(pk).decode()
        except ImportError:
            raise ImportError("Need either solders or PyNaCl for key derivation")

    def get_agent_wallet(self, agent_id: str) -> Dict[str, Any]:
        """Get or create an agent's wallet.

        Returns dict with pubkey, derivation path, and seed_info.
        Does NOT return the private key.
        """
        if agent_id not in AGENT_INDICES:
            raise ValueError(f"Unknown agent: {agent_id}")

        if agent_id in self._derived_wallets:
            return self._derived_wallets[agent_id]

        index = AGENT_INDICES[agent_id]
        seed = self._derive_agent_seed(index)
        pubkey = self._seed_to_pubkey(seed)
        derivation = f"m/simp_v1/{index}"

        wallet_info = {
            "agent_id": agent_id,
            "index": index,
            "derivation": derivation,
            "pubkey": pubkey,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        self._derived_wallets[agent_id] = wallet_info

        # Cache to file
        wallet_file = self._wallet_dir / f"{agent_id}.json"
        cache_entry = {
            **wallet_info,
            "seed_hex": seed.hex(),  # Store only the seed hash for verification
        }
        with self._lock:
            with open(wallet_file, "w") as f:
                json.dump(wallet_info, f, indent=2)

        logger.info("Derived wallet for %s -> %s", agent_id, pubkey)
        return wallet_info

    def get_all_wallets(self) -> Dict[str, Dict[str, Any]]:
        """Get or create wallets for all agents with V1 allocations."""
        wallets = {}
        for agent_id in sorted(AGENT_INDICES.keys()):
            wallets[agent_id] = self.get_agent_wallet(agent_id)
        return wallets

    def register_with_distribution(self) -> Dict[str, str]:
        """Register all derived wallets with V1DistributionManager."""
        from tokens.v1_distribution import V1_DISTRIBUTION

        wallets = self.get_all_wallets()
        registered = {}
        for agent_id, info in wallets.items():
            V1_DISTRIBUTION.set_agent_wallet(agent_id, info["pubkey"])
            registered[agent_id] = info["pubkey"]

        logger.info("Registered %d agent wallets with V1 distribution", len(registered))
        return registered

    def verify_wallet(self, agent_id: str, seed_bytes: bytes) -> bool:
        """Verify that a seed produces the expected pubkey for an agent."""
        expected = self.get_agent_wallet(agent_id)
        actual_pk = self._seed_to_pubkey(seed_bytes)
        return actual_pk == expected["pubkey"]

    def get_agent_private_key(self, agent_id: str) -> Dict[str, Any]:
        """Extract the full 64-byte keypair for an agent wallet.

        Returns a dict with:
          - agent_id
          - pubkey (str)
          - keypair_hex (str) — full 128-char hex of the 64 bytes
          - keypair_list (list[int]) — solana-cli compatible JSON format
          - private_key_path (str) — path to saved JSON keyfile, or None

        This is the method to use when you need actual signing capability
        for an agent wallet (e.g., to create ATAs, sign transfers, etc.).

        WARNING: The returned keypair gives FULL CONTROL of the agent wallet.
        Treat it like a physical key.
        """
        if agent_id not in AGENT_INDICES:
            raise ValueError(f"Unknown agent: {agent_id}")

        index = AGENT_INDICES[agent_id]
        seed = self._derive_agent_seed(index)
        kp = self._seed_to_keypair(seed)
        pubkey = str(kp.pubkey())

        # Full 64-byte keypair as list (Solana-compatible JSON format)
        key_bytes = bytes(kp)
        key_list = list(key_bytes)

        # Save to private keyfile
        priv_dir = self._wallet_dir / "private"
        priv_dir.mkdir(parents=True, exist_ok=True)
        keyfile = priv_dir / f"{agent_id}.json"
        with open(keyfile, "w") as f:
            json.dump(key_list, f)

        result = {
            "agent_id": agent_id,
            "pubkey": pubkey,
            "keypair_hex": key_bytes.hex(),
            "keypair_list": key_list,
            "private_key_path": str(keyfile),
            "note": (
                "Full 64-byte Ed25519 keypair for solana-cli compatibility. "
                "Use with: solana config set --keypair <path>"
            ),
        }
        return result

    def get_all_private_keys(self) -> Dict[str, Dict[str, Any]]:
        """Extract private keys for ALL agent wallets.

        Returns dict[agent_id] -> get_agent_private_key() result.
        Writes individual Solana-compatible JSON keyfiles to
        data/agent_wallets/private/<agent_id>.json
        """
        keys = {}
        for agent_id in sorted(AGENT_INDICES.keys()):
            keys[agent_id] = self.get_agent_private_key(agent_id)
        logger.info("Extracted private keys for %d agent wallets", len(keys))
        return keys

    def _seed_to_keypair(self, seed: bytes):
        """Convert a 32-byte seed to a solders Keypair."""
        import sys as _sys
        _sys.path = [p for p in _sys.path if 'simp/solana' not in p.replace('\\', '/')
                     and not p.endswith('/simp/solana')]
        from solders.keypair import Keypair
        return Keypair.from_seed(seed)

    def export_wallet_report(self, include_private: bool = False) -> Dict[str, Any]:
        """Export a summary of all agent wallets.

        Args:
            include_private: If True, include keypair hex and file paths (DANGEROUS).
                             Default False — public keys only.

        Returns report dict.
        """
        wallets = self.get_all_wallets()
        report: Dict[str, Any] = {
            "master_seed_derived": self._master_seed is not None,
            "wallet_count": len(wallets),
            "wallets": {
                aid: {
                    "pubkey": info["pubkey"],
                    "derivation": info["derivation"],
                    "v1_ata": self._get_v1_ata(info["pubkey"]),
                }
                for aid, info in wallets.items()
            },
            "note": (
                "These wallets are deterministically derived from the whale keyfile. "
                "Private keys are stored in data/agent_wallets/private/<agent_id>.json "
                "for solana-cli compatibility. Wallets can always be recovered by "
                "running AgentWalletManager.get_agent_private_key(agent_id)."
            ),
        }

        if include_private:
            private_keys = self.get_all_private_keys()
            report["private_keys"] = {
                aid: {
                    "pubkey": info["pubkey"],
                    "keypair_hex": info["keypair_hex"],
                    "private_key_path": info["private_key_path"],
                }
                for aid, info in private_keys.items()
            }
            report["warning"] = (
                "PRIVATE KEYS INCLUDED. These give full control of agent wallets. "
                "Do not share, commit, or publish this report."
            )

        return report

    @staticmethod
    def _get_v1_ata(pubkey_str: str) -> str:
        """Derive the V1 token Associated Token Account for a wallet."""
        import sys as _sys
        _sys.path = [p for p in _sys.path if 'simp/solana' not in p.replace('\\', '/')]
        from solders.pubkey import Pubkey
        from solders.token.associated import get_associated_token_address

        V1_MINT = "CHmgojCz8Pk5qgD8nkiiCZvHkZfpfUoYn47aUqWNDZMt"
        wallet_pk = Pubkey.from_string(pubkey_str)
        mint_pk = Pubkey.from_string(V1_MINT)
        return str(get_associated_token_address(wallet_pk, mint_pk))


# Module singleton
AGENT_WALLET_MGR = AgentWalletManager()
