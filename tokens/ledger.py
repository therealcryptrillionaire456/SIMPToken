"""
SimpMesh Token Ledger — Phase 1-7: Account model, transaction CRUD, fee middleware,
agent key registry, trust hooks + inflation, escrow + intent bundling,
sponsor onboarding + agentic credit.

Schema:
  accounts         — per-agent token accounts
  transactions     — immutable intent-linked txn log
  faucet_log       — deterministic faucet tracking
  escrow_records   — open escrow contracts
  intent_bundles   — pooled multi-agent stakes
  bundle_participants — per-agent stake in bundles
  agent_registry   — Ed25519 key registration, rotation, revocation
  intent_events    — per-intent success/failure for trust hooks
  trust_history    — trust score change audit log
  broker_trust      — per-broker acknowledgment latency & reputation
  sponsors         — sponsor -> sponsored agent bond mapping

All monetary values stored in micro-SimpMesh (10^-6), INTEGER for precision.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import nacl.bindings
import nacl.signing

logger = logging.getLogger("SimpMesh.Ledger")

DEFAULT_LEDGER_DIR = Path("~/.simp/tokens").expanduser()
DEFAULT_LEDGER_PATH = DEFAULT_LEDGER_DIR / "ledger.db"

# v2: System account constants
FEE_SINK = "simp:feepool"
BURN_VAULT = "simp:burnvault"
TREASURY = "simp:treasury"
STAKING_POOL = "simp:stakingpool"

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    agent_id          TEXT PRIMARY KEY,
    pubkey_b64       TEXT    NOT NULL,
    balance           INTEGER NOT NULL DEFAULT 0,
    nonce             INTEGER NOT NULL DEFAULT 0,
    trust_score       REAL    NOT NULL DEFAULT 0.5,
    stake_amount      INTEGER NOT NULL DEFAULT 0,
    last_active_day   INTEGER NOT NULL DEFAULT 0,
    created_at        INTEGER NOT NULL,
    updated_at        INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    id          TEXT PRIMARY KEY,
    from_agent  TEXT,
    to_agent    TEXT,
    amount      INTEGER NOT NULL,
    intent_ref  TEXT,
    intent_hash TEXT,
    fee         INTEGER NOT NULL DEFAULT 0,
    nonce       INTEGER NOT NULL,
    signature   TEXT,
    created_at  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_txns_from   ON transactions(from_agent);
CREATE INDEX IF NOT EXISTS idx_txns_to     ON transactions(to_agent);
CREATE INDEX IF NOT EXISTS idx_txns_ref    ON transactions(intent_ref);

CREATE TABLE IF NOT EXISTS faucet_log (
    pubkey_b64     TEXT PRIMARY KEY,
    last_unixday   INTEGER NOT NULL,
    total_alloc    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS escrow_records (
    escrow_id     TEXT PRIMARY KEY,
    requester    TEXT NOT NULL,
    responder    TEXT NOT NULL,
    dispute_bond INTEGER NOT NULL,
    intent_ref   TEXT,
    status       TEXT NOT NULL DEFAULT 'open',
    created_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS intent_bundles (
    bundle_id    TEXT PRIMARY KEY,
    intent_type  TEXT NOT NULL,
    participants TEXT NOT NULL,
    total_stake  INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'open',
    created_at   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS bundle_participants (
    bundle_id    TEXT NOT NULL,
    agent_id     TEXT NOT NULL,
    stake_amount INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'joined',
    joined_at    INTEGER NOT NULL,
    UNIQUE(bundle_id, agent_id)
);

CREATE TABLE IF NOT EXISTS operator_faucet (
    id         TEXT PRIMARY KEY,
    recipient  TEXT NOT NULL,
    amount     INTEGER NOT NULL,
    reason     TEXT,
    issued_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sponsors (
    sponsor_id           TEXT PRIMARY KEY,
    sponsored_agent      TEXT NOT NULL,
    sponsor_bond         INTEGER NOT NULL,
    delegation_fee_bps   INTEGER NOT NULL DEFAULT 100,
    status               TEXT NOT NULL DEFAULT 'active',
    created_at           INTEGER NOT NULL,
    updated_at           INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_registry (
    agent_id       TEXT NOT NULL,
    pubkey_b64     TEXT NOT NULL,
    key_seq        INTEGER NOT NULL DEFAULT 0,
    key_purpose    TEXT NOT NULL DEFAULT 'signing',
    status         TEXT NOT NULL DEFAULT 'active',
    issued_at      INTEGER NOT NULL,
    expires_at      INTEGER,
    revoked_at      INTEGER,
    revoked_reason  TEXT,
    UNIQUE(agent_id, key_seq)
);

CREATE INDEX IF NOT EXISTS idx_agent_registry_agent ON agent_registry(agent_id);

CREATE TABLE IF NOT EXISTS intent_events (
    event_id    TEXT PRIMARY KEY,
    agent_id    TEXT NOT NULL,
    intent_ref  TEXT NOT NULL,
    outcome     TEXT NOT NULL,
    trust_delta REAL NOT NULL DEFAULT 0.0,
    created_at  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_intent_events_agent ON intent_events(agent_id);

CREATE TABLE IF NOT EXISTS trust_history (
    id         TEXT NOT NULL,
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id   TEXT NOT NULL,
    old_score  REAL NOT NULL,
    new_score  REAL NOT NULL,
    reason     TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trust_history_agent ON trust_history(agent_id);

CREATE TABLE IF NOT EXISTS broker_trust (
    broker_id         TEXT PRIMARY KEY,
    avg_ack_time_ms   REAL    NOT NULL DEFAULT 0.0,
    ack_time_std      REAL    NOT NULL DEFAULT 0.0,
    n_rounds          INTEGER NOT NULL DEFAULT 0,
    reputation_score  REAL    NOT NULL DEFAULT 0.5,
    last_100_rounds   TEXT,           -- JSON array, rolling 100
    last_updated      INTEGER NOT NULL
);

-- v2: Fee tracking, burn + emission audit
-- NOTE: ALTER TABLE is done in _init() to handle existing columns gracefully
-- 
CREATE TABLE IF NOT EXISTS burn_events (
    id          TEXT PRIMARY KEY,
    from_account TEXT NOT NULL,
    amount      INTEGER NOT NULL,
    reason      TEXT NOT NULL,
    tx_ref      TEXT,
    created_at  INTEGER NOT NULL,
    FOREIGN KEY (tx_ref) REFERENCES transactions(id)
);

CREATE INDEX IF NOT EXISTS idx_burn_events_created ON burn_events(created_at);

CREATE TABLE IF NOT EXISTS emission_events (
    id          TEXT PRIMARY KEY,
    to_account  TEXT NOT NULL,
    amount      INTEGER NOT NULL,
    reason      TEXT NOT NULL DEFAULT 'initial_supply',
    source      TEXT NOT NULL DEFAULT 'genesis',
    created_at  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_emission_events_created ON emission_events(created_at);

CREATE TABLE IF NOT EXISTS supply_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    total_supply    INTEGER NOT NULL,
    burned          INTEGER NOT NULL,
    fee_pool        INTEGER NOT NULL,
    treasury        INTEGER NOT NULL,
    circulating     INTEGER NOT NULL,
    timestamp       INTEGER NOT NULL
);

CREATE VIEW IF NOT EXISTS supply_metrics AS
WITH totals AS (
    SELECT
        COALESCE(SUM(balance), 0) AS total_balances,
        COALESCE((SELECT balance FROM accounts WHERE agent_id = 'simp:feepool'), 0) AS fee_pool_balance,
        COALESCE((SELECT balance FROM accounts WHERE agent_id = 'simp:burnvault'), 0) AS burn_vault_balance,
        COALESCE((SELECT balance FROM accounts WHERE agent_id = 'simp:treasury'), 0) AS treasury_balance,
        COALESCE(SUM(stake_amount), 0) AS total_staked
    FROM accounts
)
SELECT
    total_balances,
    fee_pool_balance,
    burn_vault_balance,
    treasury_balance,
    total_staked,
    (SELECT COALESCE(SUM(amount), 0) FROM burn_events) AS total_burned,
    (SELECT COALESCE(SUM(amount), 0) FROM emission_events) AS total_minted,
    (SELECT COALESCE(SUM(amount), 0) FROM emission_events)
    - (SELECT COALESCE(SUM(amount), 0) FROM burn_events) AS net_supply,
    total_balances - fee_pool_balance - treasury_balance AS circulating
FROM totals;
"""


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class Account:
    agent_id: str
    pubkey_b64: str
    balance: int
    nonce: int
    trust_score: float
    stake_amount: int
    last_active_day: int
    created_at: int
    updated_at: int


