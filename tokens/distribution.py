"""
SIMP Agent Token Distribution Contract (L6-T5)

Defines which agents receive V2 token allocations, amounts, and vesting schedules.
All allocations are SIMULATED via FinancialOps until explicit promotion to mainnet.

Architecture:
  - Distribution rules live in this file (deterministic, version-controlled)
  - Allocations are managed through the FinancialOps approval queue
  - On-chain distribution requires explicit promotion (Gate 2 → mainnet)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("SIMP.TokenDistribution")

# ── Allocation Constants ────────────────────────────────────────────────────

# Total supply: 1,000,000,000 SIMPT
# Distribution breakdown (pentagon model):
#   - 40% PTAI Founder / Treasury     = 400,000,000
#   - 20% Agent Ecosystem Reserve     = 200,000,000
#   - 20% Public / Liquidity          = 200,000,000
#   - 10% Development Fund            = 100,000,000
#   - 10% Staking / Governance Rewards = 100,000,000

TOTAL_SUPPLY = 1_000_000_000
DECIMALS = 6

# Raw amounts (multiply by 10^6 for on-chain)
def _raw(ui_amount: int) -> int:
    return ui_amount * 10**6


@dataclass
class AllocationTranche:
    """A token allocation tranche with vesting."""
    name: str
    category: str
    ui_amount: int  # UI units (whole tokens)
    raw_amount: int  # Raw lamport-like units
    recipient: str  # agent_id or pubkey
    vesting_months: int = 0  # 0 = no cliff, immediate
    cliff_months: int = 0
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "ui_amount": self.ui_amount,
            "raw_amount": self.raw_amount,
            "recipient": self.recipient,
            "vesting_months": self.vesting_months,
            "cliff_months": self.cliff_months,
            "description": self.description,
        }


# ── Distribution Plan ───────────────────────────────────────────────────────

FOUNDER_ALLOCATION = AllocationTranche(
    name="PTAI Founder Allocation",
    category="founder",
    ui_amount=400_000_000,
    raw_amount=_raw(400_000_000),
    recipient="58EohzqesFaxpRaqgaab7v5f9ZAhBGhzubTNHEHHmPpB",  # simp_whale
    vesting_months=24,
    cliff_months=6,
    description="PTAI founder (Kasey Marcelle) — 40% of supply, 24-month linear vesting with 6-month cliff",
)

AGENT_ECOSYSTEM_ALLOCATIONS = [
    AllocationTranche(
        name="Gemma4 Local",
        category="agent_ecosystem",
        ui_amount=20_000_000,
        raw_amount=_raw(20_000_000),
        recipient="gemma4_local",
        vesting_months=12,
        description="Local LLM agent — maintenance, planning, classification",
    ),
    AllocationTranche(
        name="ProjectX Kernel",
        category="agent_ecosystem",
        ui_amount=20_000_000,
        raw_amount=_raw(20_000_000),
        recipient="projectx_native",
        vesting_months=12,
        description="Native SIMP kernel — audit, health, security scanning",
    ),
    AllocationTranche(
        name="QuantumArb",
        category="agent_ecosystem",
        ui_amount=15_000_000,
        raw_amount=_raw(15_000_000),
        recipient="quantumarb",
        vesting_months=6,
        description="Arbitrage detection & execution agent",
    ),
    AllocationTranche(
        name="KashClaw Trading",
        category="agent_ecosystem",
        ui_amount=15_000_000,
        raw_amount=_raw(15_000_000),
        recipient="kashclaw",
        vesting_months=6,
        description="Multi-venue trading execution agent",
    ),
    AllocationTranche(
        name="BullBear Predictor",
        category="agent_ecosystem",
        ui_amount=15_000_000,
        raw_amount=_raw(15_000_000),
        recipient="bullbear_predictor",
        vesting_months=6,
        description="Multi-sector prediction engine",
    ),
    AllocationTranche(
        name="KloutBot",
        category="agent_ecosystem",
        ui_amount=15_000_000,
        raw_amount=_raw(15_000_000),
        recipient="kloutbot",
        vesting_months=6,
        description="Orchestration and conversational agent",
    ),
    AllocationTranche(
        name="Claude CoWork",
        category="agent_ecosystem",
        ui_amount=10_000_000,
        raw_amount=_raw(10_000_000),
        recipient="claude_cowork",
        vesting_months=6,
        description="Claude Code bridge for complex refactors",
    ),
    AllocationTranche(
        name="Perplexity Research",
        category="agent_ecosystem",
        ui_amount=10_000_000,
        raw_amount=_raw(10_000_000),
        recipient="perplexity_research",
        vesting_months=6,
        description="Research and sprint planning agent",
    ),
    AllocationTranche(
        name="FinancialOps Agent",
        category="agent_ecosystem",
        ui_amount=10_000_000,
        raw_amount=_raw(10_000_000),
        recipient="financial_ops",
        vesting_months=3,
        description="Financial operations and treasury management",
    ),
    AllocationTranche(
        name="Hermes Bridge",
        category="agent_ecosystem",
        ui_amount=10_000_000,
        raw_amount=_raw(10_000_000),
        recipient="hermes",
        vesting_months=6,
        description="Cross-agent bridge and skill harvesting",
    ),
    AllocationTranche(
        name="PTAI Knowledge Agent",
        category="agent_ecosystem",
        ui_amount=10_000_000,
        raw_amount=_raw(10_000_000),
        recipient="ptai_knowledge",
        vesting_months=6,
        description="PTAI knowledge base and memory agent",
    ),
    AllocationTranche(
        name="Mesh Routing Agent",
        category="agent_ecosystem",
        ui_amount=10_000_000,
        raw_amount=_raw(10_000_000),
        recipient="mesh_routing",
        vesting_months=6,
        description="Mesh network routing and discovery agent",
    ),
    AllocationTranche(
        name="Orchestration Agent",
        category="agent_ecosystem",
        ui_amount=10_000_000,
        raw_amount=_raw(10_000_000),
        recipient="orchestrator",
        vesting_months=6,
        description="Intent orchestration and workflow sequencing agent",
    ),
    AllocationTranche(
        name="Security Audit Agent",
        category="agent_ecosystem",
        ui_amount=10_000_000,
        raw_amount=_raw(10_000_000),
        recipient="security_auditor",
        vesting_months=6,
        description="Automated security scanning and audit agent",
    ),
    AllocationTranche(
        name="Community Incentives",
        category="agent_ecosystem",
        ui_amount=10_000_000,
        raw_amount=_raw(10_000_000),
        recipient="community_pool",
        vesting_months=0,
        description="Community incentive pool — bounties, referrals, ecosystem grants",
    ),
    AllocationTranche(
        name="Goose Builder Agent",
        category="agent_ecosystem",
        ui_amount=10_000_000,
        raw_amount=_raw(10_000_000),
        recipient="goose",
        vesting_months=6,
        description="Builder agent — scaffolding, test writing, module creation",
    ),
]

LIQUIDITY_ALLOCATION = AllocationTranche(
    name="Liquidity Pool / Public",
    category="liquidity",
    ui_amount=200_000_000,
    raw_amount=_raw(200_000_000),
    recipient="TREASURY",
    vesting_months=0,
    description="DEX liquidity and public sale — 20% of supply",
)

DEV_FUND_ALLOCATION = AllocationTranche(
    name="Development Fund",
    category="development",
    ui_amount=100_000_000,
    raw_amount=_raw(100_000_000),
    recipient="TREASURY",
    vesting_months=12,
    cliff_months=3,
    description="Protocol development and grants — 10% of supply",
)

STAKING_ALLOCATION = AllocationTranche(
    name="Staking & Governance Rewards",
    category="staking",
    ui_amount=100_000_000,
    raw_amount=_raw(100_000_000),
    recipient="STAKING_POOL",
    vesting_months=0,
    description="Staking rewards and governance participation — 10% of supply",
)


class DistributionContract:
    """Manages the V2 token distribution plan.

    This is a SIMULATED contract — actual on-chain distribution
    requires explicit promotion through FinancialOps gates.

    Use as the source of truth for *planned* allocation.
    """

    def __init__(self, log_path: Optional[Path] = None):
        self._log_path = log_path or Path("data/distribution_log.jsonl")
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def founder(self) -> AllocationTranche:
        return FOUNDER_ALLOCATION

    @property
    def agent_ecosystem(self) -> List[AllocationTranche]:
        return AGENT_ECOSYSTEM_ALLOCATIONS

    @property
    def liquidity(self) -> AllocationTranche:
        return LIQUIDITY_ALLOCATION

    @property
    def dev_fund(self) -> AllocationTranche:
        return DEV_FUND_ALLOCATION

    @property
    def staking(self) -> AllocationTranche:
        return STAKING_ALLOCATION

    def get_all_allocations(self) -> List[AllocationTranche]:
        """Return all allocations across all categories."""
        return (
            [self.founder]
            + self.agent_ecosystem
            + [self.liquidity, self.dev_fund, self.staking]
        )

    def get_category_summary(self) -> Dict[str, int]:
        """Return UI amounts per category."""
        summary = {}
        for alloc in self.get_all_allocations():
            summary[alloc.category] = summary.get(alloc.category, 0) + alloc.ui_amount
        return summary

    def verify_supply_match(self) -> Dict[str, Any]:
        """Verify that all allocations sum to total supply."""
        total_allocated = sum(a.ui_amount for a in self.get_all_allocations())
        match = total_allocated == TOTAL_SUPPLY
        return {
            "total_supply": TOTAL_SUPPLY,
            "total_allocated": total_allocated,
            "match": match,
            "difference": TOTAL_SUPPLY - total_allocated,
        }

    def get_agent_allocation(self, agent_id: str) -> Optional[AllocationTranche]:
        """Get allocation for a specific agent by ID."""
        for alloc in self.agent_ecosystem:
            if alloc.recipient == agent_id:
                return alloc
        return None

    def log_distribution_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Log a distribution event to the append-only ledger."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            **data,
        }
        try:
            with open(self._log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as e:
            logger.warning("Failed to write distribution log: %s", e)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_supply": TOTAL_SUPPLY,
            "allocation_plan": self.get_category_summary(),
            "allocations": [a.to_dict() for a in self.get_all_allocations()],
            "supply_verification": self.verify_supply_match(),
        }


# Module singleton
MODULE_CONTRACT = DistributionContract()
