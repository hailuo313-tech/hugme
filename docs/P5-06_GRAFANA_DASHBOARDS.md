# P5-06: Grafana Dashboards and Alerting

## Overview
Comprehensive Grafana monitoring dashboards and alerting system for ERIS production observability, providing real-time visibility into business metrics, system health, and infrastructure performance.

## Implementation Date
2026-05-21

## Architecture

### Components
1. **Grafana Server** - Visualization and alerting platform
2. **Five Core Dashboards** - Specialized monitoring views
3. **Prometheus Alert Rules** - Automated alerting on key metrics
4. **Provisioning Configuration** - Automated dashboard and datasource setup

### Data Flow
```
Prometheus Metrics → Grafana Datasource → Dashboards → Visualization & Alerting
Alert Rules → Prometheus Evaluation → Alertmanager → Notifications
```

## File Structure

```
monitoring/
├── grafana/
│   ├── grafana.ini                  # Grafana configuration
│   ├── provisioning/
│   │   ├── datasources/
│   │   │   └── prometheus.yml       # Prometheus datasource
│   │   └── dashboards/
│   │       └── dashboard.yml        # Dashboard provisioning
│   └── dashboards/
│       ├── business_overview.json   # Business metrics dashboard
│       ├── llm_performance.json     # LLM performance dashboard
│       ├── system_health.json       # System health dashboard
│       ├── infrastructure.json      # Infrastructure dashboard
│       └── realtime_monitoring.json # Real-time monitoring dashboard
└── prometheus/
    └── alerts.yml                   # Prometheus alert rules
```

## Five Core Dashboards

### 1. Business Overview Dashboard
**UID**: `eris-business-overview`

**Purpose**: High-level business metrics and KPIs

**Key Panels**:
- Daily Active Users (gauge)
- Conversion Rate (gauge)
- Total Revenue (gauge)
- Message Queue Size (gauge)
- User Engagement Trend (timeseries)
- Conversion Rate Trend (timeseries)

**Refresh Rate**: 1 minute
**Time Range**: Last 24 hours

**Key Metrics**:
- `eris_users_daily_active` - Daily active users
- `eris_conversion_rate` - Conversion rate
- `eris_revenue_usd` - Total revenue
- `eris_messages_queue_size` - Message queue depth

### 2. LLM Performance Dashboard
**UID**: `eris-llm-performance`

**Purpose**: Monitor AI/LLM processing performance and costs

**Key Panels**:
- LLM Request Rate (gauge)
- P95 Processing Time (gauge)
- Error Rate (gauge)
- Request Rate by Provider/Model (timeseries)
- Processing Time Percentiles (timeseries)
- Token Usage by Type (timeseries)
- LLM Cost by Provider (timeseries)

**Refresh Rate**: 30 seconds
**Time Range**: Last 6 hours

**Key Metrics**:
- `eris_llm_requests_total` - Total LLM requests
- `eris_llm_processing_time_seconds` - Processing time histogram
- `eris_llm_tokens_total` - Token usage
- `eris_llm_cost_usd` - LLM costs

### 3. System Health Dashboard
**UID**: `eris-system-health`

**Purpose**: Application system health and availability monitoring

**Key Panels**:
- API Status (stat)
- API Response Time P95 (gauge)
- WebSocket Connections (gauge)
- HTTP Error Rate (gauge)
- HTTP Request Rate (timeseries)
- WebSocket Message Rate (timeseries)
- Message Queue Depth (timeseries)
- Message Processing Time (timeseries)

**Refresh Rate**: 15 seconds
**Time Range**: Last 1 hour

**Key Metrics**:
- `up{job="eris-api"}` - API uptime
- `http_request_duration_seconds` - API response times
- `eris_websocket_connections_active` - WebSocket connections
- `eris_messages_queue_size` - Message queue depth

### 4. Infrastructure Dashboard
**UID**: `eris-infrastructure`

**Purpose**: Underlying infrastructure and resource monitoring

**Key Panels**:
- CPU Usage (gauge)
- Memory Usage (gauge)
- Disk Usage (gauge)
- Network Traffic (gauge)
- CPU Usage Trend (timeseries)
- Memory Usage Trend (timeseries)
- Database Connection Usage (timeseries)
- Redis Cache Hit Rate (timeseries)

**Refresh Rate**: 30 seconds
**Time Range**: Last 6 hours

**Key Metrics**:
- `node_cpu_seconds_total` - CPU usage
- `node_memory_MemAvailable_bytes` - Memory usage
- `node_filesystem_avail_bytes` - Disk usage
- `pg_stat_activity_count` - Database connections
- `redis_keyspace_hits_total` - Redis cache hits

### 5. Real-time Monitoring Dashboard
**UID**: `eris-realtime-monitoring`

**Purpose**: Real-time operational monitoring for immediate issue detection

