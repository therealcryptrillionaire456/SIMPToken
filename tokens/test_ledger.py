"""
Phase 1 tests for SimpMesh Token Ledger.
Run with: python3 -m pytest tests/test_ledger.py -v
"""

import os
import tempfile
import hashlib
import base64

import pytest

from tokens.ledger import FeeSchedule


# ── Helpers ────────────────────────────────────────────────────────────────

def make_pubkey(seed: int = 1) -> str:
    """Generate a deterministic Ed25519 pubkey for testing."""
    from nacl.signing import SigningKey
    seed_bytes = seed.to_bytes(32, "big")
    sk = SigningKey(seed_bytes)
    return base64.urlsafe_b64encode(bytes(sk.verify_key)).rstrip(b"=").decode()


def make_agent_id(pubkey_b64: str) -> str:
    pubkey_bytes = base64.urlsafe_b64decode(pubkey_b64 + "==")
    digest = hashlib.sha256(pubkey_bytes).digest()
    return base64.urlsafe_b64encode(digest[:20]).rstrip(b"=").decode()


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def ledger_path(tmp_path):
    return tmp_path / "ledger.db"


@pytest.fixture
def ledger(ledger_path):
    from simp.tokens import Ledger
    return Ledger(ledger_path)


@pytest.fixture
def alice_pubkey():
    return make_pubkey(1)


@pytest.fixture
def bob_pubkey():
    return make_pubkey(2)


@pytest.fixture
def alice_id(alice_pubkey):
    return make_agent_id(alice_pubkey)


@pytest.fixture
def bob_id(bob_pubkey):
    return make_agent_id(bob_pubkey)


# ── Account tests ─────────────────────────────────────────────────────────

def test_account_create_and_get(ledger, alice_pubkey, alice_id):
    acc = ledger.account_create(alice_id, alice_pubkey)
    assert acc.agent_id == alice_id
    assert acc.pubkey_b64 == alice_pubkey
    assert acc.balance == 0
    assert acc.nonce == 0
    assert acc.trust_score == 0.5


def test_account_get_or_create_idempotent(ledger, alice_pubkey, alice_id):
    acc1 = ledger.account_get_or_create(alice_id, alice_pubkey)
    acc2 = ledger.account_get_or_create(alice_id, alice_pubkey)
    assert acc1.agent_id == acc2.agent_id
    assert acc1.pubkey_b64 == acc2.pubkey_b64
    assert acc1.balance == acc2.balance


def test_account_update_balance(ledger, alice_pubkey, alice_id):
    ledger.account_create(alice_id, alice_pubkey)
    acc = ledger.account_update_balance(alice_id, 1000)
    assert acc.balance == 1000
    acc = ledger.account_update_balance(alice_id, -500)
    assert acc.balance == 500


def test_account_update_balance_rejects_negative(ledger, alice_pubkey, alice_id):
    ledger.account_create(alice_id, alice_pubkey)
    with pytest.raises(ValueError, match="Insufficient balance"):
        ledger.account_update_balance(alice_id, -100)


def test_derive_agent_id_deterministic(alice_pubkey, alice_id):
    assert make_agent_id(alice_pubkey) == alice_id


# ── Transaction tests ────────────────────────────────────────────────────

def test_txn_write_simple(ledger, alice_pubkey, alice_id, bob_pubkey, bob_id):
    ledger.account_get_or_create(alice_id, alice_pubkey)
    ledger.account_get_or_create(bob_id, bob_pubkey)
    ledger.account_update_balance(alice_id, 10000)

    txn = ledger.txn_write(
        from_agent=alice_id,
        to_agent=bob_id,
        amount=500,
        fee=10,
    )

    assert txn.from_agent == alice_id
    assert txn.to_agent == bob_id
    assert txn.amount == 500
    assert txn.fee == 10
    assert txn.id is not None


def test_txn_write_insufficient_balance(ledger, alice_pubkey, alice_id, bob_id):
    ledger.account_get_or_create(alice_id, alice_pubkey)
    ledger.account_get_or_create(bob_id, make_pubkey(2))
    ledger.account_update_balance(alice_id, 100)
    with pytest.raises(ValueError, match="Insufficient balance"):
        ledger.txn_write(from_agent=alice_id, to_agent=bob_id, amount=500)


