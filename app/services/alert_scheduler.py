"""Alert scheduler for P1-20: Account monitoring alerts."""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from uuid import UUID

from loguru import logger
from pydantic import BaseModel, Field

from core.config import settings
from services.account_monitor import account_monitor


class AlertRule(BaseModel):
    """Alert rule configuration."""

    name: str = Field(..., description="Alert rule name")
    enabled: bool = Field(default=True, description="Whether the rule is enabled")
    condition: str = Field(..., description="Condition expression")
    severity: str = Field(default="warning", description="Alert severity: info, warning, error, critical")
    description: str = Field(..., description="Alert description")
    cooldown_minutes: int = Field(default=60, description="Cooldown period in minutes")


class Alert(BaseModel):
    """Alert instance."""

    id: str
    rule_name: str
    account_id: str
    severity: str
    message: str
    triggered_at: str
    resolved: bool = False
    resolved_at: Optional[str] = None


class AlertScheduler:
    """Scheduler for account monitoring alerts."""

    def __init__(
        self,
        check_interval: int = 60,
        alert_rules_path: Optional[str] = None,
    ):
        self.check_interval = check_interval
        self.alert_rules_path = alert_rules_path or "config/alert_rules.json"

        self._lock = asyncio.Lock()
        self._running = False
        self._check_task: Optional[asyncio.Task] = None

        self.alert_rules: List[AlertRule] = []
        self.active_alerts: Dict[str, Alert] = {}
        self.alert_history: List[Alert] = []

    async def start(self):
        """Start alert scheduler."""
        if self._running:
            logger.warning("Alert scheduler already running")
            return

        self._running = True
        logger.info("Starting alert scheduler")

        # Load alert rules
        await self._load_alert_rules()

        # Start check task
        self._check_task = asyncio.create_task(self._check_loop())

    async def stop(self):
        """Stop alert scheduler."""
        if not self._running:
            return

        logger.info("Stopping alert scheduler")
        self._running = False

        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass

        logger.info("Alert scheduler stopped")

    async def _check_loop(self):
        """Periodically check for alert conditions."""
        while self._running:
            try:
                await asyncio.sleep(self.check_interval)
                await self._check_alert_conditions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in alert check loop: {e}")

    async def _load_alert_rules(self):
        """Load alert rules from configuration file."""
        try:
            rules_path = Path(self.alert_rules_path)
            if not rules_path.exists():
                logger.warning(f"Alert rules file not found: {self.alert_rules_path}")
                # Create default rules
                await self._create_default_rules()
                return

            with open(rules_path, 'r', encoding='utf-8') as f:
                rules_data = json.load(f)

            self.alert_rules = [AlertRule(**rule) for rule in rules_data.get("rules", [])]
            logger.info(f"Loaded {len(self.alert_rules)} alert rules")

        except Exception as e:
            logger.error(f"Error loading alert rules: {e}")
            # Create default rules on error
            await self._create_default_rules()

    async def _create_default_rules(self):
        """Create default alert rules."""
        default_rules = [
            {
                "name": "account_banned",
                "enabled": True,
                "condition": "is_banned == true",
                "severity": "critical",
                "description": "Account has been banned",
                "cooldown_minutes": 60,
            },
            {
                "name": "account_offline",
                "enabled": True,
                "condition": "is_connected == false and is_banned == false",
                "severity": "warning",
                "description": "Account is offline",
                "cooldown_minutes": 30,
            },
            {
                "name": "high_error_rate",
                "enabled": True,
                "condition": "error_rate > 0.5",
                "severity": "error",
                "description": "Account error rate exceeds 50%",
                "cooldown_minutes": 15,
            },
            {
                "name": "low_success_rate",
                "enabled": True,
                "condition": "send_success_rate < 0.8 and is_connected == true",
                "severity": "warning",
                "description": "Account send success rate below 80%",
                "cooldown_minutes": 20,
            },
        ]

        self.alert_rules = [AlertRule(**rule) for rule in default_rules]
        logger.info(f"Created {len(self.alert_rules)} default alert rules")

    async def _check_alert_conditions(self):
        """Check all alert conditions against current account stats."""
        try:
            stats = await account_monitor.get_all_accounts_stats()

            for stat in stats:
                await self._check_account_alerts(stat)

            # Check for resolved alerts
            await self._check_resolved_alerts(stats)

        except Exception as e:
            logger.error(f"Error checking alert conditions: {e}")

    async def _check_account_alerts(self, stat: dict):
        """Check alert conditions for a specific account."""
        account_id = stat["account_id"]

        for rule in self.alert_rules:
            if not rule.enabled:
                continue

            try:
                # Check if alert is already active and in cooldown
                alert_key = f"{account_id}_{rule.name}"
                if alert_key in self.active_alerts:
                    existing_alert = self.active_alerts[alert_key]
                    # Check cooldown
                    triggered_at = datetime.fromisoformat(existing_alert.triggered_at)
                    cooldown_expiry = triggered_at + timedelta(minutes=rule.cooldown_minutes)
                    if datetime.utcnow() < cooldown_expiry:
                        continue  # Still in cooldown

                # Evaluate condition
                if self._evaluate_condition(rule.condition, stat):
                    await self._trigger_alert(rule, stat)

            except Exception as e:
                logger.error(f"Error evaluating rule {rule.name} for account {account_id}: {e}")

    def _evaluate_condition(self, condition: str, context: dict) -> bool:
        """Evaluate a condition expression against context."""
        try:
            # Simple condition evaluation (for production, use a safer eval alternative)
            # This is a simplified version - in production, use a proper expression parser
            result = eval(condition, {}, context)
            return bool(result)
        except Exception as e:
            logger.error(f"Error evaluating condition '{condition}': {e}")
            return False

    async def _trigger_alert(self, rule: AlertRule, stat: dict):
        """Trigger an alert."""
        account_id = stat["account_id"]
        alert_key = f"{account_id}_{rule.name}"

        alert = Alert(
            id=f"{alert_key}_{datetime.utcnow().timestamp()}",
            rule_name=rule.name,
            account_id=account_id,
            severity=rule.severity,
            message=f"{rule.description} (Account: {stat['phone']})",
            triggered_at=datetime.utcnow().isoformat(),
        )

        self.active_alerts[alert_key] = alert
        self.alert_history.append(alert)

        logger.warning(f"Alert triggered: {rule.name} for account {account_id} - {alert.message}")

        # Here you could integrate with notification systems (email, Slack, etc.)
        await self._send_alert_notification(alert)

    async def _check_resolved_alerts(self, current_stats: List[dict]):
        """Check if any active alerts have been resolved."""
        to_resolve = []

        for alert_key, alert in self.active_alerts.items():
            account_id = alert.account_id

            # Find current stats for this account
            current_stat = None
            for stat in current_stats:
                if stat["account_id"] == account_id:
                    current_stat = stat
                    break

            if not current_stat:
                continue

            # Find the rule for this alert
            rule = None
            for r in self.alert_rules:
                if r.name == alert.rule_name:
                    rule = r
                    break

            if not rule:
                continue

            # Check if condition is no longer met
            if not self._evaluate_condition(rule.condition, current_stat):
                to_resolve.append(alert_key)

        # Resolve alerts
        for alert_key in to_resolve:
            alert = self.active_alerts.pop(alert_key)
            alert.resolved = True
            alert.resolved_at = datetime.utcnow().isoformat()
            logger.info(f"Alert resolved: {alert.rule_name} for account {alert.account_id}")

    async def _send_alert_notification(self, alert: Alert):
        """Send alert notification (placeholder for actual notification integration)."""
        # This is a placeholder - integrate with your notification system
        # Examples: email, Slack, PagerDuty, etc.
        logger.info(f"Notification would be sent for alert: {alert.message}")

    async def get_active_alerts(self) -> List[Alert]:
        """Get all active alerts."""
        return list(self.active_alerts.values())

    async def get_alert_history(self, limit: int = 100) -> List[Alert]:
        """Get alert history."""
        return self.alert_history[-limit:]

    async def get_alert_rules(self) -> List[AlertRule]:
        """Get current alert rules."""
        return self.alert_rules

    async def reload_alert_rules(self):
        """Reload alert rules from configuration file."""
        await self._load_alert_rules()
        logger.info("Alert rules reloaded")


# Global instance
alert_scheduler = AlertScheduler(
    check_interval=getattr(settings, "ALERT_SCHEDULER_CHECK_INTERVAL", 60),
    alert_rules_path=getattr(settings, "ALERT_RULES_PATH", "config/alert_rules.json"),
)
