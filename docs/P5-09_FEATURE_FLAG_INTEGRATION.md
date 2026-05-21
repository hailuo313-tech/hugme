# P5-09: Feature Flag Integration Guide

## Overview
This guide demonstrates how to integrate the feature flag system into existing ERIS business processes for gradual rollout by user level.

## Basic Usage

### 1. Check Feature Flag in Business Logic

```python
from app.services.feature_flags import feature_flag_service

# Check if a feature is enabled for a specific user
is_enabled = await feature_flag_service.is_enabled(
    name="new_ai_model",
    user_id="user_123",
    user_level="S"
)

if is_enabled:
    # Use new AI model
    response = await new_ai_model.process(message)
else:
    # Use legacy AI model
    response = await legacy_ai_model.process(message)
```

### 2. LLM Processing Integration

```python
# In app/services/llm_service.py
async def process_message_with_llm(message: str, user_id: str, user_level: str):
    # Check if new AI model is enabled for this user
    use_new_model = await feature_flag_service.is_enabled(
        name="new_ai_model",
        user_id=user_id,
        user_level=user_level
    )
    
    if use_new_model:
        # Use new model
        return await new_llm_service.generate_response(message)
    else:
        # Use existing model
        return await existing_llm_service.generate_response(message)
```

### 3. Script Matching Integration

```python
# In app/services/script_matching.py
async def match_script_with_enhancement(message: str, user_id: str, user_level: str):
    # Check if enhanced matching is enabled
    use_enhanced = await feature_flag_service.is_enabled(
        name="enhanced_matching",
        user_id=user_id,
        user_level=user_level
    )
    
    if use_enhanced:
        # Use enhanced algorithm
        return await enhanced_script_matcher.find_best_match(message)
    else:
        # Use standard algorithm
        return await standard_script_matcher.find_best_match(message)
```

### 4. Real-time Features Integration

```python
# In app/services/realtime_service.py
async def handle_realtime_translation(message: str, user_id: str, user_level: str):
    # Check if real-time translation is enabled
    translation_enabled = await feature_flag_service.is_enabled(
        name="real_time_translation",
        user_id=user_id,
        user_level=user_level
    )
    
    if translation_enabled:
        # Translate message in real-time
        translated = await translation_service.translate(message)
        return translated
    else:
        # Return original message
        return message
```

### 5. Dashboard Features Integration

```python
# In app/services/dashboard_service.py
async def get_dashboard_features(user_id: str, user_level: str):
    features = {
        'basic_analytics': True,  # Always available
        'advanced_analytics': await feature_flag_service.is_enabled(
            name="advanced_analytics",
            user_id=user_id,
            user_level=user_level
        ),
        'beta_features': await feature_flag_service.is_enabled(
            name="beta_features",
            user_id=user_id,
            user_level=user_level
        )
    }
    return features
```

## API Integration Examples

### Using the Feature Flag API

```python
import httpx

async def check_feature_flag_via_api(flag_name: str, user_id: str, user_level: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/api/v1/feature-flags/check",
            json={
                "name": flag_name,
                "user_id": user_id,
                "user_level": user_level
            }
        )
        return response.json()
```

### Managing Feature Flags via API

```python
import httpx

# Create a new feature flag
async def create_feature_flag():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/api/v1/feature-flags/",
            json={
                "name": "new_feature",
                "description": "A new feature for testing",
                "rollout_type": "level",
                "target_levels": "S,A",
                "created_by": "admin"
            }
        )
        return response.json()

# Update feature flag to enable for S level only
async def update_feature_flag_rollout():
    async with httpx.AsyncClient() as client:
        response = await client.put(
            "http://localhost:8000/api/v1/feature-flags/new_feature",
            json={
                "enabled": True,
                "rollout_type": "level",
                "target_levels": "S",
                "updated_by": "admin"
            }
        )
        return response.json()
```

## CLI Tool Usage

### Basic Commands

```bash
# List all feature flags
python scripts/manage_feature_flags.py list

# List only enabled flags
python scripts/manage_feature_flags.py list --enabled-only

# Create a new feature flag
python scripts/manage_feature_flags.py create "new_ai_model" "Enable new AI model for processing" --rollout-type level --levels S

# Enable a feature flag
python scripts/manage_feature_flags.py enable "new_ai_model"

# Disable a feature flag
python scripts/manage_feature_flags.py disable "new_ai_model"

# Check if a feature is enabled for a specific user
python scripts/manage_feature_flags.py check "new_ai_model" --user-id "user_123" --user-level S

# Set level-based rollout
python scripts/manage_feature_flags.py set-level "new_ai_model" "S,A"

# Set percentage-based rollout
python scripts/manage_feature_flags.py set-percentage "enhanced_matching" 25

# Delete a feature flag
python scripts/manage_feature_flags.py delete "old_feature"
```