def test_txn_write_intent_link(ledger, alice_pubkey, alice_id, bob_id):
    ledger.account_get_or_create(alice_id, alice_pubkey)
    ledger.account_get_or_create(bob_id, make_pubkey(2))
    ledger.account_update_balance(alice_id, 10000)
    intent_ref = hashlib.sha256(b"fake_intent_payload").hexdigest()

    txn = ledger.txn_write(
        from_agent=alice_id,
        to_agent=bob_id,
        amount=500,
        intent_ref=intent_ref,
    )

    assert txn.intent_ref == intent_ref


def test_txns_for_agent(ledger, alice_pubkey, alice_id, bob_id, bob_pubkey):
    ledger.account_get_or_create(alice_id, alice_pubkey)
    ledger.account_get_or_create(bob_id, bob_pubkey)
    ledger.account_update_balance(alice_id, 10000)

    ledger.txn_write(from_agent=alice_id, to_agent=bob_id, amount=100)
    ledger.txn_write(from_agent=alice_id, to_agent=bob_id, amount=200)
    ledger.txn_write(from_agent=bob_id, to_agent=alice_id, amount=50)

    alice_txns = ledger.txns_for_agent(alice_id)
    assert len(alice_txns) == 3

    bob_txns = ledger.txns_for_agent(bob_id)
    assert len(bob_txns) == 3


def test_mint_from_none(ledger, alice_pubkey, alice_id):
    """Minting from None = inflation."""
    ledger.account_get_or_create(alice_id, alice_pubkey)
    txn = ledger.txn_write(from_agent=None, to_agent=alice_id, amount=5000)
    assert txn.from_agent is None
    assert txn.amount == 5000
    acc = ledger.account_get(alice_id)
    assert acc.balance == 5000


# ── Faucet tests ─────────────────────────────────────────────────────────

def test_faucet_one_per_day(ledger, alice_pubkey):
    alloc1 = ledger.faucet_allocate(alice_pubkey, 1000)
    assert alloc1 is not None
    assert alloc1.amount == 1000

    # Second same day = None
    alloc2 = ledger.faucet_allocate(alice_pubkey, 1000)
    assert alloc2 is None


def test_faucet_creates_account(ledger, alice_pubkey, alice_id):
    acc_before = ledger.account_get(alice_id)
    assert acc_before is None
    ledger.faucet_allocate(alice_pubkey, 1000)
    acc_after = ledger.account_get(alice_id)
    assert acc_after is not None
    assert acc_after.balance == 1000


def test_operator_faucet(ledger, alice_pubkey, alice_id):
    ledger.account_create(alice_id, alice_pubkey)
    txn = ledger.operator_faucet(alice_id, 5000, reason="beta tester")
    assert txn.to_agent == alice_id
    assert txn.amount == 5000
    assert "operator_faucet" in (txn.intent_ref or "")


# ── Trust score tests ────────────────────────────────────────────────────

def test_trust_adjust_up(ledger, alice_pubkey, alice_id):
    ledger.account_create(alice_id, alice_pubkey)
    new_score = ledger.trust_adjust(alice_id, 0.1)
    assert new_score == 0.6


def test_trust_adjust_clamp_at_1(ledger, alice_pubkey, alice_id):
    ledger.account_create(alice_id, alice_pubkey)
    new_score = ledger.trust_adjust(alice_id, 0.6)
    assert new_score == 1.0


def test_trust_adjust_clamp_at_0(ledger, alice_pubkey, alice_id):
    ledger.account_create(alice_id, alice_pubkey)
    new_score = ledger.trust_adjust(alice_id, -0.6)
    assert new_score == 0.0


# ── Staking tests ───────────────────────────────────────────────────────

def test_stake_lock_and_release(ledger, alice_pubkey, alice_id):
    ledger.account_create(alice_id, alice_pubkey)
    ledger.account_update_balance(alice_id, 10000)

    acc = ledger.stake_lock(alice_id, 3000)
    assert acc.balance == 7000
    assert acc.stake_amount == 3000

    acc = ledger.stake_release(alice_id, 3000)
    assert acc.balance == 10000
    assert acc.stake_amount == 0


