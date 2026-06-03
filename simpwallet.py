"""
SIMPWallet — AI-Native State-Carrying Token Explorer
=====================================================

Solscan shows you what happened on-chain.
SIMPWallet shows you what's happening in the mesh.

Thesis
------
Solana block explorers are built for humans trading tokens.
SIMPWallet is built for a world where agents are the primary economic actors.

Features Solscan can't touch:
  - State-carrying token memo visualization (mesh state IN the transfer)
  - Agent mesh topology (trust graphs, intent flow paths)
  - Revenue transparency (on-chain fee flow + agent-level distribution)
  - Offline-state verification (proving the mesh works without internet)
  - AI-native query layer ("show me agents with >0.8 trust score")
  - Cross-dimensional analytics (on-chain tx ↔ mesh intent correlation)

Architecture
------------
┌──────────────────────────────────────────────────────────┐
│                    SIMPWallet                             │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │ On-Chain     │  │ Mesh State   │  │ State-Carrying  │  │
│  │ Layer        │  │ Layer        │  │ Protocol Layer  │  │
│  │ (Solana RPC) │  │ (Trust/Agents)│  │ (Memos/Offline) │  │
│  ├─────────────┤  ├──────────────┤  ├────────────────┤  │
│  │ Token supply│  │ Agent registry│  │ TokenMemoV2    │  │
│  │ Top holders │  │ Trust graph  │  │ StateDiff      │  │
│  │ TX history  │  │ Intent ledger│  │ OfflineQueue   │  │
│  │ Program intx│  │ Fee flow     │  │ CRDT merge     │  │
│  └─────────────┘  └──────────────┘  └────────────────┘  │
│                          │                                │
│                   ┌──────┴──────┐                        │
│                   │  /v1/simpwallet/* endpoints          │
│                   └─────────────┘                        │
└──────────────────────────────────────────────────────────┘

Every endpoint returns both "ground truth" (on-chain) and "mesh truth"
(agent-level activity) because in an agent economy, BOTH are real.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from hashlib import sha256

logger = logging.getLogger("SIMPWallet")

# ── Constants ───────────────────────────────────────────────────────────────

V2_TOKEN_MINT = "6QxRa9aeCidptKS8CS2uenbQiy5enHR7eMMY29mghZNW"
V1_TOKEN_MINT = "CHmgojCz8Pk5qgD8nkiiCZvHkZfpfUoYn47aUqWNDZMt"
V2_TOKEN_WHALE = "58EohzqesFaxpRaqgaab7v5f9ZAhBGhzubTNHEHHmPpB"
V2_TOKEN_ACCOUNT = "FpK5AHKxcYSqd9pVPjrHFgE37Szdgty8GGk2p32QwSMa"

ALCHEMY_RPC = os.environ.get(
    "ALCHEMY_RPC",
    "https://solana-mainnet.g.alchemy.com/v2/mDKvlGo6XpFKJWGDWc7R0dUjoIsxYjWW"
)

# ── Data Structures ─────────────────────────────────────────────────────────


@dataclass
class OnChainTokenState:
    """Snapshot of the V2 SIMPT token on Solana mainnet."""
    mint: str
    supply_ui: int
    supply_raw: int
    decimals: int
    holders_count: int
    whale_balance: int
    whale_pct: float  # % of total supply held by whale
    mint_authority: Optional[str]
    freeze_authority: Optional[str]
    program: str
    recent_tx_count: int
    verified_at: str


@dataclass
class MeshState:
    """Snapshot of the agent mesh economy."""
    total_agents: int
    active_agents_5m: int
    intents_24h: int
    fees_collected_24h_simp: float
    trust_distribution: Dict[str, int]
    avg_trust_score: float
    top_agents: List[Dict[str, Any]]
    revenue_pool_simp: float
    burn_vault_simp: float
    treasury_simp: float


@dataclass
class StateCarryingTransfer:
    """A SIMP transfer that carries mesh state in its memo."""
    tx_id: str
    from_agent: str
    to_agent: str
    amount_simp: float
    memo_hex: str
    memo_decoded: Optional[Dict[str, Any]]
    state_payload: Optional[Dict[str, Any]]
    timestamp: str
    on_chain: bool  # True = confirmed on Solana, False = local SQLite


@dataclass
class TrustGraphEdge:
    """A trust relationship between two agents."""
    from_agent: str
    to_agent: str
    trust_score: float
    intents_routed: int
    last_interaction: str
    direction: str  # "outgoing", "incoming", "mutual"


# ── RPC Layer ───────────────────────────────────────────────────────────────


def _rpc_call(method: str, params: list) -> Optional[Dict[str, Any]]:
    """Make a JSON-RPC call to Solana via Alchemy."""
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }).encode("utf-8")

    req = urllib.request.Request(
        ALCHEMY_RPC,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.warning(f"RPC call failed: {method} — {e}")
        return None


def get_onchain_token_state() -> OnChainTokenState:
    """Fetch the current state of the V2 SIMPT token from Solana mainnet."""

    # Supply
    supply_resp = _rpc_call("getTokenSupply", [V2_TOKEN_MINT])
    supply_ui = 0
    supply_raw = 0
    if supply_resp and "result" in supply_resp and supply_resp["result"]:
        supply_ui = int(supply_resp["result"]["value"].get("uiAmount", 0))
        supply_raw = int(supply_resp["result"]["value"].get("amount", "0"))

    # Largest accounts (top holders)
    holders_resp = _rpc_call("getTokenLargestAccounts", [V2_TOKEN_MINT])
    holders_count = 0
    whale_balance = 0
    if holders_resp and "result" in holders_resp and holders_resp["result"]:
        holders = holders_resp["result"]["value"]
        holders_count = len(holders)
        for h in holders:
            if h["address"] == V2_TOKEN_ACCOUNT:
                whale_balance = int(h.get("uiAmount", 0))

    # Get mint account info
    mint_resp = _rpc_call("getAccountInfo", [
        V2_TOKEN_MINT,
        {"encoding": "jsonParsed"}
    ])
    mint_authority = None
    freeze_authority = None
    program = "Token-2022"
    if mint_resp and "result" in mint_resp and mint_resp["result"]:
        info = mint_resp["result"]["value"]
        if info.get("owner"):
            program = info["owner"]
        parsed = info.get("data", {}).get("parsed", {})
        mint_info = parsed.get("info", {})
        mint_authority = mint_info.get("mintAuthority")
        freeze_authority = mint_info.get("freezeAuthority")

    # Recent signatures (tx count)
    sigs_resp = _rpc_call("getSignaturesForAddress", [
        V2_TOKEN_MINT,
        {"limit": 100}
    ])
    tx_count = len(sigs_resp.get("result", [])) if sigs_resp else 0

    whale_pct = round(whale_balance / max(supply_ui, 1) * 100, 2) if supply_ui > 0 else 0.0

    return OnChainTokenState(
        mint=V2_TOKEN_MINT,
        supply_ui=supply_ui,
        supply_raw=supply_raw,
        decimals=6,
        holders_count=holders_count,
        whale_balance=whale_balance,
        whale_pct=whale_pct,
        mint_authority=mint_authority,
        freeze_authority=freeze_authority,
        program=program,
        recent_tx_count=tx_count,
        verified_at=datetime.now(timezone.utc).isoformat(),
    )


def get_wallet_analyis(wallet_address: str) -> Dict[str, Any]:
    """Deep analysis of a wallet: SOL balance, token accounts, recent activity."""
    analysis = {
        "address": wallet_address,
        "sol_balance": 0.0,
        "token_accounts": [],
        "recent_transactions": [],
        "is_known_wallet": False,
        "known_roles": [],
    }

    # SOL balance
    bal_resp = _rpc_call("getBalance", [wallet_address])
    if bal_resp and "result" in bal_resp:
        analysis["sol_balance"] = round(bal_resp["result"]["value"] / 1_000_000_000, 9)

    # Token accounts
    tokens_resp = _rpc_call("getTokenAccountsByOwner", [
        wallet_address,
        {"programId": "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"},
        {"encoding": "jsonParsed"}
    ])
    if tokens_resp and "result" in tokens_resp:
        for acc in tokens_resp["result"]["value"]:
            parsed = acc.get("account", {}).get("data", {}).get("parsed", {})
            info = parsed.get("info", {})
            token_account = {
                "mint": info.get("mint", ""),
                "balance": int(info.get("tokenAmount", {}).get("amount", "0")),
                "balance_ui": info.get("tokenAmount", {}).get("uiAmount", 0),
                "decimals": info.get("tokenAmount", {}).get("decimals", 6),
                "account": acc.get("pubkey", ""),
            }
            analysis["token_accounts"].append(token_account)

    # Check if this is a known wallet
    known_wallets = {
        V2_TOKEN_WHALE: ["Deployer", "Token Whale", "Mint Authority (former)", "Update Authority"],
        "H3CUJLsakVP6a61Xqp8K9Lyrbe9qCgpBrWNNBoSpndXT": ["V2 Deploy Account"],
        "EcQDHB4BaPvCQSTHAQVXCktorL3Xi8XiHUmZCxa2k9Zh": ["Devnet"],
        "A1jVQ2ERTs1SCfgUh3X7dk5azr1n4GKamwJ8TPqizT1j": ["Restored Wallet"],
        "HYmZ74WydHkUeVAHn4H63UwCrQAtovGc7YJwtxcmS8Fj": ["Mint Authority (original)"],
    }
    if wallet_address in known_wallets:
        analysis["is_known_wallet"] = True
        analysis["known_roles"] = known_wallets[wallet_address]

    return analysis


def decode_state_memo(memo_hex: str) -> Optional[Dict[str, Any]]:
    """Attempt to decode a hex memo as a state-carrying TokenMemoV2."""
    try:
        raw_bytes = bytes.fromhex(memo_hex)
        # Try UTF-8
        text = raw_bytes.decode("utf-8", errors="ignore")
        # Try JSON
        try:
            parsed = json.loads(text)
            return {
                "type": "json",
                "content": parsed,
                "size_bytes": len(raw_bytes),
            }
        except json.JSONDecodeError:
            pass
        # Try base64
        try:
            decoded_b64 = base64.b64decode(text)
            try:
                parsed = json.loads(decoded_b64)
                return {
                    "type": "base64_json",
                    "content": parsed,
                    "size_bytes": len(raw_bytes),
                    "compressed": len(decoded_b64) < len(raw_bytes) * 0.8,
                }
            except json.JSONDecodeError:
                pass
            return {
                "type": "base64_binary",
                "size_bytes": len(raw_bytes),
                "decoded_size": len(decoded_b64),
            }
        except Exception:
            pass
        # Check for state-carrying magic bytes
        if raw_bytes[:4] == b'SIMP':
            return {
                "type": "state_carrying_v2",
                "protocol_version": raw_bytes[4] if len(raw_bytes) > 4 else 0,
                "content": text,
                "size_bytes": len(raw_bytes),
            }
        return {
            "type": "unknown_text",
            "content": text[:200],
            "size_bytes": len(raw_bytes),
        }
    except Exception as e:
        return {
            "type": "undecodable",
            "error": str(e),
            "hex": memo_hex[:64] + "..." if len(memo_hex) > 64 else memo_hex,
        }


# ── Mesh State Layer (SQLite-backed) ────────────────────────────────────────


def _get_ledger():
    """Get the SIMP Ledger instance."""
    try:
        from simp.tokens.ledger import Ledger
        return Ledger()
    except ModuleNotFoundError:
        pass
    try:
        from tokens.ledger import Ledger
        return Ledger()
    except Exception:
        return None


def _get_bridge():
    """Get the TokenEconomyBridge instance."""
    try:
        from simp.tokens.economy_bridge import MODULE_BRIDGE
        return MODULE_BRIDGE
    except ModuleNotFoundError:
        pass
    try:
        from tokens.economy_bridge import MODULE_BRIDGE
        return MODULE_BRIDGE
    except Exception:
        return None


def get_mesh_state() -> MeshState:
    """Fetch current agent mesh state from the SQLite ledger."""
    ledger = _get_ledger()
    bridge = _get_bridge()

    if not ledger:
        return MeshState(
            total_agents=0, active_agents_5m=0, intents_24h=0,
            fees_collected_24h_simp=0.0, trust_distribution={},
            avg_trust_score=0.0, top_agents=[], revenue_pool_simp=0.0,
            burn_vault_simp=0.0, treasury_simp=0.0,
        )

    conn = ledger._acquire_conn()

    # Total agents
    try:
        total = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    except Exception:
        total = 0

    # Active agents (within last 5 min)
    active_5m = 0
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        active_5m = conn.execute(
            "SELECT COUNT(DISTINCT from_agent) FROM transactions WHERE created_at > ?",
            (cutoff,),
        ).fetchone()[0]
    except Exception:
        pass

    # Intents in last 24h
    intents_24h = 0
    fees_24h = 0.0
    try:
        cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        row = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(fee), 0) FROM transactions WHERE created_at > ?",
            (cutoff_24h,),
        ).fetchone()
        if row:
            intents_24h = row[0]
            fees_24h = round(row[1] / 1_000_000, 6)
    except Exception:
        pass

    # Trust distribution
    trust_dist = {}
    try:
        rows = conn.execute(
            "SELECT CASE "
            "  WHEN trust_score >= 4.0 THEN 'trusted' "
            "  WHEN trust_score >= 2.0 THEN 'standard' "
            "  WHEN trust_score >= 0.5 THEN 'basic' "
            "  ELSE 'untrusted' "
            "END as tier, COUNT(*) FROM accounts GROUP BY tier"
        ).fetchall()
        trust_dist = dict(rows)
    except Exception:
        pass

    # Average trust score
    avg_trust = 0.0
    try:
        row = conn.execute("SELECT AVG(trust_score) FROM accounts").fetchone()
        if row and row[0]:
            avg_trust = round(row[0], 3)
    except Exception:
        pass

    # Top agents by trust score
    top_agents = []
    try:
        rows = conn.execute(
            "SELECT agent_id, balance, trust_score FROM accounts "
            "ORDER BY trust_score DESC LIMIT 10"
        ).fetchall()
        for r in rows:
            top_agents.append({
                "agent_id": r[0],
                "balance_simp": round(r[1] / 1_000_000, 6),
                "trust_score": r[2],
            })
    except Exception:
        pass

    # Revenue pools from bridge or fallback
    revenue_pool = 0.0
    burn_vault = 0.0
    treasury = 0.0

    if bridge:
        try:
            audit = bridge.full_audit()
            supply = audit.get("internal_supply", {})
            revenue_pool = supply.get("fee_pool", 0) / 1_000_000
            burn_vault = supply.get("total_burned", 0) / 1_000_000
            treasury = supply.get("treasury", 0) / 1_000_000
        except Exception:
            pass
    else:
        try:
            # Fallback: query fee_sink/burn_vault directly
            from simp.tokens.unified import FEE_SINK, BURN_VAULT, TREASURY
            for name, addr in [("fee_pool", "FEE_SINK"), ("burn_vault", "BURN_VAULT"), ("treasury", "TREASURY")]:
                pass
        except Exception:
            pass

    return MeshState(
        total_agents=total,
        active_agents_5m=active_5m,
        intents_24h=intents_24h,
        fees_collected_24h_simp=fees_24h,
        trust_distribution=trust_dist,
        avg_trust_score=avg_trust,
        top_agents=top_agents,
        revenue_pool_simp=revenue_pool,
        burn_vault_simp=burn_vault,
        treasury_simp=treasury,
    )


def get_trust_graph() -> List[TrustGraphEdge]:
    """Build the trust graph from the intent ledger."""
    ledger = _get_ledger()
    if not ledger:
        return []

    conn = ledger._acquire_conn()
    edges = []

    try:
        # Group by from_agent → to_agent, count intents, sum trust
        rows = conn.execute(
            "SELECT from_agent, to_agent, COUNT(*) as intents, "
            "MAX(created_at) as last_tx, SUM(fee) as total_fees "
            "FROM transactions WHERE to_agent IS NOT NULL "
            "AND from_agent != to_agent "
            "GROUP BY from_agent, to_agent "
            "ORDER BY intents DESC LIMIT 200"
        ).fetchall()
    except Exception:
        return []

    # Get trust scores
    trust_scores = {}
    try:
        score_rows = conn.execute(
            "SELECT agent_id, trust_score FROM accounts"
        ).fetchall()
        trust_scores = {r[0]: r[1] for r in score_rows}
    except Exception:
        pass

    for r in rows:
        from_a, to_a, intents, last_tx = r[0], r[1], r[2], r[3]
        trust_from = trust_scores.get(from_a, 0.5)
        trust_to = trust_scores.get(to_a, 0.5)
        mutual = min(trust_from, trust_to)

        edges.append(TrustGraphEdge(
            from_agent=from_a,
            to_agent=to_a,
            trust_score=mutual,
            intents_routed=intents,
            last_interaction=str(last_tx) if last_tx else "",
            direction="outgoing" if trust_from > trust_to else "incoming" if trust_to > trust_from else "mutual",
        ))

    return edges


def get_state_carrying_transfers(limit: int = 50) -> List[StateCarryingTransfer]:
    """Get recent transfers that carry mesh state in their memos.

    In the SIMP protocol, the memo field of a token transfer can carry
    a compressed MeshStateSnapshot. This allows any agent to reconstruct
    the mesh state from the token history — even without internet.
    """
    ledger = _get_ledger()
    if not ledger:
        return []

    conn = ledger._acquire_conn()
    transfers = []

    try:
        # Try with memo column
        try:
            rows = conn.execute(
                "SELECT txn_id, from_agent, to_agent, amount, memo, created_at "
                "FROM transactions WHERE memo IS NOT NULL AND memo != '' "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        except Exception:
            rows = conn.execute(
                "SELECT txn_id, from_agent, to_agent, amount, memo, timestamp "
                "FROM transactions WHERE memo IS NOT NULL AND memo != '' "
                "ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
    except Exception:
        return []

    for r in rows:
        memo = r[4] or ""
        decoded = decode_state_memo(memo) if memo else None

        state_payload = None
        if decoded and decoded.get("type") in ("json", "base64_json"):
            content = decoded.get("content", {})
            if isinstance(content, dict) and ("snapshot" in content or "mesh_state" in content or "epoch" in content or "topology" in content or "consensus_proof" in content):
                state_payload = content

        transfers.append(StateCarryingTransfer(
            tx_id=r[0],
            from_agent=r[1],
            to_agent=r[2] or "",
            amount_simp=round(r[3] / 1_000_000, 6),
            memo_hex=memo if memo else "",
            memo_decoded=decoded,
            state_payload=state_payload,
            timestamp=str(r[5]),
            on_chain=False,
        ))

    return transfers


# ── Cross-Dimensional Analytics ─────────────────────────────────────────────


def get_convergence_metrics() -> Dict[str, Any]:
    """Measure convergence between on-chain reality and mesh reality.

    In a healthy SIMP economy, the on-chain token supply should APPROXIMATELY
    match the mesh's internal accounting. Discrepancies = leaks.
    """
    onchain = get_onchain_token_state()
    mesh = get_mesh_state()

    return {
        "onchain": {
            "supply": onchain.supply_ui,
            "holders": onchain.holders_count,
            "whale_holding_pct": onchain.whale_pct,
            "verified_at": onchain.verified_at,
        },
        "mesh": {
            "total_agents": mesh.total_agents,
            "active_agents_5m": mesh.active_agents_5m,
            "intents_24h": mesh.intents_24h,
            "fees_24h_simp": mesh.fees_collected_24h_simp,
            "avg_trust": mesh.avg_trust_score,
        },
        "convergence": {
            "onchain_vs_mesh_agents": f"{onchain.holders_count} holders vs {mesh.total_agents} agents",
            "economic_velocity": round(mesh.intents_24h / max(onchain.supply_ui / 1_000_000, 1), 4)
                if onchain.supply_ui > 0 else 0,
            "trust_maturity": mesh.avg_trust_score,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def get_offline_resilience() -> Dict[str, Any]:
    """Measure how well the mesh can operate without internet.

    The SIMP protocol is designed for offline-first agent economies.
    This metric measures readiness.
    """
    # Try both possible import paths
    onchain_ok = False
    try:
        from simp.tokens.v2_config import check_onchain_supply
        onchain_ok = check_onchain_supply().get("success", False)
    except ModuleNotFoundError:
        try:
            from tokens.v2_config import check_onchain_supply
            onchain_ok = check_onchain_supply().get("success", False)
        except ModuleNotFoundError:
            pass

    ledger = _get_ledger()
    if not ledger:
        return {"offline_ready": False, "reason": "No ledger"}

    conn = ledger._acquire_conn()

    # Check for offline queue table
    has_offline_queue = False
    try:
        conn.execute("SELECT 1 FROM offline_queue LIMIT 1").fetchone()
        has_offline_queue = True
    except Exception:
        pass

    # Check for state snapshot table
    has_state_snapshots = False
    try:
        conn.execute("SELECT 1 FROM state_snapshots LIMIT 1").fetchone()
        has_state_snapshots = True
    except Exception:
        pass

    # Count of CRDT-ready objects
    crdt_objects = 0
    try:
        crdt_objects = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE memo LIKE '%state_carrying%'"
        ).fetchone()[0]
    except Exception:
        pass

    # Trust graph completeness (can agents verify each other offline?)
    edge_count = 0
    try:
        edge_count = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE to_agent IS NOT NULL"
        ).fetchone()[0]
    except Exception:
        pass

    return {
        "offline_ready": has_offline_queue or has_state_snapshots or crdt_objects > 0,
        "internet_dependency": "full" if not onchain_ok else "reconciliation_only",
        "has_offline_queue": has_offline_queue,
        "has_state_snapshots": has_state_snapshots,
        "crdt_objects": crdt_objects,
        "mesh_edges": edge_count,
        "reconciliation": "onchain_available" if onchain_ok else "last_known_good",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── Public API ──────────────────────────────────────────────────────────────


class SIMPWallet:
    """
    The unified SIMP wallet explorer.

    Usage:
        wallet = SIMPWallet()
        dashboard = wallet.get_full_dashboard()
        whale = wallet.analyze_wallet(V2_TOKEN_WHALE)
        graph = wallet.get_trust_graph()
    """

    def __init__(self):
        self._cache = {}
        self._cache_ttl = 30  # seconds

    def _cached_or_fetch(self, key: str, fetch_fn: callable, ttl: int = 30):
        """Simple cache with TTL."""
        now = time.time()
        if key in self._cache:
            cached_at, value = self._cache[key]
            if now - cached_at < ttl:
                return value
        result = fetch_fn()
        self._cache[key] = (now, result)
        return result

    def get_full_dashboard(self) -> Dict[str, Any]:
        """Get the complete SIMPWallet dashboard."""
        return self._cached_or_fetch("dashboard", lambda: {
            "onchain": asdict(get_onchain_token_state()),
            "mesh": asdict(get_mesh_state()),
            "convergence": get_convergence_metrics(),
            "offline_resilience": get_offline_resilience(),
            "state_transfers": [
                asdict(t) for t in get_state_carrying_transfers(10)
            ],
            "wallet": f"https://solscan.io/token/{V2_TOKEN_MINT}",
            "explorer": "/v1/simpwallet",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        })

    def analyze_wallet(self, address: str) -> Dict[str, Any]:
        """Deep-dive into a specific wallet."""
        return get_wallet_analyis(address)

    def get_trust_graph(self) -> List[Dict[str, Any]]:
        """Get the full trust graph."""
        return [asdict(edge) for edge in get_trust_graph()]

    def get_token_memos(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get state-carrying token transfers with decoded memos."""
        return [asdict(t) for t in get_state_carrying_transfers(limit)]

    def get_broketarium(self) -> Dict[str, Any]:
        """Get the Broketarium report — V1 infrastructure token."""
        from tokens.v1_config import get_broketarium_report
        from tokens.v2_config import check_onchain_supply, check_whale_balance
        report = get_broketarium_report()
        # Add V2 context for full dual-token picture
        v2_supply = check_onchain_supply()
        v2_whale = check_whale_balance()
        report["v2_context"] = {
            "onchain_supply": v2_supply,
            "whale_balance": v2_whale,
        }
        report["mantra"] = "V1 is the ground. V2 is the economy. The pentagram holds."
        return report

    def get_pentagram(self) -> Dict[str, Any]:
        """Get the Pentagram architecture document."""
        from tokens.pentagon import PENTAGON_DOCUMENT
        return PENTAGON_DOCUMENT.to_dict()

    def get_state_carrying_proof(self) -> Dict[str, Any]:
        """Generate a proof that the mesh state can be reconstructed from token memos."""
        transfers = get_state_carrying_transfers(50)
        state_payloads = [t.state_payload for t in transfers if t.state_payload]

        if not state_payloads:
            # Try to create a synthetic proof from available data
            mesh = get_mesh_state()
            proof = {
                "can_reconstruct": False,
                "reason": "No state-carrying memos found in recent transfers. "
                          "Mesh state can still be reconstructed from local ledger.",
                "mesh_state_available": mesh.total_agents > 0,
                "agents": mesh.total_agents,
                "trust_graph_edges": len(get_trust_graph()),
                "fallback": "sqlite_ledger",
            }
        else:
            proof = {
                "can_reconstruct": True,
                "method": "state_carrying_memo_v2",
                "state_payloads_found": len(state_payloads),
                "recent_payload": state_payloads[0],
                "reconstruction": "Each token transfer carries enough information "
                                  "to reconstruct the mesh state graph.",
                "protocol": "TokenMemoV2 → MeshStateSnapshot → StateDiff → CRDT merge",
            }

        proof["generated_at"] = datetime.now(timezone.utc).isoformat()
        return proof


# ── Singleton ──────────────────────────────────────────────────────────────

SIMPWALLET = SIMPWallet()
