# P5-09: Feature Flag Gradual Rollout by User Level

## Overview
Feature flag system for gradual rollout by user level, enabling safe and controlled deployment of new features to different user segments (S/A/B/C/D levels).

## Implementation Date
2026-05-21

## Purpose
To provide a flexible feature flag system that allows gradual rollout of new features based on user levels, minimizing risk and enabling data-driven decisions about feature deployment.

## Architecture

### Components
1. **Database Schema** - Feature flags storage with audit logging
2. **Feature Flag Service** - Core business logic for flag management
3. **REST API** - HTTP endpoints for flag management
4. **CLI Tool** - Command-line interface for operations
5. **Integration Layer** - Easy integration with existing business logic

### Data Flow
```
Admin/User → API/CLI → Feature Flag Service → Database
Application → Feature Flag Service → Cache → Database
User Request → Feature Check → Business Logic → Response
```

## File Structure

```
db/
└── migrations/
    └── V3__feature_flags.sql          # Database schema and migrations

app/
├── services/
│   └── feature_flags.py              # Core feature flag service
└── api/
    └── feature_flags.py              # REST API endpoints

scripts/
└── manage_feature_flags.py           # CLI management tool

docs/
├── P5-09_FEATURE_FLAG_GRADUAL_ROLLOUT.md  # Main documentation
└── P5-09_FEATURE_FLAG_INTEGRATION.md      # Integration guide
```

## Feature Flag Types

### 1. All Users Rollout
Enable feature for all users immediately.
- **Use Case**: Low-risk features, bug fixes, UI improvements
- **Configuration**: `rollout_type = "all"`

### 2. Percentage-Based Rollout
Enable feature for a percentage of users using consistent hashing.
- **Use Case**: A/B testing, gradual performance validation
- **Configuration**: `rollout_type = "percentage"`, `rollout_percentage = 0-100`
- **Algorithm**: Consistent hashing based on user ID

### 3. Level-Based Rollout
Enable feature for specific user levels (S/A/B/C/D).
- **Use Case**: VIP features, gradual rollout by user segment
- **Configuration**: `rollout_type = "level"`, `target_levels = "S,A,B"`
- **Priority**: S (highest) → A → B → C → D (lowest)

### 4. User List Rollout
Enable feature for specific user IDs.
- **Use Case**: Beta testing, internal testing, specific user grants
- **Configuration**: `rollout_type = "user_list"`, `target_user_ids = "user1,user2,user3"`

## Database Schema

### Feature Flags Table
```sql
CREATE TABLE feature_flags (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    enabled BOOLEAN DEFAULT FALSE,
    rollout_type VARCHAR(20) NOT NULL DEFAULT 'all',
    rollout_percentage INTEGER DEFAULT 0,
    target_levels VARCHAR(100),
    target_user_ids TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100)
);
```

### Audit Log Table
```sql
CREATE TABLE feature_flag_audit_log (
    id SERIAL PRIMARY KEY,
    feature_flag_id INTEGER REFERENCES feature_flags(id),
    action VARCHAR(20) NOT NULL,
    old_value JSONB,
    new_value JSONB,
    changed_by VARCHAR(100) NOT NULL,
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reason TEXT
);
```

## API Endpoints

### Management Endpoints

#### Create Feature Flag
```http
POST /api/v1/feature-flags/
Content-Type: application/json

{
  "name": "new_ai_model",
  "description": "Enable new AI model for processing",
  "rollout_type": "level",
  "target_levels": "S",
  "created_by": "admin"
}
```

#### List Feature Flags
```http
GET /api/v1/feature-flags/?enabled_only=false
```

#### Get Specific Feature Flag
```http
GET /api/v1/feature-flags/{name}
```

#### Update Feature Flag
```http
PUT /api/v1/feature-flags/{name}
Content-Type: application/json

{
  "enabled": true,
  "rollout_type": "level",
  "target_levels": "S,A",
  "updated_by": "admin"
}
```

#### Delete Feature Flag
```http
DELETE /api/v1/feature-flags/{name}
```

### Usage Endpoints

#### Check Feature Flag
```http
POST /api/v1/feature-flags/check
Content-Type: application/json

{
  "name": "new_ai_model",
  "user_id": "user_123",
  "user_level": "S"
}
```

#### Get Audit Log
```http
GET /api/v1/feature-flags/{name}/audit?limit=50
```

#### Clear Cache
```http
POST /api/v1/feature-flags/cache/clear
```

## CLI Tool Usage

### Installation
```bash
# Make the script executable
chmod +x scripts/manage_feature_flags.py

# Run directly
python scripts/manage_feature_flags.py --help
```

### Common Commands