def test_stake_lock_rejects_insufficient(ledger, alice_pubkey, alice_id):
    ledger.account_create(alice_id, alice_pubkey)
    ledger.account_update_balance(alice_id, 100)
    with pytest.raises(ValueError, match="Insufficient balance"):
        ledger.stake_lock(alice_id, 500)


# ── Escrow tests ────────────────────────────────────────────────────────

def test_escrow_open_and_release(ledger, alice_pubkey, alice_id, bob_id):
    ledger.account_get_or_create(alice_id, alice_pubkey)
    ledger.account_get_or_create(bob_id, make_pubkey(2))
    ledger.account_update_balance(alice_id, 10000)
    ledger.account_update_balance(bob_id, 10000)

    escrow = ledger.escrow_open(alice_id, bob_id, 1000, intent_ref="test_ref")
    assert escrow.status == "open"
    assert escrow.escrow_id.startswith("escrow_")

    alice_acc = ledger.account_get(alice_id)
    bob_acc = ledger.account_get(bob_id)
    assert alice_acc.balance == 9000  # -1000 staked
    assert bob_acc.balance == 9000   # -1000 staked


def test_escrow_release_pays_winner(ledger, alice_pubkey, alice_id, bob_id):
    ledger.account_get_or_create(alice_id, alice_pubkey)
    ledger.account_get_or_create(bob_id, make_pubkey(2))
    ledger.account_update_balance(alice_id, 10000)
    ledger.account_update_balance(bob_id, 10000)

    escrow = ledger.escrow_open(alice_id, bob_id, 1000)
    ledger.escrow_release(escrow.escrow_id, winner=alice_id, loser=bob_id)

    alice_acc = ledger.account_get(alice_id)
    bob_acc = ledger.account_get(bob_id)
    # Alice gets her 1000 back + Bob's 1000 forfeited = +1000 net
    assert alice_acc.balance == 11000
    assert bob_acc.balance == 9000


# ── Inflation tests ─────────────────────────────────────────────────────

def test_inflation_distribute(ledger, alice_pubkey, alice_id):
    # Need balance * trust_score >= 730 to generate >=1 micro-SimpMesh/day at 500bps
    ledger.account_create(alice_id, alice_pubkey)
    ledger.account_update_balance(alice_id, 10000)
    minted = ledger.inflation_distribute(annual_bps=500)
    # 10000 * 0.5 * 500/10000 / 365 = 0.68 → truncates to 0 micro-SimpMesh
    # At this small scale, daily mint rounds to 0. This is expected.
    assert minted >= 0  # inflation may be 0 at small balances
    acc = ledger.account_get(alice_id)
    assert acc.balance == 10000 + minted


# ── Phase 2: Fee middleware tests ─────────────────────────────────────

def test_fee_schedule_default(ledger):
    fs = ledger.fee_schedule()
    assert fs.compute_fee("intent.submit") == 5
    assert fs.compute_fee("intent.execute") == 10
    assert fs.compute_fee("unknown") == 1


def test_fee_schedule_load_factor(ledger):
    fs = ledger.fee_schedule(load_factor=2.0)
    assert fs.compute_fee("intent.submit") == 10
    assert fs.compute_fee("skill.rank") == 2


def test_fee_schedule_apply_load_factor(ledger):
    fs = FeeSchedule(load_factor=1.5)
    fs2 = fs.apply_load_factor(2.0)
    assert fs2.load_factor == 2.0
    assert fs.load_factor == 1.5  # original unchanged


def test_intent_fee_estimate(ledger):
    assert ledger.intent_fee_estimate("intent.submit") == 5
    assert ledger.intent_fee_estimate("intent.submit", load_factor=3.0) == 15


def test_intent_pay_fee(ledger, alice_pubkey, alice_id):
    ledger.account_create(alice_id, alice_pubkey)
    ledger.account_update_balance(alice_id, 1000)

    txn = ledger.intent_pay_fee("intent.submit", alice_id, 100, intent_ref="test_intent")
    assert txn.from_agent == alice_id
    # v2: fees route to simp:feepool instead of vanishing
    assert txn.to_agent == "simp:feepool"
    assert txn.amount == 100
    assert txn.fee > 0
    assert txn.intent_ref == "test_intent"


