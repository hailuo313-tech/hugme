"""
P5-09: Feature Flag Service for Gradual Rollout by User Level

This module provides feature flag management with support for:
- All users rollout
- Percentage-based rollout
- Level-based rollout (S/A/B/C/D)
- User list-based rollout
- Audit logging for all changes
"""

from typing import Optional, List, Dict, Any
from enum import Enum
import json
import hashlib
from datetime import datetime


class RolloutType(str, Enum):
    """Feature flag rollout types"""
    ALL = "all"           # Enable for all users
    PERCENTAGE = "percentage"  # Enable for percentage of users
    LEVEL = "level"       # Enable for specific user levels
    USER_LIST = "user_list"  # Enable for specific user IDs


class FeatureFlagService:
    """Service for managing feature flags with gradual rollout support"""
    
    def __init__(self, db_pool=None):
        """
        Initialize feature flag service
        
        Args:
            db_pool: Database connection pool (optional for testing)
        """
        self.db_pool = db_pool
        self._cache = {}  # Simple in-memory cache
        self._cache_ttl = 60  # Cache TTL in seconds
    
    async def get_feature_flag(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get feature flag configuration by name
        
        Args:
            name: Feature flag name
            
        Returns:
            Feature flag configuration dict or None if not found
        """
        # Check cache first
        if name in self._cache:
            cached_data, timestamp = self._cache[name]
            if datetime.now().timestamp() - timestamp < self._cache_ttl:
                return cached_data
        
        # Query database
        query = """
        SELECT id, name, description, enabled, rollout_type, 
               rollout_percentage, target_levels, target_user_ids,
               created_at, updated_at, created_by, updated_by
        FROM feature_flags 
        WHERE name = $1
        """
        
        try:
            if self.db_pool:
                row = await self.db_pool.fetchrow(query, name)
                if row:
                    flag_data = dict(row)
                    # Cache the result
                    self._cache[name] = (flag_data, datetime.now().timestamp())
                    return flag_data
        except Exception as e:
            print(f"Error fetching feature flag {name}: {e}")
        
        return None
    
    async def is_enabled(
        self, 
        name: str, 
        user_id: Optional[str] = None, 
        user_level: Optional[str] = None
    ) -> bool:
        """
        Check if a feature flag is enabled for a specific user
        
        Args:
            name: Feature flag name
            user_id: User ID (optional)
            user_level: User level (S/A/B/C/D, optional)
            
        Returns:
            True if feature is enabled for the user, False otherwise
        """
        flag = await self.get_feature_flag(name)
        if not flag:
            return False
        
        if not flag['enabled']:
            return False
        
        rollout_type = flag['rollout_type']
        
        if rollout_type == RolloutType.ALL:
            return True
        
        elif rollout_type == RolloutType.PERCENTAGE:
            if not user_id:
                return False
            return self._check_percentage_rollout(
                user_id, 
                flag['rollout_percentage']
            )
        
        elif rollout_type == RolloutType.LEVEL:
            if not user_level:
                return False
            return self._check_level_rollout(
                user_level, 
                flag['target_levels']
            )
        
        elif rollout_type == RolloutType.USER_LIST:
            if not user_id:
                return False
            return self._check_user_list_rollout(
                user_id, 
                flag['target_user_ids']
            )
        
        return False
    
    def _check_percentage_rollout(self, user_id: str, percentage: int) -> bool:
        """
        Check if user falls within percentage rollout
        
        Args:
            user_id: User ID
            percentage: Rollout percentage (0-100)
            
        Returns:
            True if user is in rollout percentage
        """
        if percentage >= 100:
            return True
        if percentage <= 0:
            return False
        
        # Use consistent hashing based on user ID
        hash_value = int(hashlib.md5(user_id.encode()).hexdigest(), 16)
        rollout_threshold = (percentage / 100) * (2**32)
        
        return hash_value < rollout_threshold
    
    def _check_level_rollout(self, user_level: str, target_levels: str) -> bool:
        """
        Check if user level is in target levels
        
        Args:
            user_level: User level (S/A/B/C/D)
            target_levels: Comma-separated target levels
            
        Returns:
            True if user level is in target levels
        """
        if not target_levels:
            return False
        
        allowed_levels = [level.strip().upper() for level in target_levels.split(',')]
        return user_level.upper() in allowed_levels
    
    def _check_user_list_rollout(self, user_id: str, target_user_ids: str) -> bool:
        """
        Check if user ID is in target user list
        
        Args:
            user_id: User ID
            target_user_ids: Comma-separated user IDs
            
        Returns:
            True if user ID is in target list
        """
        if not target_user_ids:
            return False
        
        allowed_users = [uid.strip() for uid in target_user_ids.split(',')]
        return user_id in allowed_users
    
    async def create_feature_flag(
        self,
        name: str,
        description: str,
        rollout_type: RolloutType,
        rollout_percentage: int = 0,
        target_levels: str = None,
        target_user_ids: str = None,
        created_by: str = "system"
    ) -> Dict[str, Any]:
        """
        Create a new feature flag
        
        Args:
            name: Feature flag name (unique)
            description: Feature description
            rollout_type: Rollout type
            rollout_percentage: Percentage for percentage-based rollout
            target_levels: Target levels for level-based rollout
            target_user_ids: Target user IDs for user list rollout
            created_by: Creator identifier
            
        Returns:
            Created feature flag data
        """
        query = """
        INSERT INTO feature_flags 
        (name, description, enabled, rollout_type, rollout_percentage, 
         target_levels, target_user_ids, created_by)
        VALUES ($1, $2, FALSE, $3, $4, $5, $6, $7)
        RETURNING *
        """
        
        try:
            if self.db_pool:
                row = await self.db_pool.fetchrow(
                    query,
                    name, description, rollout_type.value, rollout_percentage,
                    target_levels, target_user_ids, created_by
                )
                flag_data = dict(row)
                # Clear cache
                if name in self._cache:
                    del self._cache[name]
                return flag_data
        except Exception as e:
            print(f"Error creating feature flag {name}: {e}")
            raise
        
        return {}
    
    async def update_feature_flag(
        self,
        name: str,
        enabled: Optional[bool] = None,
        rollout_type: Optional[RolloutType] = None,
        rollout_percentage: Optional[int] = None,
        target_levels: Optional[str] = None,
        target_user_ids: Optional[str] = None,
        updated_by: str = "system"
    ) -> Optional[Dict[str, Any]]:
        """
        Update an existing feature flag
        
        Args:
            name: Feature flag name
            enabled: Enable/disable flag
            rollout_type: Rollout type
            rollout_percentage: Percentage for percentage-based rollout
            target_levels: Target levels for level-based rollout
            target_user_ids: Target user IDs for user list rollout
            updated_by: Updater identifier
            
        Returns:
            Updated feature flag data
        """
        updates = []
        params = []
        param_count = 1
        
        if enabled is not None:
            updates.append(f"enabled = ${param_count}")
            params.append(enabled)
            param_count += 1
        
        if rollout_type is not None:
            updates.append(f"rollout_type = ${param_count}")
            params.append(rollout_type.value)
            param_count += 1
        
        if rollout_percentage is not None:
            updates.append(f"rollout_percentage = ${param_count}")
            params.append(rollout_percentage)
            param_count += 1
        
        if target_levels is not None:
            updates.append(f"target_levels = ${param_count}")
            params.append(target_levels)
            param_count += 1
        
        if target_user_ids is not None:
            updates.append(f"target_user_ids = ${param_count}")
            params.append(target_user_ids)
            param_count += 1
        
        updates.append(f"updated_by = ${param_count}")
        params.append(updated_by)
        param_count += 1
        
        params.append(name)
        
        if not updates:
            return await self.get_feature_flag(name)
        
        query = f"""
        UPDATE feature_flags 
        SET {', '.join(updates)}
        WHERE name = ${param_count}
        RETURNING *
        """
        
        try:
            if self.db_pool:
                row = await self.db_pool.fetchrow(query, *params)
                if row:
                    flag_data = dict(row)
                    # Clear cache
                    if name in self._cache:
                        del self._cache[name]
                    return flag_data
        except Exception as e:
            print(f"Error updating feature flag {name}: {e}")
            raise
        
        return None
    
    async def delete_feature_flag(self, name: str) -> bool:
        """
        Delete a feature flag
        
        Args:
            name: Feature flag name
            
        Returns:
            True if deleted successfully
        """
        query = "DELETE FROM feature_flags WHERE name = $1"
        
        try:
            if self.db_pool:
                await self.db_pool.execute(query, name)
                # Clear cache
                if name in self._cache:
                    del self._cache[name]
                return True
        except Exception as e:
            print(f"Error deleting feature flag {name}: {e}")
            raise
        
        return False
    
    async def list_feature_flags(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        """
        List all feature flags
        
        Args:
            enabled_only: Only return enabled flags
            
        Returns:
            List of feature flag configurations
        """
        query = """
        SELECT id, name, description, enabled, rollout_type, 
               rollout_percentage, target_levels, target_user_ids,
               created_at, updated_at, created_by, updated_by
        FROM feature_flags
        """
        
        if enabled_only:
            query += " WHERE enabled = TRUE"
        
        query += " ORDER BY name"
        
        try:
            if self.db_pool:
                rows = await self.db_pool.fetch(query)
                return [dict(row) for row in rows]
        except Exception as e:
            print(f"Error listing feature flags: {e}")
        
        return []
    
    async def get_audit_log(self, feature_flag_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get audit log for a feature flag
        
        Args:
            feature_flag_id: Feature flag ID
            limit: Maximum number of log entries
            
        Returns:
            List of audit log entries
        """
        query = """
        SELECT id, feature_flag_id, action, old_value, new_value, 
               changed_by, changed_at, reason
        FROM feature_flag_audit_log
        WHERE feature_flag_id = $1
        ORDER BY changed_at DESC
        LIMIT $2
        """
        
        try:
            if self.db_pool:
                rows = await self.db_pool.fetch(query, feature_flag_id, limit)
                return [dict(row) for row in rows]
        except Exception as e:
            print(f"Error fetching audit log: {e}")
        
        return []
    
    def clear_cache(self):
        """Clear the in-memory cache"""
        self._cache.clear()


# Global feature flag service instance
feature_flag_service = FeatureFlagService()