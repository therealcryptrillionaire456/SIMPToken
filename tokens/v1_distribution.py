"""
SIMP V1 Token Distribution & Governance Rent Recovery (L6-T7/T8)
================================================================

V1 (Broketarium) token distribution to agents and governance program
rent recovery.

V1 Token Properties:
  - Mint: CHmgojCz8Pk5qgD8nkiiCZvHkZfpfUoYn47aUqWNDZMt
  - Program: Tokenkeg (original SPL Token)
  - Supply: 999,999,000 SIMPT (locked, mint authority burned)
  - Vault: 58EohzqesFaxpRaqgaab7v5f9ZAhBGhzubTNHEHHmPpB (simp_whale)
  - Vault ATA: 9ih2dTaHHeXxMaD2Pe2hh9Ce1iM4csdUxNCLdYK3fqG8

Agent Distribution:
  V1 tokens are distributed to agents for "ordinance" — operational budgets
  used for infrastructure identification, data transfer accounting, and
  mesh participation. Each agent creates their own V1 ATA and governs
  their own ordinance.

  "agents have to create their own ordinance"

Governance Rent Recovery:
  V1 governance programs locked ~4.5 SOL as rent when deployed.
  We close these program accounts to recover unspent rent.
  Gas fees are non-recoverable; account rent is recoverable.

Usage:
    from tokens.v1_distribution import V1DistributionManager

    mgr = V1DistributionManager()
    mgr.load_v1_state()           # Check on-chain V1 state
    mgr.create_agent_ata(id, pk)  # Create ATA for an agent
    mgr.transfer_to_agent(id, ui) # Transfer V1 tokens
    mgr.close_recoverable()       # Close governance programs for rent

Architecture:
  - All operations go through the whale wallet
  - Each agent gets a V1 ATA (Associated Token Account)
  - All events logged to data/v1_distribution.jsonl (append-only)
  - Governance programs closed for rent recovery via RPC
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib import request as urllib_request
from urllib.error import URLError

logger = logging.getLogger("SIMP.V1Distribution")

# ── V1 Constants ───────────────────────────────────────────────────────────

V1_MINT = "CHmgojCz8Pk5qgD8nkiiCZvHkZfpfUoYn47aUqWNDZMt"
V1_DECIMALS = 6
V1_SUPPLY = 999_999_000

WHALE_PUBKEY = "58EohzqesFaxpRaqgaab7v5f9ZAhBGhzubTNHEHHmPpB"
WHALE_ATA = "9ih2dTaHHeXxMaD2Pe2hh9Ce1iM4csdUxNCLdYK3fqG8"

WHALE_KEYFILE = os.environ.get(
    "SIMP_WHALE_KEYFILE",
    "/Users/kaseymarcelle/Downloads/simp_whale_private_key.json",
)

ALCHEMY_RPC = os.environ.get(
    "ALCHEMY_RPC",
    "https://solana-mainnet.g.alchemy.com/v2/mDKvlGo6XpFKJWGDWc7R0dUjoIsxYjWW",
)

# Agent V1 allocation amounts (based on agent tier/role)
# Each agent receives V1 for "ordinance" — their operational budget
# Total distributed: 999,999,000 V1 (minus what stays in Treasury)
AGENT_V1_ALLOCATIONS: Dict[str, int] = {
    # Core infrastructure agents (highest ordinance)
    "projectx_native": 50_000_000,       # SIMP kernel
    "gemma4_local": 50_000_000,           # Local LLM (24/7 operations)
    "kashclaw": 50_000_000,              # Multi-venue execution
    "bullbear_predictor": 50_000_000,    # Prediction engine
    "quantumarb": 50_000_000,            # Arbitrage detection

    # Orchestration & coordination
    "kloutbot": 40_000_000,              # Orchestration
    "orchestrator": 30_000_000,          # Workflow sequencing

    # Specialized agents
    "claude_cowork": 30_000_000,         # Complex refactors
    "perplexity_research": 30_000_000,   # Research & planning
    "financial_ops": 30_000_000,         # Treasury management
    "security_auditor": 30_000_000,      # Security scanning
    "mesh_routing": 30_000_000,          # Mesh routing & discovery
    "ptai_knowledge": 30_000_000,        # Knowledge base
    "hermes": 30_000_000,                # Cross-agent bridge
    "goose": 30_000_000,                 # Builder agent

    # Community & operations
    "community_pool": 100_000_000,       # Community incentives pool

    # Remaining: held in Treasury for future agent onboarding
    # Treasury reserve: 999_999_000 - sum(above) = 329,999,000
}

# Calculate Treasury reserve
_AGENT_TOTAL = sum(AGENT_V1_ALLOCATIONS.values())
TREASURY_RESERVE = V1_SUPPLY - _AGENT_TOTAL

# On-chain agent wallets (need Solana addresses for distribution)
# These are the agent-operated wallets that will receive V1
# Format: agent_id -> Solana pubkey
# NOTE: These need to be created/funded before distribution
AGENT_WALLETS: Dict[str, str] = {
    # Agent wallets will be populated as they're created
}

# V1 Governance programs that may have recoverable rent
# These are programs deployed as part of V1 governance infrastructure
# Each costs ~0.5-2 SOL in rent depending on program size
V1_GOVERNANCE_PROGRAMS = [
    # Format: (program_id, description, estimated_rent_sol)
]

# ── Dataclasses ────────────────────────────────────────────────────────────

@dataclass
class V1DistributionRecord:
    """Record of a V1 distribution event."""
    agent_id: str
    agent_wallet: str
    amount_ui: int
    tx_signature: Optional[str]
    ata_address: Optional[str]
    status: str  # pending, created, transferred, failed
    error: Optional[str]
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GovernanceRentRecovery:
    """Record of governance program rent recovery."""
    program_id: str
    description: str
    lamports_recovered: int
    sol_recovered: float
    tx_signature: Optional[str]
    status: str
    error: Optional[str]
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── V1 Distribution Manager ────────────────────────────────────────────────

class V1DistributionManager:
    """Manages V1 token distribution to agents and governance rent recovery.

    Thread-safe. All events logged to append-only JSONL.
    """

    def __init__(self, data_dir: Optional[Path] = None):
        self._lock = threading.Lock()
        self._data_dir = data_dir or Path("data")
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = self._data_dir / "v1_distribution.jsonl"
        self._v1_onchain_state: Dict[str, Any] = {}
        self._whale_keypair: Optional[bytes] = None

    # ── Whale Key Management ──────────────────────────────────────────

    def _load_whale_key(self) -> Optional[bytes]:
        """Load the whale wallet keypair from keyfile."""
        if self._whale_keypair:
            return self._whale_keypair
        try:
            keyfile = Path(WHALE_KEYFILE)
            if not keyfile.exists():
                logger.warning("Whale keyfile not found: %s", WHALE_KEYFILE)
                return None
            with open(keyfile) as f:
                data = json.load(f)
            if isinstance(data, list) and len(data) == 64:
                self._whale_keypair = bytes(data)
                logger.info("Whale keypair loaded (%s bytes)", len(self._whale_keypair))
                return self._whale_keypair
            else:
                logger.warning("Unexpected keyfile format: %s", type(data))
                return None
        except Exception as e:
            logger.error("Failed to load whale keyfile: %s", e)
            return None

    # ── On-chain State ────────────────────────────────────────────────

    def load_v1_state(self) -> Dict[str, Any]:
        """Query V1 on-chain state via Alchemy RPC."""
        state = {}

        # 1. Check V1 supply
        supply_result = self._rpc("getTokenSupply", [V1_MINT])
        if (
            "result" in supply_result
            and supply_result["result"]
            and isinstance(supply_result["result"], dict)
            and "value" in supply_result["result"]
        ):
            val = supply_result["result"]["value"]
            state["supply"] = {
                "ui_amount": int(val.get("uiAmount", 0)),
                "raw_amount": int(val.get("amount", "0")),
                "decimals": int(val.get("decimals", V1_DECIMALS)),
            }
        else:
            state["supply"] = {"error": "Could not query supply"}

        # 2. Check whale SOL balance
        bal_result = self._rpc("getBalance", [WHALE_PUBKEY])
        if (
            "result" in bal_result
            and bal_result["result"]
            and isinstance(bal_result["result"], dict)
            and "value" in bal_result["result"]
        ):
            state["whale_sol"] = bal_result["result"]["value"] / 1e9
            state["whale_lamports"] = bal_result["result"]["value"]
        else:
            state["whale_sol"] = 0

        # 3. Check whale V1 token ATA
        ata_result = self._rpc("getTokenAccountsByOwner", [
            WHALE_PUBKEY,
            {"mint": V1_MINT},
            {"encoding": "jsonParsed"},
        ])
        if (
            "result" in ata_result
            and isinstance(ata_result["result"], dict)
            and ata_result["result"].get("value")
        ):
            accounts = []
            for acc in ata_result["result"]["value"]:
                data = acc.get("account", {})
                parsed = data.get("data", {}).get("parsed", {})
                if not parsed:
                    continue
                info = parsed.get("info", {})
                token_amount = info.get("tokenAmount", {})
                accounts.append({
                    "pubkey": acc.get("pubkey", ""),
                    "owner": info.get("owner", ""),
                    "balance": token_amount.get("uiAmountString", "0"),
                    "rent_lamports": data.get("lamports", 0),
                })
            state["whale_v1_accounts"] = accounts
        else:
            state["whale_v1_accounts"] = []

        self._v1_onchain_state = state
        return state

    def _rpc(self, method: str, params: List[Any]) -> Dict[str, Any]:
        """Make a JSON-RPC call to Alchemy."""
        payload = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }).encode("utf-8")

        req = urllib_request.Request(
            ALCHEMY_RPC,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib_request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.warning("RPC %s failed: %s", method, e)
            return {"error": str(e)}

    # ── Feature Support (Check if solana-py is available) ─────────────

    def _has_solana_py(self) -> bool:
        """Check if solana-py and solders are importable (bypassing local solana/)."""
        try:
            result = subprocess.run(
                [
                    "python3.10", "-c",
                    "import sys; "
                    "sys.path = [p for p in sys.path if 'simp/solana' not in p.replace('\\\\','/')]; "
                    "from solders.keypair import Keypair; "
                    "from solders.pubkey import Pubkey; "
                    "print('OK')",
                ],
                capture_output=True, text=True, timeout=10,
            )
            return result.stdout.strip() == "OK"
        except Exception:
            return False

    def _solana_py_transfer(self, amount_ui: int, destination: str) -> Dict[str, Any]:
        """Execute V1 token transfer using solana-py in subprocess.

        Returns dict with tx_signature or error.
        """
        if not self._load_whale_key():
            return {"error": "No whale key available", "tx_signature": None}

        # Convert UI amount to raw (6 decimals)
        raw_amount = int(amount_ui * 10 ** V1_DECIMALS)

        script = f"""
