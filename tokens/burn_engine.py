"""
SIMP Burn Engine — Fee pipeline, burn vault, and supply transparency.

The Burn Engine sits between fee collection and token destruction:
  1. Fees are collected into simp:feepool (via ledger.txn_write with fee>0)
  2. Burn Engine drains feepool -> simp:burnvault in verifiable batches
  3. Supply metrics are available at all times

Token preservation strategy:
  - Only PROTOCOL FEES (intent fees, registration) go to feepool -> burn
  - DELEGATION FEES (sponsor fees) go to simp:treasury -> distributed back
  - External revenue (trading profits) goes to simp:treasury -> distributed back
  - This keeps the ecosystem self-sustaining while burning only what's "spent" on compute
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("SIMP.BurnEngine")

# System accounts managed by this engine
FEE_SINK = "simp:feepool"
BURN_VAULT = "simp:burnvault"
TREASURY = "simp:treasury"

# How often we flush fees from feepool -> burnvault (seconds)
BURN_FLUSH_INTERVAL = 3600  # 1 hour

# Percentage of fees to burn vs preserve for distribution
# 70% burned, 30% available for distribution from treasury
BURN_RATIO_NUMERATOR = 70
BURN_RATIO_DENOMINATOR = 100


class BurnEngine:
    """Manages fee collection, burn scheduling, and supply transparency."""

    def __init__(self, ledger=None):
        self._ledger = ledger
        self._last_flush = 0

    @property
    def ledger(self):
        """Lazy import to avoid circular imports."""
        if self._ledger is None:
            from .ledger import Ledger
            self._ledger = Ledger()
        return self._ledger

    # ── Fee Pipeline ────────────────────────────────────────────────────────

    def record_burn(
        self,
        from_account: str,
        amount: int,
        reason: str = "protocol_fee",
        tx_ref: Optional[str] = None,
    ) -> str:
        """Record a burn event in the burn_events table.

        This moves tokens from from_account to simp:burnvault via transfer.
        """
        if amount <= 0:
            raise ValueError(f"Burn amount must be positive: {amount}")

        le = self.ledger
        event_id = f"burn_{uuid.uuid4().hex[:16]}"

        # Ensure burnvault account exists
        le.account_get_or_create(BURN_VAULT, BURN_VAULT, trust_score=0.0)

        # Transfer from source to burnvault
        try:
            txn = le.txn_write(
                from_agent=from_account,
                to_agent=BURN_VAULT,
                amount=amount,
                fee=0,
                intent_ref=f"burn:{reason}",
            )
        except ValueError as e:
            logger.error("Burn failed: %s", e)
            raise

        # Record the burn event
        conn = le._write()
        try:
            conn.execute(
                """INSERT INTO burn_events (id, from_account, amount, reason, tx_ref, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (event_id, from_account, amount, reason, txn.id, int(time.time())),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        logger.info(
            "Burn: %d from %s (%s) — tx=%s event=%s",
            amount, from_account, reason, txn.id, event_id,
        )
        return event_id

    def flush_fee_pool(self, force: bool = False) -> Dict[str, int]:
        """Drain protocol fees from feepool.

        Splits: BURN_RATIO burned, remainder stays for distribution.
        Returns {burned: N, preserved: N, total: N}.
        """
        le = self.ledger
        now = int(time.time())

        if not force and (now - self._last_flush) < BURN_FLUSH_INTERVAL:
            return {"burned": 0, "preserved": 0, "total": 0, "skipped": True}

        # Ensure feepool exists
        try:
            fee_account = le.account_get(FEE_SINK)
        except Exception:
            le.account_get_or_create(FEE_SINK, FEE_SINK, trust_score=0.0)
            fee_account = le.account_get(FEE_SINK)

        if not fee_account or fee_account.balance <= 0:
            self._last_flush = now
            return {"burned": 0, "preserved": 0, "total": 0, "reason": "empty"}

        total = fee_account.balance
        burn_amount = (total * BURN_RATIO_NUMERATOR) // BURN_RATIO_DENOMINATOR
        preserve_amount = total - burn_amount

        # Burn the burn portion
        event_id = self.record_burn(FEE_SINK, burn_amount, reason="protocol_fee_flush")

        # Preserved stays in feepool (will be distributed by TokenDistributor)
        # or we can route it to treasury
        if preserve_amount > 0:
            try:
                le.txn_write(
                    from_agent=FEE_SINK,
                    to_agent=TREASURY,
                    amount=preserve_amount,
                    fee=0,
                    intent_ref="fee_pool:preserve_to_treasury",
                )
            except ValueError:
                # If treasury doesn't exist, create it
                le.account_get_or_create(TREASURY, TREASURY, trust_score=0.0)
                le.txn_write(
                    from_agent=FEE_SINK,
                    to_agent=TREASURY,
                    amount=preserve_amount,
                    fee=0,
                    intent_ref="fee_pool:preserve_to_treasury",
                )

        self._last_flush = now
        logger.info(
            "Fee pool flush: %d total → %d burned (%s), %d preserved to treasury",
            total, burn_amount, event_id, preserve_amount,
        )
        return {
            "burned": burn_amount,
            "preserved": preserve_amount,
            "total": total,
            "event_id": event_id,
        }

    # ── Manual burn (for revenue injection burns) ──────────────────────────

    def manual_burn(self, amount: int, reason: str = "manual") -> str:
        """Manually burn tokens from treasury."""
        le = self.ledger
        treasury = le.account_get(TREASURY)
        if not treasury or treasury.balance < amount:
            raise ValueError(
                f"Insufficient treasury balance: "
                f"{treasury.balance if treasury else 0} < {amount}"
            )
        return self.record_burn(TREASURY, amount, reason=f"manual:{reason}")

    # ── Supply Metrics ────────────────────────────────────────────────────

    def get_supply_metrics(self) -> Dict[str, int]:
        """Get comprehensive supply metrics from the ledger."""
        le = self.ledger

        conn = le._acquire_conn() if not le.readonly else le._write()

        # Total minted via emission_events
        minted_row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM emission_events"
        ).fetchone()
        total_minted = minted_row[0] if minted_row else 0

        # Total burned via burn_events
        burned_row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM burn_events"
        ).fetchone()
        total_burned = burned_row[0] if burned_row else 0

        # Balances of system accounts
        fee_pool = le.account_get(FEE_SINK)
        burn_vault = le.account_get(BURN_VAULT)
        treasury_acc = le.account_get(TREASURY)

        fee_pool_bal = fee_pool.balance if fee_pool else 0
        burn_vault_bal = burn_vault.balance if burn_vault else 0
        treasury_bal = treasury_acc.balance if treasury_acc else 0

        # Sum of ALL balances across ALL accounts
        all_balances = conn.execute(
            "SELECT COALESCE(SUM(balance), 0) FROM accounts"
        ).fetchone()[0]

        # Total staked
        total_staked = conn.execute(
            "SELECT COALESCE(SUM(stake_amount), 0) FROM accounts"
        ).fetchone()[0]

        # Circulating = all balances - system accounts
        circulating = all_balances - fee_pool_bal - burn_vault_bal - treasury_bal

        # Net supply = what's been minted minus what's been burned
        net_supply = total_minted - total_burned

        return {
            "total_minted": total_minted,
            "total_burned": total_burned,
            "net_supply": net_supply,
            "fee_pool_balance": fee_pool_bal,
            "burn_vault_balance": burn_vault_bal,
            "treasury_balance": treasury_bal,
            "total_staked": total_staked,
            "all_balances_sum": all_balances,
            "circulating_supply": circulating,
            "burn_percent": round((total_burned / max(total_minted, 1)) * 100, 2),
        }

    def take_snapshot(self) -> int:
        """Take a supply snapshot for audit trail. Returns snapshot id."""
        le = self.ledger
        metrics = self.get_supply_metrics()
        conn = le._write()
        now = int(time.time())
        try:
            c = conn.execute(
                """INSERT INTO supply_snapshots
                   (total_supply, burned, fee_pool, treasury, circulating, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    metrics["net_supply"],
                    metrics["total_burned"],
                    metrics["fee_pool_balance"],
                    metrics["treasury_balance"],
                    metrics["circulating_supply"],
                    now,
                ),
            )
            conn.commit()
            return c.lastrowid
        except Exception:
            conn.rollback()
            raise

    def get_burn_events(
        self, limit: int = 50, offset: int = 0
    ) -> List[Dict]:
        """Get recent burn events."""
        le = self.ledger
        conn = le._acquire_conn() if not le.readonly else le._write()
        rows = conn.execute(
            """SELECT id, from_account, amount, reason, tx_ref, created_at
               FROM burn_events
               ORDER BY created_at DESC
               LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()
        return [
            {
                "id": r[0],
                "from_account": r[1],
                "amount": r[2],
                "reason": r[3],
                "tx_ref": r[4],
                "created_at": r[5],
            }
            for r in rows
        ]

    def get_emission_events(
        self, limit: int = 50, offset: int = 0
    ) -> List[Dict]:
        """Get recent emission (minting) events."""
        le = self.ledger
        conn = le._acquire_conn() if not le.readonly else le._write()
        rows = conn.execute(
            """SELECT id, to_account, amount, reason, source, created_at
               FROM emission_events
               ORDER BY created_at DESC
               LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchone()
        return [
            {
                "id": r[0],
                "to_account": r[1],
                "amount": r[2],
                "reason": r[3],
                "source": r[4],
                "created_at": r[5],
            }
            for r in rows
        ]


# Singleton
MODULE_BURN_ENGINE = BurnEngine()
