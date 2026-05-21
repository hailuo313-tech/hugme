"""Account monitoring service for P1-20: Account online rate and send success rate monitoring."""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from uuid import UUID

from loguru import logger
from prometheus_client import Counter, Gauge, Histogram, start_http_server
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import get_async_session
from models.telegram_accounts import TelegramAccount
from services.telegram_account_manager import telegram_account_manager


class AccountMonitor:
    """Monitor Telegram accounts for online rate and send success rate."""

    def __init__(
        self,
        metrics_port: int = 9091,
        collection_interval: int = 60,
        history_retention_hours: int = 24,
    ):
        self.metrics_port = metrics_port
        self.collection_interval = collection_interval
        self.history_retention_hours = history_retention_hours

        self._lock = asyncio.Lock()
        self._running = False
        self._collection_task: Optional[asyncio.Task] = None

        # Account statistics cache
        self.account_stats: Dict[UUID, dict] = {}

        # Prometheus metrics
        self._setup_prometheus_metrics()

    def _setup_prometheus_metrics(self):
        """Setup Prometheus metrics for account monitoring."""
        # Account online status
        self.account_online: Gauge = Gauge(
            'eris_telegram_account_online',
            'Telegram account online status (1=online, 0=offline)',
            ['account_id', 'phone']
        )

        # Account connection duration
        self.account_connection_duration: Gauge = Gauge(
            'eris_telegram_account_connection_duration_seconds',
            'Telegram account connection duration in seconds',
            ['account_id', 'phone']
        )

        # Message send attempts
        self.message_send_attempts: Counter = Counter(
            'eris_telegram_message_send_attempts_total',
            'Total message send attempts',
            ['account_id', 'phone', 'status']
        )

        # Message send success rate
        self.message_send_success_rate: Gauge = Gauge(
            'eris_telegram_message_send_success_rate',
            'Message send success rate (0-1)',
            ['account_id', 'phone']
        )

        # Account banned status
        self.account_banned: Gauge = Gauge(
            'eris_telegram_account_banned',
            'Telegram account banned status (1=banned, 0=active)',
            ['account_id', 'phone']
        )

        # Account error rate
        self.account_error_rate: Gauge = Gauge(
            'eris_telegram_account_error_rate',
            'Account error rate in last hour',
            ['account_id', 'phone']
        )

        # Collection duration
        self.collection_duration: Histogram = Histogram(
            'eris_account_monitor_collection_duration_seconds',
            'Account monitor collection duration'
        )

    async def start(self):
        """Start account monitoring service."""
        if self._running:
            logger.warning("Account monitor already running")
            return

        self._running = True
        logger.info(f"Starting account monitor on port {self.metrics_port}")

        # Start Prometheus metrics server
        try:
            start_http_server(self.metrics_port)
            logger.info(f"Prometheus metrics server started on port {self.metrics_port}")
        except Exception as e:
            logger.error(f"Failed to start Prometheus metrics server: {e}")

        # Start collection task
        self._collection_task = asyncio.create_task(self._collection_loop())

    async def stop(self):
        """Stop account monitoring service."""
        if not self._running:
            return

        logger.info("Stopping account monitor")
        self._running = False

        if self._collection_task:
            self._collection_task.cancel()
            try:
                await self._collection_task
            except asyncio.CancelledError:
                pass

        logger.info("Account monitor stopped")

    async def _collection_loop(self):
        """Periodically collect account statistics."""
        while self._running:
            try:
                await asyncio.sleep(self.collection_interval)
                await self._collect_account_stats()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in collection loop: {e}")

    async def _collect_account_stats(self):
        """Collect statistics for all accounts."""
        import time
        start_time = time.time()

        try:
            async with self._lock:
                accounts = await telegram_account_manager.get_active_accounts()

                for account in accounts:
                    stats = await self._get_account_stats(account)
                    self.account_stats[account.id] = stats
                    self._update_prometheus_metrics(account, stats)

                # Clean up old stats
                self._cleanup_old_stats()

            duration = time.time() - start_time
            logger.debug(f"Account stats collection completed in {duration:.2f}s")

        except Exception as e:
            logger.error(f"Error collecting account stats: {e}")

    async def _get_account_stats(self, account: TelegramAccount) -> dict:
        """Get statistics for a single account."""
        is_connected = account.id in telegram_account_manager.clients

        # Calculate connection duration
        connection_duration = 0
        if account.last_connected_at:
            connection_duration = (datetime.utcnow() - account.last_connected_at).total_seconds()

        # Calculate error rate (errors in last hour)
        error_rate = await self._calculate_error_rate(account.id)

        # Calculate send success rate
        success_rate = await self._calculate_send_success_rate(account.id)

        return {
            "account_id": str(account.id),
            "phone": account.phone,
            "status": account.status,
            "is_connected": is_connected,
            "is_banned": account.status == "banned",
            "connection_duration": connection_duration,
            "last_connected_at": account.last_connected_at.isoformat() if account.last_connected_at else None,
            "last_error_at": account.last_error_at.isoformat() if account.last_error_at else None,
            "error_message": account.error_message,
            "error_rate": error_rate,
            "send_success_rate": success_rate,
            "collected_at": datetime.utcnow().isoformat(),
        }

    async def _calculate_error_rate(self, account_id: UUID) -> float:
        """Calculate error rate for an account (errors in last hour)."""
        try:
            # This would typically query a message/send log table
            # For now, we'll use the account's error status as a proxy
            account = await telegram_account_manager.get_account(account_id)
            if not account:
                return 0.0

            # If account has recent error, return high error rate
            if account.last_error_at:
                hours_since_error = (datetime.utcnow() - account.last_error_at).total_seconds() / 3600
                if hours_since_error < 1:
                    return 1.0
                elif hours_since_error < 24:
                    return 1.0 - (hours_since_error / 24)

            return 0.0
        except Exception as e:
            logger.error(f"Error calculating error rate for account {account_id}: {e}")
            return 0.0

    async def _calculate_send_success_rate(self, account_id: UUID) -> float:
        """Calculate send success rate for an account."""
        try:
            # This would typically query a message log table
            # For now, we'll use the account's connection status as a proxy
            is_connected = account_id in telegram_account_manager.clients

            if is_connected:
                return 1.0  # Connected accounts assumed to have good success rate
            else:
                return 0.0  # Disconnected accounts have 0 success rate

        except Exception as e:
            logger.error(f"Error calculating success rate for account {account_id}: {e}")
            return 0.0

    def _update_prometheus_metrics(self, account: TelegramAccount, stats: dict):
        """Update Prometheus metrics for an account."""
        try:
            account_id_str = str(account.id)
            phone = account.phone

            # Account online status
            self.account_online.labels(account_id=account_id_str, phone=phone).set(
                1 if stats["is_connected"] else 0
            )

            # Connection duration
            self.account_connection_duration.labels(account_id=account_id_str, phone=phone).set(
                stats["connection_duration"]
            )

            # Banned status
            self.account_banned.labels(account_id=account_id_str, phone=phone).set(
                1 if stats["is_banned"] else 0
            )

            # Error rate
            self.account_error_rate.labels(account_id=account_id_str, phone=phone).set(
                stats["error_rate"]
            )

            # Send success rate
            self.message_send_success_rate.labels(account_id=account_id_str, phone=phone).set(
                stats["send_success_rate"]
            )

        except Exception as e:
            logger.error(f"Error updating Prometheus metrics for account {account.id}: {e}")

    def _cleanup_old_stats(self):
        """Clean up old statistics beyond retention period."""
        cutoff_time = datetime.utcnow() - timedelta(hours=self.history_retention_hours)

        to_remove = []
        for account_id, stats in self.account_stats.items():
            try:
                collected_at = datetime.fromisoformat(stats["collected_at"])
                if collected_at < cutoff_time:
                    to_remove.append(account_id)
            except Exception as e:
                logger.error(f"Error parsing stats timestamp for account {account_id}: {e}")
                to_remove.append(account_id)

        for account_id in to_remove:
            del self.account_stats[account_id]

    async def record_send_attempt(self, account_id: UUID, success: bool):
        """Record a message send attempt."""
        try:
            account = await telegram_account_manager.get_account(account_id)
            if not account:
                return

            account_id_str = str(account.id)
            phone = account.phone
            status = "success" if success else "failure"

            # Update counter
            self.message_send_attempts.labels(
                account_id=account_id_str,
                phone=phone,
                status=status
            ).inc()

            # Update success rate immediately
            if account_id in self.account_stats:
                self.account_stats[account_id]["send_success_rate"] = await self._calculate_send_success_rate(account_id)
                self._update_prometheus_metrics(account, self.account_stats[account_id])

        except Exception as e:
            logger.error(f"Error recording send attempt for account {account_id}: {e}")

    async def get_account_stats(self, account_id: UUID) -> Optional[dict]:
        """Get statistics for a specific account."""
        return self.account_stats.get(account_id)

    async def get_all_accounts_stats(self) -> List[dict]:
        """Get statistics for all accounts."""
        return list(self.account_stats.values())

    async def get_summary_stats(self) -> dict:
        """Get summary statistics for all accounts."""
        stats = await self.get_all_accounts_stats()

        if not stats:
            return {
                "total_accounts": 0,
                "online_accounts": 0,
                "offline_accounts": 0,
                "banned_accounts": 0,
                "average_success_rate": 0.0,
                "average_error_rate": 0.0,
            }

        total = len(stats)
        online = sum(1 for s in stats if s["is_connected"])
        offline = total - online
        banned = sum(1 for s in stats if s["is_banned"])
        avg_success = sum(s["send_success_rate"] for s in stats) / total if total > 0 else 0.0
        avg_error = sum(s["error_rate"] for s in stats) / total if total > 0 else 0.0

        return {
            "total_accounts": total,
            "online_accounts": online,
            "offline_accounts": offline,
            "banned_accounts": banned,
            "average_success_rate": avg_success,
            "average_error_rate": avg_error,
        }


# Global instance
account_monitor = AccountMonitor(
    metrics_port=getattr(settings, "ACCOUNT_MONITOR_METRICS_PORT", 9091),
    collection_interval=getattr(settings, "ACCOUNT_MONITOR_COLLECTION_INTERVAL", 60),
    history_retention_hours=getattr(settings, "ACCOUNT_MONITOR_HISTORY_RETENTION_HOURS", 24),
)