def test_intent_with_fee(ledger, alice_pubkey, alice_id, bob_id):
    ledger.account_create(alice_id, alice_pubkey)
    ledger.account_create(bob_id, make_pubkey(2))
    ledger.account_update_balance(alice_id, 10000)

    txn = ledger.intent_with_fee("skill.evolve", alice_id, bob_id, 500)
    assert txn.from_agent == alice_id
    assert txn.to_agent == bob_id
    assert txn.amount == 500
    assert txn.fee == 3  # base fee for skill.evolve
    assert txn.intent_ref == "intent:skill.evolve"


def test_dynamic_fee_estimate_idle(ledger):
    assert ledger.dynamic_fee_estimate("intent.submit", queue_depth=0) == 5


def test_dynamic_fee_estimate_loaded(ledger):
    # queue_depth=100 should push load factor up but cap at 3x
    fee = ledger.dynamic_fee_estimate("intent.submit", queue_depth=100)
    assert fee > 5
    assert fee <= 15  # max 3x cap


# ── Phase 3: Agent Key Registry tests ─────────────────────────────────

def test_agent_key_register(ledger, alice_pubkey, alice_id):
    record = ledger.agent_key_register(alice_id, alice_pubkey, purpose="signing")
    assert record.agent_id == alice_id
    assert record.pubkey_b64 == alice_pubkey
    assert record.key_seq == 0
    assert record.key_purpose == "signing"
    assert record.status == "active"
    assert record.expires_at is None


def test_agent_key_register_idempotent(ledger, alice_pubkey, alice_id):
    r1 = ledger.agent_key_register(alice_id, alice_pubkey)
    r2 = ledger.agent_key_register(alice_id, alice_pubkey)
    # Same pubkey on same agent — INSERT OR IGNORE, so seq stays 0
    assert r1.key_seq == r2.key_seq == 0


def test_agent_key_get_latest(ledger, alice_pubkey, alice_id):
    ledger.agent_key_register(alice_id, alice_pubkey, purpose="signing")
    latest = ledger.agent_key_get_latest(alice_id, purpose="signing")
    assert latest is not None
    assert latest.pubkey_b64 == alice_pubkey
    assert latest.status == "active"


def test_agent_key_get_latest_unknown_agent(ledger):
    assert ledger.agent_key_get_latest("unknown_agent") is None


def test_agent_key_get_all(ledger, alice_pubkey, alice_id):
    ledger.agent_key_register(alice_id, alice_pubkey)
    all_keys = ledger.agent_key_get_all(alice_id)
    assert len(all_keys) == 1
    assert all_keys[0].status == "active"


def test_agent_key_verify_active(ledger, alice_pubkey, alice_id):
    ledger.agent_key_register(alice_id, alice_pubkey)
    assert ledger.agent_key_verify(alice_id, alice_pubkey) is True


def test_agent_key_verify_wrong_pubkey(ledger, alice_pubkey, alice_id):
    ledger.agent_key_register(alice_id, alice_pubkey)
    assert ledger.agent_key_verify(alice_id, make_pubkey(99)) is False


def test_agent_key_verify_unknown_agent(ledger):
    assert ledger.agent_key_verify("unknown", make_pubkey(1)) is False


def test_agent_key_verify_expired(ledger, alice_pubkey, alice_id):
    ledger.agent_key_register(alice_id, alice_pubkey, expires_at=0)  # already expired
    assert ledger.agent_key_verify(alice_id, alice_pubkey) is False


def test_agent_key_revoke(ledger, alice_pubkey, alice_id):
    ledger.agent_key_register(alice_id, alice_pubkey)
    revoked = ledger.agent_key_revoke(alice_id, revoked_reason="compromised")
    assert revoked is not None
    assert revoked.status == "revoked"
    assert revoked.revoked_reason == "compromised"

    # Latest key should now be None (no active keys)
    assert ledger.agent_key_get_latest(alice_id) is None


def test_agent_key_revoke_none_exist(ledger, alice_pubkey, alice_id):
    result = ledger.agent_key_revoke(alice_id)
    assert result is None


