# Background Job Management System

## Overview

The CallCenterAI Background Job Management System provides comprehensive automation for maintaining system health, ensuring HIPAA compliance, and automating routine maintenance tasks. This system is critical for preventing resource leaks, maintaining data integrity, and ensuring the system operates smoothly without manual intervention.

## Why This Is Critical

### 1. Automatic Cleanup Without Manual Intervention
- **Expired slot holds released every minute** - No manual database queries needed
- **System self-heals automatically** - Reduces operational burden
- **Prevents resource leaks** - Slots held for 5 minutes, user abandons call, system releases automatically

### 2. Monthly Billing Cycle Automation
- **Usage counters reset first of month** - No manual SQL scripts needed
- **Consistent timing across all clinics** - Prevents billing errors
- **Real-time usage tracking** - Updates every 5 minutes

### 3. HIPAA Retention Compliance
- **After 7 years, data automatically purged** - Reduces legal liability from old data
- **Demonstrates data minimization** - No manual intervention required
- **Audit trail maintenance** - Old logs deleted automatically

### 4. Proactive Monitoring
- **Database health checked every 5 minutes** - Alert before connection pool exhausted
- **Fix issues before users affected** - Prevents outages
- **System metrics collection** - Performance monitoring

### 5. Graceful Degradation
- **License expiration checked daily** - Grace period warnings sent automatically
- **Suspensions happen predictably** - No surprise service interruptions
- **Abandoned call cleanup** - Calls stuck "active" for 24+ hours marked abandoned

## System Architecture

### Core Components

1. **BackgroundJobManager** - Central manager for all background jobs
2. **JobDefinition** - Defines job properties and scheduling
3. **JobResult** - Tracks execution results and performance
4. **API Endpoints** - REST API for monitoring and control

### Job Types

#### Cleanup Jobs
- **cleanup_expired_slots** - Release appointment slots held too long (every minute)
- **cleanup_abandoned_calls** - Mark calls as abandoned if active too long (every 5 minutes)
- **cleanup_old_audit_logs** - Delete audit logs older than retention period (daily)

#### Billing Jobs
- **monthly_billing_cycle** - Reset usage counters and process monthly billing (daily check)
- **update_usage_counters** - Update real-time usage counters for billing (every 5 minutes)

#### HIPAA Compliance Jobs
- **enforce_retention_policy** - Hard delete records older than 7 years (daily)

#### Monitoring Jobs
- **database_health_check** - Monitor database health and connection pool (every 5 minutes)
- **license_expiration_check** - Check for expiring licenses and send warnings (daily)
- **system_metrics_collection** - Collect and log system performance metrics (every minute)

## Configuration

### Environment Variables

```bash
# Background job settings
APP_BACKGROUND_JOBS_ENABLED=true
APP_BACKGROUND_JOBS_MAX_RETRIES=3
APP_BACKGROUND_JOBS_TIMEOUT_SECONDS=300
```

### Job Scheduling

Jobs are scheduled using interval-based execution:
- **High Priority**: Critical system health jobs (every minute)
- **Normal Priority**: Regular maintenance jobs (every 5 minutes)
- **Low Priority**: Analytics and cleanup jobs (daily)

## API Endpoints

### Job Management

#### Get All Jobs Status
```http
GET /api/v1/background-jobs/
```

#### Get Specific Job Status
```http
GET /api/v1/background-jobs/{job_id}
```

#### Run Job Immediately
```http
POST /api/v1/background-jobs/{job_id}/run
```

#### Enable/Disable Job
```http
PUT /api/v1/background-jobs/{job_id}/enable
PUT /api/v1/background-jobs/{job_id}/disable
```

### Health Monitoring

#### System Health
```http
GET /api/v1/background-jobs/health/system
```

#### Detailed Health
```http
GET /api/v1/background-jobs/health/detailed
```

#### Performance Statistics
```http
GET /api/v1/background-jobs/stats/performance
```

### Job Control

#### Start Background Jobs
```http
POST /api/v1/background-jobs/start
```

#### Stop Background Jobs
```http
POST /api/v1/background-jobs/stop
```

## Job Details

### Cleanup Jobs

#### Expired Slot Cleanup
- **Purpose**: Release appointment slots that have been held too long
- **Frequency**: Every minute
- **Logic**: Find slots with `is_booked="held"` and `held_until < now()`
- **Action**: Set `is_booked="no"`, clear hold fields
- **Impact**: Prevents permanent slot locks from abandoned calls

#### Abandoned Call Cleanup
- **Purpose**: Mark calls as abandoned if they've been active too long
- **Frequency**: Every 5 minutes
- **Logic**: Find calls with `status="active"` and `started_at < now() - 24 hours`
- **Action**: Set `status="abandoned"`, set `ended_at`
- **Impact**: Accurate call statistics and clean data for reporting

#### Old Audit Log Cleanup
- **Purpose**: Delete audit logs older than retention period
- **Frequency**: Daily
- **Logic**: Find logs with `created_at < now() - 7 years`
- **Action**: Hard delete old logs
- **Impact**: Keeps database size manageable, prevents performance degradation

### Billing Jobs

#### Monthly Billing Cycle
- **Purpose**: Reset usage counters and process monthly billing
- **Frequency**: Daily (only runs on 1st of month)
- **Logic**: Check if current date is 1st of month
- **Action**: Reset `current_month_calls`, `current_month_minutes`, update billing dates
- **Impact**: Consistent billing cycles across all clinics

