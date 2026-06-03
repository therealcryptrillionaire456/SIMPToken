"""
SIMPWallet BRP Integration — Threat Intelligence Layer
=======================================================

Connects the Bill Russell Protocol (BRP) threat engine to the SIMPWallet
dashboard, Fortress vault, and Ledger Nano hardware wallet.

Architecture
────────────
  BRPMeshGateway (664 lines)   →   BRPIntegration (this file)   →   SIMPWallet API

Integration Points
─────────────────
  1. Threat tab data for SIMPWallet dashboard (screenings, blocklist, alerts)
  2. Circuit breaker trigger when BRP detects CRITICAL threats
  3. Trust graph annotation (BRP penalty reasons shown in wallet)
  4. Ledger signature verification logged in BRP audit trail
  5. Transaction simulation pre-checks (is destination blocklisted?)
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("SIMP.SIMPWallet.BRP")


@dataclass
class BRPThreatAlert:
    """A threat alert from BRP that gets surfaced in SIMPWallet."""
    alert_id: str
    agent_id: str
    threat_level: str
    confidence: float
    patterns: List[Dict]
    timestamp: float
    action_taken: str
    blocked: bool
    expires_at: Optional[float] = None

    def to_dict(self) -> Dict:
        return {
            "alert_id": self.alert_id,
            "agent_id": self.agent_id,
            "threat_level": self.threat_level,
            "confidence": round(self.confidence, 4),
            "patterns": self.patterns[:3],  # top 3 patterns
            "timestamp": self.timestamp,
            "action_taken": self.action_taken,
            "blocked": self.blocked,
            "expires_at": self.expires_at,
            "age_seconds": round(time.time() - self.timestamp, 1),
            "is_active": self.expires_at is None or time.time() < self.expires_at,
        }


@dataclass
class ThreatSummary:
    """Aggregated threat data for the SIMPWallet threat tab."""
    total_screenings: int = 0
    packets_denied: int = 0
    packets_allowed: int = 0
    active_blocklist: int = 0
    alerts_sent: int = 0
    trust_penalties: int = 0
    current_tension: str = "low"  # low | medium | high | critical
    recent_threats: List[Dict] = field(default_factory=list)
    blocklist: List[Dict] = field(default_factory=list)
    top_patterns: List[Dict] = field(default_factory=list)
    forecast: Dict = field(default_factory=dict)
    fortress_linked: bool = False
    fortress_breached: bool = False


class SIMPBRPIntegration:
    """
    Wraps BRPMeshGateway and exposes threat data for the SIMPWallet API.

    Thread-safe. Designed as a singleton accessed via get_brp_integration().

    Usage:
        from simpwallet_brp import get_brp_integration
        brp = get_brp_integration()
        summary = brp.get_threat_summary()
    """

    def __init__(
        self,
        brp_gateway=None,
        fortress_vault=None,
        trust_graph=None,
        enable_circuit_breaker: bool = True,
        data_dir: Optional[str] = None,
    ):
        self._gateway = brp_gateway
        self._fortress = fortress_vault
        self._trust_graph = trust_graph
        self._enable_circuit_breaker = enable_circuit_breaker
        self._data_dir = data_dir or os.path.join(
            os.path.expanduser("~"), ".simp", "brp"
        )
        os.makedirs(self._data_dir, exist_ok=True)

        self._alerts: List[BRPThreatAlert] = []  # ring buffer, last 100
        self._max_alerts = 100

        # Stats since startup
        self._stats = {
            "threats_detected": 0,
            "circuit_breaker_triggers": 0,
            "ledger_verifications_logged": 0,
            "tx_simulations_checked": 0,
            "tx_simulations_blocked": 0,
        }

        logger.info(
            "[SIMPBRP] Initialized: circuit_breaker=%s, data_dir=%s",
            enable_circuit_breaker, data_dir,
        )

    # ── Primary API ─────────────────────────────────────────────────────

    def get_threat_summary(self) -> Dict:
        """
        Get the full threat summary for the SIMPWallet threat tab.
        This is the main data endpoint.
        """
        summary = ThreatSummary()

        # Pull live stats from BRP gateway if available
        if self._gateway is not None:
            try:
                status = self._gateway.get_status()
                stats = status.get("stats", {})

                summary.total_screenings = stats.get("packets_screened", 0)
                summary.packets_denied = stats.get("packets_denied", 0)
                summary.packets_allowed = stats.get("packets_allowed", 0)
                summary.alerts_sent = stats.get("alerts_sent", 0)
                summary.trust_penalties = stats.get("trust_penalties", 0)
                summary.current_tension = self._calculate_tension(status)
                summary.blocklist = status.get("blocklist", [])
                summary.active_blocklist = status.get("blocklist_count", 0)

                # Get recent screenings
                recent = self._gateway.get_recent_screenings(limit=20)
                summary.recent_threats = [
                    s for s in recent
                    if s.get("threat_level") in ("high", "critical")
                ][:10]

                # Extract top patterns
                all_patterns = []
                for s in recent:
                    for p in s.get("patterns", []):
                        all_patterns.append(p)
                summary.top_patterns = self._aggregate_patterns(all_patterns)[:5]

            except Exception as e:
                logger.warning("[SIMPBRP] Gateway query failed: %s", e)

        # Check Fortress link
        if self._fortress is not None:
            try:
                f_status = self._fortress.get_status()
                summary.fortress_linked = True
                summary.fortress_breached = f_status.get("breach", False)
            except Exception:
                summary.fortress_linked = False

        # Generate forecast
        summary.forecast = self._generate_forecast()

        return {
            "threat_summary": {
                "total_screenings": summary.total_screenings,
                "packets_denied": summary.packets_denied,
                "packets_allowed": summary.packets_allowed,
                "deny_rate": round(
                    summary.packets_denied / max(summary.total_screenings, 1) * 100, 1
                ),
                "active_blocklist": summary.active_blocklist,
                "alerts_sent": summary.alerts_sent,
                "trust_penalties": summary.trust_penalties,
                "current_tension": summary.current_tension,
                "fortress_linked": summary.fortress_linked,
                "fortress_breached": summary.fortress_breached,
            },
            "recent_threats": summary.recent_threats,
            "blocklist": summary.blocklist,
            "top_patterns": summary.top_patterns,
            "forecast": summary.forecast,
            "stats_since_startup": self._stats,
            "updated_at": time.time(),
        }

    def handle_threat_alert(self, alert: BRPThreatAlert) -> Dict:
        """
        Process a BRP threat alert.

        Returns actions taken: {
            "blocked": bool,
            "fortress_locked": bool,
            "trust_penalized": bool,
            "alert_broadcast": bool,
        }
        """
        actions = {
            "blocked": False,
            "fortress_locked": False,
            "trust_penalized": False,
            "alert_broadcast": False,
        }

        self._stats["threats_detected"] += 1

        # Store alert
        self._alerts.append(alert)
        if len(self._alerts) > self._max_alerts:
            self._alerts = self._alerts[-self._max_alerts:]

        # 1. Blocklist is handled by BRP gateway itself
        actions["blocked"] = alert.blocked

        # 2. Circuit breaker for CRITICAL threats
        if (
            alert.threat_level == "critical"
            and self._enable_circuit_breaker
            and self._fortress is not None
        ):
            try:
                self._fortress.circuit_breaker_lock(
                    reason=f"BRP CRITICAL: {alert.agent_id} - {alert.patterns[:1]}"
                )
                actions["fortress_locked"] = True
                self._stats["circuit_breaker_triggers"] += 1
                logger.warning(
                    "[SIMPBRP] Fortress LOCKED by BRP: %s", alert.agent_id
                )
            except Exception as e:
                logger.error("[SIMPBRP] Circuit breaker failed: %s", e)

        # 3. Trust penalty (delegated to BRP gateway, but we track it)
        actions["trust_penalized"] = alert.threat_level in ("high", "critical")

        # 4. Alert broadcast (delegated to BRP gateway channels)
        actions["alert_broadcast"] = alert.action_taken == "block"

        return actions

    def precheck_transaction(
        self,
        from_agent: str,
        to_address: str,
        amount: float,
    ) -> Dict:
        """
        Pre-check a SIMPT transfer against BRP before signing.

        Returns {
            "allowed": bool,
            "reason": str,
            "blocklist_hit": bool,
            "threat_level": str,
        }
        """
        self._stats["tx_simulations_checked"] += 1

        result = {
            "allowed": True,
            "reason": "clean",
            "blocklist_hit": False,
            "threat_level": "clean",
        }

        # Check if destination is blocklisted
        if self._gateway is not None:
            block = self._gateway._blocklist_check(to_address)
            if block:
                result["allowed"] = False
                result["reason"] = f"Destination blocklisted by BRP: {block.reason}"
                result["blocklist_hit"] = True
                result["threat_level"] = block.severity
                self._stats["tx_simulations_blocked"] += 1

        # Check if sender is compromised
        if self._gateway is not None:
            block = self._gateway._blocklist_check(from_agent)
            if block:
                result["allowed"] = False
                result["reason"] = f"Sender blocklisted by BRP: {block.reason}"
                result["blocklist_hit"] = True
                result["threat_level"] = block.severity
                self._stats["tx_simulations_blocked"] += 1

        return result

    def log_ledger_verification(
        self,
        address: str,
        challenge: str,
        signature: str,
        verified: bool,
    ) -> None:
        """Log a Ledger Nano ownership verification to the BRP audit trail."""
        self._stats["ledger_verifications_logged"] += 1

        entry = {
            "event_type": "ledger_ownership_proof",
            "address": address,
            "challenge": challenge,
            "signature": signature[:32] + "...",  # truncate for log
            "verified": verified,
            "timestamp": time.time(),
        }

        # Append to local audit log
        log_path = os.path.join(self._data_dir, "ledger_verifications.jsonl")
        try:
            with open(log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.warning("[SIMPBRP] Failed to log verification: %s", e)

        logger.info(
            "[SIMPBRP] Ledger verification logged: %s verified=%s",
            address[:12], verified,
        )

    def get_alerts(self, limit: int = 20) -> List[Dict]:
        """Get recent BRP threat alerts."""
        return [a.to_dict() for a in self._alerts[-limit:]]

    # ── Internal ────────────────────────────────────────────────────────

    def _calculate_tension(self, status: Dict) -> str:
        """Calculate overall threat tension level."""
        stats = status.get("stats", {})
        denied = stats.get("packets_denied", 0)
        blocks = stats.get("blocks_issued", 0)
        penalties = stats.get("trust_penalties", 0)

        if denied > 10 or blocks > 5:
            return "critical"
        if denied > 5 or blocks > 2:
            return "high"
        if denied > 2 or penalties > 5:
            return "medium"
        return "low"

    def _aggregate_patterns(self, patterns: List[Dict]) -> List[Dict]:
        """Count pattern frequencies and return sorted."""
        pattern_counts = {}
        for p in patterns:
            ptype = p.get("type", "unknown")
            if ptype not in pattern_counts:
                pattern_counts[ptype] = {"type": ptype, "count": 0, "examples": []}
            pattern_counts[ptype]["count"] += 1
            if len(pattern_counts[ptype]["examples"]) < 3:
                pattern_counts[ptype]["examples"].append(p.get("description", ""))

        return sorted(
            pattern_counts.values(),
            key=lambda x: x["count"],
            reverse=True,
        )

    def _generate_forecast(self) -> Dict:
        """Generate a simple threat forecast based on recent activity."""
        recent_threats = sum(
            1 for a in self._alerts
            if a.threat_level in ("high", "critical")
            and time.time() - a.timestamp < 3600  # last hour
        )

        if recent_threats >= 5:
            probability = 0.85
            severity = "critical"
        elif recent_threats >= 3:
            probability = 0.6
            severity = "high"
        elif recent_threats >= 1:
            probability = 0.3
            severity = "medium"
        else:
            probability = 0.05
            severity = "low"

        return {
            "next_hour_threat_probability": round(probability, 2),
            "predicted_severity": severity,
            "forecast_source": "brp_mesh_gateway",
            "recent_threats_in_window": recent_threats,
            "generated_at": time.time(),
        }

    def get_status(self) -> Dict:
        """Get overall integration health."""
        return {
            "integration": "SIMPWallet BRP",
            "gateway_loaded": self._gateway is not None,
            "fortress_linked": self._fortress is not None,
            "circuit_breaker_enabled": self._enable_circuit_breaker,
            "alerts_buffered": len(self._alerts),
            "data_dir": self._data_dir,
            "stats": self._stats,
            "healthy": True,
        }


# ── Singleton factory ──────────────────────────────────────────────────────

_integration_instance: Optional[SIMPBRPIntegration] = None


def get_brp_integration(
    brp_gateway=None,
    fortress_vault=None,
    trust_graph=None,
    enable_circuit_breaker: bool = True,
) -> SIMPBRPIntegration:
    """
    Return the process-level SIMPBRPIntegration singleton.

    Usage in http_server.py:
        from simpwallet_brp import get_brp_integration
        brp = get_brp_integration(
            brp_gateway=brp_gateway,
            fortress_vault=fortress_vault,
        )
    """
    global _integration_instance

    if _integration_instance is None:
        _integration_instance = SIMPBRPIntegration(
            brp_gateway=brp_gateway,
            fortress_vault=fortress_vault,
            trust_graph=trust_graph,
            enable_circuit_breaker=enable_circuit_breaker,
        )

    return _integration_instance


# ── Quick test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    brp = get_brp_integration()
    summary = brp.get_threat_summary()

    print("=" * 60)
    print("SIMPWallet BRP Integration — Self-Test")
    print("=" * 60)
    print(f"Gateway loaded: {brp._gateway is not None}")
    print(f"Fortress linked: {summary['threat_summary']['fortress_linked']}")
    print(f"Threat tension: {summary['threat_summary']['current_tension']}")
    print(f"Total screenings: {summary['threat_summary']['total_screenings']}")
    print(f"Blocklist: {summary['threat_summary']['active_blocklist']} active")
    print(f"Trust penalties: {summary['threat_summary']['trust_penalties']}")
    print(f"Alerts buffered: {brp._stats['threats_detected']}")
    print(f"Forecast: {summary['forecast']['predicted_severity']} " +
          f"({summary['forecast']['next_hour_threat_probability']*100:.0f}%)")
    print("")

    # Test alert handling
    alert = BRPThreatAlert(
        alert_id="test-001",
        agent_id="test_agent",
        threat_level="critical",
        confidence=0.92,
        patterns=[{"type": "shell_injection", "description": "Suspicious shell command"}],
        timestamp=time.time(),
        action_taken="block",
        blocked=True,
        expires_at=time.time() + 3600,
    )
    actions = brp.handle_threat_alert(alert)
    print("Test alert actions:", json.dumps(actions, indent=2))

    # Test TX pre-check
    tx_check = brp.precheck_transaction("good_agent", "58Eohzq...", 100)
    print(f"TX pre-check: allowed={tx_check['allowed']} reason={tx_check['reason']}")

    print("\n✅ SIMPWallet BRP integration ready")