@dataclass
class Transaction:
    id: str
    from_agent: Optional[str]
    to_agent: str
    amount: int
    intent_ref: Optional[str]
    intent_hash: Optional[str]
    fee: int
    nonce: int
    signature: Optional[str]
    created_at: int


@dataclass
class EscrowRecord:
    escrow_id: str
    requester: str
    responder: str
    dispute_bond: int
    intent_ref: Optional[str]
    status: str
    created_at: int
    updated_at: int


@dataclass
class IntentBundle:
    bundle_id: str
    intent_type: str
    participants: List[str]
    total_stake: int
    status: str
    created_at: int


@dataclass
class BundleParticipant:
    bundle_id: str
    agent_id: str
    stake_amount: int
    status: str
    joined_at: int


@dataclass
class FeeSchedule:
    """Intent-type-based fee schedule, adjusted by broker load."""

    base_fees: Dict[str, int] = field(default_factory=lambda: {
        "intent.submit":    5,
        "intent.execute": 10,
        "skill.evolve":     3,
        "skill.rank":       1,
        "agent.register":  75,
        "channel.publish":   1,
        "escrow.open":     20,
        "escrow.close":     0,
        "bundle.fund":      5,
    })

    load_factor: float = 1.0

    def compute_fee(self, intent_type: str) -> int:
        base = self.base_fees.get(intent_type, 1)
        return int(base * self.load_factor)

    def apply_load_factor(self, load_factor: float) -> FeeSchedule:
        return FeeSchedule(base_fees=self.base_fees, load_factor=load_factor)


@dataclass
class AgentKeyRecord:
    agent_id: str
    pubkey_b64: str
    key_seq: int
    key_purpose: str
    status: str
    issued_at: int
    expires_at: Optional[int]
    revoked_at: Optional[int]
    revoked_reason: Optional[str]


@dataclass
class IntentEvent:
    event_id: str
    agent_id: str
    intent_ref: str
    outcome: str
    trust_delta: float
    created_at: int


@dataclass
class Sponsor:
    sponsor_id: str
    sponsored_agent: str
    sponsor_bond: int
    delegation_fee_bps: int
    status: str
    created_at: int
    updated_at: int


@dataclass
class BrokerTrust:
    broker_id: str
    avg_ack_time_ms: float
    ack_time_std: float
    n_rounds: int
    reputation_score: float
    last_100_rounds: List[float]
    last_updated: int


# ── Ledger class ────────────────────────────────────────────────────────────────