**Key Panels**:
- Real-time Online Users (gauge)
- Real-time Message Rate (gauge)
- Real-time Queue Depth (gauge)
- WebSocket Connections (timeseries)
- Message Processing Rate (timeseries)
- HTTP Request Rate (timeseries)
- API Response Time (timeseries)

**Refresh Rate**: 5 seconds
**Time Range**: Last 15 minutes

**Key Metrics**:
- `eris_websocket_connections_active` - Active connections
- `rate(eris_messages_total[1m])` - Message rate
- `rate(http_requests_total[1m])` - HTTP request rate

## Alert Rules

### Business Alerts
- **LowActiveUsers**: Warning when daily active users < 50 for 1h
- **ConversionRateDrop**: Warning when conversion rate < 1% for 2h
- **HighMessageQueue**: Critical when message queue > 1000 for 5m

### LLM Alerts
- **HighLLMErrorRate**: Critical when LLM error rate > 5% for 5m
- **LLMLatencyHigh**: Warning when P95 processing time > 10s for 5m
- **LLMCostSpike**: Warning when cost rate > $10/hour for 10m

### System Alerts
- **APIDown**: Critical when API service down for 1m
- **HighAPIResponseTime**: Warning when P95 response time > 2s for 5m
- **HighHTTPErrorRate**: Critical when 5xx error rate > 5% for 5m
- **WebSocketConnectionDrop**: Warning when connections dropping > 10/min for 2m

### Infrastructure Alerts
- **HighCPUUsage**: Warning when CPU > 80% for 5m
- **HighMemoryUsage**: Warning when memory > 85% for 5m
- **HighDiskUsage**: Critical when disk > 85% for 5m
- **DatabaseConnectionHigh**: Warning when DB connections > 80% for 5m
- **RedisCacheHitRateLow**: Warning when cache hit rate < 80% for 10m

## Deployment

### Docker Compose Configuration
Added Grafana service to `docker-compose.yml`:

```yaml
grafana:
  image: grafana/grafana:latest
  container_name: eris-grafana
  restart: always
  environment:
    GF_SECURITY_ADMIN_USER: ${GRAFANA_ADMIN_USER:-admin}
    GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:-admin}
    GF_INSTALL_PLUGINS: ""
    GF_SERVER_ROOT_URL: http://localhost:3000
  volumes:
    - ./monitoring/grafana/grafana.ini:/etc/grafana/grafana.ini
    - ./monitoring/grafana/provisioning:/etc/grafana/provisioning
    - ./monitoring/grafana/dashboards:/etc/grafana/provisioning/dashboards
    - grafana_data:/var/lib/grafana
  ports:
    - "127.0.0.1:3000:3000"
  depends_on:
    - prometheus
```

### Start Monitoring Stack
```bash
# Start all monitoring services
docker compose up -d prometheus node-exporter postgres-exporter redis-exporter grafana

# Start only Grafana
docker compose up -d grafana
```

### Access Points
- **Grafana UI**: http://localhost:3000
- **Default Credentials**: admin / admin (change in production)
- **Prometheus UI**: http://localhost:9090

## Configuration

### Grafana Configuration (`grafana.ini`)
- HTTP Port: 3000
- Admin User: admin (configurable via environment variable)
- Database: SQLite (persistent volume)
- Theme: Dark mode default

### Datasource Provisioning
- **Name**: Prometheus
- **Type**: Prometheus
- **URL**: http://prometheus:9090
- **Scrape Interval**: 15s
- **Access**: Proxy

### Dashboard Provisioning
- **Folder**: ERIS Monitoring
- **Update Interval**: 10s
- **Auto-update**: Enabled
- **UI Modifications**: Allowed

## Usage

### Accessing Dashboards
1. Navigate to http://localhost:3000
2. Login with admin credentials
3. Browse to Dashboards → ERIS Monitoring folder
4. Select desired dashboard

### Dashboard Navigation
- **Business Overview**: High-level KPIs and trends
- **LLM Performance**: AI processing metrics
- **System Health**: Application health status
- **Infrastructure**: Resource utilization
- **Real-time Monitoring**: Live operational view

### Customizing Dashboards
- Dashboards can be customized via UI
- Changes are persisted to Grafana database
- Provisioning ensures baseline configuration
- Export modified dashboards to update provisioning files

### Alert Management
- View alert rules in Prometheus UI: http://localhost:9090/alerts
- Configure alert notifications in Alertmanager (future)
- Set up notification channels (email, Slack, etc.)
- Configure alert severity and routing

## Testing

### Verify Grafana Access
```bash
# Check Grafana is running
curl http://localhost:3000/api/health

# Check datasource connectivity
curl http://localhost:3000/api/datasources
```

### Verify Dashboards
1. Login to Grafana UI
2. Navigate to Dashboards → ERIS Monitoring
3. Verify all 5 dashboards are present
4. Check panels are loading data
5. Verify time ranges and refresh rates

### Test Alert Rules
```bash
# Check Prometheus rule evaluation
curl http://localhost:9090/api/v1/rules

# View active alerts
curl http://localhost:9090/api/v1/alerts
```

