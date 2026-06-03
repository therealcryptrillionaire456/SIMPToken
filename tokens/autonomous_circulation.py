"""
SIMP Autonomous Token Circulation Pipeline
============================================
Connects QuantumArb trading profits → SIMPT token economy → autonomous flywheel.

The Pipeline:
  QuantumArb trades → profits detected → inject_revenue() splits 30/70 →
  30% to feepool (→ burned) / 70% to treasury (→ distributed to agents) →
  agents get SIMPT → agents pay intent fees → feepool burns →
  scarcity ↑ → SIMPT value ↑ → QuantumArb trades more

Run modes:
  python -m tokens.autonomous_circulation        # Single cycle
  python -m tokens.autonomous_circulation --daemon  # Every 60s
  python -m tokens.autonomous_circulation --once --amount 1000000  # Test with 1 SIMPT
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("SIMP.AutonomousCirculation")

# Add parent to path for standalone execution
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))

from tokens.economy_bridge import MODULE_BRIDGE, TokenEconomyBridge
from tokens.unified import UNIFIED_ENGINE

# ── Configuration ──────────────────────────────────────────────────────────

# Path where QuantumArb writes P&L data
QUANTUMARB_PNL_PATH = Path(os.environ.get(
    "SIMP_QUANTUMARB_PNL",
    "data/quantumarb_pnl.jsonl"
))

# Path to write circulation events for the dashboard
CIRCULATION_LOG_PATH = Path("data/circulation_events.jsonl")

# Default cycle interval (seconds)
DEFAULT_INTERVAL = 60  # 1 minute

# Minimum profit to trigger a cycle (in micro-SIMP, 0.01 SIMPT minimum)
MIN_PROFIT_THRESHOLD = 10_000  # 0.01 SIMPT

# How much of treasury to distribute each cycle (50% = half)
DISTRIBUTION_RATIO = 0.5

# ── P&L Reader ────────────────────────────────────────────────────────────


def read_quantumarb_pnl() -> int:
    """Read accumulated profits from QuantumArb's P&L ledger.

    Returns total profit in micro-SIMP units since last read.
    Creates a checkpoint file to track what's already been consumed.
    """
    checkpoint_path = Path("data/.pnl_checkpoint")

    if not QUANTUMARB_PNL_PATH.exists():
        logger.debug("No P&L file at %s", QUANTUMARB_PNL_PATH)
        return 0

    # Read last processed position
    last_position = 0
    if checkpoint_path.exists():
        try:
            last_position = int(checkpoint_path.read_text().strip())
        except (ValueError, OSError):
            last_position = 0

    # Read all new entries since last checkpoint
    total_profit = 0
    new_position = last_position
    lines_read = 0

    try:
        with open(QUANTUMARB_PNL_PATH, "r") as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                if i < last_position:
                    continue
                try:
                    entry = json.loads(line)
                    # Look for profit fields
                    profit = entry.get("profit", entry.get("pnl", entry.get("net_profit", 0)))
                    if isinstance(profit, (int, float)) and profit > 0:
                        total_profit += int(profit * 1_000_000)  # Convert to micro-SIMP
                    lines_read += 1
                except (json.JSONDecodeError, TypeError):
                    continue
                new_position = i + 1
    except OSError as e:
        logger.warning("Cannot read P&L file: %s", e)
        return 0

    # Save checkpoint
    if lines_read > 0:
        try:
            checkpoint_path.write_text(str(new_position))
        except OSError:
            pass

    if total_profit > 0:
        logger.info("P&L reader: %d new entries, %.4f SIMPT profit detected",
                     lines_read, total_profit / 1_000_000)

    return total_profit


def simulate_profit() -> int:
    """Generate a simulated profit for testing/demo mode.

    Returns a random profit between 0.001 and 0.5 SIMPT.
    Used when the real QuantumArb isn't running.
    """
    import random
    # Random profit: 0 to 0.25 SIMPT, occasionally bigger
    if random.random() < 0.3:  # 30% chance of profit this cycle
        return random.randint(1_000, 250_000)  # 0.001 to 0.25 SIMPT
    return 0


# ── Circulation Cycle ────────────────────────────────────────────────────


def run_circulation_cycle(
    bridge: Optional[TokenEconomyBridge] = None,
    force_amount: Optional[int] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Execute one full circulation cycle.

    1. Read QuantumArb P&L
    2. Inject revenue (30% feepool → burn, 70% treasury → distribute)
    3. Flush fee pool to burn vault
    4. Distribute treasury to active agents

    Returns a report dict with all actions taken.
    """
    bridge = bridge or MODULE_BRIDGE
    report = {
        "cycle_id": uuid.uuid4().hex[:12],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "steps": [],
        "total_injected": 0,
        "total_burned": 0,
        "total_distributed": 0,
        "dry_run": dry_run,
    }

    # Step 1: Read profit
    if force_amount is not None:
        profit = force_amount
        source = "manual_test"
    else:
        profit = read_quantumarb_pnl()
        source = "quantumarb"

        # Fallback to simulation if no real data
        if profit < MIN_PROFIT_THRESHOLD:
            sim = simulate_profit()
            if sim > 0:
                profit = sim
                source = "simulated_quantumarb"
                logger.info("Using simulated profit: %d micro-SIMP", profit)

    if profit < MIN_PROFIT_THRESHOLD:
        report["status"] = "skipped"
        report["reason"] = f"Profit ({profit}) below threshold ({MIN_PROFIT_THRESHOLD})"
        logger.info("Cycle skipped — profit %d below threshold %d", profit, MIN_PROFIT_THRESHOLD)
        return report

    report["total_injected"] = profit
    report["source"] = source

    # Step 2: Inject revenue
    if not dry_run:
        try:
            success = bridge.inject_revenue(profit, source=source)
            if not success:
                report["status"] = "error"
                report["reason"] = "inject_revenue failed"
                logger.error("Revenue injection failed")
                return report
        except Exception as e:
            report["status"] = "error"
            report["reason"] = str(e)
            logger.error("Revenue injection exception: %s", e)
            return report

    report["steps"].append({
        "step": "inject_revenue",
        "amount": profit,
        "source": source,
        "to_feepool_30pct": int(profit * 0.30),
        "to_treasury_70pct": int(profit * 0.70),
    })
    logger.info("Injected %d micro-SIMP from %s (30%%→burn, 70%%→treasury)",
                profit, source)

    if dry_run:
        report["status"] = "dry_run_complete"
        return report

    # Step 3: Flush fee pool to burn vault
    try:
        flush_result = bridge.engine.flush_fees()
        burned = flush_result.get("burned", 0)
        report["total_burned"] = burned
        report["steps"].append({
            "step": "flush_fees",
            "burned": burned,
        })
        if burned > 0:
            logger.info("Fee pool flushed: %d burned", burned)
    except Exception as e:
        logger.warning("Fee flush skipped: %s", e)

    # Step 4: Distribute treasury to active agents
    try:
        distribution = bridge.engine.distribute_fee_pool()
        distributed = sum(distribution.values())
        report["total_distributed"] = distributed
        report["distribution"] = distribution
        report["steps"].append({
            "step": "distribute_treasury",
            "total_distributed": distributed,
            "recipients": len(distribution),
        })
        if distributed > 0:
            logger.info("Treasury distributed: %d to %d agents",
                        distributed, len(distribution))
    except Exception as e:
        logger.warning("Treasury distribution skipped: %s", e)

    # Step 5: Get final state
    try:
        stats = bridge.engine.get_stats()
        report["post_cycle_stats"] = {
            "total_supply": stats.get("total_supply", 0),
            "circulating_supply": stats.get("circulating_supply", 0),
            "total_burned": stats.get("total_burned", 0),
            "burn_percent": stats.get("burn_percent", 0),
            "treasury_remaining": stats.get("treasury", 0),
            "fee_pool": stats.get("fee_pool", 0),
            "num_accounts": stats.get("num_accounts", 0),
        }
    except Exception:
        pass

    report["status"] = "completed"
    _log_circulation_event(report)
    return report


