import sqlite3, os

DB_PATH = "data/simp_token.db"
os.makedirs("data", exist_ok=True)

# Create clean database
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=NORMAL")

# Schema
conn.execute("""
    CREATE TABLE accounts (
        agent_id TEXT PRIMARY KEY,
        balance INTEGER NOT NULL DEFAULT 0,
        role TEXT NOT NULL DEFAULT "agent",
        created_at INTEGER NOT NULL DEFAULT (unixepoch()),
        last_active INTEGER
    )
""")
conn.execute("""
    CREATE TABLE transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tx_type TEXT NOT NULL,
        from_id TEXT,
        to_id TEXT NOT NULL,
        amount INTEGER NOT NULL,
        fee INTEGER NOT NULL DEFAULT 0,
        intent_id TEXT,
        timestamp INTEGER NOT NULL DEFAULT (unixepoch())
    )
""")
conn.execute("""
    CREATE TABLE supply_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        total_supply INTEGER NOT NULL,
        circulating INTEGER NOT NULL DEFAULT 0,
        total_burned INTEGER NOT NULL DEFAULT 0,
        treasury INTEGER NOT NULL DEFAULT 0,
        fee_pool INTEGER NOT NULL DEFAULT 0,
        timestamp INTEGER NOT NULL DEFAULT (unixepoch())
    )
""")

# System accounts
system_accts = [("treasury", 0, "treasury"), ("feepool", 0, "feepool"), ("burnvault", 0, "burnvault")]
for aid, bal, role in system_accts:
    conn.execute("INSERT INTO accounts (agent_id, balance, role) VALUES (?, ?, ?)", (aid, bal, role))

# Agent accounts
active_agents = [
    "kashclaw", "quantumarb", "bullbear_predictor", "kloutbot",
    "projectx_native", "perplexity_research", "gemma4_local",
    "financial_ops", "claude_cowork", "brp_guardian",
    "arb_detector_v2", "signal_aggregator", "mcp_router",
    "token_oracle", "mesh_monitor", "intent_scheduler",
    "risk_analyzer", "fee_collector"
]
for agent in active_agents:
    conn.execute("INSERT INTO accounts (agent_id, role) VALUES (?, ?)", (agent, agent))

# Initial supply: 1B total, 1K circulating (liquidity), rest treasury
conn.execute("""
    INSERT INTO supply_snapshots (total_supply, circulating, total_burned, treasury, fee_pool)
    VALUES (?, ?, ?, ?, ?)
""", (1_000_000_000_000_000, 1_000_000_000_000, 0, 999_999_000_000_000, 0))

conn.execute("UPDATE accounts SET balance = 999999000000000 WHERE agent_id = ?", ("treasury",))
conn.commit()

acct_count = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
snap = conn.execute("SELECT * FROM supply_snapshots ORDER BY id DESC LIMIT 1").fetchone()

print("LEDGER CREATED")
print(f"  Accounts: {acct_count}")
print(f"  Total supply: {snap[1]:,}")
print(f"  Treasury:     {snap[4]:,}")
print(f"  DB: {DB_PATH} ({os.path.getsize(DB_PATH):,} bytes)")

# ── INJECT REVENUE: 100 SIMPT from quantumarb ──
amount = 100 * 10**6  # 100 SIMPT in micro-units
fee_portion = int(amount * 0.30)
treasury_portion = int(amount * 0.70)

conn.execute("UPDATE accounts SET balance = balance + ? WHERE agent_id = ?", (fee_portion, "feepool"))
conn.execute("UPDATE accounts SET balance = balance + ? WHERE agent_id = ?", (treasury_portion, "treasury"))
conn.execute("INSERT INTO transactions (tx_type, from_id, to_id, amount, intent_id) VALUES (?, ?, ?, ?, ?)",
             ("revenue:quantumarb", "external", "feepool", fee_portion, "arb_rev_100"))
conn.execute("INSERT INTO transactions (tx_type, from_id, to_id, amount, intent_id) VALUES (?, ?, ?, ?, ?)",
             ("revenue:quantumarb", "external", "treasury", treasury_portion, "arb_rev_100"))
conn.commit()

feepool_bal = conn.execute("SELECT balance FROM accounts WHERE agent_id = ?", ("feepool",)).fetchone()[0]
treasury_bal = conn.execute("SELECT balance FROM accounts WHERE agent_id = ?", ("treasury",)).fetchone()[0]

print("\nREVENUE INJECTED: 100 SIMPT")
print(f"  Fee pool (30%): {fee_portion:,} micro-SIMP ({fee_portion/10**6:.4f} SIMPT)")
print(f"  Treasury (70%): {treasury_portion:,} micro-SIMP ({treasury_portion/10**6:.4f} SIMPT)")