## Maintenance

### Backup Grafana Configuration
```bash
# Backup Grafana database
docker run --rm -v eris_grafana_data:/data -v $(pwd):/backup alpine tar czf /backup/grafana_backup_$(date +%Y%m%d).tar.gz -C /data .

# Backup dashboard configurations
cp -r monitoring/grafana/dashboards backup/grafana_dashboards_$(date +%Y%m%d)
```

### Update Dashboards
1. Modify dashboard JSON files in `monitoring/grafana/dashboards/`
2. Restart Grafana: `docker compose restart grafana`
3. Verify changes in UI
4. Commit updated JSON files to version control

### Update Alert Rules
1. Modify `monitoring/prometheus/alerts.yml`
2. Restart Prometheus: `docker compose restart prometheus`
3. Verify rules in Prometheus UI: http://localhost:9090/alerts
4. Test alert conditions

### Troubleshooting

#### Grafana Not Starting
1. Check Grafana logs: `docker compose logs grafana`
2. Verify configuration file syntax: `monitoring/grafana/grafana.ini`
3. Check volume permissions
4. Verify port 3000 is not in use

#### Dashboards Not Loading
1. Verify Prometheus datasource is configured
2. Check Prometheus is running: `docker compose ps prometheus`
3. Test Prometheus API: `curl http://localhost:9090/api/v1/query?query=up`
4. Check dashboard JSON syntax

#### Alerts Not Firing
1. Verify alert rules are loaded: `curl http://localhost:9090/api/v1/rules`
2. Check rule evaluation interval
3. Verify alert conditions are being met
4. Check Prometheus logs for rule evaluation errors

#### Data Not Displaying
1. Verify metrics are being scraped: `curl http://localhost:9090/api/v1/targets`
2. Check time range in dashboard
3. Verify metric names match Prometheus data
4. Check for label mismatches

## Security Considerations

1. **Authentication**: Change default admin credentials in production
2. **Network Isolation**: Grafana binds to localhost only
3. **HTTPS**: Configure reverse proxy with SSL for production
4. **Role-Based Access**: Configure user roles and permissions
5. **Audit Logging**: Enable Grafana audit logging
6. **Secret Management**: Use environment variables for sensitive data

## Performance Impact

- **Grafana Resource Usage**: ~200MB memory, ~0.5 CPU core
- **Dashboard Refresh**: Optimized intervals (5s-1m based on use case)
- **Query Performance**: Efficient PromQL queries with proper time ranges
- **Browser Load**: Optimized panel counts and query complexity

## Future Enhancements

1. **Alertmanager Integration**: Configure notification routing
2. **Custom Plugins**: Add specialized visualization plugins
3. **Advanced Annotations**: Integrate deployment and incident markers
4. **ML Anomaly Detection**: Implement anomaly detection on metrics
5. **Report Generation**: Automated PDF/PNG report generation
6. **Mobile Support**: Responsive design for mobile monitoring
7. **Multi-tenancy**: Team-specific dashboards and permissions

## Integration with CI/CD

### GitHub Actions Integration
```yaml
name: Monitoring Tests
on: [push, pull_request]
jobs:
  test-grafana:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Start services
        run: docker compose up -d prometheus grafana
      - name: Wait for services
        run: sleep 30
      - name: Test Grafana health
        run: curl -f http://localhost:3000/api/health
      - name: Test datasource
        run: curl -f http://localhost:3000/api/datasources
```

## Monitoring Best Practices

1. **Dashboard Design**: Keep dashboards focused and actionable
2. **Alert Tuning**: Set appropriate thresholds to avoid alert fatigue
3. **Performance**: Optimize queries for fast dashboard loading
4. **Documentation**: Document dashboard purpose and key metrics
5. **Regular Review**: Review and update dashboards regularly
6. **User Training**: Train team members on dashboard usage

## References

- [Grafana Documentation](https://grafana.com/docs/)
- [Prometheus Alerting Rules](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)
- [Grafana Provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/)
- [PromQL Query Language](https://prometheus.io/docs/prometheus/latest/querying/basics/)

## Acceptance Criteria

- ✅ Five core dashboards implemented (Business, LLM, System, Infrastructure, Real-time)
- ✅ Grafana server configured and integrated with Prometheus
- ✅ Dashboard provisioning configured for automated setup
- ✅ Comprehensive alert rules defined for key metrics
- ✅ Docker Compose integration completed
- ✅ Access documentation and usage guidelines provided
- ✅ Testing and troubleshooting procedures documented

## Related Tasks

- P5-05: Prometheus Monitoring Instrumentation (prerequisite)
- P5-07: Payment Conversion Funnel SQL (next)
- P5-08: Grafana Conversion Dashboard Integration (next)

---

**Status**: ✅ Completed
**Last Updated**: 2026-05-21
**Maintained By**: ERIS Development Team