def _log_circulation_event(report: Dict[str, Any]) -> None:
    """Append circulation event to the event log for dashboard display."""
    try:
        CIRCULATION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": report["timestamp"],
            "cycle_id": report["cycle_id"],
            "status": report["status"],
            "injected": report["total_injected"],
            "burned": report["total_burned"],
            "distributed": report["total_distributed"],
            "source": report.get("source", "unknown"),
        }
        with open(CIRCULATION_LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as e:
        logger.warning("Cannot log circulation event: %s", e)


# ── HTTP-friendly JSON report (for REST API) ────────────────────────────


def format_report_for_api(report: Dict[str, Any]) -> Dict[str, Any]:
    """Format a circulation report for REST API consumption."""
    return {
        "cycle_id": report.get("cycle_id"),
        "timestamp": report.get("timestamp"),
        "status": report.get("status"),
        "dry_run": report.get("dry_run", False),
        "source": report.get("source", "none"),
        "profit_detected": report.get("total_injected", 0),
        "profit_display": f"{report.get('total_injected', 0) / 1_000_000:.6f} SIMPT",
        "burned": report.get("total_burned", 0),
        "distributed": report.get("total_distributed", 0),
        "recipients": len(report.get("distribution", {})),
        "reason": report.get("reason", ""),
        "post_cycle": report.get("post_cycle_stats", {}),
        "steps": report.get("steps", []),
    }


def get_circulation_history(limit: int = 20) -> list:
    """Read recent circulation events for dashboard display."""
    entries = []
    try:
        if CIRCULATION_LOG_PATH.exists():
            with open(CIRCULATION_LOG_PATH, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
    except OSError:
        pass
    return entries[-limit:]


# ── Daemon Mode ─────────────────────────────────────────────────────────


def run_daemon(interval: int = DEFAULT_INTERVAL):
    """Run circulation cycles in a loop."""
    logger.info("Autonomous circulation daemon started (interval=%ds)", interval)
    logger.info("P&L source: %s", QUANTUMARB_PNL_PATH)
    logger.info("Min profit threshold: %d micro-SIMP (%.4f SIMPT)",
                MIN_PROFIT_THRESHOLD, MIN_PROFIT_THRESHOLD / 1_000_000)

    cycle_count = 0
    while True:
        try:
            cycle_count += 1
            report = run_circulation_cycle()
            status_icon = "✅" if report["status"] == "completed" else "⏭️"
            logger.info("%s Cycle #%d: %s | injected=%.4f | burned=%.4f | distributed=%.4f",
                        status_icon, cycle_count,
                        report["status"],
                        report["total_injected"] / 1_000_000,
                        report["total_burned"] / 1_000_000,
                        report["total_distributed"] / 1_000_000)
        except KeyboardInterrupt:
            logger.info("Daemon stopped by user after %d cycles", cycle_count)
            break
        except Exception as e:
            logger.error("Cycle #%d failed: %s", cycle_count + 1, e)

        time.sleep(interval)


# ── CLI Entry Point ─────────────────────────────────────────────────────


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="SIMP Autonomous Token Circulation Pipeline",
    )
    parser.add_argument(
        "--daemon", "-d", action="store_true",
        help="Run continuously every N seconds",
    )
    parser.add_argument(
        "--interval", "-i", type=int, default=DEFAULT_INTERVAL,
        help=f"Daemon interval in seconds (default: {DEFAULT_INTERVAL})",
    )
    parser.add_argument(
        "--once", "-o", action="store_true",
        help="Run a single cycle and exit",
    )
    parser.add_argument(
        "--amount", "-a", type=int, default=None,
        help="Force a specific profit amount (micro-SIMP units, 1e6 = 1 SIMPT)",
    )
    parser.add_argument(
        "--dry-run", "-n", action="store_true",
        help="Simulate without writing to the ledger",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--history", action="store_true",
        help="Show recent circulation history",
    )
    parser.add_argument(
        "--amount-display", type=float, default=None,
        help="Force profit in SIMPT display units (e.g. --amount-display 5.0 = 5 SIMPT)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Handle --amount-display (SIMPT units, converts to micro-SIMP)
    if args.amount_display is not None:
        args.amount = int(args.amount_display * 1_000_000)

    if args.history:
        history = get_circulation_history()
        if not history:
            print("No circulation history yet. Run a cycle first.")
            return
        print(f"\n{'═' * 70}")
        print(f"  SIMP Circulation History (last {len(history)} events)")
        print(f"{'═' * 70}")
        for entry in reversed(history):
            ts = entry.get("timestamp", "?")[11:19]  # HH:MM:SS
            status = entry.get("status", "?")
            injected = entry.get("injected", 0) / 1_000_000
            burned = entry.get("burned", 0) / 1_000_000
            dist = entry.get("distributed", 0) / 1_000_000
            print(f"  {ts} | {status:12s} | +{injected:.4f} SIMPT | 🔥 {burned:.4f} | 📤 {dist:.4f}")
        return

    if args.daemon:
        run_daemon(interval=args.interval)
    else:
        # Single cycle
        report = run_circulation_cycle(
            force_amount=args.amount,
            dry_run=args.dry_run,
        )
        api = format_report_for_api(report)

        print(f"\n{'═' * 70}")
        print(f"  SIMP Circulation Cycle — {api['cycle_id']}")
        print(f"  Status: {api['status']}")
        print(f"{'═' * 70}")

        if api["status"] == "skipped":
            print(f"  ⏭️  {api['reason']}")
            return

        print(f"  Source:         {api['source']}")
        print(f"  Profit:         +{api['profit_display']}")
        print(f"  Burned:         {api['burned'] / 1_000_000:.6f} SIMPT")
        print(f"  Distributed:    {api['distributed'] / 1_000_000:.6f} SIMPT to {api['recipients']} agents")

        if api["post_cycle"]:
            ps = api["post_cycle"]
            print(f"\n  Post-Cycle State:")
            print(f"    Circulating Supply: {ps.get('circulating_supply', 0) / 1_000_000:,.2f} SIMPT")
            print(f"    Total Burned:      {ps.get('total_burned', 0) / 1_000_000:,.4f} SIMPT")
            print(f"    Burn Rate:         {ps.get('burn_percent', 0):.2f}%")
            print(f"    Treasury:          {ps.get('treasury_remaining', 0) / 1_000_000:,.4f} SIMPT")
            print(f"    Fee Pool:          {ps.get('fee_pool', 0) / 1_000_000:,.4f} SIMPT")

        if api.get("steps"):
            print(f"\n  Steps Executed:")
            for s in api["steps"]:
                print(f"    ✅ {s['step']}")


if __name__ == "__main__":
    main()