```bash
# List all feature flags
python scripts/manage_feature_flags.py list

# Create a new feature flag
python scripts/manage_feature_flags.py create "new_feature" "Description" --rollout-type level --levels S

# Enable a feature flag
python scripts/manage_feature_flags.py enable "new_feature"

# Disable a feature flag
python scripts/manage_feature_flags.py disable "new_feature"

# Check feature flag status
python scripts/manage_feature_flags.py check "new_feature" --user-id "user_123" --user-level S

# Set level-based rollout
python scripts/manage_feature_flags.py set-level "new_feature" "S,A,B"

# Set percentage-based rollout
python scripts/manage_feature_flags.py set-percentage "new_feature" 25

# Delete feature flag
python scripts/manage_feature_flags.py delete "old_feature"
```

## Gradual Rollout Strategy

### Recommended Rollout Phases

#### Phase 1: Internal Testing (S Level Only)
```bash
# Create and enable for S level
python scripts/manage_feature_flags.py create "new_feature" "Feature description" --rollout-type level --levels S
python scripts/manage_feature_flags.py enable "new_feature"
```
- **Duration**: 1-3 days
- **Monitoring**: Error rates, performance metrics
- **Success Criteria**: Zero critical errors, acceptable performance

#### Phase 2: Early Adopters (S + A Levels)
```bash
# Expand to A level
python scripts/manage_feature_flags.py set-level "new_feature" "S,A"
```
- **Duration**: 3-7 days
- **Monitoring**: User feedback, conversion rates, engagement
- **Success Criteria**: Positive user feedback, no regression

#### Phase 3: Broader Rollout (S + A + B Levels)
```bash
# Expand to B level
python scripts/manage_feature_flags.py set-level "new_feature" "S,A,B"
```
- **Duration**: 7-14 days
- **Monitoring**: System load, business metrics, support tickets
- **Success Criteria**: System stability, business impact positive

#### Phase 4: Percentage Rollout (Controlled Expansion)
```bash
# Switch to percentage rollout
python scripts/manage_feature_flags.py set-percentage "new_feature" 10
# Gradually increase
python scripts/manage_feature_flags.py set-percentage "new_feature" 25
python scripts/manage_feature_flags.py set-percentage "new_feature" 50
python scripts/manage_feature_flags.py set-percentage "new_feature" 75
```
- **Duration**: 14-30 days
- **Monitoring**: System capacity, error rates, user experience
- **Success Criteria**: System handles load smoothly

#### Phase 5: Full Rollout (All Users)
```bash
# Enable for all users
python scripts/manage_feature_flags.py update "new_feature" --rollout-type all
```
- **Duration**: Ongoing
- **Monitoring**: Continuous monitoring, quick rollback capability

## Integration Examples

### Basic Usage in Business Logic
```python
from app.services.feature_flags import feature_flag_service

async def process_user_request(user_id: str, user_level: str):
    # Check if new feature is enabled
    if await feature_flag_service.is_enabled("new_feature", user_id, user_level):
        return await new_feature_handler()
    else:
        return await legacy_handler()
```

### LLM Service Integration
```python
async def generate_ai_response(message: str, user_id: str, user_level: str):
    use_new_model = await feature_flag_service.is_enabled(
        "new_ai_model", user_id, user_level
    )
    
    if use_new_model:
        return await new_llm_model.generate(message)
    else:
        return await legacy_llm_model.generate(message)
```

### Real-time Features
```python
async def enable_realtime_translation(user_id: str, user_level: str):
    translation_enabled = await feature_flag_service.is_enabled(
        "real_time_translation", user_id, user_level
    )
    
    if translation_enabled:
        return await translation_service.translate(message)
    return message
```

## Monitoring and Observability

### Metrics to Track
1. **Feature Flag Check Rate**: How often flags are checked
2. **Enable/Disable Ratio**: Percentage of users with feature enabled
3. **Error Rates**: Comparison between enabled/disabled groups
4. **Performance Metrics**: Latency comparison between groups
5. **Business Metrics**: Conversion rates, engagement, revenue

### Prometheus Integration
```python
from app.services.business_metrics import business_metrics

# Track feature flag usage
if await feature_flag_service.is_enabled("new_feature", user_id, user_level):
    business_metrics.increment_conversion("feature_flag_new_feature_enabled")
else:
    business_metrics.increment_conversion("feature_flag_new_feature_disabled")
```

### Grafana Dashboard
Create dashboard panels to monitor:
- Feature flag enablement rates by level
- Error rates comparison (enabled vs disabled)
- Performance metrics comparison
- User engagement by feature status

## Security and Access Control

### Authentication
- API endpoints should be protected with authentication
- CLI tool should require authentication for production use
- Audit logging tracks all changes with user attribution

### Authorization
- Implement role-based access control:
  - **Admin**: Full CRUD operations on feature flags
  - **Operator**: Read-only access and enable/disable operations
  - **Developer**: Create/update flags in development environment

### Audit Trail
All changes are logged in `feature_flag_audit_log` table:
- Who made the change
- What was changed
- When the change was made
- Old and new values
- Reason for change

## Testing