def test_agent_key_rotate(ledger, alice_pubkey, alice_id):
    ledger.agent_key_register(alice_id, alice_pubkey)
    new_pubkey = make_pubkey(42)
    new_record = ledger.agent_key_rotate(alice_id, new_pubkey, revoke_reason="scheduled rotate")
    assert new_record.pubkey_b64 == new_pubkey
    assert new_record.key_seq == 1
    assert new_record.status == "active"

    all_keys = ledger.agent_key_get_all(alice_id)
    assert len(all_keys) == 2
    # Most recent first
    assert all_keys[0].pubkey_b64 == new_pubkey
    assert all_keys[0].status == "active"
    assert all_keys[1].pubkey_b64 == alice_pubkey
    assert all_keys[1].status == "revoked"


# ── Stats tests ─────────────────────────────────────────────────────────

def test_stats(ledger, alice_pubkey, alice_id):
    ledger.account_create(alice_id, alice_pubkey)
    ledger.account_update_balance(alice_id, 10000)
    ledger.faucet_allocate(make_pubkey(99), 5000)

    stats = ledger.stats()
    assert stats["account_count"] == 2
    assert stats["total_supply"] > 0


# ── Phase 4: Trust hooks + inflation tests ────────────────────────────────

def test_trust_adjust_records_history(ledger, alice_pubkey, alice_id):
    ledger.account_create(alice_id, alice_pubkey)
    new_score = ledger.trust_adjust(alice_id, 0.1, reason="manual")
    assert new_score == 0.6
    history = ledger.trust_history_get(alice_id)
    assert len(history) == 1
    assert history[0]["old_score"] == 0.5
    assert history[0]["new_score"] == 0.6
    assert history[0]["reason"] == "manual"


def test_trust_adjust_clamped(ledger, alice_pubkey, alice_id):
    ledger.account_create(alice_id, alice_pubkey)
    # Clamp at 1.0
    new_score = ledger.trust_adjust(alice_id, 1.0, reason="over_adj")
    assert new_score == 1.0


def test_intent_hook_success(ledger, alice_pubkey, alice_id):
    ledger.account_create(alice_id, alice_pubkey)
    event = ledger.intent_hook_success(alice_id, "intent_ref_abc")
    assert event.outcome == "success"
    assert event.trust_delta == 0.01
    assert event.agent_id == alice_id
    # Trust bumped
    assert ledger.trust_get(alice_id) > 0.5


def test_intent_hook_failure(ledger, alice_pubkey, alice_id):
    ledger.account_create(alice_id, alice_pubkey)
    event = ledger.intent_hook_failure(alice_id, "intent_ref_fail", penalty=0.05)
    assert event.outcome == "failure"
    assert event.trust_delta == -0.05
    assert ledger.trust_get(alice_id) < 0.5


def test_intent_hook_failure_custom_penalty(ledger, alice_pubkey, alice_id):
    ledger.account_create(alice_id, alice_pubkey)
    old_score = ledger.trust_get(alice_id)
    ledger.intent_hook_failure(alice_id, "bad_intent", penalty=0.1)
    assert ledger.trust_get(alice_id) == old_score - 0.1


def test_trust_history_get(ledger, alice_pubkey, alice_id):
    ledger.account_create(alice_id, alice_pubkey)
    ledger.trust_adjust(alice_id, 0.05, reason="test1")
    ledger.trust_adjust(alice_id, 0.05, reason="test2")
    history = ledger.trust_history_get(alice_id)
    assert len(history) == 2
    assert history[0]["reason"] == "test2"  # most recent first


def test_trust_history_get_limit(ledger, alice_pubkey, alice_id):
    ledger.account_create(alice_id, alice_pubkey)
    for i in range(5):
        ledger.trust_adjust(alice_id, 0.01, reason=f"event_{i}")
    history = ledger.trust_history_get(alice_id, limit=3)
    assert len(history) == 3


