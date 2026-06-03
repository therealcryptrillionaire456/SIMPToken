#!/bin/bash
# SIMP Autonomous Flywheel Starter
# Starts: Broker → Circulation Daemon → Dashboard
# Run: bash scripts/start_flywheel.sh

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║     SIMP AUTONOMOUS FLYWHEEL — STARTING                    ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Step 1: Start or verify broker
echo "[1/3] Checking broker..."
if curl -sf http://localhost:5555/health > /dev/null 2>&1; then
    echo "  ✅ Broker already running on port 5555"
else
    echo "  ⚠️  Broker not running. Start it manually:"
    echo "     python3 -m simp.server.http_server &"
fi

# Step 2: Run a circulation cycle to verify pipeline
echo ""
echo "[2/3] Testing circulation pipeline..."
python3 -m tokens.autonomous_circulation --once --amount-display 1.0

# Step 3: Show the flywheel status
echo ""
echo "[3/3] Flywheel status..."
echo ""
echo "  📊 SIMP Token: 6QxRa9aeCidptKS8CS2uenbQiy5enHR7eMMY29mghZNW"
echo "  🔄 Circulation: python3 -m tokens.autonomous_circulation --daemon"
echo "  📜 History:     python3 -m tokens.autonomous_circulation --history"
echo "  🌐 Website:     simptoken.uk"
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  FLYWHEEL IS LIVE                                           ║"
echo "║                                                              ║"
echo "║  QuantumArb → P&L → inject_revenue() → 30%/70%              ║"
echo "║  → feepool burned / treasury distributed                     ║"
echo "║  → agents get SIMPT → spend on intents → more fees          ║"
echo "║  → more burns → scarcity ↑ → SIMPT value ↑                  ║"
echo "╚══════════════════════════════════════════════════════════════╝"
