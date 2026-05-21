#!/usr/bin/env python3
"""
P5-09: Feature Flag Management CLI Tool

Command-line tool for managing feature flags with gradual rollout support.
"""

import asyncio
import argparse
import sys
import os

# Add the parent directory to the path to import app modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.feature_flags import FeatureFlagService, RolloutType


class FeatureFlagManager:
    """CLI manager for feature flags"""
    
    def __init__(self):
        self.service = FeatureFlagService()
        # Note: In production, you would initialize the service with a real database pool
        # For this CLI tool, we'll use mock data or connect to database if available
    
    async def list_flags(self, enabled_only=False):
        """List all feature flags"""
        flags = await self.service.list_feature_flags(enabled_only=enabled_only)
        
        if not flags:
            print("No feature flags found.")
            return
        
        print(f"\n{'Name':<30} {'Enabled':<10} {'Rollout Type':<15} {'Description'}")
        print("-" * 100)
        
        for flag in flags:
            status = "✓" if flag['enabled'] else "✗"
            print(f"{flag['name']:<30} {status:<10} {flag['rollout_type']:<15} {flag['description'][:50]}")
    
    async def create_flag(self, name, description, rollout_type, **kwargs):
        """Create a new feature flag"""
        try:
            flag = await self.service.create_feature_flag(
                name=name,
                description=description,
                rollout_type=RolloutType(rollout_type),
                rollout_percentage=kwargs.get('percentage', 0),
                target_levels=kwargs.get('levels'),
                target_user_ids=kwargs.get('user_ids'),
                created_by=kwargs.get('created_by', 'cli')
            )
            print(f"✓ Feature flag '{name}' created successfully!")
            print(f"  ID: {flag['id']}")
            print(f"  Rollout Type: {flag['rollout_type']}")
            return True
        except Exception as e:
            print(f"✗ Error creating feature flag: {e}")
            return False
    
    async def update_flag(self, name, **kwargs):
        """Update an existing feature flag"""
        try:
            flag = await self.service.update_feature_flag(
                name=name,
                enabled=kwargs.get('enabled'),
                rollout_type=RolloutType(kwargs['rollout_type']) if kwargs.get('rollout_type') else None,
                rollout_percentage=kwargs.get('percentage'),
                target_levels=kwargs.get('levels'),
                target_user_ids=kwargs.get('user_ids'),
                updated_by=kwargs.get('updated_by', 'cli')
            )
            if flag:
                print(f"✓ Feature flag '{name}' updated successfully!")
                return True
            else:
                print(f"✗ Feature flag '{name}' not found.")
                return False
        except Exception as e:
            print(f"✗ Error updating feature flag: {e}")
            return False
    
    async def enable_flag(self, name):
        """Enable a feature flag"""
        return await self.update_flag(name, enabled=True)
    
    async def disable_flag(self, name):
        """Disable a feature flag"""
        return await self.update_flag(name, enabled=False)
    
    async def delete_flag(self, name):
        """Delete a feature flag"""
        try:
            success = await self.service.delete_feature_flag(name)
            if success:
                print(f"✓ Feature flag '{name}' deleted successfully!")
                return True
            else:
                print(f"✗ Feature flag '{name}' not found.")
                return False
        except Exception as e:
            print(f"✗ Error deleting feature flag: {e}")
            return False
    
    async def check_flag(self, name, user_id=None, user_level=None):
        """Check if a feature flag is enabled for a specific user"""
        is_enabled = await self.service.is_enabled(
            name=name,
            user_id=user_id,
            user_level=user_level
        )
        
        flag = await self.service.get_feature_flag(name)
        if not flag:
            print(f"✗ Feature flag '{name}' not found.")
            return False
        
        status = "✓ ENABLED" if is_enabled else "✗ DISABLED"
        print(f"\nFeature Flag: {name}")
        print(f"Status: {status}")
        print(f"Rollout Type: {flag['rollout_type']}")
        
        if user_id:
            print(f"User ID: {user_id}")
        if user_level:
            print(f"User Level: {user_level}")
        
        if flag['rollout_type'] == RolloutType.PERCENTAGE:
            print(f"Rollout Percentage: {flag['rollout_percentage']}%")
        elif flag['rollout_type'] == RolloutType.LEVEL:
            print(f"Target Levels: {flag['target_levels']}")
        elif flag['rollout_type'] == RolloutType.USER_LIST:
            print(f"Target User IDs: {flag['target_user_ids']}")
        
        return is_enabled
    
    async def set_level_rollout(self, name, levels):
        """Configure level-based rollout for a feature flag"""
        return await self.update_flag(
            name,
            rollout_type='level',
            levels=levels
        )
    
    async def set_percentage_rollout(self, name, percentage):
        """Configure percentage-based rollout for a feature flag"""
        return await self.update_flag(
            name,
            rollout_type='percentage',
            percentage=percentage
        )