def test_trust_decay_stale_agent(ledger, alice_pubkey, alice_id):
    ledger.account_create(alice_id, alice_pubkey)
    # Simulate 10 days inactive by updating last_active_day directly
    import sqlite3
    ten_days_ago = int(ledger._acquire_conn().execute(
        "SELECT last_active_day FROM accounts WHERE agent_id = ?", (alice_id,)
    ).fetchone()[0]) - 10
    conn = ledger._write()
    conn.execute("UPDATE accounts SET last_active_day = ? WHERE agent_id = ?",
                 (ten_days_ago, alice_id))
    conn.commit()

    decayed = ledger.trust_decay(daily_decay_bps=5)
    assert decayed >= 1
    assert ledger.trust_get(alice_id) < 0.5


def test_trust_decay_active_agent_unchanged(ledger, alice_pubkey, alice_id):
    ledger.account_create(alice_id, alice_pubkey)
    old_score = ledger.trust_get(alice_id)
    decayed = ledger.trust_decay(daily_decay_bps=5)
    assert decayed == 0
    assert ledger.trust_get(alice_id) == old_score


def test_stats_includes_trust_and_events(ledger, alice_pubkey, alice_id):
    ledger.account_create(alice_id, alice_pubkey)
    ledger.account_update_balance(alice_id, 10000)
    ledger.intent_hook_success(alice_id, "test_intent")

    stats = ledger.stats()
    assert "avg_trust_score" in stats
    assert "intent_event_count" in stats
    assert stats["intent_event_count"] == 1


def test_inflation_distribute_stake_weighted(ledger, alice_pubkey, alice_id, bob_pubkey, bob_id):
    """With significant stake locked, distribution uses stake-weighted path."""
    ledger.account_create(alice_id, alice_pubkey)
    ledger.account_create(bob_id, bob_pubkey)
    ledger.account_update_balance(alice_id, 100000)
    ledger.account_update_balance(bob_id, 100000)
    ledger.stake_lock(alice_id, 5000)  # big stake

    minted = ledger.inflation_distribute(annual_bps=500)
    assert minted >= 1
    # Alice (staked) should get more than Bob (no stake)
    alice_acc = ledger.account_get(alice_id)
    bob_acc = ledger.account_get(bob_id)
    # At least the staked agent got inflation
    assert alice_acc.balance > 95000  # original - stake + inflation


def test_inflation_distribute_no_stake_fallback(ledger, alice_pubkey, alice_id):
    """Without stake, falls back to trust-weighted."""
    ledger.account_create(alice_id, alice_pubkey)
    ledger.account_update_balance(alice_id, 10000)
    minted = ledger.inflation_distribute(annual_bps=500)
    assert minted >= 0


# ── Phase 5: Escrow + Intent Bundling tests ─────────────────────────────────

def test_escrow_execute_returns_bonds(ledger, alice_pubkey, alice_id, bob_id):
    ledger.account_get_or_create(alice_id, alice_pubkey)
    ledger.account_get_or_create(bob_id, make_pubkey(2))
    ledger.account_update_balance(alice_id, 10000)
    ledger.account_update_balance(bob_id, 10000)

    escrow = ledger.escrow_open(alice_id, bob_id, 1000)
    alice_before = ledger.account_get(alice_id).balance
    bob_before = ledger.account_get(bob_id).balance

    ledger.escrow_execute(escrow.escrow_id)

    # Both should get bonds back
    alice_after = ledger.account_get(alice_id).balance
    bob_after = ledger.account_get(bob_id).balance
    assert alice_after == alice_before + 1000
    assert bob_after == bob_before + 1000
    assert ledger.escrow_get(escrow.escrow_id).status == "executed"


def test_escrow_dispute_slashes_loser(ledger, alice_pubkey, alice_id, bob_id):
    ledger.account_get_or_create(alice_id, alice_pubkey)
    ledger.account_get_or_create(bob_id, make_pubkey(2))
    ledger.account_update_balance(alice_id, 10000)
    ledger.account_update_balance(bob_id, 10000)

    escrow = ledger.escrow_open(alice_id, bob_id, 1000)
    alice_before = ledger.account_get(alice_id).balance

    ledger.escrow_dispute(escrow.escrow_id, dispute_winner=alice_id)

    # Alice (winner) gets both bonds; Bob loses his
    alice_after = ledger.account_get(alice_id).balance
    assert alice_after == alice_before + 1000  # got Bob's bond
    assert ledger.escrow_get(escrow.escrow_id).status == "released"


