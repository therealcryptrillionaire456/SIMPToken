-- SIMP Token Schema v2 — Fee tracking + burn mechanism
-- Extends the v1 schema with fee_sink, burn vault, and emission tracking

-- System accounts (created by Ledger.__init__)
-- 'simp:feepool'   — collects all protocol fees
-- 'simp:burnvault' — final resting place for burned tokens (irreversible)
-- 'simp:treasury'  — revenue injection, delegation rewards, build rewards

ALTER TABLE accounts ADD COLUMN last_burn_epoch INTEGER NOT NULL DEFAULT 0;

-- Track burn events for transparency / audit
CREATE TABLE IF NOT EXISTS burn_events (
    id          TEXT PRIMARY KEY,
    from_account TEXT NOT NULL,       -- 'simp:feepool' or direct
    amount      INTEGER NOT NULL,     -- in micro-SIMP
    reason      TEXT NOT NULL,        -- 'protocol_fee', 'manual_burn', 'delegation_penalty'
    tx_ref      TEXT,                 -- reference transaction that triggered burn
    created_at  INTEGER NOT NULL,
    FOREIGN KEY (tx_ref) REFERENCES transactions(id)
);

CREATE INDEX IF NOT EXISTS idx_burn_events_created ON burn_events(created_at);

-- Track emission (minting) events — only for operator faucet / initial supply
CREATE TABLE IF NOT EXISTS emission_events (
    id          TEXT PRIMARY KEY,
    to_account  TEXT NOT NULL,
    amount      INTEGER NOT NULL,
    reason      TEXT NOT NULL DEFAULT 'initial_supply',
    source      TEXT NOT NULL DEFAULT 'genesis',
    created_at  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_emission_events_created ON emission_events(created_at);

-- Supply snapshot (for off-chain verification)
CREATE TABLE IF NOT EXISTS supply_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    total_supply    INTEGER NOT NULL,
    burned          INTEGER NOT NULL,
    fee_pool        INTEGER NOT NULL,
    treasury        INTEGER NOT NULL,
    circulating     INTEGER NOT NULL,
    timestamp       INTEGER NOT NULL
);

-- View: current supply metrics
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
    total_balances AS total_balances,
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