async def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(description='Feature Flag Management CLI')
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # List command
    list_parser = subparsers.add_parser('list', help='List all feature flags')
    list_parser.add_argument('--enabled-only', action='store_true', help='Show only enabled flags')
    
    # Create command
    create_parser = subparsers.add_parser('create', help='Create a new feature flag')
    create_parser.add_argument('name', help='Feature flag name')
    create_parser.add_argument('description', help='Feature description')
    create_parser.add_argument('--rollout-type', choices=['all', 'percentage', 'level', 'user_list'], 
                              default='all', help='Rollout type')
    create_parser.add_argument('--percentage', type=int, help='Percentage for percentage rollout (0-100)')
    create_parser.add_argument('--levels', help='Comma-separated target levels (S,A,B,C,D)')
    create_parser.add_argument('--user-ids', help='Comma-separated target user IDs')
    
    # Update command
    update_parser = subparsers.add_parser('update', help='Update a feature flag')
    update_parser.add_argument('name', help='Feature flag name')
    update_parser.add_argument('--enable', action='store_true', help='Enable the flag')
    update_parser.add_argument('--disable', action='store_true', help='Disable the flag')
    update_parser.add_argument('--rollout-type', choices=['all', 'percentage', 'level', 'user_list'], 
                              help='Rollout type')
    update_parser.add_argument('--percentage', type=int, help='Percentage for percentage rollout (0-100)')
    update_parser.add_argument('--levels', help='Comma-separated target levels (S,A,B,C,D)')
    update_parser.add_argument('--user-ids', help='Comma-separated target user IDs')
    
    # Enable command
    enable_parser = subparsers.add_parser('enable', help='Enable a feature flag')
    enable_parser.add_argument('name', help='Feature flag name')
    
    # Disable command
    disable_parser = subparsers.add_parser('disable', help='Disable a feature flag')
    disable_parser.add_argument('name', help='Feature flag name')
    
    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete a feature flag')
    delete_parser.add_argument('name', help='Feature flag name')
    
    # Check command
    check_parser = subparsers.add_parser('check', help='Check if a feature flag is enabled')
    check_parser.add_argument('name', help='Feature flag name')
    check_parser.add_argument('--user-id', help='User ID for user-specific checks')
    check_parser.add_argument('--user-level', help='User level (S/A/B/C/D)')
    
    # Set level rollout command
    level_parser = subparsers.add_parser('set-level', help='Set level-based rollout')
    level_parser.add_argument('name', help='Feature flag name')
    level_parser.add_argument('levels', help='Comma-separated target levels (S,A,B,C,D)')
    
    # Set percentage rollout command
    percentage_parser = subparsers.add_parser('set-percentage', help='Set percentage-based rollout')
    percentage_parser.add_argument('name', help='Feature flag name')
    percentage_parser.add_argument('percentage', type=int, help='Percentage (0-100)')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    manager = FeatureFlagManager()
    
    if args.command == 'list':
        await manager.list_flags(enabled_only=args.enabled_only)
    elif args.command == 'create':
        await manager.create_flag(
            name=args.name,
            description=args.description,
            rollout_type=args.rollout_type,
            percentage=args.percentage,
            levels=args.levels,
            user_ids=args.user_ids
        )
    elif args.command == 'update':
        enabled = None
        if args.enable:
            enabled = True
        elif args.disable:
            enabled = False
        
        await manager.update_flag(
            name=args.name,
            enabled=enabled,
            rollout_type=args.rollout_type,
            percentage=args.percentage,
            levels=args.levels,
            user_ids=args.user_ids
        )
    elif args.command == 'enable':
        await manager.enable_flag(args.name)
    elif args.command == 'disable':
        await manager.disable_flag(args.name)
    elif args.command == 'delete':
        await manager.delete_flag(args.name)
    elif args.command == 'check':
        await manager.check_flag(
            name=args.name,
            user_id=args.user_id,
            user_level=args.user_level
        )
    elif args.command == 'set-level':
        await manager.set_level_rollout(args.name, args.levels)
    elif args.command == 'set-percentage':
        await manager.set_percentage_rollout(args.name, args.percentage)


if __name__ == '__main__':
    asyncio.run(main())