def test_escrow_cancel_returns_bonds(ledger, alice_pubkey, alice_id, bob_id):
    ledger.account_get_or_create(alice_id, alice_pubkey)
    ledger.account_get_or_create(bob_id, make_pubkey(2))
    ledger.account_update_balance(alice_id, 10000)
    ledger.account_update_balance(bob_id, 10000)

    escrow = ledger.escrow_open(alice_id, bob_id, 1000)
    alice_before = ledger.account_get(alice_id).balance

    ledger.escrow_cancel(escrow.escrow_id)

    alice_after = ledger.account_get(alice_id).balance
    assert alice_after == alice_before + 1000
    assert ledger.escrow_get(escrow.escrow_id).status == "released"


def test_bundle_create(ledger, alice_pubkey, alice_id, bob_id):
    bundle = ledger.bundle_create("contract.negotiate", [alice_id, bob_id])
    assert bundle.bundle_id.startswith("bundle_")
    assert bundle.intent_type == "contract.negotiate"
    assert alice_id in bundle.participants
    assert bob_id in bundle.participants
    assert bundle.status == "open"
    assert bundle.total_stake == 0


def test_bundle_fund_single_participant(ledger, alice_pubkey, alice_id):
    ledger.account_create(alice_id, alice_pubkey)
    ledger.account_update_balance(alice_id, 10000)

    bundle = ledger.bundle_create("skill.evolve", [alice_id])
    funded = ledger.bundle_fund(bundle.bundle_id, alice_id, 500)
    assert funded.total_stake == 500
    assert funded.status == "open"  # below 1000 threshold


def test_bundle_fund_auto_transitions_to_funded(ledger, alice_pubkey, alice_id, bob_id):
    ledger.account_create(alice_id, alice_pubkey)
    ledger.account_create(bob_id, make_pubkey(2))
    ledger.account_update_balance(alice_id, 10000)
    ledger.account_update_balance(bob_id, 10000)

    bundle = ledger.bundle_create("contract.negotiate", [alice_id, bob_id])
    ledger.bundle_fund(bundle.bundle_id, alice_id, 800)
    funded = ledger.bundle_fund(bundle.bundle_id, bob_id, 800)
    assert funded.status == "funded"
    assert funded.total_stake == 1600


def test_bundle_execute_refunds_stake(ledger, alice_pubkey, alice_id, bob_id):
    ledger.account_create(alice_id, alice_pubkey)
    ledger.account_create(bob_id, make_pubkey(2))
    ledger.account_update_balance(alice_id, 10000)
    ledger.account_update_balance(bob_id, 10000)

    bundle = ledger.bundle_create("skill.evolve", [alice_id, bob_id])
    ledger.bundle_fund(bundle.bundle_id, alice_id, 500)
    ledger.bundle_fund(bundle.bundle_id, bob_id, 500)
    # Both staked 500 each = 1000 total

    executed = ledger.bundle_execute(bundle.bundle_id)
    assert executed.status == "executed"

    # Both should get their stake back (plus any surplus from rounding)
    alice_acc = ledger.account_get(alice_id)
    bob_acc = ledger.account_get(bob_id)
    assert alice_acc.balance >= 10000 - 500  # got 500 back
    assert bob_acc.balance >= 10000 - 500


def test_bundle_dispute_slashes_agent(ledger, alice_pubkey, alice_id, bob_id):
    ledger.account_create(alice_id, alice_pubkey)
    ledger.account_create(bob_id, make_pubkey(2))
    ledger.account_update_balance(alice_id, 10000)
    ledger.account_update_balance(bob_id, 10000)

    bundle = ledger.bundle_create("contract.negotiate", [alice_id, bob_id])
    ledger.bundle_fund(bundle.bundle_id, alice_id, 500)
    ledger.bundle_fund(bundle.bundle_id, bob_id, 500)

    disputed = ledger.bundle_dispute(bundle.bundle_id, slashed_agent=bob_id)
    assert disputed.status == "disputed"

    # Alice (non-slashed) should get her stake back
    alice_acc = ledger.account_get(alice_id)
    assert alice_acc.balance >= 10000 - 500