## Gradual Rollout Strategy

### Phase 1: Internal Testing (S Level)
```bash
# Create feature flag for S level only
python scripts/manage_feature_flags.py create "new_feature" "New feature description" --rollout-type level --levels S
python scripts/manage_feature_flags.py enable "new_feature"
```

### Phase 2: Early Adopters (S + A Levels)
```bash
# Expand to A level
python scripts/manage_feature_flags.py set-level "new_feature" "S,A"
```

### Phase 3: Broader Rollout (S + A + B Levels)
```bash
# Expand to B level
python scripts/manage_feature_flags.py set-level "new_feature" "S,A,B"
```

### Phase 4: Percentage-Based Rollout
```bash
# Switch to percentage rollout for gradual expansion
python scripts/manage_feature_flags.py set-percentage "new_feature" 10
# Gradually increase: 25% → 50% → 75% → 100%
python scripts/manage_feature_flags.py set-percentage "new_feature" 100
```

### Phase 5: Full Rollout (All Users)
```bash
# Enable for all users
python scripts/manage_feature_flags.py update "new_feature" --rollout-type all
```

## WebSocket Integration

### Real-time Feature Flag Updates

```python
# In app/api/realtime.py
@router.websocket("/ws/feature-flags")
async def feature_flags_websocket(websocket: WebSocket):
    await websocket.accept()
    
    try:
        while True:
            # Send current feature flag status
            flags = await feature_flag_service.list_feature_flags()
            await websocket.send_json({
                "type": "feature_flags_update",
                "flags": flags
            })
            
            # Wait for updates or periodic refresh
            await asyncio.sleep(30)
            
    except WebSocketDisconnect:
        print("WebSocket disconnected")
```

## Monitoring Integration

### Track Feature Flag Usage

```python
from app.services.business_metrics import business_metrics

async def track_feature_flag_usage(flag_name: str, user_id: str, user_level: str, is_enabled: bool):
    # Track feature flag checks
    business_metrics.increment_error(
        error_type=f"feature_flag_check_{flag_name}",
        severity="info" if is_enabled else "disabled"
    )
    
    # Track enabled vs disabled ratio
    if is_enabled:
        business_metrics.increment_conversion("feature_flag_enabled")
    else:
        business_metrics.increment_conversion("feature_flag_disabled")
```

## Error Handling

### Graceful Degradation

```python
async def get_feature_flag_with_fallback(name: str, user_id: str, user_level: str, default: bool = False):
    try:
        return await feature_flag_service.is_enabled(
            name=name,
            user_id=user_id,
            user_level=user_level
        )
    except Exception as e:
        # Log error but return default value
        print(f"Error checking feature flag {name}: {e}")
        return default
```

## Testing Integration

### Mock Feature Flags for Testing

```python
import pytest
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_new_feature_with_flag_enabled():
    # Mock feature flag service
    feature_flag_service.is_enabled = AsyncMock(return_value=True)
    
    # Test new feature logic
    result = await process_with_new_feature("test", "user_123", "S")
    assert result["used_new_feature"] is True

@pytest.mark.asyncio
async def test_new_feature_with_flag_disabled():
    # Mock feature flag service
    feature_flag_service.is_enabled = AsyncMock(return_value=False)
    
    # Test fallback logic
    result = await process_with_new_feature("test", "user_123", "S")
    assert result["used_new_feature"] is False
```

## Performance Considerations

### Caching Strategy
The feature flag service includes built-in caching with a 60-second TTL. This reduces database load while ensuring near real-time updates.

### Database Indexing
Ensure the following indexes exist for optimal performance:
- `idx_feature_flags_name` on `feature_flags.name`
- `idx_feature_flags_enabled` on `feature_flags.enabled`

### Async Operations
All feature flag operations are async to prevent blocking the main application thread.

## Security Considerations

1. **Authentication**: Secure the management API endpoints with proper authentication
2. **Authorization**: Implement role-based access control for feature flag management
3. **Audit Logging**: All changes are logged in the `feature_flag_audit_log` table
4. **Input Validation**: Validate user input for feature flag names and configurations

## Troubleshooting

### Feature Flag Not Working
1. Check if the flag exists: `GET /api/v1/feature-flags/{name}`
2. Verify the flag is enabled
3. Check rollout configuration matches user attributes
4. Review audit logs for recent changes

### Cache Issues
1. Clear cache: `POST /api/v1/feature-flags/cache/clear`
2. Wait for cache TTL (60 seconds) to expire
3. Check database connectivity

### Performance Issues
1. Monitor database query performance
2. Review cache hit rates
3. Consider increasing cache TTL for frequently accessed flags

This integration guide provides comprehensive examples for incorporating feature flags into ERIS business processes, enabling safe gradual rollout by user level.