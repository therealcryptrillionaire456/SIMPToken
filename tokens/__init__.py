"""
SIMP Token System — Unified Token Foundation

Single source of truth: tokens/ledger.py (SQLite)
Thin compatibility layer: mesh_token.py -> delegates to Ledger

Architecture:
  - All token state lives in one SQLite DB
  - fees flow to fee_sink -> burn treasury
  - burn is a (hopefully) one-way operation
  - Supply is capped at 1_000_000_000 SIMP (1B)
  - Two fee types: protocol fees (burned) and delegation fees (distributed)
"""

from .ledger import (
    Ledger,
    Account,
    Transaction,
    FeeSchedule,
    AgentKeyRecord,
    IntentEvent,
    Sponsor,
    BrokerTrust,
    EscrowRecord,
    IntentBundle,
    BundleParticipant,
    # v2 constants
    FEE_SINK,
    BURN_VAULT,
    TREASURY,
    STAKING_POOL,
    # Paths
    DEFAULT_LEDGER_DIR,
    DEFAULT_LEDGER_PATH,
    SCHEMA,
)

from .burn_engine import BurnEngine, MODULE_BURN_ENGINE
from .unified import UnifiedTokenEngine, UNIFIED_ENGINE, MODULE_ENGINE, TokenConfig
from .v2_config import (
    V2_TOKEN_INFO,
    V2_TOKEN_MINT,
    V1_TOKEN_MINT,
    TOKEN_NAME as V2_TOKEN_NAME,
    TOKEN_SYMBOL as V2_TOKEN_SYMBOL,
    check_onchain_supply,
    check_whale_balance,
    get_audit_results as get_v2_audit,
)
from .economy_bridge import TokenEconomyBridge, MODULE_BRIDGE
from .v1_config import (
    V1_TOKEN_INFO,
    V1_TOKEN_NAME,
    V1_TOKEN_SYMBOL,
    check_v1_onchain,
    get_broketarium_report,
    DUAL_TOKEN_MAP,
)
from .pentagon import PentagonDocument, PENTAGON_DOCUMENT
from .v1_distribution import (
    V1DistributionManager,
    V1DistributionRecord,
    V1_DISTRIBUTION,
    AGENT_V1_ALLOCATIONS,
    AGENT_WALLETS,
    V1_SUPPLY,
    TREASURY_RESERVE,
    WHALE_PUBKEY,
    WHALE_ATA,
)
from .agent_wallets import (
    AgentWalletManager,
    AgentWallet,
    AGENT_WALLET_MGR,
    AGENT_INDICES,
)

__all__ = [
    # Core
    "Ledger", "Account", "Transaction", "FeeSchedule",
    "AgentKeyRecord", "IntentEvent", "Sponsor", "BrokerTrust",
    "EscrowRecord", "IntentBundle", "BundleParticipant",
    # v2
    "FEE_SINK", "BURN_VAULT", "TREASURY", "STAKING_POOL",
    "BurnEngine", "MODULE_BURN_ENGINE",
    # Unified
    "UnifiedTokenEngine", "UNIFIED_ENGINE", "MODULE_ENGINE",
    "TokenConfig",
    # V2 On-Chain
    "V2_TOKEN_INFO", "V2_TOKEN_MINT", "V1_TOKEN_MINT",
    "V2_TOKEN_NAME", "V2_TOKEN_SYMBOL",
    "check_onchain_supply", "check_whale_balance", "get_v2_audit",
    # Bridge
    "TokenEconomyBridge", "MODULE_BRIDGE",
    # V1 Broketarium
    "V1_TOKEN_INFO", "V1_TOKEN_NAME", "V1_TOKEN_SYMBOL",
    "check_v1_onchain", "get_broketarium_report",
    "DUAL_TOKEN_MAP",
    # Pentagram
    "PentagonDocument", "PENTAGON_DOCUMENT",
    # V1 Distribution
    "V1DistributionManager", "V1DistributionRecord",
    "V1_DISTRIBUTION", "AGENT_V1_ALLOCATIONS",
    "AGENT_WALLETS", "V1_SUPPLY", "TREASURY_RESERVE",
    "WHALE_PUBKEY", "WHALE_ATA",
    # Agent Wallets
    "AgentWalletManager", "AgentWallet",
    "AGENT_WALLET_MGR", "AGENT_INDICES",
    # Paths
    "DEFAULT_LEDGER_DIR", "DEFAULT_LEDGER_PATH", "SCHEMA",
]
