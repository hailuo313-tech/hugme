"""User level integration service for P2-12: Inbound pipeline calcUserLevel integration."""

from __future__ import annotations

import asyncio
from typing import Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telethon.errors import SessionPasswordNeededError

from core.database import get_async_session
from models.users import User
from services.level_engine import UserLevelInput, calc_user_level, load_thresholds
from services.telegram_account_manager import telegram_account_manager


class UserLevelService:
    """Service for integrating user level calculation into inbound pipeline."""

    def __init__(self):
        self._thresholds_cache: Optional[object] = None
        self._cache_lock = asyncio.Lock()

    async def get_thresholds(self):
        """Get level thresholds with caching."""
        if self._thresholds_cache is None:
            async with self._cache_lock:
                if self._thresholds_cache is None:
                    self._thresholds_cache = load_thresholds()
        return self._thresholds_cache

    async def invalidate_thresholds_cache(self):
        """Invalidate thresholds cache (for config reload)."""
        async with self._cache_lock:
            self._thresholds_cache = None
        logger.info("User level thresholds cache invalidated")

    async def calculate_user_level_from_inbound(
        self,
        external_user_id: str,
        country_code: Optional[str] = None,
    ) -> dict:
        """Calculate user level from inbound message context.

        Args:
            external_user_id: External user ID (e.g., "tg_123456789")
            country_code: User's country code (optional, will be fetched from profile if not provided)

        Returns:
            Dictionary with level calculation results
        """
        try:
            # Extract Telegram user ID from external_user_id
            telegram_user_id = self._extract_telegram_user_id(external_user_id)
            if not telegram_user_id:
                logger.warning(f"Could not extract Telegram user ID from {external_user_id}")
                return self._get_default_level_result("invalid_user_id", "unknown")

            # Fetch user profile from database
            user_profile = await self._get_user_profile(telegram_user_id)

            # Prepare input for level calculation
            level_input = UserLevelInput(
                profile_complete=user_profile is not None,
                country_code=country_code or (user_profile.country_code if user_profile else None),
                lifetime_spend_usd=user_profile.lifetime_spend_usd if user_profile else 0.0,
                vip_level=user_profile.vip_level if user_profile else 0,
                operator_assigned_s=user_profile.operator_assigned_s if user_profile else False,
            )

            # Calculate user level
            thresholds = await self.get_thresholds()
            result = calc_user_level(level_input, thresholds=thresholds)

            logger.info(
                f"Calculated user level for {external_user_id}: "
                f"level={result.level}, route={result.chat_route}, reason={result.reason}, "
                f"tier={result.country_tier}"
            )

            return {
                "external_user_id": external_user_id,
                "telegram_user_id": telegram_user_id,
                "level": result.level,
                "chat_route": result.chat_route,
                "reason": result.reason,
                "country_tier": result.country_tier,
                "profile_complete": level_input.profile_complete,
                "lifetime_spend_usd": level_input.lifetime_spend_usd,
                "vip_level": level_input.vip_level,
                "operator_assigned_s": level_input.operator_assigned_s,
            }

        except Exception as e:
            logger.error(f"Error calculating user level for {external_user_id}: {e}")
            return self._get_default_level_result("calculation_error", "unknown")

    def _extract_telegram_user_id(self, external_user_id: str) -> Optional[str]:
        """Extract Telegram user ID from external user ID."""
        if external_user_id.startswith("tg_"):
            return external_user_id[3:]
        return external_user_id

    async def _get_user_profile(self, telegram_user_id: str) -> Optional[User]:
        """Fetch user profile from database."""
        try:
            async for session in get_async_session():
                result = await session.execute(
                    select(User).where(User.telegram_user_id == telegram_user_id)
                )
                return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching user profile for {telegram_user_id}: {e}")
            return None

    def _get_default_level_result(self, reason: str, country_tier: str) -> dict:
        """Return default level result for error cases."""
        return {
            "external_user_id": None,
            "telegram_user_id": None,
            "level": "C",
            "chat_route": "ai_auto",
            "reason": reason,
            "country_tier": country_tier,
            "profile_complete": False,
            "lifetime_spend_usd": 0.0,
            "vip_level": 0,
            "operator_assigned_s": False,
        }

    async def enrich_inbound_envelope_with_level(
        self,
        envelope: dict,
    ) -> dict:
        """Enrich inbound envelope with user level information.

        This is the main integration point for P2-12.
        """
        try:
            external_user_id = envelope.get("external_user_id")
            if not external_user_id:
                logger.warning("No external_user_id in envelope, skipping level calculation")
                return envelope

            # Calculate user level
            level_result = await self.calculate_user_level_from_inbound(
                external_user_id,
                country_code=envelope.get("metadata", {}).get("country_code"),
            )

            # Add level information to envelope metadata
            if "metadata" not in envelope:
                envelope["metadata"] = {}

            envelope["metadata"]["user_level"] = level_result["level"]
            envelope["metadata"]["chat_route"] = level_result["chat_route"]
            envelope["metadata"]["level_reason"] = level_result["reason"]
            envelope["metadata"]["country_tier"] = level_result["country_tier"]

            logger.debug(
                f"Enriched envelope for {external_user_id} with level: {level_result['level']}"
            )

            return envelope

        except Exception as e:
            logger.error(f"Error enriching envelope with user level: {e}")
            # Return original envelope on error to not break the pipeline
            return envelope


# Global instance
user_level_service = UserLevelService()