class Ledger:
    """Thread-safe SQLite ledger for $SimpMesh token operations.

    All writes are serialized. Reads can be done against a read-only connection.
    """

    def __init__(self, path: Optional[Path] = None, *, readonly: bool = False):
        self.path = Path(path) if path else DEFAULT_LEDGER_PATH
        self.readonly = readonly
        self._write_conn: Optional[sqlite3.Connection] = None
        self._init_lock = __import__("threading").Lock()
        self._init()

    def _init(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._acquire_conn()
        conn.executescript(SCHEMA)
        # v2: Add last_burn_epoch column if it doesn't exist
        try:
            conn.execute("ALTER TABLE accounts ADD COLUMN last_burn_epoch INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # Column already exists
        conn.commit()
        conn.close()

    def _acquire_conn(self) -> sqlite3.Connection:
        uri = f"file:{self.path}?mode=ro" if self.readonly else str(self.path)
        conn = sqlite3.connect(uri, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _write(self) -> sqlite3.Connection:
        conn = self._acquire_conn()
        conn.execute("BEGIN IMMEDIATE")
        return conn

    # ── Account operations ─────────────────────────────────────────────────

    def account_create(
        self, agent_id: str, pubkey_b64: str, *,
        conn: Optional[sqlite3.Connection] = None,
        trust_score: float = 0.5,
    ) -> Account:
        """Create a new account. Idempotent - returns existing if already exists."""
        now = int(time.time())
        today = int(now // 86400)
        if conn is None:
            conn = self._write()
        try:
            conn.execute(
                """INSERT INTO accounts
                   (agent_id, pubkey_b64, balance, nonce, trust_score,
                    stake_amount, last_active_day, created_at, updated_at)
                   VALUES (?, ?, 0, 0, ?, 0, ?, ?, ?)""",
                (agent_id, pubkey_b64, trust_score, today, now, now),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            pass
        return self.account_get(agent_id)

    def account_get(self, agent_id: str) -> Optional[Account]:
        """Fetch account by agent_id. Returns None if not found."""
        conn = self._acquire_conn() if not self.readonly else self._write()
        row = conn.execute(
            "SELECT * FROM accounts WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        if row is None:
            return None
        return Account(
            agent_id=row[0], pubkey_b64=row[1], balance=row[2], nonce=row[3],
            trust_score=row[4], stake_amount=row[5], last_active_day=row[6],
            created_at=row[7], updated_at=row[8],
        )

    def account_update_balance(self, agent_id: str, delta: int) -> Account:
        """Apply delta to balance atomically. Raises if result would go negative."""
        conn = self._write()
        now = int(time.time())
        row = conn.execute(
            "SELECT balance FROM accounts WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Account not found: {agent_id}")
        new_balance = row[0] + delta
        if new_balance < 0:
            raise ValueError(f"Insufficient balance for {agent_id}: {row[0]} < {abs(delta)}")
        conn.execute(
            "UPDATE accounts SET balance = ?, updated_at = ? WHERE agent_id = ?",
            (new_balance, now, agent_id),
        )
        conn.commit()
        return self.account_get(agent_id)

    def account_get_or_create(self, agent_id: str, pubkey_b64: str, trust_score: float = 0.5) -> Account:
        """Get existing or create new account."""
        existing = self.account_get(agent_id)
        if existing:
            return existing
        return self.account_create(agent_id, pubkey_b64, conn=self._write(), trust_score=trust_score)

    # ── Transaction operations ───────────────────────────────────────────────

    def txn_write(
        self,
        from_agent: Optional[str],
        to_agent: str,
        amount: int,
        *,
        intent_ref: Optional[str] = None,
        intent_hash: Optional[str] = None,
        fee: int = 0,
        nonce: Optional[int] = None,
        signature: Optional[str] = None,
    ) -> Transaction:
        """Write a token transaction. ALL token movements go through here."""
        if amount <= 0:
            raise ValueError(f"Amount must be positive: {amount}")

        conn = self._write()
        now_ms = int(time.time() * 1000)
        txn_id = str(uuid.uuid4())

        # v2: Fee routing — ensure feepool account exists
        if fee > 0:
            self._ensure_account(conn, "simp:feepool", "simp:feepool")

        if from_agent is not None:
            if nonce is None:
                row = conn.execute(
                    "SELECT nonce FROM accounts WHERE agent_id = ?", (from_agent,)
                ).fetchone()
                nonce = (row[0] + 1) if row else 1
            sender_row = conn.execute(
                "SELECT balance FROM accounts WHERE agent_id = ?", (from_agent,)
            ).fetchone()
            if not sender_row:
                raise ValueError(f"Sender account not found: {from_agent}")
            if sender_row[0] < amount + fee:
                raise ValueError(
                    f"Insufficient balance for {from_agent}: "
                    f"{sender_row[0]} < {amount} + {fee}"
                )
            conn.execute(
                "UPDATE accounts SET balance = balance - ?, nonce = ?, updated_at = ? "
                "WHERE agent_id = ?",
                (amount + fee, nonce, now_ms // 1000, from_agent),
            )

            # v2: Route fee to feepool instead of letting it vanish
            if fee > 0:
                conn.execute(
                    "UPDATE accounts SET balance = balance + ?, updated_at = ? "
                    "WHERE agent_id = ?",
                    (fee, now_ms // 1000, "simp:feepool"),
                )
        else:
            nonce = 0

        # Handle to_agent: if it's None or empty (minting/void), skip credit
        if to_agent and to_agent != "None":
            self._ensure_account(conn, to_agent, to_agent)
            conn.execute(
                "UPDATE accounts SET balance = balance + ?, updated_at = ? WHERE agent_id = ?",
                (amount, now_ms // 1000, to_agent),
            )

        conn.execute(
            """INSERT INTO transactions
               (id, from_agent, to_agent, amount, intent_ref, intent_hash,
                fee, nonce, signature, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (txn_id, from_agent, to_agent, amount, intent_ref, intent_hash,
             fee, nonce, signature, now_ms),
        )
        conn.commit()

        return Transaction(
            id=txn_id, from_agent=from_agent, to_agent=to_agent, amount=amount,
            intent_ref=intent_ref, intent_hash=intent_hash, fee=fee, nonce=nonce,
            signature=signature, created_at=now_ms,
        )

    def _ensure_account(self, conn: sqlite3.Connection, agent_id: str, pubkey_b64: str) -> None:
        """Create account if it doesn't exist (for system accounts)."""
        row = conn.execute(
            "SELECT 1 FROM accounts WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        if row is None:
            now = int(time.time())
            today = int(now // 86400)
            try:
                conn.execute(
                    """INSERT INTO accounts
                       (agent_id, pubkey_b64, balance, nonce, trust_score,
                        stake_amount, last_active_day, created_at, updated_at)
                       VALUES (?, ?, 0, 0, 0.0, 0, ?, ?, ?)""",
                    (agent_id, pubkey_b64, today, now, now),
                )
            except sqlite3.IntegrityError:
                pass

    def txn_get(self, txn_id: str) -> Optional[Transaction]:
        """Fetch transaction by ID."""
        conn = self._acquire_conn() if not self.readonly else self._write()
        row = conn.execute(
            "SELECT * FROM transactions WHERE id = ?", (txn_id,)
        ).fetchone()
        if row is None:
            return None
        return Transaction(
            id=row[0], from_agent=row[1], to_agent=row[2], amount=row[3],
            intent_ref=row[4], intent_hash=row[5], fee=row[6], nonce=row[7],
            signature=row[8], created_at=row[9],
        )

    def txns_for_agent(
        self, agent_id: str, *, limit: int = 100, offset: int = 0
    ) -> List[Transaction]:
        """Return all transactions involving an agent (sent or received)."""
        conn = self._acquire_conn() if not self.readonly else self._write()
        rows = conn.execute(
            """SELECT * FROM transactions
               WHERE from_agent = ? OR to_agent = ?
               ORDER BY created_at DESC
               LIMIT ? OFFSET ?""",
            (agent_id, agent_id, limit, offset),
        ).fetchall()
        return [
            Transaction(
                id=r[0], from_agent=r[1], to_agent=r[2], amount=r[3],
                intent_ref=r[4], intent_hash=r[5], fee=r[6], nonce=r[7],
                signature=r[8], created_at=r[9],
            )
            for r in rows
        ]

    # ── Agent ID derivation ─────────────────────────────────────────────────

    @staticmethod
    def derive_agent_id(pubkey_b64: str) -> str:
        """Derive agent_id from Ed25519 pubkey: sha256(pubkey)[:20], base64url."""
        import base64
        pubkey_bytes = base64.urlsafe_b64decode(pubkey_b64 + "==")
        digest = hashlib.sha256(pubkey_bytes).digest()
        agent_id = base64.urlsafe_b64encode(digest[:20]).rstrip(b"=").decode()
        return agent_id

    # ── Faucet operations ───────────────────────────────────────────────────

    def faucet_allocate(self, pubkey_b64: str, amount: int = 1000) -> Optional[Transaction]:
        """Deterministic faucet: one allocation per pubkey per unix day.

        Returns a Transaction if allocated, None if already allocated today.
        """
        today = int(time.time()) // 86400
        conn = self._write()

        row = conn.execute(
            "SELECT total_alloc FROM faucet_log WHERE pubkey_b64 = ? AND last_unixday = ?",
            (pubkey_b64, today),
        ).fetchone()
        if row:
            conn.commit()
            return None

        agent_id = self.derive_agent_id(pubkey_b64)

        existing = conn.execute(
            "SELECT agent_id FROM accounts WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        if not existing:
            now = int(time.time())
            today = int(now // 86400)
            conn.execute(
                """INSERT INTO accounts
                   (agent_id, pubkey_b64, balance, nonce, trust_score,
                    stake_amount, last_active_day, created_at, updated_at)
                   VALUES (?, ?, 0, 0, 0.5, 0, ?, ?, ?)""",
                (agent_id, pubkey_b64, today, now, now),
            )

        try:
            conn.execute(
                "INSERT INTO faucet_log (pubkey_b64, last_unixday, total_alloc) VALUES (?, ?, ?)",
                (pubkey_b64, today, amount),
            )
        except sqlite3.IntegrityError:
            conn.commit()
            return None

        txn_id = str(uuid.uuid4())
        now_ms = int(time.time() * 1000)
        conn.execute(
            "UPDATE accounts SET balance = balance + ?, updated_at = ? WHERE agent_id = ?",
            (amount, now_ms // 1000, agent_id),
        )
        conn.execute(
            """INSERT INTO transactions
               (id, from_agent, to_agent, amount, intent_ref, fee, nonce, signature, created_at)
               VALUES (?, NULL, ?, ?, 'faucet', 0, 0, NULL, ?)""",
            (txn_id, agent_id, amount, now_ms),
        )
        conn.commit()
        return Transaction(
            id=txn_id, from_agent=None, to_agent=agent_id, amount=amount,
            intent_ref="faucet", intent_hash=None, fee=0, nonce=0,
            signature=None, created_at=now_ms,
        )

    def operator_faucet(self, recipient: str, amount: int, reason: str = "") -> Transaction:
        """Operator-issued faucet allocation (bypasses daily limit).

        v2: Also records emission event for supply tracking.
        """
        now = int(time.time())
        record_id = str(uuid.uuid4())

        # First: record the operator faucet log entry
        conn = self._write()
        try:
            conn.execute(
                "INSERT INTO operator_faucet (id, recipient, amount, reason, issued_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (record_id, recipient, amount, reason, now),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
        finally:
            conn.close()

        # Next: execute the actual token transfer (mint from void)
        txn = self.txn_write(
            from_agent=None,
            to_agent=recipient,
            amount=amount,
            intent_ref=f"operator_faucet:{record_id}",
            fee=0,
        )

        # Finally: record emission for supply tracking (separate transaction)
        try:
            conn2 = self._write()
            emission_id = str(uuid.uuid4())
            conn2.execute(
                """INSERT INTO emission_events (id, to_account, amount, reason, source, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (emission_id, recipient, amount, reason, f"operator_faucet:{record_id}", now),
            )
            conn2.commit()
            conn2.close()
        except sqlite3.IntegrityError:
            pass

        return txn

    # ── Trust score ─────────────────────────────────────────────────────────

    def trust_adjust(
        self,
        agent_id: str,
        delta: float,
        reason: str = "manual",
        *,
        conn: Optional[sqlite3.Connection] = None,
    ) -> Optional[float]:
        """Adjust trust score by delta, clamped to [0.0, 1.0]. Records to history."""
        if conn is None:
            conn = self._write()
        now = int(time.time())
        today = int(now // 86400)
        row = conn.execute(
            "SELECT trust_score FROM accounts WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        if not row:
            return None
        old_score = row[0]
        new_score = max(0.0, min(1.0, old_score + delta))
        conn.execute(
            "UPDATE accounts SET trust_score = ?, last_active_day = ?, updated_at = ? "
            "WHERE agent_id = ?",
            (new_score, today, now, agent_id),
        )
        conn.execute(
            """INSERT INTO trust_history (id, agent_id, old_score, new_score, reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), agent_id, old_score, new_score, reason, now),
        )
        conn.commit()
        return new_score

    def trust_get(self, agent_id: str) -> Optional[float]:
        """Get current trust score."""
        conn = self._acquire_conn() if not self.readonly else self._write()
        row = conn.execute(
            "SELECT trust_score FROM accounts WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        return row[0] if row else None

    def trust_decay(self, daily_decay_bps: int = 5) -> int:
        """Apply inactivity decay to agents stale 7+ days. Returns count of decayed."""
        conn = self._write()
        now = int(time.time())
        today = int(now // 86400)
        stale_cutoff = today - 7

        rows = conn.execute(
            """SELECT agent_id, trust_score FROM accounts
               WHERE last_active_day < ? AND trust_score > 0""",
            (stale_cutoff,),
        ).fetchall()
        decayed = 0
        for agent_id, old_score in rows:
            last_day = conn.execute(
                "SELECT last_active_day FROM accounts WHERE agent_id = ?", (agent_id,)
            ).fetchone()[0]
            days_inactive = today - last_day
            delta = -min(daily_decay_bps / 10000 * days_inactive, old_score)
            new_score = max(0.0, old_score + delta)
            conn.execute(
                "UPDATE accounts SET trust_score = ?, updated_at = ? WHERE agent_id = ?",
                (new_score, now, agent_id),
            )
            conn.execute(
                """INSERT INTO trust_history (id, agent_id, old_score, new_score, reason, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), agent_id, old_score, new_score, "decay", now),
            )
            decayed += 1
        conn.commit()
        return decayed

    def intent_hook_success(self, agent_id: str, intent_ref: str) -> IntentEvent:
        """Record successful intent execution, bump trust."""
        conn = self._write()
        now = int(time.time())
        today = int(now // 86400)
        delta = 0.01
        row = conn.execute(
            "SELECT trust_score FROM accounts WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        old_score = row[0] if row else 0.5
        new_score = min(1.0, old_score + delta)
        event_id = str(uuid.uuid4())
        conn.execute(
            "UPDATE accounts SET trust_score = ?, last_active_day = ?, updated_at = ? "
            "WHERE agent_id = ?",
            (new_score, today, now, agent_id),
        )
        conn.execute(
            """INSERT INTO trust_history (id, agent_id, old_score, new_score, reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), agent_id, old_score, new_score, "intent_success", now),
        )
        conn.execute(
            """INSERT INTO intent_events (event_id, agent_id, intent_ref, outcome, trust_delta, created_at)
               VALUES (?, ?, ?, 'success', ?, ?)""",
            (event_id, agent_id, intent_ref, delta, now),
        )
        conn.commit()
        return IntentEvent(
            event_id=event_id, agent_id=agent_id, intent_ref=intent_ref,
            outcome="success", trust_delta=delta, created_at=now,
        )

    def intent_hook_failure(
        self, agent_id: str, intent_ref: str, penalty: float = 0.02
    ) -> IntentEvent:
        """Record failed intent execution, apply trust penalty."""
        conn = self._write()
        now = int(time.time())
        today = int(now // 86400)
        row = conn.execute(
            "SELECT trust_score FROM accounts WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        old_score = row[0] if row else 0.5
        new_score = max(0.0, old_score - penalty)
        event_id = str(uuid.uuid4())
        conn.execute(
            "UPDATE accounts SET trust_score = ?, last_active_day = ?, updated_at = ? "
            "WHERE agent_id = ?",
            (new_score, today, now, agent_id),
        )
        conn.execute(
            """INSERT INTO trust_history (id, agent_id, old_score, new_score, reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), agent_id, old_score, new_score, "intent_failure", now),
        )
        conn.execute(
            """INSERT INTO intent_events (event_id, agent_id, intent_ref, outcome, trust_delta, created_at)
               VALUES (?, ?, ?, 'failure', ?, ?)""",
            (event_id, agent_id, intent_ref, -penalty, now),
        )
        conn.commit()
        return IntentEvent(
            event_id=event_id, agent_id=agent_id, intent_ref=intent_ref,
            outcome="failure", trust_delta=-penalty, created_at=now,
        )

    def trust_history_get(self, agent_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Return recent trust history for an agent."""
        conn = self._acquire_conn() if not self.readonly else self._write()
        rows = conn.execute(
            """SELECT id, agent_id, old_score, new_score, reason, created_at
               FROM trust_history WHERE agent_id = ?
               ORDER BY seq DESC LIMIT ?""",
            (agent_id, limit),
        ).fetchall()
        return [
            {"id": r[0], "agent_id": r[1], "old_score": r[2], "new_score": r[3],
             "reason": r[4], "created_at": r[5]}
            for r in rows
        ]

    # ── Broker Trust (SIP-002 §5) ─────────────────────────────────────────────

    def broker_trust_record(self, broker_id: str, elapsed_ms: float) -> BrokerTrust:
        """Append an ack-time observation, recompute rolling avg/std, update reputation."""
        import statistics
        now = int(time.time())
        conn = self._write()
        row = conn.execute(
            "SELECT last_100_rounds, n_rounds FROM broker_trust WHERE broker_id = ?",
            (broker_id,),
        ).fetchone()
        if row:
            rounds = json.loads(row[0]) if row[0] else []
        else:
            rounds = []
        n = row[1] if row else 0

        rounds.append(elapsed_ms)
        if len(rounds) > 100:
            rounds = rounds[-100:]
        avg = statistics.mean(rounds) if rounds else 0.0
        std = statistics.stdev(rounds) if len(rounds) > 1 else 0.0
        rep = self._derive_broker_reputation(
            BrokerTrust(broker_id, avg, std, n + 1, 0.5, rounds, now)
        )
        conn.execute(
            """INSERT INTO broker_trust
               (broker_id, avg_ack_time_ms, ack_time_std, n_rounds,
                reputation_score, last_100_rounds, last_updated)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(broker_id) DO UPDATE SET
               avg_ack_time_ms = excluded.avg_ack_time_ms,
               ack_time_std = excluded.ack_time_std,
               n_rounds = excluded.n_rounds,
               reputation_score = excluded.reputation_score,
               last_100_rounds = excluded.last_100_rounds,
               last_updated = excluded.last_updated""",
            (broker_id, avg, std, n + 1, rep, json.dumps(rounds), now),
        )
        conn.commit()
        return BrokerTrust(broker_id, avg, std, n + 1, rep, rounds, now)

    def broker_trust_get(self, broker_id: str) -> Optional[BrokerTrust]:
        """Fetch broker trust record."""
        conn = self._acquire_conn() if not self.readonly else self._write()
        row = conn.execute(
            "SELECT * FROM broker_trust WHERE broker_id = ?", (broker_id,)
        ).fetchone()
        if not row:
            return None
        return BrokerTrust(
            broker_id=row[0], avg_ack_time_ms=row[1], ack_time_std=row[2],
            n_rounds=row[3], reputation_score=row[4],
            last_100_rounds=json.loads(row[5]) if row[5] else [],
            last_updated=row[6],
        )

    def _derive_broker_reputation(self, trust: BrokerTrust) -> float:
        """SIP-002 §5.3: 0.6 * consistency + 0.4 * latency_score."""
        if trust.n_rounds < 2:
            return 0.5
        cv = trust.ack_time_std / trust.avg_ack_time_ms if trust.avg_ack_time_ms > 0 else 1.0
        consistency = max(0.0, 1.0 - cv)
        best_ms, worst_ms = 10.0, 500.0
        latency_score = max(0.0, min(1.0,
            1.0 - (trust.avg_ack_time_ms - best_ms) / (worst_ms - best_ms)
        ))
        return 0.6 * consistency + 0.4 * latency_score

    def select_broker_for_intent(self, intent: Any, brokers: List[str]) -> str:
        """Route high-value intents (fee > 10 or type starts with escrow/bundle) to
        lowest avg_ack_time_ms broker; otherwise return first broker."""
        fee = getattr(intent, 'fee', 0) or 0
        intent_type = getattr(intent, 'intent_type', '') or ''
        if fee > 10 or intent_type.startswith('escrow') or intent_type.startswith('bundle'):
            candidates = []
            for b in brokers:
                t = self.broker_trust_get(b)
                if t:
                    candidates.append((t.avg_ack_time_ms, b))
            if candidates:
                candidates.sort(key=lambda x: x[0])
                return candidates[0][1]
        return brokers[0] if brokers else ""

    # ── Staking ───────────────────────────────────────────────────────────────

    def stake_lock(
        self, agent_id: str, amount: int, *, conn: Optional[sqlite3.Connection] = None
    ) -> Account:
        """Lock amount into stake (reduces available balance)."""
        if conn is None:
            conn = self._write()
        now = int(time.time())
        row = conn.execute(
            "SELECT balance, stake_amount FROM accounts WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Account not found: {agent_id}")
        if row[0] < amount:
            raise ValueError(f"Insufficient balance to stake: {row[0]} < {amount}")
        conn.execute(
            "UPDATE accounts SET balance = balance - ?, stake_amount = stake_amount + ?, "
            "updated_at = ? WHERE agent_id = ?",
            (amount, amount, now, agent_id),
        )
        conn.commit()
        return self.account_get(agent_id)

    def stake_release(
        self, agent_id: str, amount: int, *, conn: Optional[sqlite3.Connection] = None
    ) -> Account:
        """Release stake back to available balance."""
        if conn is None:
            conn = self._write()
        now = int(time.time())
        row = conn.execute(
            "SELECT stake_amount FROM accounts WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Account not found: {agent_id}")
        if row[0] < amount:
            raise ValueError(f"Cannot release {amount} - stake balance is {row[0]}")
        conn.execute(
            "UPDATE accounts SET balance = balance + ?, stake_amount = stake_amount - ?, "
            "updated_at = ? WHERE agent_id = ?",
            (amount, amount, now, agent_id),
        )
        conn.commit()
        return self.account_get(agent_id)

    # ── Escrow ───────────────────────────────────────────────────────────────

    def escrow_open(
        self,
        requester: str,
        responder: str,
        dispute_bond: int,
        intent_ref: Optional[str] = None,
    ) -> EscrowRecord:
        """Open an escrow: both parties lock dispute_bond. Uses single conn."""
        escrow_id = f"escrow_{uuid.uuid4().hex[:16]}"
        now = int(time.time())
        conn = self._write()
        self.stake_lock(requester, dispute_bond, conn=conn)
        self.stake_lock(responder, dispute_bond, conn=conn)
        conn.execute(
            """INSERT INTO escrow_records
               (escrow_id, requester, responder, dispute_bond, intent_ref,
                status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'open', ?, ?)""",
            (escrow_id, requester, responder, dispute_bond, intent_ref, now, now),
        )
        conn.commit()
        return EscrowRecord(
            escrow_id=escrow_id, requester=requester, responder=responder,
            dispute_bond=dispute_bond, intent_ref=intent_ref,
            status="open", created_at=now, updated_at=now,
        )

    def escrow_release(self, escrow_id: str, winner: str, loser: str) -> None:
        """Release escrow: winner gets both bonds, loser forfeits. Uses single conn."""
        conn = self._write()
        row = conn.execute(
            "SELECT dispute_bond FROM escrow_records WHERE escrow_id = ? AND status = 'open'",
            (escrow_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Escrow not found or not open: {escrow_id}")
        bond = row[0]
        self.stake_release(winner, bond, conn=conn)
        conn.execute(
            "UPDATE accounts SET stake_amount = stake_amount - ? WHERE agent_id = ?",
            (bond, loser),
        )
        conn.execute(
            "UPDATE accounts SET balance = balance + ? WHERE agent_id = ?",
            (bond, winner),
        )
        conn.execute(
            "UPDATE escrow_records SET status = 'released', updated_at = ? WHERE escrow_id = ?",
            (int(time.time()), escrow_id),
        )
        conn.commit()

    def escrow_execute(self, escrow_id: str) -> EscrowRecord:
        """Execute escrow: both parties performed. Return bonds. Uses single conn."""
        conn = self._write()
        now = int(time.time())
        row = conn.execute(
            "SELECT * FROM escrow_records WHERE escrow_id = ? AND status = 'open'",
            (escrow_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Escrow not found or not open: {escrow_id}")
        _, requester, responder, dispute_bond, intent_ref, _, created_at, _ = row
        self.stake_release(requester, dispute_bond, conn=conn)
        self.stake_release(responder, dispute_bond, conn=conn)
        conn.execute(
            "UPDATE escrow_records SET status = 'executed', updated_at = ? WHERE escrow_id = ?",
            (now, escrow_id),
        )
        conn.commit()
        return EscrowRecord(
            escrow_id=escrow_id, requester=requester, responder=responder,
            dispute_bond=dispute_bond, intent_ref=intent_ref,
            status="executed", created_at=created_at, updated_at=now,
        )

    def escrow_dispute(self, escrow_id: str, dispute_winner: str) -> EscrowRecord:
        """Dispute resolved: winner gets both bonds, loser forfeits."""
        row = self.escrow_get(escrow_id)
        if not row:
            raise ValueError(f"Escrow not found: {escrow_id}")
        loser = row.requester if dispute_winner != row.requester else row.responder
        self.escrow_release(escrow_id, winner=dispute_winner, loser=loser)
        return self.escrow_get(escrow_id)

    def escrow_cancel(self, escrow_id: str) -> EscrowRecord:
        """Cancel escrow: only allowed while open. Return bonds to both parties."""
        conn = self._write()
        now = int(time.time())
        row = conn.execute(
            "SELECT * FROM escrow_records WHERE escrow_id = ? AND status = 'open'",
            (escrow_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Escrow not found or not open: {escrow_id}")
        _, requester, responder, dispute_bond, intent_ref, _, created_at, _ = row
        self.stake_release(requester, dispute_bond, conn=conn)
        self.stake_release(responder, dispute_bond, conn=conn)
        conn.execute(
            "UPDATE escrow_records SET status = 'released', updated_at = ? WHERE escrow_id = ?",
            (now, escrow_id),
        )
        conn.commit()
        return EscrowRecord(
            escrow_id=escrow_id, requester=requester, responder=responder,
            dispute_bond=dispute_bond, intent_ref=intent_ref,
            status="released", created_at=created_at, updated_at=now,
        )

    def escrow_get(self, escrow_id: str) -> Optional[EscrowRecord]:
        conn = self._acquire_conn() if not self.readonly else self._write()
        row = conn.execute(
            "SELECT * FROM escrow_records WHERE escrow_id = ?", (escrow_id,)
        ).fetchone()
        if not row:
            return None
        return EscrowRecord(
            escrow_id=row[0], requester=row[1], responder=row[2],
            dispute_bond=row[3], intent_ref=row[4], status=row[5],
            created_at=row[6], updated_at=row[7],
        )

    # ── Intent Bundles ───────────────────────────────────────────────────────

    def bundle_create(self, intent_type: str, participants: List[str]) -> IntentBundle:
        """Create a new intent bundle. Creator must fund it separately via bundle_fund."""
        bundle_id = f"bundle_{uuid.uuid4().hex[:16]}"
        now = int(time.time())
        conn = self._write()
        conn.execute(
            """INSERT INTO intent_bundles
               (bundle_id, intent_type, participants, total_stake, status, created_at)
               VALUES (?, ?, ?, 0, 'open', ?)""",
            (bundle_id, intent_type, json.dumps(participants), now),
        )
        conn.commit()
        return IntentBundle(
            bundle_id=bundle_id, intent_type=intent_type,
            participants=participants, total_stake=0, status="open", created_at=now,
        )

    def bundle_fund(
        self, bundle_id: str, agent_id: str, stake_amount: int
    ) -> IntentBundle:
        """Fund a bundle with stake from a participant. Uses single conn."""
        now = int(time.time())
        conn = self._write()
        row = conn.execute(
            "SELECT status FROM intent_bundles WHERE bundle_id = ?", (bundle_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Bundle not found: {bundle_id}")
        if row[0] != "open":
            raise ValueError(f"Bundle is not open: {row[0]}")

        self.stake_lock(agent_id, stake_amount, conn=conn)

        conn.execute(
            """INSERT INTO bundle_participants (bundle_id, agent_id, stake_amount, status, joined_at)
               VALUES (?, ?, ?, 'funded', ?)
               ON CONFLICT(bundle_id, agent_id) DO UPDATE SET
               stake_amount = stake_amount + ?, status = 'funded'""",
            (bundle_id, agent_id, stake_amount, now, stake_amount),
        )
        conn.execute(
            "UPDATE intent_bundles SET total_stake = total_stake + ? WHERE bundle_id = ?",
            (stake_amount, bundle_id),
        )
        conn.commit()

        bundle = self.bundle_get(bundle_id)
        if bundle and bundle.total_stake >= 1000 and bundle.status == "open":
            conn2 = self._write()
            conn2.execute(
                "UPDATE intent_bundles SET status = 'funded' WHERE bundle_id = ?",
                (bundle_id,),
            )
            conn2.commit()
            bundle = self.bundle_get(bundle_id)
        return bundle

    def bundle_execute(self, bundle_id: str) -> IntentBundle:
        """Execute bundle: distribute total_stake back to participants pro-rata."""
        conn = self._write()
        now = int(time.time())
        row = conn.execute(
            "SELECT * FROM intent_bundles WHERE bundle_id = ? AND status = 'funded'",
            (bundle_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Bundle not found or not funded: {bundle_id}")
        _, intent_type, participants_json, total_stake, _, created_at = row
        participants = json.loads(participants_json)

        rows = conn.execute(
            "SELECT agent_id, stake_amount FROM bundle_participants "
            "WHERE bundle_id = ? AND status = 'funded'",
            (bundle_id,),
        ).fetchall()

        total_contributed = sum(r[1] for r in rows)
        if total_contributed == 0:
            raise ValueError("No funded participants in bundle")

        for agent_id, stake_amount in rows:
            share = int(total_stake * stake_amount / total_contributed)
            if share > 0:
                self.stake_release(agent_id, stake_amount, conn=conn)
                conn.execute(
                    "UPDATE accounts SET balance = balance + ? WHERE agent_id = ?",
                    (share, agent_id),
                )
                conn.execute(
                    "UPDATE bundle_participants SET status = 'slashed' "
                    "WHERE bundle_id = ? AND agent_id = ?",
                    (bundle_id, agent_id),
                )

        conn.execute(
            "UPDATE intent_bundles SET status = 'executed', total_stake = 0 "
            "WHERE bundle_id = ?",
            (bundle_id,),
        )
        conn.commit()
        return IntentBundle(
            bundle_id=bundle_id, intent_type=intent_type,
            participants=participants, total_stake=0, status="executed",
            created_at=created_at,
        )

    def bundle_dispute(self, bundle_id: str, slashed_agent: str) -> IntentBundle:
        """Dispute resolved: one agent is slashed, rest get their stake back."""
        conn = self._write()
        now = int(time.time())
        row = conn.execute(
            "SELECT * FROM intent_bundles WHERE bundle_id = ? AND status = 'funded'",
            (bundle_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Bundle not found or not funded: {bundle_id}")
        _, intent_type, participants_json, total_stake, _, created_at = row
        participants = json.loads(participants_json)

        slashed_row = conn.execute(
            "SELECT stake_amount FROM bundle_participants "
            "WHERE bundle_id = ? AND agent_id = ?",
            (bundle_id, slashed_agent),
        ).fetchone()
        if not slashed_row:
            raise ValueError(f"Agent not a participant in bundle: {slashed_agent}")

        rows = conn.execute(
            "SELECT agent_id, stake_amount FROM bundle_participants WHERE bundle_id = ?",
            (bundle_id,),
        ).fetchall()
        for agent_id, stake_amount in rows:
            if agent_id != slashed_agent:
                self.stake_release(agent_id, stake_amount, conn=conn)
                conn.execute(
                    "UPDATE bundle_participants SET status = 'funded' "
                    "WHERE bundle_id = ? AND agent_id = ?",
                    (bundle_id, agent_id),
                )

        conn.execute(
            "UPDATE bundle_participants SET status = 'slashed' "
            "WHERE bundle_id = ? AND agent_id = ?",
            (bundle_id, slashed_agent),
        )
        conn.execute(
            "UPDATE intent_bundles SET status = 'disputed' WHERE bundle_id = ?",
            (bundle_id,),
        )
        conn.commit()
        return IntentBundle(
            bundle_id=bundle_id, intent_type=intent_type,
            participants=participants, total_stake=0, status="disputed",
            created_at=created_at,
        )

    def bundle_get(self, bundle_id: str) -> Optional[IntentBundle]:
        """Get a bundle by ID."""
        conn = self._acquire_conn() if not self.readonly else self._write()
        row = conn.execute(
            "SELECT * FROM intent_bundles WHERE bundle_id = ?", (bundle_id,)
        ).fetchone()
        if not row:
            return None
        return IntentBundle(
            bundle_id=row[0], intent_type=row[1],
            participants=json.loads(row[2]), total_stake=row[3],
            status=row[4], created_at=row[5],
        )

    def bundles_for_agent(self, agent_id: str) -> List[IntentBundle]:
        """Return all bundles an agent participates in (funded or listed)."""
        conn = self._acquire_conn() if not self.readonly else self._write()
        rows = conn.execute(
            """SELECT DISTINCT b.* FROM intent_bundles b
               WHERE b.bundle_id IN (
                   SELECT p.bundle_id FROM bundle_participants p WHERE p.agent_id = ?
                   UNION
                   SELECT bundle_id FROM intent_bundles, json_each(participants)
                   WHERE json_each.value = ?
               )
               ORDER BY b.created_at DESC""",
            (agent_id, agent_id),
        ).fetchall()
        return [
            IntentBundle(
                bundle_id=r[0], intent_type=r[1],
                participants=json.loads(r[2]), total_stake=r[3],
                status=r[4], created_at=r[5],
            )
            for r in rows
        ]

    # ── Inflation ───────────────────────────────────────────────────────────

    def inflation_distribute(self, annual_bps: int = 500) -> int:
        """Daily inflation mint with stake-weighted distribution.

        Distribution weight = stake_amount * trust_score.
        When total_stake is low, falls back to trust-only weighted balance.
        """
        conn = self._write()
        now = int(time.time())
        total = conn.execute(
            "SELECT SUM(balance * trust_score) FROM accounts"
        ).fetchone()[0] or 0
        if total == 0:
            return 0
        daily = total * (annual_bps / 10000) / 365
        if daily < 1:
            return 0
        daily_int = int(daily)

        total_stake = conn.execute(
            "SELECT SUM(stake_amount) FROM accounts"
        ).fetchone()[0] or 0

        if total_stake >= 1000:
            rows = conn.execute(
                "SELECT agent_id, balance, stake_amount, trust_score FROM accounts "
                "WHERE trust_score > 0"
            ).fetchall()
            stake_portion = int(daily_int * 0.7)
            trust_portion = daily_int - stake_portion
            total_stake_score = sum(r[2] * r[3] for r in rows) or 1
            total_balance_score = sum(r[1] * r[3] for r in rows) or 1
            for agent_id, balance, stake_amount, trust_score in rows:
                stake_w = (stake_amount * trust_score) / total_stake_score
                trust_w = (balance * trust_score) / total_balance_score
                allocation = int(stake_portion * stake_w) + int(trust_portion * trust_w)
                if allocation > 0:
                    conn.execute(
                        "UPDATE accounts SET balance = balance + ?, updated_at = ? "
                        "WHERE agent_id = ?",
                        (allocation, now, agent_id),
                    )
                    conn.execute(
                        """INSERT INTO transactions
                           (id, from_agent, to_agent, amount, intent_ref, fee, nonce, created_at)
                           VALUES (?, NULL, ?, ?, 'inflation', 0, 0, ?)""",
                        (str(uuid.uuid4()), agent_id, allocation, now),
                    )
            conn.commit()
        else:
            rows = conn.execute(
                "SELECT agent_id FROM accounts WHERE trust_score > 0"
            ).fetchall()
            for (agent_id,) in rows:
                conn.execute(
                    "UPDATE accounts SET balance = balance + ?, updated_at = ? "
                    "WHERE agent_id = ?",
                    (daily_int, now, agent_id),
                )
                conn.execute(
                    """INSERT INTO transactions
                       (id, from_agent, to_agent, amount, intent_ref, fee, nonce, created_at)
                       VALUES (?, NULL, ?, ?, 'inflation', 0, 0, ?)""",
                    (str(uuid.uuid4()), agent_id, daily_int, now),
                )
            conn.commit()
        return daily_int

    # ── Fee middleware ───────────────────────────────────────────────────────

    def fee_schedule(self, load_factor: float = 1.0) -> FeeSchedule:
        """Return a FeeSchedule for the given broker load factor."""
        return FeeSchedule(load_factor=load_factor)

    def intent_fee_estimate(self, intent_type: str, load_factor: float = 1.0) -> int:
        """Pre-commit fee estimate for an intent type at current load."""
        return FeeSchedule(load_factor=load_factor).compute_fee(intent_type)

    def intent_pay_fee(
        self,
        intent_type: str,
        from_agent: str,
        amount: int,
        load_factor: float = 1.0,
        intent_ref: Optional[str] = None,
    ) -> Transaction:
        """Pay fee for an intent and deduct amount in one atomic operation.

        v2: Fee routes to simp:feepool (system account), not black hole.
        """
        fee = FeeSchedule(load_factor=load_factor).compute_fee(intent_type)
        return self.txn_write(
            from_agent=from_agent,
            to_agent=FEE_SINK,
            amount=amount,
            fee=fee,
            intent_ref=intent_ref or f"intent_fee:{intent_type}",
        )

    def intent_with_fee(
        self,
        intent_type: str,
        from_agent: str,
        to_agent: str,
        amount: int,
        load_factor: float = 1.0,
        intent_ref: Optional[str] = None,
    ) -> Transaction:
        """Execute intent payment with fee - both deducted atomically from sender."""
        fee = FeeSchedule(load_factor=load_factor).compute_fee(intent_type)
        return self.txn_write(
            from_agent=from_agent,
            to_agent=to_agent,
            amount=amount,
            fee=fee,
            intent_ref=intent_ref or f"intent:{intent_type}",
        )

    def dynamic_fee_estimate(self, intent_type: str, queue_depth: int = 0) -> int:
        """Estimate fee accounting for broker queue depth. Caps at 3x base."""
        base = FeeSchedule().compute_fee(intent_type)
        if queue_depth <= 0:
            return base
        load = min(3.0, 1.0 + math.log1p(queue_depth) / 10.0)
        return int(base * load)

    # ── Agent Key Registry ───────────────────────────────────────────────────

    def agent_key_register(
        self,
        agent_id: str,
        pubkey_b64: str,
        purpose: str = "signing",
        expires_at: Optional[int] = None,
    ) -> AgentKeyRecord:
        """Register a new Ed25519 key for an agent. Idempotent for same pubkey."""
        conn = self._write()
        now = int(time.time())

        existing_row = conn.execute(
            "SELECT key_seq FROM agent_registry WHERE agent_id = ? AND pubkey_b64 = ?",
            (agent_id, pubkey_b64),
        ).fetchone()
        if existing_row:
            conn.commit()
            return self.agent_key_get_latest(agent_id, purpose=purpose)

        row = conn.execute(
            "SELECT MAX(key_seq) FROM agent_registry WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()
        key_seq = (row[0] + 1) if row[0] is not None else 0

        conn.execute(
            """INSERT INTO agent_registry
               (agent_id, pubkey_b64, key_seq, key_purpose, status, issued_at, expires_at)
               VALUES (?, ?, ?, ?, 'active', ?, ?)""",
            (agent_id, pubkey_b64, key_seq, purpose, now, expires_at),
        )
        conn.commit()

        return self.agent_key_get_latest(agent_id, purpose=purpose)

    def agent_key_get_latest(
        self, agent_id: str, purpose: str = "signing"
    ) -> Optional[AgentKeyRecord]:
        """Get the most recent active key for an agent and purpose."""
        conn = self._acquire_conn() if not self.readonly else self._write()
        row = conn.execute(
            """SELECT agent_id, pubkey_b64, key_seq, key_purpose, status,
                      issued_at, expires_at, revoked_at, revoked_reason
               FROM agent_registry
               WHERE agent_id = ? AND key_purpose = ? AND status = 'active'
               ORDER BY key_seq DESC LIMIT 1""",
            (agent_id, purpose),
        ).fetchone()
        if not row:
            return None
        return AgentKeyRecord(
            agent_id=row[0], pubkey_b64=row[1], key_seq=row[2],
            key_purpose=row[3], status=row[4], issued_at=row[5],
            expires_at=row[6], revoked_at=row[7], revoked_reason=row[8],
        )

    def agent_key_get_all(self, agent_id: str) -> List[AgentKeyRecord]:
        """Get all key records for an agent (all purposes and statuses)."""
        conn = self._acquire_conn() if not self.readonly else self._write()
        rows = conn.execute(
            """SELECT agent_id, pubkey_b64, key_seq, key_purpose, status,
                      issued_at, expires_at, revoked_at, revoked_reason
               FROM agent_registry
               WHERE agent_id = ?
               ORDER BY key_seq DESC""",
            (agent_id,),
        ).fetchall()
        return [
            AgentKeyRecord(
                agent_id=r[0], pubkey_b64=r[1], key_seq=r[2], key_purpose=r[3],
                status=r[4], issued_at=r[5], expires_at=r[6],
                revoked_at=r[7], revoked_reason=r[8],
            )
            for r in rows
        ]

    def agent_key_verify(self, agent_id: str, pubkey_b64: str) -> bool:
        """Verify a pubkey is currently active for an agent."""
        record = self.agent_key_get_latest(agent_id, purpose="signing")
        if record is None:
            return False
        if record.pubkey_b64 != pubkey_b64:
            return False
        now = int(time.time())
        if record.expires_at is not None and record.expires_at < now:
            return False
        return record.status == "active"

    def agent_key_revoke(
        self,
        agent_id: str,
        revoked_reason: str = "",
        *,
        conn: Optional[sqlite3.Connection] = None,
    ) -> Optional[AgentKeyRecord]:
        """Revoke the latest active key for an agent. Uses single conn for atomicity."""
        if conn is None:
            conn = self._write()
        now = int(time.time())
        row = conn.execute(
            """SELECT agent_id, pubkey_b64, key_seq, key_purpose, status,
                      issued_at, expires_at, revoked_at, revoked_reason
               FROM agent_registry
               WHERE agent_id = ? AND status = 'active'
               ORDER BY key_seq DESC LIMIT 1""",
            (agent_id,),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE agent_registry SET status = 'revoked', revoked_at = ?, "
            "revoked_reason = ? WHERE agent_id = ? AND key_seq = ?",
            (now, revoked_reason, row[0], row[2]),
        )
        conn.commit()
        return AgentKeyRecord(
            agent_id=row[0], pubkey_b64=row[1], key_seq=row[2],
            key_purpose=row[3], status="revoked", issued_at=row[5],
            expires_at=row[6], revoked_at=now, revoked_reason=revoked_reason,
        )

    def agent_key_rotate(
        self, agent_id: str, new_pubkey_b64: str, revoke_reason: str = "key rotation"
    ) -> AgentKeyRecord:
        """Rotate to a new key: revoke current, register new. Atomic."""
        conn = self._write()
        self.agent_key_revoke(agent_id, revoke_reason, conn=conn)
        return self.agent_key_register(agent_id, new_pubkey_b64, purpose="signing")

    # ── Sponsor onboarding (Phase 7) ──────────────────────────────────────

    def sponsor_onboard(
        self,
        sponsor_id: str,
        sponsored_agent: str,
        sponsor_bond: int = 500_000,
        delegation_fee_bps: int = 100,
    ) -> Sponsor:
        """Onboard a new agent via sponsor bond. Sponsor must have trust_score >= 0.7."""
        trust = self.trust_get(sponsor_id)
        if trust is None:
            raise ValueError(f"Sponsor account not found: {sponsor_id}")
        if trust < 0.7:
            raise ValueError(f"Sponsor trust_score must be >= 0.7, got {trust}")

        sponsor_acc = self.account_get(sponsor_id)
        if sponsor_acc.balance < sponsor_bond:
            raise ValueError(
                f"Sponsor balance {sponsor_acc.balance} < bond {sponsor_bond}"
            )

        conn = self._write()
        now = int(time.time())
        self.stake_lock(sponsor_id, sponsor_bond, conn=conn)

        conn.execute(
            """INSERT INTO sponsors
               (sponsor_id, sponsored_agent, sponsor_bond, delegation_fee_bps,
                status, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'active', ?, ?)""",
            (sponsor_id, sponsored_agent, sponsor_bond, delegation_fee_bps, now, now),
        )
        conn.commit()

        return Sponsor(
            sponsor_id=sponsor_id, sponsored_agent=sponsored_agent,
            sponsor_bond=sponsor_bond, delegation_fee_bps=delegation_fee_bps,
            status="active", created_at=now, updated_at=now,
        )

    def sponsor_get(self, sponsored_agent: str) -> Optional[Sponsor]:
        """Get active sponsor for a sponsored agent."""
        conn = self._acquire_conn() if not self.readonly else self._write()
        row = conn.execute(
            """SELECT sponsor_id, sponsored_agent, sponsor_bond, delegation_fee_bps,
                      status, created_at, updated_at
               FROM sponsors WHERE sponsored_agent = ? AND status = 'active'""",
            (sponsored_agent,),
        ).fetchone()
        if not row:
            return None
        return Sponsor(
            sponsor_id=row[0], sponsored_agent=row[1], sponsor_bond=row[2],
            delegation_fee_bps=row[3], status=row[4], created_at=row[5], updated_at=row[6],
        )

    def sponsor_charge_delegation_fee(
        self, sponsor_id: str, sponsored_agent: str, fee_amount: int
    ) -> None:
        """Charge delegation fee from sponsor's balance."""
        sp = self.sponsor_get(sponsored_agent)
        if sp is None or sp.sponsor_id != sponsor_id:
            return
        delegation = int(fee_amount * sp.delegation_fee_bps / 10000)
        if delegation <= 0:
            return
        conn = self._write()
        conn.execute(
            "UPDATE accounts SET balance = balance - ?, updated_at = ? WHERE agent_id = ?",
            (delegation, int(time.time()), sponsor_id),
        )
        conn.commit()

    def sponsor_release(self, sponsor_id: str, sponsored_agent: str) -> Sponsor:
        """Release sponsor bond (agent left gracefully)."""
        conn = self._write()
        now = int(time.time())
        row = conn.execute(
            """SELECT sponsor_id, sponsored_agent, sponsor_bond, delegation_fee_bps,
                      status, created_at, updated_at
               FROM sponsors WHERE sponsored_agent = ? AND status = 'active'""",
            (sponsored_agent,),
        ).fetchone()
        if not row:
            raise ValueError(f"No active sponsor for: {sponsored_agent}")
        if row[0] != sponsor_id:
            raise ValueError(f"Sponsor mismatch: {row[0]} != {sponsor_id}")
        sponsor_bond = row[2]
        self.stake_release(sponsor_id, sponsor_bond, conn=conn)
        conn.execute(
            "UPDATE sponsors SET status = 'released', updated_at = ? "
            "WHERE sponsored_agent = ?",
            (now, sponsored_agent),
        )
        conn.commit()
        return Sponsor(
            sponsor_id=sponsor_id, sponsored_agent=sponsored_agent,
            sponsor_bond=sponsor_bond, delegation_fee_bps=row[3],
            status="released", created_at=row[5], updated_at=now,
        )

    # ── Stats ───────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """Return ledger statistics."""
        conn = self._acquire_conn() if not self.readonly else self._write()
        account_count = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
        txn_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        total_supply = conn.execute("SELECT SUM(balance) FROM accounts").fetchone()[0] or 0
        total_staked = conn.execute("SELECT SUM(stake_amount) FROM accounts").fetchone()[0] or 0
        avg_trust = conn.execute(
            "SELECT AVG(trust_score) FROM accounts WHERE trust_score > 0"
        ).fetchone()[0] or 0.0
        event_count = conn.execute(
            "SELECT COUNT(*) FROM intent_events"
        ).fetchone()[0]
        return {
            "account_count": account_count,
            "txn_count": txn_count,
            "total_supply": total_supply,
            "total_staked": total_staked,
            "avg_trust_score": round(avg_trust, 4),
            "intent_event_count": event_count,
        }

    def get_supply_metrics(self) -> Dict[str, Any]:
        """Get comprehensive supply metrics via the supply_metrics view."""
        conn = self._acquire_conn() if not self.readonly else self._write()
        try:
            row = conn.execute("SELECT * FROM supply_metrics").fetchone()
            if row:
                return {
                    "total_balances": row[0],
                    "fee_pool_balance": row[1],
                    "burn_vault_balance": row[2],
                    "treasury_balance": row[3],
                    "total_staked": row[4],
                    "total_burned": row[5],
                    "total_minted": row[6],
                    "net_supply": row[7],
                    "circulating": row[8],
                }
        except sqlite3.OperationalError:
            pass
        # Fallback: compute manually
        from .burn_engine import BurnEngine
        return BurnEngine(self).get_supply_metrics()
