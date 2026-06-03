"""
SIMP Token Economy — Wire V2 On-Chain Token into Broker.

L6-T3: This module creates the bridge between the broker's internal
UnifiedTokenEngine (SQLite, simulated economy) and the real V2 SIMPT
token on Solana mainnet.

The connection is read-only (mint authority revoked) — we track agent
balances locally but verify against on-chain state via RPC queries.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .unified import UNIFIED_ENGINE, UnifiedTokenEngine
from .v2_config import (
    V2_TOKEN_MINT,
    V2_TOKEN_INFO,
    check_onchain_supply,
    check_whale_balance,
    get_audit_results,
)

logger = logging.getLogger("SIMP.TokenEconomyBridge")

# Agent fee deduction (simulated, tracked in SQLite)
# This is the amount per intent routed through the broker
AGENT_FEE_PER_INTENT = int(0.01 * 10**6)  # 0.01 SIMPT


class TokenEconomyBridge:
    """Bridges broker economy to V2 on-chain token.

    Architecture:
      - Agent balances live in SQLite (UnifiedTokenEngine)
      - On-chain supply/whale balance verified via RPC
      - Fee deduction and tracking are SQLite-local (no on-chain TX per intent)
      - Revenue events get logged to security_audit.jsonl
    """

    def __init__(self, engine: Optional[UnifiedTokenEngine] = None):
        self._engine = engine or UNIFIED_ENGINE
        self._audit_log = Path("data/token_economy_audit.jsonl")
        self._audit_log.parent.mkdir(parents=True, exist_ok=True)

    # ── Properties ─────────────────────────────────────────────────────────

    @property
    def engine(self) -> UnifiedTokenEngine:
        return self._engine

    @property
    def v2_token(self) -> str:
        return V2_TOKEN_MINT

    # ── On-chain queries ───────────────────────────────────────────────────

    def verify_supply(self) -> Dict[str, Any]:
        """Compare local vs on-chain supply."""
        onchain = check_onchain_supply()
        local = self._engine.get_stats()

        return {
            "onchain": onchain,
            "local_total": local.get("total_supply", 0),
            "local_circulating": local.get("circulating_supply", 0),
            "match": onchain.get("success") and onchain.get("supply", 0) == local.get("total_supply", 0),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def verify_whale(self) -> Dict[str, Any]:
        """Check whale balance on-chain."""
        return check_whale_balance()

    def full_audit(self) -> Dict[str, Any]:
        """Full token audit combining on-chain and local state."""
        return get_audit_results()

    # ── Agent economy operations ───────────────────────────────────────────

    def deduct_intent_fee(self, agent_id: str, intent_type: str = "generic") -> bool:
        """Deduct intent fee from an agent's local balance."""
        result = self._engine.deduct_fee(agent_id, AGENT_FEE_PER_INTENT)
        if result:
            self._log_audit_entry("fee_deduction", {
                "agent_id": agent_id,
                "amount": AGENT_FEE_PER_INTENT,
                "intent_type": intent_type,
                "success": True,
            })
        return result

    def inject_revenue(self, amount: int, source: str = "quantumarb") -> bool:
        """Inject revenue into the token economy."""
        result = self._engine.inject_revenue(amount, source)
        if result:
            self._log_audit_entry("revenue_injection", {
                "amount": amount,
                "source": source,
                "success": True,
            })
        return result

    # ── Audit logging ──────────────────────────────────────────────────────

    def _log_audit_entry(self, event_type: str, data: Dict[str, Any]) -> None:
        """Append a token economy event to the audit ledger."""
        import json
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            "token": V2_TOKEN_MINT,
            **data,
        }
        try:
            with open(self._audit_log, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as e:
            logger.warning("Failed to write audit log: %s", e)

    def get_audit_log(self, limit: int = 50) -> list:
        """Read recent audit log entries."""
        import json
        entries = []
        try:
            with open(self._audit_log, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entries.append(json.loads(line))
        except (OSError, json.JSONDecodeError):
            pass
        return entries[-limit:]


# Module singleton
MODULE_BRIDGE = TokenEconomyBridge()
