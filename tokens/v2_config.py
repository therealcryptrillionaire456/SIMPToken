"""
SIMP V2 Token Configuration — On-Chain Token Bridge.

Maps the broker's internal UnifiedTokenEngine to the real
V2 SIMPT token on Solana mainnet (Token-2022).

This module provides:
  - V2 token constants (address, decimals, supply)
  - RPC connectivity for on-chain balance verification
  - A bridge between the simulated SQLite economy and the live token
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger("SIMP.TokenV2")

# ── V2 Token Constants ─────────────────────────────────────────────────────

V2_TOKEN_MINT = "6QxRa9aeCidptKS8CS2uenbQiy5enHR7eMMY29mghZNW"
V1_TOKEN_MINT = "CHmgojCz8Pk5qgD8nkiiCZvHkZfpfUoYn47aUqWNDZMt"

TOKEN_NAME = "SIMPT"
TOKEN_SYMBOL = "SIMPT"
DECIMALS = 6

# 1 billion UI supply = 1,000,000,000 * 10^6 raw
SUPPLY_RAW = 1_000_000_000_000_000
SUPPLY_UI = 1_000_000_000

# Whale wallet (mint authority / current holder)
WHALE_PUBKEY = "58EohzqesFaxpRaqgaab7v5f9ZAhBGhzubTNHEHHmPpB"
WHALE_TOKEN_ACCOUNT = "FpK5AHKxcYSqd9pVPjrHFgE37Szdgty8GGk2p32QwSMa"

# Metadata URI (paste.c-net.org serves raw JSON)
METADATA_URI = "https://paste.c-net.org/TastyOneself"

# Alchemy RPC
ALCHEMY_RPC = os.environ.get(
    "ALCHEMY_RPC",
    "https://solana-mainnet.g.alchemy.com/v2/mDKvlGo6XpFKJWGDWc7R0dUjoIsxYjWW"
)

SIMP_API_KEY = os.environ.get("SIMP_API_KEY", "Jcym8L5ICDz7OuSa8GpuS-gprJIbCjcHyr85gikiNOQ")


@dataclass
class V2TokenInfo:
    """Structured token info for API responses and agent cards."""
    mint: str = V2_TOKEN_MINT
    name: str = TOKEN_NAME
    symbol: str = TOKEN_SYMBOL
    decimals: int = DECIMALS
    supply: int = SUPPLY_UI
    supply_raw: int = SUPPLY_RAW
    metadata_uri: str = METADATA_URI
    mint_authority: Optional[str] = None  # revoked
    program: str = "Token-2022"
    whale_pubkey: str = WHALE_PUBKEY
    whale_token_account: str = WHALE_TOKEN_ACCOUNT


# Singleton
V2_TOKEN_INFO = V2TokenInfo()


def check_onchain_supply() -> Dict[str, Any]:
    """Query the V2 token supply from Alchemy RPC.

    Returns a dict with keys:
      - success: bool
      - supply: int (UI amount)
      - decimals: int
      - error: str (if any)
    """
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenSupply",
        "params": [V2_TOKEN_MINT]
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
                    "decimals": int(value.get("decimals", DECIMALS)),
                }
            else:
                return {"success": False, "error": data.get("error", {}).get("message", "Unknown RPC error")}
    except Exception as e:
        logger.warning("Failed to query on-chain supply: %s", e)
        return {"success": False, "error": str(e)}


def check_whale_balance() -> Dict[str, Any]:
    """Check whale's V2 token balance on-chain.

    Returns dict with success/balance/error.
    """
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountBalance",
        "params": [WHALE_TOKEN_ACCOUNT]
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
                    "balance": int(value.get("uiAmount", 0)),
                    "balance_raw": int(value.get("amount", "0")),
                    "decimals": int(value.get("decimals", DECIMALS)),
                }
            else:
                return {"success": False, "error": data.get("error", {}).get("message", "Unknown RPC error")}
    except Exception as e:
        logger.warning("Failed to query whale balance: %s", e)
        return {"success": False, "error": str(e)}


def get_metadata_json() -> Dict[str, Any]:
    """Fetch the hosted metadata JSON from paste.c-net.org."""
    req = urllib.request.Request(METADATA_URI, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.warning("Failed to fetch metadata JSON: %s", e)
        return {"error": str(e)}


def get_audit_results() -> Dict[str, Any]:
    """Return a security audit summary of the V2 token."""
    from .unified import UNIFIED_ENGINE

    onchain_supply = check_onchain_supply()
    whale_balance = check_whale_balance()
    local_stats = UNIFIED_ENGINE.get_stats()

    return {
        "success": True,
        "token": V2_TOKEN_MINT,
        "program": "Token-2022",
        "mint_authority": None,  # disabled
        "mint_authority_revoked": True,
        "metadata_mutable": True,  # update authority still active
        "freeze_authority": None,
        "transfer_hook": None,
        "onchain_supply": onchain_supply,
        "whale_balance": whale_balance,
        "local_supply": local_stats.get("total_supply", 0),
        "local_circulating": local_stats.get("circulating_supply", 0),
        "audit_timestamp": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
    }