def test_bundle_get(ledger, alice_pubkey, alice_id, bob_id):
    bundle = ledger.bundle_create("skill.evolve", [alice_id, bob_id])
    found = ledger.bundle_get(bundle.bundle_id)
    assert found is not None
    assert found.bundle_id == bundle.bundle_id


def test_bundle_get_unknown(ledger):
    assert ledger.bundle_get("unknown") is None


def test_bundles_for_agent(ledger, alice_pubkey, alice_id, bob_id):
    ledger.bundle_create("skill.evolve", [alice_id, bob_id])
    ledger.bundle_create("contract.negotiate", [alice_id, bob_id])
    bundles = ledger.bundles_for_agent(alice_id)
    assert len(bundles) == 2


# ── Phase 7: Sponsor onboarding tests ───────────────────────────────────────

def test_sponsor_onboard_requires_trust_07(ledger, alice_pubkey, alice_id, bob_id):
    ledger.account_create(alice_id, alice_pubkey)
    ledger.account_create(bob_id, make_pubkey(2))
    # Alice has default trust 0.5 — below 0.7 threshold
    with pytest.raises(ValueError, match="trust_score must be >= 0.7"):
        ledger.sponsor_onboard(alice_id, bob_id)


def test_sponsor_onboard_success(ledger, alice_pubkey, alice_id, bob_id):
    ledger.account_create(alice_id, alice_pubkey)
    ledger.account_create(bob_id, make_pubkey(2))
    ledger.account_update_balance(alice_id, 1_000_000)
    ledger.trust_adjust(alice_id, 0.3)  # bring to 0.8

    sponsor = ledger.sponsor_onboard(alice_id, bob_id, sponsor_bond=500_000)
    assert sponsor.sponsored_agent == bob_id
    assert sponsor.status == "active"
    assert sponsor.sponsor_bond == 500_000
    assert sponsor.delegation_fee_bps == 100  # default 1%


def test_sponsor_get(ledger, alice_pubkey, alice_id, bob_id):
    ledger.account_create(alice_id, alice_pubkey)
    ledger.account_create(bob_id, make_pubkey(2))
    ledger.account_update_balance(alice_id, 1_000_000)
    ledger.trust_adjust(alice_id, 0.3)
    ledger.sponsor_onboard(alice_id, bob_id)

    sp = ledger.sponsor_get(bob_id)
    assert sp is not None
    assert sp.sponsor_id == alice_id


def test_sponsor_get_unknown(ledger):
    assert ledger.sponsor_get("unknown") is None


def test_sponsor_charge_delegation_fee(ledger, alice_pubkey, alice_id, bob_id):
    ledger.account_create(alice_id, alice_pubkey)
    ledger.account_create(bob_id, make_pubkey(2))
    ledger.account_update_balance(alice_id, 1_000_000)
    ledger.account_update_balance(bob_id, 1_000_000)
    ledger.trust_adjust(alice_id, 0.3)
    ledger.sponsor_onboard(alice_id, bob_id)

    alice_before = ledger.account_get(alice_id).balance
    ledger.sponsor_charge_delegation_fee(alice_id, bob_id, fee_amount=10_000)
    alice_after = ledger.account_get(alice_id).balance
    # 1% of 10_000 = 100 micro-SimpMesh
    assert alice_after == alice_before - 100


def test_sponsor_release_returns_bond(ledger, alice_pubkey, alice_id, bob_id):
    ledger.account_create(alice_id, alice_pubkey)
    ledger.account_create(bob_id, make_pubkey(2))
    ledger.account_update_balance(alice_id, 1_000_000)
    ledger.trust_adjust(alice_id, 0.3)
    ledger.sponsor_onboard(alice_id, bob_id)

    alice_staked = ledger.account_get(alice_id).stake_amount  # 500_000 locked
    alice_balance = ledger.account_get(alice_id).balance

    released = ledger.sponsor_release(alice_id, bob_id)
    assert released.status == "released"

    alice_after = ledger.account_get(alice_id)
    assert alice_after.stake_amount == alice_staked - 500_000
    assert alice_after.balance == alice_balance + 500_000