# ── FLUSH FEE POOL → BURN VAULT ──
burn_amount = feepool_bal
conn.execute("UPDATE accounts SET balance = 0 WHERE agent_id = ?", ("feepool",))
conn.execute("UPDATE accounts SET balance = balance + ? WHERE agent_id = ?", (burn_amount, "burnvault"))
conn.execute("INSERT INTO transactions (tx_type, from_id, to_id, amount) VALUES (?, ?, ?, ?)",
             ("burn", "feepool", "burnvault", burn_amount))
conn.execute("""
    INSERT INTO supply_snapshots (total_supply, circulating, total_burned, treasury, fee_pool)
    VALUES (?, ?,
        (SELECT COALESCE(SUM(balance), 0) FROM accounts WHERE agent_id = "burnvault"),
        (SELECT balance FROM accounts WHERE agent_id = "treasury"),
        (SELECT balance FROM accounts WHERE agent_id = "feepool"))
""", (1_000_000_000_000_000, 1_000_000_000_000))
conn.commit()

burn_bal = conn.execute("SELECT balance FROM accounts WHERE agent_id = ?", ("burnvault",)).fetchone()[0]
snap = conn.execute("SELECT * FROM supply_snapshots ORDER BY id DESC LIMIT 1").fetchone()

print(f"\nBURN: {burn_amount:,} micro-SIMP ({burn_amount/10**6:.4f} SIMPT)")
print(f"  Burn vault: {burn_bal:,} micro-SIMP ({burn_bal/10**6:.4f} SIMPT)")
print(f"  Total burned all-time: {snap[3]:,}")

# ── DISTRIBUTE TREASURY TO AGENTS ──
dist_amount = int(treasury_portion * 0.50)
rows = conn.execute("SELECT agent_id FROM accounts WHERE role NOT IN ('treasury','feepool','burnvault')").fetchall()
agents = [r[0] for r in rows]
num_agents = len(agents)
share = dist_amount // num_agents
remainder = dist_amount - (share * num_agents)

for aid in agents:
    conn.execute("UPDATE accounts SET balance = balance + ? WHERE agent_id = ?", (share, aid))
    conn.execute("INSERT INTO transactions (tx_type, from_id, to_id, amount) VALUES (?, ?, ?, ?)",
                 ("distribution", "treasury", aid, share))

if remainder > 0:
    conn.execute("UPDATE accounts SET balance = balance + ? WHERE agent_id = ?", (remainder, agents[0]))

conn.execute("UPDATE accounts SET balance = balance - ? WHERE agent_id = ?", (dist_amount, "treasury"))
conn.commit()

# Final state
final_treasury = conn.execute("SELECT balance FROM accounts WHERE agent_id = ?", ("treasury",)).fetchone()[0]
final_feepool = conn.execute("SELECT balance FROM accounts WHERE agent_id = ?", ("feepool",)).fetchone()[0]
final_burn = conn.execute("SELECT balance FROM accounts WHERE agent_id = ?", ("burnvault",)).fetchone()[0]

print(f"\nDISTRIBUTED: {dist_amount:,} micro-SIMP ({dist_amount/10**6:.4f} SIMPT) to {num_agents} agents")
print(f"  Per agent: {share:,} micro-SIMP ({share/10**6:.6f} SIMPT)")
print(f"\n═══ FINAL STATE ═══")
print(f"Treasury:  {final_treasury:,} micro-SIMP ({final_treasury/10**6:,.4f} SIMPT)")
print(f"Fee pool:  {final_feepool:,}")
print(f"Burn vault: {final_burn:,} micro-SIMP ({final_burn/10**6:,.6f} SIMPT)")

# Verify on Solana
import urllib.request, json
req = urllib.request.Request(
    "https://api.mainnet-beta.solana.com",
    data=json.dumps({"jsonrpc":"2.0","id":1,"method":"getTokenSupply","params":["6QxRa9aeCidptKS8CS2uenbQiy5enHR7eMMY29mghZNW"]}).encode(),
    headers={"Content-Type": "application/json"}
)
resp = json.loads(urllib.request.urlopen(req, timeout=5).read())
onchain = resp["result"]["value"]
print(f"\n═══ ON-CHAIN VERIFICATION ═══")
print(f"Total supply: {int(onchain['amount']):,} ({float(onchain['uiAmountString']):,.0f} SIMPT)")
print(f"Decimals: {onchain['decimals']}")

conn.close()