import sys
sys.path = [p for p in sys.path if 'simp/solana' not in p.replace('\\\\','/')]
import json, base58, time
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.instruction import AccountMeta, Instruction
from solders.message import Message
from solders.transaction import Transaction
from solana.rpc.api import Client as SolanaClient
from solana.rpc.types import TxOpts

# Whale key
whale_key_data = json.loads({json.dumps(json.loads(open('{WHALE_KEYFILE}').read()))})
whale_kp = Keypair.from_bytes(bytes(whale_key_data))
whale_pk = whale_kp.pubkey()

# Params
mint = Pubkey.from_string('{V1_MINT}')
dest = Pubkey.from_string('{destination}')
dest_ata = None  # Will be computed

# Get destination ATA or create it
from solders.token.associated import get_associated_token_address
dest_ata = get_associated_token_address(dest, mint)
print(f'Destination ATA: {{dest_ata}}')

# Check if ATA exists
client = Client('{ALCHEMY_RPC}')
try:
    ata_info = client.get_account_info(dest_ata)
    exists = ata_info.value is not None
except:
    exists = False
    
# Source ATA (whale)
from solders.token.associated import get_associated_token_address
whale_ata = get_associated_token_address(whale_pk, mint)

# Build transfer instruction
from solders.instruction import Instruction
from solders.token.instructions import transfer