#### Usage Counter Updates
- **Purpose**: Update real-time usage counters for billing
- **Frequency**: Every 5 minutes
- **Logic**: Count active calls for each clinic
- **Action**: Update `current_concurrent_calls` for all licenses
- **Impact**: Accurate real-time usage tracking

### HIPAA Compliance Jobs

#### Retention Policy Enforcement
- **Purpose**: Hard delete records older than 7 years
- **Frequency**: Daily
- **Logic**: Use SoftDeleteService to find records older than 7 years
- **Action**: Hard delete expired records
- **Impact**: HIPAA compliance, data minimization, reduced legal liability

### Monitoring Jobs

#### Database Health Check
- **Purpose**: Monitor database health and connection pool
- **Frequency**: Every 5 minutes
- **Logic**: Check database connectivity, pool status, warnings
- **Action**: Log warnings if pool utilization high or issues detected
- **Impact**: Proactive issue detection, prevents outages

#### License Expiration Check
- **Purpose**: Check for expiring licenses and send warnings
- **Frequency**: Daily
- **Logic**: Find licenses in grace period with expired grace period
- **Action**: Suspend licenses, log warnings
- **Impact**: Predictable license management, no surprise interruptions

#### System Metrics Collection
- **Purpose**: Collect and log system performance metrics
- **Frequency**: Every minute
- **Logic**: Collect CPU, memory, disk usage, job statistics
- **Action**: Log performance metrics
- **Impact**: Performance monitoring, capacity planning

## Error Handling

### Retry Logic
- **Max Retries**: 3 attempts per job
- **Retry Delay**: Exponential backoff
- **Failure Handling**: Disable job after max retries exceeded

### Error Logging
- **Structured Logging**: All job executions logged with context
- **Error Aggregation**: Similar errors grouped and counted
- **Alerting**: Critical failures trigger alerts

### Job Recovery
- **Automatic Recovery**: Jobs automatically retry on failure
- **Manual Recovery**: Admin can re-enable disabled jobs
- **Health Monitoring**: System health score based on job success rates

## Performance Monitoring

### Metrics Tracked
- **Execution Time**: Duration of each job execution
- **Success Rate**: Percentage of successful executions
- **Records Processed**: Number of records affected by each job
- **System Health**: Overall system health score

### Performance Optimization
- **Concurrent Execution**: Jobs run in separate threads
- **Priority Scheduling**: High-priority jobs run first
- **Resource Management**: Jobs have timeout limits
- **Memory Management**: Results limited to last 100 executions

## Security Considerations

### Access Control
- **API Authentication**: All endpoints require authentication
- **Role-Based Access**: Admin-only access to job control
- **Audit Logging**: All job operations logged

### Data Protection
- **PHI Handling**: Jobs respect PHI masking and encryption
- **Secure Execution**: Jobs run in isolated context
- **Error Sanitization**: Error messages don't expose sensitive data

## Troubleshooting

### Common Issues

#### Job Not Running
- **Check**: Job enabled status
- **Check**: Schedule interval configuration
- **Check**: System logs for errors
- **Solution**: Re-enable job or fix configuration

#### High Failure Rate
- **Check**: Database connectivity
- **Check**: Resource availability
- **Check**: Job timeout settings
- **Solution**: Increase timeout or fix underlying issues

#### Performance Issues
- **Check**: Job execution frequency
- **Check**: Database query performance
- **Check**: System resource usage
- **Solution**: Optimize queries or adjust schedule

### Monitoring Commands

#### Check Job Status
```bash
curl -X GET "http://localhost:8000/api/v1/background-jobs/health/system"
```

#### View Job History
```bash
curl -X GET "http://localhost:8000/api/v1/background-jobs/{job_id}/history"
```

#### Manual Job Execution
```bash
curl -X POST "http://localhost:8000/api/v1/background-jobs/{job_id}/run"
```

## Best Practices

### Job Design
- **Idempotent**: Jobs should be safe to run multiple times
- **Atomic**: Jobs should complete fully or fail completely
- **Efficient**: Jobs should process data in batches
- **Logged**: All job activities should be logged

### Monitoring
- **Health Checks**: Regular health check endpoints
- **Alerting**: Set up alerts for job failures
- **Metrics**: Track job performance metrics
- **Logs**: Monitor job execution logs

### Maintenance
- **Regular Review**: Review job performance regularly
- **Tuning**: Adjust schedules based on system load
- **Updates**: Keep job logic updated with business requirements
- **Testing**: Test job changes in staging environment

## Integration

### Application Startup
Background jobs are automatically started when the application starts:

```python
# In main.py
from services.background_jobs import start_background_jobs

@app.on_event("startup")
def on_startup():
    start_background_jobs()
```

### Application Shutdown
Background jobs are gracefully stopped when the application shuts down:

```python
@app.on_event("shutdown")
def on_shutdown():
    stop_background_jobs()
```

### Custom Jobs
You can register custom jobs:

```python
from services.background_jobs import get_background_job_manager

manager = get_background_job_manager()
manager.register_job(
    job_id="custom_job",
    name="Custom Job",
    description="Custom background job",
    function=my_custom_function,
    schedule_interval=3600,  # Every hour
    priority=JobPriority.NORMAL
)
```

## Conclusion

The Background Job Management System is essential for maintaining the health, compliance, and performance of the CallCenterAI system. It provides:

- **Automatic cleanup** of expired resources
- **Billing automation** for consistent revenue tracking
- **HIPAA compliance** through retention policy enforcement
- **Proactive monitoring** to prevent issues
- **Graceful degradation** for predictable system behavior

This system ensures the CallCenterAI platform operates reliably without manual intervention, reducing operational costs and improving system reliability.
