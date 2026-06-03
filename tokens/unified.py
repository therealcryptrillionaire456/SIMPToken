"""
Unified Token API — Bridges legacy mesh_token.py with the SQLite ledger.

Provides the same API as MeshTokenEngine but backed by the real Ledger.
mesh_token.py will be migrated to delegate here.

All functions work with micro-SIMP units (10^-6).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .ledger import Ledger, FeeSchedule, Transaction
from .burn_engine import BurnEngine, FEE_SINK, BURN_VAULT, TREASURY

logger = logging.getLogger("SIMP.TokenUnified")

# Constants (match mesh_token.py for compatibility)
TOKEN_NAME = "SIMP"
TOKEN_SYMBOL = "SIMP"
DECIMALS = 6
TOTAL_SUPPLY_CAP = 1_000_000_000 * 10**6  # 1 billion base units
FAUCET_AMOUNT = 10_000 * 10**6  # 10K SIMP
INTENT_FEE = int(0.01 * 10**6)  # 0.01 SIMP

# How much to inject into feepool vs treasury on revenue
REVENUE_FEE_POOL_RATIO = 0.3  # 30% to feepool (some gets burned), 70% to treasury


class TokenConfig:
    """Token configuration constants (compat with mesh_token.py)."""
    name = TOKEN_NAME
    symbol = TOKEN_SYMBOL
    decimals = DECIMALS
    total_supply = TOTAL_SUPPLY_CAP
    faucet_amount = FAUCET_AMOUNT
    intent_fee = INTENT_FEE


class TokenTransfer:
    """Represents a token transfer (compat with mesh_token.py)."""
    def __init__(
        self,
        from_agent: str,
        to_agent: str,
        amount: int,
        tx_id: Optional[str] = None,
        signature: str = "",
        memo: str = "",
    ):
        self.from_agent = from_agent
        self.to_agent = to_agent
        self.amount = amount
        self.tx_id = tx_id or str(uuid.uuid4())
        self.signature = signature
        self.memo = memo
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tx_id": self.tx_id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "amount": self.amount,
            "signature": self.signature,
            "memo": self.memo,
            "timestamp": self.timestamp,
        }


class UnifiedTokenEngine:
    """Unified token engine — Ledger-backed, burn-aware.

    This is the single source of truth for token operations.
    MeshTokenEngine will delegate here.
    """

    def __init__(self, ledger: Optional[Ledger] = None):
        self._ledger = ledger or Ledger()
        self._burn = BurnEngine(self._ledger)

        # Ensure system accounts exist
        self._ensure_system_accounts()

    def _ensure_system_accounts(self):
        """Create system accounts if they don't exist."""
        le = self._ledger
        le.account_get_or_create(FEE_SINK, FEE_SINK, trust_score=0.0)
        le.account_get_or_create(BURN_VAULT, BURN_VAULT, trust_score=0.0)
        le.account_get_or_create(TREASURY, TREASURY, trust_score=0.0)

    @property
    def ledger(self):
        return self._ledger

    @property
    def burn(self):
        return self._burn

    # ── Faucet (one-time allocation) ───────────────────────────────────────

    def grant_faucet(self, agent_id: str, pubkey_b64: Optional[str] = None) -> bool:
        """Grant initial tokens to an agent (one-time per agent_id).

        Uses operator_faucet for all agents (deterministic faucet is only
        for real Ed25519 pubkeys passed via `pubkey_b64`).
        """
        le = self._ledger

        # Check if already exists with balance
        existing = le.account_get(agent_id)
        if existing and existing.balance > 0:
            logger.warning("Faucet skipped: %s already has balance %d", agent_id, existing.balance)
            return False

        # Ensure account exists
        pub = pubkey_b64 or agent_id
        le.account_get_or_create(agent_id, pub)

        # Always use operator_faucet (deterministic faucet requires real Ed25519
        # pubkey and most agents use string IDs, not crypto keys)
        le.operator_faucet(agent_id, FAUCET_AMOUNT, reason="faucet_grant")

        logger.info("Faucet: %s → %d SIMP", agent_id, FAUCET_AMOUNT // 10**6)
        return True

    # ── Transfers ──────────────────────────────────────────────────────────

    def transfer(
        self,
        from_agent: str,
        to_agent: str,
        amount: int,
        memo: str = "",
    ) -> Optional[str]:
        """Transfer tokens between agents. Returns tx_id on success."""
        le = self._ledger

        # Ensure recipient exists
        le.account_get_or_create(to_agent, to_agent)

        try:
            txn = le.txn_write(
                from_agent=from_agent,
                to_agent=to_agent,
                amount=amount,
                fee=0,
                intent_ref=f"transfer:{memo}" if memo else None,
            )
            logger.info("Transfer: %s → %s : %d (tx=%s)", from_agent, to_agent, amount, txn.id)
            return txn.id
        except ValueError as e:
            logger.error("Transfer failed: %s → %s : %d — %s", from_agent, to_agent, amount, e)
            return None

    # ── Fees ───────────────────────────────────────────────────────────────

    def deduct_fee(self, agent_id: str, amount: int = INTENT_FEE) -> bool:
        """Deduct a protocol fee from an agent. Fee goes to feepool → eventually burned."""
        le = self._ledger

        if amount <= 0:
            return True  # No-op

        try:
            # Send 1 micro-SIMP as amount (minimum), rest is fee
            # This ensures the fee is properly routed to feepool
            txn = le.txn_write(
                from_agent=agent_id,
                to_agent=FEE_SINK,
                amount=1,
                fee=amount - 1 if amount > 1 else 0,
                intent_ref=f"protocol_fee:{int(time.time())}",
            )
            return True
        except ValueError as e:
            logger.warning("Fee deduction failed: %s — %s", agent_id, e)
            return False

    def pay_intent_fee(
        self,
        agent_id: str,
        intent_type: str,
        load_factor: float = 1.0,
    ) -> Optional[str]:
        """Pay intent routing fee. Fee goes to feepool."""
        le = self._ledger
        fee = FeeSchedule(load_factor=load_factor).compute_fee(intent_type)
        if fee <= 0:
            return None

        try:
            txn = le.txn_write(
                from_agent=agent_id,
                to_agent=FEE_SINK,
                amount=0,
                fee=fee,
                intent_ref=f"intent_fee:{intent_type}:{int(time.time())}",
            )
            return txn.id
        except ValueError:
            return None

    # ── Revenue Injection ──────────────────────────────────────────────────

    def inject_revenue(self, amount: int, source: str = "quantumarb") -> bool:
        """Inject external revenue: split between feepool (burn) and treasury (distribute)."""
        le = self._ledger

        # Revenue comes in as minting (from void)
        # Split: 30% to feepool (eventually burned), 70% to treasury (distributed)
        to_fee_pool = int(amount * REVENUE_FEE_POOL_RATIO)
        to_treasury = amount - to_fee_pool

        try:
            if to_fee_pool > 0:
                # Record emission for feepool portion
                self._record_emission(FEE_SINK, to_fee_pool, f"revenue:{source}")
                txn_feepool = le.txn_write(
                    from_agent=None,  # Mint from void
                    to_agent=FEE_SINK,
                    amount=to_fee_pool,
                    fee=0,
                    intent_ref=f"revenue:{source}:feepool",
                )

            if to_treasury > 0:
                self._record_emission(TREASURY, to_treasury, f"revenue:{source}")
                txn_treasury = le.txn_write(
                    from_agent=None,
                    to_agent=TREASURY,
                    amount=to_treasury,
                    fee=0,
                    intent_ref=f"revenue:{source}:treasury",
                )

            logger.info(
                "Revenue injected: %d from %s → %d feepool, %d treasury",
                amount, source, to_fee_pool, to_treasury,
            )
            return True
        except Exception as e:
            logger.error("Revenue injection failed: %s", e)
            return False

    def _record_emission(self, to_account: str, amount: int, source: str):
        """Record an emission (minting) event in the ledger."""
        le = self._ledger
        conn = le._write()
        try:
            conn.execute(
                """INSERT INTO emission_events (id, to_account, amount, reason, source, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), to_account, amount, "revenue_injection", source, int(time.time())),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # ── Burn ───────────────────────────────────────────────────────────────

    def burn(self, amount: int) -> bool:
        """Burn tokens from treasury. Returns True on success."""
        try:
            self._burn.manual_burn(amount, reason="manual_burn")
            return True
        except ValueError:
            return False

    def get_burn_metrics(self) -> Dict[str, Any]:
        """Get burn tracker metrics."""
        return self._burn.get_supply_metrics()

    def flush_fees(self) -> Dict[str, int]:
        """Flush accumulated fees from feepool."""
        return self._burn.flush_fee_pool()

    # ── Distribution ───────────────────────────────────────────────────────

    def distribute_fee_pool(self, weights: Optional[Dict[str, float]] = None) -> Dict[str, int]:
        """Distribute from treasury to active agents.

        Compatible with MeshTokenEngine.distribute_fee_pool().
        Distributes up to 50% of treasury balance proportionally.
        """
        le = self._ledger
        treasury = le.account_get(TREASURY)

        if not treasury or treasury.balance <= 0:
            return {}

        # Distribute 50% of treasury
        distribute_amount = treasury.balance // 2
        if distribute_amount <= 0:
            return {}

        # Get active agents (all accounts with balance > 0, excluding system accounts)
        conn = le._acquire_conn()
        system_accounts = {FEE_SINK, BURN_VAULT, TREASURY}

        if not weights:
            rows = conn.execute(
                "SELECT agent_id FROM accounts WHERE balance > 0 AND agent_id NOT IN (?, ?, ?)",
                (FEE_SINK, BURN_VAULT, TREASURY),
            ).fetchall()
            active = [r[0] for r in rows]
            if not active:
                return {}
            share = distribute_amount // len(active)
            distributions: Dict[str, int] = {}
            for aid in active:
                try:
                    le.txn_write(
                        from_agent=TREASURY,
                        to_agent=aid,
                        amount=share,
                        fee=0,
                        intent_ref="distribution:equal",
                    )
                    distributions[aid] = share
                except ValueError:
                    continue
        else:
            total_weight = sum(weights.values())
            if total_weight <= 0:
                return {}
            distributions = {}
            for aid, weight in weights.items():
                share = int(distribute_amount * (weight / total_weight))
                if share > 0:
                    try:
                        le.txn_write(
                            from_agent=TREASURY,
                            to_agent=aid,
                            amount=share,
                            fee=0,
                            intent_ref="distribution:weighted",
                        )
                        distributions[aid] = share
                    except ValueError:
                        continue

        logger.info(
            "Distributed %d from treasury to %d agents",
            sum(distributions.values()), len(distributions),
        )
        return distributions

    # ── Queries ────────────────────────────────────────────────────────────

    def get_total_supply(self) -> int:
        """Get total supply (minted minus burned)."""
        return self._burn.get_supply_metrics()["net_supply"]

    def get_circulating_supply(self) -> int:
        """Get circulating supply."""
        return self._burn.get_supply_metrics()["circulating_supply"]

    def get_balance(self, agent_id: str) -> int:
        """Get an agent's balance."""
        le = self._ledger
        acc = le.account_get(agent_id)
        return acc.balance if acc else 0

    def get_fee_pool(self) -> int:
        """Get current fee pool size."""
        le = self._ledger
        acc = le.account_get(FEE_SINK)
        return acc.balance if acc else 0

    def get_treasury(self) -> int:
        """Get treasury balance."""
        le = self._ledger
        acc = le.account_get(TREASURY)
        return acc.balance if acc else 0

    def get_all_balances(self) -> Dict[str, int]:
        """Get all agent balances."""
        le = self._ledger
        conn = le._acquire_conn()
        rows = conn.execute(
            "SELECT agent_id, balance FROM accounts ORDER BY balance DESC"
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def get_burn_info(self) -> Dict[str, Any]:
        """Get comprehensive burn info."""
        metrics = self._burn.get_supply_metrics()
        recent_burns = self._burn.get_burn_events(limit=10)
        return {
            **metrics,
            "recent_burns": recent_burns,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive stats (compat with mesh_token engine queries)."""
        le = self._ledger
        metrics = self._burn.get_supply_metrics()
        stats = le.stats() if hasattr(le, 'stats') else {}

        return {
            "total_supply": metrics["net_supply"],
            "circulating_supply": metrics["circulating_supply"],
            "total_burned": metrics["total_burned"],
            "burn_percent": metrics["burn_percent"],
            "fee_pool": metrics["fee_pool_balance"],
            "treasury": metrics["treasury_balance"],
            "total_staked": metrics["total_staked"],
            "num_accounts": stats.get("num_accounts", 0),
            "num_transactions": stats.get("num_transactions", 0),
        }


# Singleton
UNIFIED_ENGINE = UnifiedTokenEngine()
MODULE_ENGINE = UNIFIED_ENGINE  # Aliased for compat with mesh_token.py consumers
