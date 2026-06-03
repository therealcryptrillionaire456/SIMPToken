"""
PENTAGON — The Dual-Token Architecture Document
=================================================

The Pentagram is the architectural blueprint of the SIMP token system.
It defines two tokens, two layers, and one infrastructure.

Reference: Ripple Labs dual-token model
  - XRP  = Public market token → V2 SIMPT
  - XRPL = Internal infrastructure token → V1 SIMPT (The Broketarium)

V1 is not burnable. V1 is not tradable. V1 identifies the PTAI/SIMP
infrastructure and can never be held or owned by any outside agent or agency.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("SIMP.Pentagon")


# ── Pentagram Elements ─────────────────────────────────────────────────────

ELEMENTS = {
    "electro": {
        "token": "v1",
        "role": "ground",
        "color": "#00FF88",
        "description": (
            "The Broketarium — infrastructure identification token. "
            "V1 is the digital ground of the PTAI/SIMP mesh. "
            "It has no external value. It authenticates the network itself."
        ),
        "immutable": True,
        "transferable": False,  # cannot leave the mesh
    },
    "aether": {
        "token": "v2",
        "role": "economy",
        "color": "#FFD700",
        "description": (
            "The SIMPT market token — agent economy fuel. "
            "V2 is the public-facing token for value transfer, "
            "agent compensation, and mesh transactions."
        ),
        "immutable": True,
        "transferable": True,
    },
    "ignis": {
        "token": None,
        "role": "action",
        "color": "#FF4444",
        "description": (
            "The fire of intent routing. Ignis is not a token — "
            "it is the energy that flows through the mesh when "
            "agents transact. It represents intent throughput."
        ),
        "immutable": True,
        "transferable": False,
    },
    "aqua": {
        "token": None,
        "role": "liquidity",
        "color": "#4488FF",
        "description": (
            "The flow of value through the mesh. Aqua represents "
            "the liquidity pools, fee sinks, and staking reserves "
            "that keep the economy liquid."
        ),
        "immutable": False,
        "transferable": True,
    },
    "terra": {
        "token": None,
        "role": "record",
        "color": "#88AA44",
        "description": (
            "The ledger itself. Terra is the permanent record "
            "of all intent flows, token transfers, and agent "
            "interactions. It is the truth."
        ),
        "immutable": True,
        "transferable": False,
    },
}


@dataclass
class PentagramElement:
    """One point of the five-pointed star."""
    name: str
    token: Optional[str]
    role: str
    color: str
    description: str
    immutable: bool
    transferable: bool


@dataclass
class PentagonDocument:
    """The Pentagram — full architecture specification."""

    title: str = "The SIMP Pentagram"
    version: str = "2.0.0"
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    elements: Dict[str, PentagramElement] = field(default_factory=lambda: {
        name: PentagramElement(name=name, **props)
        for name, props in ELEMENTS.items()
    })

    dual_token_map: Dict[str, Dict[str, Any]] = field(default_factory=lambda: {
        "v1": {
            "mint": "CHmgojCz8Pk5qgD8nkiiCZvHkZfpfUoYn47aUqWNDZMt",
            "symbol": "SIMPTv1",
            "role": "ground (infrastructure ID)",
            "element": "electro",
            "mint_authority": "REVOKED",
            "supply": 999_999_000,
            "external_value": 0,
            "holder_restriction": "MESH_INTERNAL_ONLY",
            "comparable_to": "XRPL (Ripple Labs internal token)",
            "philosophy": (
                "Just as Ripple Labs holds an internal token that "
                "authenticates their network infrastructure, V1 SIMPT "
                "is the Broketarium — the token that proves the mesh "
                "is the real mesh. It maps to the electro element of "
                "the Pentagram and is the heartbeat of the agent ecosystem."
            ),
        },
        "v2": {
            "mint": "6QxRa9aeCidptKS8CS2uenbQiy5enHR7eMMY29mghZNW",
            "symbol": "SIMPT",
            "role": "economy (market token)",
            "element": "aether",
            "mint_authority": "DISABLED",
            "supply": 1_000_000_000,
            "external_value": None,
            "holder_restriction": "OPEN",
            "comparable_to": "XRP (Ripple Labs market token)",
            "philosophy": (
                "V2 is the fuel of the agent economy. It is traded, "
                "transferred, and used for value exchange between "
                "agents. It is the visible token that the world sees."
            ),
        },
    })

    laws: List[str] = field(default_factory=lambda: [
        "LAW 1 — V1 is the ground. V1 supply is fixed at 999,999,000. "
        "It will never change. It identifies the infrastructure.",
        "LAW 2 — V2 is the economy. V2 supply is fixed at 1,000,000,000. "
        "It fuels agent transactions and mesh operations.",
        "LAW 3 — V1 cannot be held by external agents. No route, no "
        "transfer, no contract allows V1 to leave the mesh.",
        "LAW 4 — The Pentagram has five elements: electro, aether, ignis, "
        "aqua, terra. Each maps to a token or function.",
        "LAW 5 — The heartbeat carries both tokens. Every agent "
        "registration includes V1 as the infrastructure identifier.",
        "LAW 6 — Neither token can be burned. Supply is permanent. "
        "Value is created through utility, not scarcity.",
    ])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "version": self.version,
            "created": self.created,
            "elements": {
                name: asdict(el) for name, el in self.elements.items()
            },
            "dual_token_map": self.dual_token_map,
            "laws": self.laws,
            "pentagram_visual": self._render_pentagram(),
        }

    def _render_pentagram(self) -> str:
        return """
                          ╔═══════════════════╗
                          ║  ELECTRO (V1)     ║
                          ║  Ground / Infra   ║
                          ║  Token: SIMPTv1   ║
                          ╚═══════════════════╝
                                ║
              ┌─────────────────╫─────────────────┐
              ║                 ║                 ║
   ╔═══════════════╗   ╔═══════════════╗   ╔═══════════════╗
   ║  AETHER (V2)  ║───║  IGNIS        ║───║  AQUA         ║
   ║  Economy      ║   ║  Intent Flow  ║   ║  Liquidity    ║
   ║  Token: SIMPT ║   ║  (No Token)   ║   ║  (Pools)      ║
   ╚═══════════════╝   ╚═══════════════╝   ╚═══════════════╝
        ║                                         ║
        ╚═════════════╦═════════════════╗         ║
                      ║                 ║         ║
              ╔═══════════════════════════════════════╗
              ║  TERRA (Ledger / Permanent Record)    ║
              ╚═══════════════════════════════════════╝
        """


# Singleton
PENTAGON_DOCUMENT = PentagonDocument()