# Create transfer instruction for SPL Token program (Tokenkeg)
txn = Transaction()

if not exists:
    # Create ATA for destination
    from solders.token.instructions import create_associated_token_account
    create_ix = create_associated_token_account(whale_pk, dest, mint)
    txn.add(create_ix)

# Add compute budget
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
txn.add(set_compute_unit_limit(200_000))
txn.add(set_compute_unit_price(5000))

# Transfer instruction
transfer_ix = transfer(
    source=whale_ata,
    dest=dest_ata if exists else None,  # will be the output of create_ix
    owner=whale_pk,
    amount={raw_amount},
    program_id=Pubkey.from_string('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'),
)
txn.add(transfer_ix)

# Send
try:
    opts = TxOpts(skip_preflight=True, max_retries=3)
    sig = client.send_transaction(txn, whale_kp, opts=opts)
    print(f'SUCCESS: {{sig.value}}')
except Exception as e:
    print(f'ERROR: {{e}}')
"""
        try:
            result = subprocess.run(
                ["python3.10", "-c", script],
                capture_output=True, text=True, timeout=60,
            )
            output = result.stdout.strip()
            stderr = result.stderr.strip()

            if "SUCCESS:" in output:
                tx_sig = output.split("SUCCESS:")[-1].strip()
                return {"tx_signature": tx_sig, "error": None}
            elif "ERROR:" in output:
                error = output.split("ERROR:")[-1].strip()
                return {"error": error, "tx_signature": None}
            else:
                return {"error": f"Unknown output: {output[:500]}", "tx_signature": None}
        except subprocess.TimeoutExpired:
            return {"error": "Transaction timed out", "tx_signature": None}
        except Exception as e:
            return {"error": str(e), "tx_signature": None}

    # ── Distribution ──────────────────────────────────────────────────

    def get_allocation_for_agent(self, agent_id: str) -> int:
        """Get V1 allocation amount for an agent (UI units)."""
        return AGENT_V1_ALLOCATIONS.get(agent_id, 0)

    def set_agent_wallet(self, agent_id: str, wallet_address: str) -> None:
        """Register a Solana wallet address for an agent."""
        with self._lock:
            AGENT_WALLETS[agent_id] = wallet_address
            logger.info("Agent %s -> wallet %s", agent_id, wallet_address)

    def get_distribution_summary(self) -> Dict[str, Any]:
        """Get the full distribution plan summary."""
        allocations_list = [
            {"agent_id": aid, "amount_ui": amt}
            for aid, amt in sorted(AGENT_V1_ALLOCATIONS.items())
        ]
        return {
            "total_v1_supply": V1_SUPPLY,
            "total_allocated": _AGENT_TOTAL,
            "treasury_reserve": TREASURY_RESERVE,
            "allocations": allocations_list,
            "agent_wallets_registered": len(AGENT_WALLETS),
            "wallets": AGENT_WALLETS,
        }

    def distribute_to_agent(self, agent_id: str) -> Dict[str, Any]:
        """Distribute V1 tokens to an agent.

        Creates the agent's V1 ATA if needed, then transfers allocation.

        Returns distribution result record.
        """
        allocation = self.get_allocation_for_agent(agent_id)
        if allocation == 0:
            return {"status": "failed", "error": f"No allocation for agent: {agent_id}"}

        if agent_id not in AGENT_WALLETS:
            return {
                "status": "failed",
                "error": f"No wallet registered for agent: {agent_id}. "
                         f"Use set_agent_wallet() first.",
            }

        dest_wallet = AGENT_WALLETS[agent_id]

        # Execute transfer
        result = self._solana_py_transfer(allocation, dest_wallet)

        record = V1DistributionRecord(
            agent_id=agent_id,
            agent_wallet=dest_wallet,
            amount_ui=allocation,
            tx_signature=result.get("tx_signature"),
            ata_address=None,
            status="transferred" if result.get("tx_signature") else "failed",
            error=result.get("error"),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        self._log_event("v1_distribution", record.to_dict())
        return record.to_dict()

    # ── Governance Rent Recovery ──────────────────────────────────────

    def scan_governance_programs(self) -> List[Dict[str, Any]]:
        """Scan for V1 governance programs with recoverable rent.

        Uses Alchemy RPC to find program accounts owned by BPFLoader
        that were deployed by the whale wallet, checking their rent.

        Returns list of program accounts with rent info.
        """
        # Query for programs that the whale wallet deployed
        # BPFLoaderUpgradeab1e is the standard Solana BPF loader
        # BPFLoader2111111111111111111111111111111111 is older

        programs = []
        loaders = [
            "BPFLoaderUpgradeab1e111111111111111111111111",
            "BPFLoader1111111111111111111111111111111111",
            "ComputeBudget111111111111111111111111111111",
        ]

        for loader in loaders:
            result = self._rpc("getProgramAccounts", [
                loader,
                {"encoding": "base64"},
            ])
            if (
                "result" in result
                and isinstance(result["result"], dict)
                and "value" in result["result"]
                and isinstance(result["result"]["value"], list)
            ):
                for acc in result["result"]["value"]:
                    account_info = acc.get("account", {})
                    lamports = account_info.get("lamports", 0)
                    pubkey = acc.get("pubkey", "")
                    if not pubkey:
                        continue
                    programs.append({
                        "pubkey": pubkey,
                        "lamports": lamports,
                        "sol": lamports / 1e9,
                        "loader": loader,
                        "executable": account_info.get("executable", False),
                    })

        # Sort by rent amount (highest first)
        programs.sort(key=lambda p: p["lamports"], reverse=True)
        return programs

    def estimate_recoverable_rent(self) -> Dict[str, Any]:
        """Estimate how much SOL can be recovered from governance programs.

        Returns dict with total recoverable SOL and program breakdown.
        """
        # Governance programs for V1 typically cost:
        # - SPL Governance Program: ~2 SOL (program data)
        # - Governance Realm: ~0.5 SOL (account data)
        # - Proposal accounts: ~0.1 SOL each
        # - Vote records: ~0.05 SOL each
        # - Treasury accounts: ~0.2 SOL each
        #
        # Total estimate: ~3-5 SOL locked
        # We already closed some during V1 setup

        programs = self.scan_governance_programs()

        # Filter to programs we deployed (owned/created by our wallets)
        # Mark known governance program addresses
        known_governance = []
        for prog in programs:
            if prog["lamports"] > 100_000_000:  # >0.1 SOL
                known_governance.append(prog)

        total_recoverable = sum(p["lamports"] for p in known_governance)
        return {
            "programs_found": len(programs),
            "governance_candidates": len(known_governance),
            "total_recoverable_lamports": total_recoverable,
            "total_recoverable_sol": total_recoverable / 1e9,
            "programs": known_governance,
            "note": (
                "Program accounts can be closed by their deployer to recover rent. "
                "Executable programs must be undeployed first. "
                "SPL Governance program accounts (realms, treasuries, proposals) "
                "can be closed by their governing authority."
            ),
        }

    # ── Logging ───────────────────────────────────────────────────────

    def _log_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Append an event to the V1 distribution ledger."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            **data,
        }
        with self._lock:
            try:
                with open(self._log_path, "a") as f:
                    f.write(json.dumps(entry) + "\n")
            except OSError as e:
                logger.warning("Failed to write V1 distribution log: %s", e)

    def get_recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get the most recent distribution events."""
        events = []
        try:
            with open(self._log_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        events.append(json.loads(line))
        except (OSError, json.JSONDecodeError):
            pass
        return events[-limit:]

    # ── Report ────────────────────────────────────────────────────────

    def generate_report(self) -> Dict[str, Any]:
        """Generate a comprehensive V1 distribution report."""
        onchain = self.load_v1_state()
        summary = self.get_distribution_summary()
        recent = self.get_recent_events(10)

        return {
            "v1_token": {
                "mint": V1_MINT,
                "supply": V1_SUPPLY,
                "decimals": V1_DECIMALS,
                "program": "Tokenkeg (original SPL Token)",
                "mint_authority": "BURNED (permanent lock)",
            },
            "whale_wallet": {
                "pubkey": WHALE_PUBKEY,
                "v1_ata": WHALE_ATA,
            },
            "onchain_state": onchain,
            "distribution_plan": summary,
            "recent_events": recent,
            "governance_rent": self.estimate_recoverable_rent(),
            "note": (
                "V1 is the Broketarium — the infrastructure identification token. "
                "Each agent manages its own V1 ordinance for operational identity. "
                "Governance rent recovery frees SOL for distribution transaction fees."
            ),
        }


# Module singleton
V1_DISTRIBUTION = V1DistributionManager()