### Unit Tests
```python
import pytest
from app.services.feature_flags import FeatureFlagService, RolloutType

@pytest.mark.asyncio
async def test_percentage_rollout():
    service = FeatureFlagService()
    
    # Test with user ID that should be in 50% rollout
    result = service._check_percentage_rollout("user_123", 50)
    assert isinstance(result, bool)
    
    # Test edge cases
    assert service._check_percentage_rollout("user_123", 0) == False
    assert service._check_percentage_rollout("user_123", 100) == True

@pytest.mark.asyncio
async def test_level_rollout():
    service = FeatureFlagService()
    
    assert service._check_level_rollout("S", "S,A,B") == True
    assert service._check_level_rollout("C", "S,A,B") == False
    assert service._check_level_rollout("A", "") == False
```

### Integration Tests
```python
@pytest.mark.asyncio
async def test_feature_flag_api_flow():
    # Create flag
    response = await client.post("/api/v1/feature-flags/", json={
        "name": "test_flag",
        "description": "Test flag",
        "rollout_type": "level",
        "target_levels": "S"
    })
    assert response.status_code == 200
    
    # Check flag
    response = await client.post("/api/v1/feature-flags/check", json={
        "name": "test_flag",
        "user_id": "user_123",
        "user_level": "S"
    })
    assert response.json()["enabled"] == False  # Not enabled yet
    
    # Enable flag
    response = await client.put("/api/v1/feature-flags/test_flag", json={
        "enabled": True
    })
    assert response.status_code == 200
    
    # Check again
    response = await client.post("/api/v1/feature-flags/check", json={
        "name": "test_flag",
        "user_id": "user_123",
        "user_level": "S"
    })
    assert response.json()["enabled"] == True
```

## Troubleshooting

### Feature Flag Not Working
1. **Check if flag exists**: `GET /api/v1/feature-flags/{name}`
2. **Verify flag is enabled**: Check `enabled` field
3. **Validate rollout configuration**: Ensure user attributes match rollout rules
4. **Check cache**: Clear cache if recent changes aren't reflected
5. **Review audit logs**: Check for recent changes or errors

### Performance Issues
1. **Monitor cache hit rate**: Low hit rate indicates cache issues
2. **Check database queries**: Ensure indexes are properly configured
3. **Review rollout complexity**: Percentage rollouts require more computation
4. **Monitor service health**: Check service logs for errors

### Data Consistency
1. **Audit log review**: Check for unexpected changes
2. **Cache invalidation**: Ensure cache is cleared after updates
3. **Database connectivity**: Verify database connection is stable
4. **Concurrent updates**: Handle race conditions in updates

## Best Practices

### 1. Naming Conventions
- Use descriptive, lowercase names with underscores: `new_ai_model`, `enhanced_matching`
- Avoid spaces and special characters
- Keep names under 100 characters

### 2. Description Standards
- Provide clear, concise descriptions
- Include the purpose and target users
- Update descriptions when functionality changes

### 3. Rollout Strategy
- Always start with smallest segment (S level)
- Monitor metrics at each phase
- Have rollback plan ready
- Document success criteria for each phase

### 4. Testing
- Test feature flag logic before deployment
- Use feature flags in test environment
- Verify rollback procedures
- Test edge cases (boundary conditions)

### 5. Monitoring
- Set up alerts for error rate increases
- Monitor performance metrics
- Track business impact
- Review audit logs regularly

### 6. Documentation
- Document purpose and target audience for each flag
- Record rollout timeline and decisions
- Maintain integration examples
- Update documentation as system evolves

## Future Enhancements

1. **Time-Based Rollout**: Enable features based on time schedules
2. **Geographic Rollout**: Roll out features by region
3. **A/B Testing Integration**: Built-in A/B test framework
4. **Dependency Management**: Handle feature flag dependencies
5. **Webhook Notifications**: Notify on flag changes
6. **Advanced Analytics**: Built-in analytics dashboard
7. **Rule Engine**: Complex conditional logic for flag evaluation
8. **Multi-Environment Support**: Environment-specific flag configurations

## References

- [Feature Flag Best Practices](https://martinfowler.com/articles/feature-toggles.html)
- [Gradual Rollout Strategies](https://www.atlassian.com/continuous-delivery/principles/continuous-delivery-vs-continuous-deployment)
- [Database Migration Best Practices](https://www.postgresql.org/docs/current/ddl.html)

## Acceptance Criteria

- ✅ Feature flag database schema implemented
- ✅ Core service with all rollout types implemented
- ✅ REST API for flag management created
- ✅ CLI tool for command-line operations
- ✅ Level-based rollout functionality working
- ✅ Audit logging for all changes
- ✅ Integration with existing application
- ✅ Comprehensive documentation
- ✅ Testing guidelines provided

## Related Tasks

- P5-05: Prometheus Monitoring (can track feature flag metrics)
- P5-06: Grafana Dashboards (visualize flag usage)
- P5-08: Conversion Panel (monitor impact of feature rollouts)

---

**Status**: ✅ Completed
**Last Updated**: 2026-05-21
**Maintained By**: ERIS Development Team