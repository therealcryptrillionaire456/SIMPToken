"""
SIMP V1 Token Configuration — The BROKETARIUM
===============================================

V1 is the infrastructure identification token.
It is the GROUND element of the SIMP Pentagram.

Architecture (Ripple Labs dual-token model):
  - XRP  = V2 SIMPT — public-facing, market-traded, agent economy fuel
  - XRPL = V1 SIMPT — the Broketarium, infrastructure ID, never traded externally

V1 Token Properties:
  - Program: TokenkegQf (original SPL Token, NOT Token-2022)
  - Mint Authority: BURNED/REVOKED — can never mint more
  - Supply: 999,999,000 SIMPT (locked permanently)
  - External Value: ZERO — no market, no trading pairs
  - Purpose: The digital ground of the PTAI/SIMP infrastructure
  - Ownership: EXCLUSIVELY held by the mesh — no external holder can own V1

Philosophy:
  Just as Ripple Labs holds an internal token that authenticates their network
  infrastructure, V1 SIMPT is the Broketarium — the token that proves the mesh
  is the real mesh. It maps to the electro element of the Pentagram and is
  the heartbeat of the agent ecosystem.

  "V1 is the ground we walk on. V2 is the economy we build."
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("SIMP.TokenV1")

# ── V1 Token Constants ─────────────────────────────────────────────────────

V1_TOKEN_MINT = "CHmgojCz8Pk5qgD8nkiiCZvHkZfpfUoYn47aUqWNDZMt"
V1_TOKEN_NAME = "SIMPT (Legacy)"
V1_TOKEN_SYMBOL = "SIMPTv1"
V1_DECIMALS = 6
V1_SUPPLY = 999_999_000

# All V1 supply is locked in this account
V1_VAULT_PUBKEY = "58EohzqesFaxpRaqgaab7v5f9ZAhBGhzubTNHEHHmPpB"
V1_VAULT_TOKEN_ACCOUNT = "FpK5AHKxcYSqd9pVPjrHFgE37Szdgty8GGk2p32QwSMa"

# Program: Original SPL Token (NOT Token-2022)
V1_PROGRAM = "TokenkegQfFeKZQ6J9HtNqTf9gkUqGqQKQPmXmYqQUWp"

# Metadata URI
V1_METADATA_URI = "https://paste.c-net.org/ConnellChantal"

# Alchemy RPC
ALCHEMY_RPC = os.environ.get(
    "ALCHEMY_RPC",
    "https://solana-mainnet.g.alchemy.com/v2/mDKvlGo6XpFKJWGDWc7R0dUjoIsxYjWW"
)

# ── Dual-Token Architecture Constants ──────────────────────────────────────

DUAL_TOKEN_MAP = {
    "v1": {
        "mint": V1_TOKEN_MINT,
        "name": V1_TOKEN_NAME,
        "symbol": V1_TOKEN_SYMBOL,
        "role": "ground",
        "element": "electro",
        "program": V1_PROGRAM,
        "supply": V1_SUPPLY,
        "mint_authority": None,  # revoked permanently
        "external_value": 0,
        "purpose": "Infrastructure identification token (Broketarium)",
        "holder_restriction": "MESH_INTERNAL_ONLY — cannot be held by external agents",
        "solscan": f"https://solscan.io/token/{V1_TOKEN_MINT}",
    },
    "v2": {
        "mint": "6QxRa9aeCidptKS8CS2uenbQiy5enHR7eMMY29mghZNW",
        "name": "SIMPT",
        "symbol": "SIMPT",
        "role": "economy",
        "element": "aether",
        "program": "Token-2022",
        "supply": 1_000_000_000,
        "mint_authority": None,  # revoked
        "external_value": None,  # market-determined
        "purpose": "Agent economy fuel and value transfer",
        "holder_restriction": "OPEN — any agent or external wallet can hold",
        "solscan": "https://solscan.io/token/6QxRa9aeCidptKS8CS2uenbQiy5enHR7eMMY29mghZNW",
    },
}


@dataclass
class V1TokenInfo:
    """V1 Broketarium token metadata — infrastructure identification."""
    mint: str = V1_TOKEN_MINT
    name: str = V1_TOKEN_NAME
    symbol: str = V1_TOKEN_SYMBOL
    decimals: int = V1_DECIMALS
    supply: int = V1_SUPPLY
    program: str = V1_PROGRAM
    metadata_uri: str = V1_METADATA_URI
    mint_authority: Optional[str] = None  # permanently revoked
    vault_pubkey: str = V1_VAULT_PUBKEY
    vault_token_account: str = V1_VAULT_TOKEN_ACCOUNT
    external_value: int = 0
    purpose: str = "Infrastructure identification token (Broketarium)"
    holder_restriction: str = "MESH_INTERNAL_ONLY"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_heartbeat_entry(self) -> Dict[str, Any]:
        """Return the V1 entry for the dual-token heartbeat."""
        return {
            "mint": self.mint,
            "name": self.name,
            "symbol": self.symbol,
            "role": "ground",
            "element": "electro",
            "program": self.program,
            "supply": self.supply,
            "mint_authority": self.mint_authority,
            "external_value": self.external_value,
            "purpose": self.purpose,
            "holder_restriction": self.holder_restriction,
            "solscan": f"https://solscan.io/token/{self.mint}",
            "audit_timestamp": datetime.now(timezone.utc).isoformat(),
        }


# Singleton
V1_TOKEN_INFO = V1TokenInfo()


def check_v1_onchain() -> Dict[str, Any]:
    """Query V1 supply on-chain via Alchemy RPC.

    V1 uses the original SPL Token program (Tokenkeg...).
    The supply should be 999,999,000 and should NEVER change.
    """
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenSupply",
        "params": [V1_TOKEN_MINT]
    }).encode("utf-8")

    req = urllib.request.Request(
        ALCHEMY_RPC,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "result" in data and data["result"]:
                value = data["result"]["value"]
                return {
                    "success": True,
                    "supply": int(value.get("uiAmount", 0)),
                    "supply_raw": int(value.get("amount", "0")),
                    "decimals": int(value.get("decimals", V1_DECIMALS)),
                    "program": V1_PROGRAM,
                    "verified": int(value.get("uiAmount", 0)) == V1_SUPPLY,
                }
            else:
                return {"success": False,
                        "error": data.get("error", {}).get("message", "Unknown RPC error")}
    except Exception as e:
        logger.warning("V1 on-chain query failed: %s", e)
        return {"success": False, "error": str(e)}


def get_broketarium_report() -> Dict[str, Any]:
    """Full Broketarium report: V1 identity, on-chain state, and dual-token map."""
    onchain = check_v1_onchain()
    return {
        "success": True,
        "broketarium": V1_TOKEN_INFO.to_dict(),
        "dual_token_architecture": DUAL_TOKEN_MAP,
        "onchain_verification": onchain,
        "philosophy": (
            "V1 is the ground. V2 is the economy. "
            "V1 identifies the infrastructure. V2 fuels the agents. "
            "Neither can exist without the other."
        ),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
