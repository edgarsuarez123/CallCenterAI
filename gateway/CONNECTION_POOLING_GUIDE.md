# Database Connection Pooling Guide

This guide explains the database connection pooling configuration in the CallCenterAI system and how to monitor and troubleshoot connection issues.

## Why Connection Pooling Is Critical

### Problems Without Connection Pooling
- **Connection Exhaustion**: Each request creates a new connection, quickly exhausting PostgreSQL's max_connections limit
- **Performance Degradation**: Creating new connections takes 100-200ms each, causing slow response times
- **Memory Leaks**: Connections not properly closed consume server memory indefinitely
- **Cascading Failures**: When connections are exhausted, all new requests fail with "too many connections"
- **No Traffic Spike Handling**: System crashes when traffic doubles instead of gracefully degrading

### Benefits of Proper Connection Pooling
- **Connection Reuse**: Reusing existing connections (< 1ms) vs creating new ones (100-200ms)
- **Controlled Resource Usage**: Predictable memory consumption and connection limits
- **Traffic Spike Handling**: Overflow connections handle temporary load increases
- **Health Monitoring**: Automatic detection and replacement of stale connections
- **Graceful Degradation**: System continues working under load with performance warnings

## Configuration

### Environment Variables

```bash
# Base number of connections to maintain in the pool
DB_POOL_SIZE=10

# Additional connections allowed during traffic spikes
DB_MAX_OVERFLOW=20

# Seconds to wait for a connection from the pool
DB_POOL_TIMEOUT=30

# Recycle connections after this many seconds (1 hour = 3600)
DB_POOL_RECYCLE=3600

# Test connections before use (recommended: true)
DB_POOL_PRE_PING=true
```

### Configuration Guidelines

#### Pool Size (`DB_POOL_SIZE`)
- **Small Clinic (1-5 providers)**: 5-10 connections
- **Medium Clinic (5-20 providers)**: 10-20 connections
- **Large Clinic (20+ providers)**: 20-50 connections
- **Multi-tenant System**: 50-100 connections

#### Max Overflow (`DB_MAX_OVERFLOW`)
- Should be 1.5-2x the pool size
- Allows handling traffic spikes without blocking requests
- Temporary connections that are closed when not needed

#### Pool Timeout (`DB_POOL_TIMEOUT`)
- 30 seconds is recommended for most applications
- Prevents requests from hanging indefinitely
- Should be longer than typical request duration

#### Pool Recycle (`DB_POOL_RECYCLE`)
- 3600 seconds (1 hour) is recommended
- Prevents stale connections from network issues
- Balances connection freshness with performance

#### Pre-ping (`DB_POOL_PRE_PING`)
- Always set to `true` in production
- Tests connections before use
- Prevents "connection already closed" errors

## Monitoring

### Health Check Endpoints

#### Basic Health Check
```bash
curl http://localhost:8443/healthz
```

#### Database Health Check
```bash
curl http://localhost:8443/health/database
```

Response includes:
- Database connection status
- Connection pool health
- Pool utilization statistics
- Configuration details
- Any warnings or issues

#### Pool-Specific Health Check
```bash
curl http://localhost:8443/health/pool
```

Response includes:
- Pool utilization percentage
- Number of checked out connections
- Available connections
- Warnings and recommendations

### Pool Status Monitoring

```python
from services.database import ConnectionPoolMonitor

# Get current pool status
status = ConnectionPoolMonitor.get_pool_status()
print(f"Pool utilization: {status['utilization_percent']}%")
print(f"Available connections: {status['available_connections']}")

# Check if pool is healthy
is_healthy = ConnectionPoolMonitor.is_pool_healthy()
print(f"Pool healthy: {is_healthy}")

# Get warnings
warnings = ConnectionPoolMonitor.get_pool_warnings()
for warning in warnings:
    print(f"Warning: {warning}")
```

### Key Metrics to Monitor

1. **Pool Utilization**: Should stay below 90%
2. **Overflow Usage**: Frequent overflow indicates need for larger pool
3. **Connection Timeouts**: High timeout rates indicate pool exhaustion
4. **Connection Errors**: Monitor for "too many connections" errors
5. **Response Times**: Slow responses may indicate connection issues

## Troubleshooting

### Common Issues and Solutions

#### "Too Many Connections" Error
**Symptoms**: PostgreSQL errors about too many connections
**Causes**: 
- Pool size too small for load
- Connection leaks (connections not returned to pool)
- Database max_connections limit reached

**Solutions**:
1. Increase `DB_POOL_SIZE` and `DB_MAX_OVERFLOW`
2. Check for connection leaks in code
3. Increase PostgreSQL `max_connections` setting
4. Monitor pool utilization to find optimal size

#### High Pool Utilization (>90%)
**Symptoms**: Pool health warnings, slow response times
**Solutions**:
1. Increase `DB_POOL_SIZE`
2. Optimize database queries to reduce connection hold time
3. Implement connection pooling at application level
4. Consider read replicas for read-heavy workloads

#### Frequent Overflow Usage
**Symptoms**: Regular use of overflow connections
**Solutions**:
1. Increase `DB_POOL_SIZE` to handle normal load
2. Keep `DB_MAX_OVERFLOW` for true spikes only
3. Monitor traffic patterns to predict load

#### Stale Connection Errors
**Symptoms**: "connection already closed" or similar errors
**Solutions**:
1. Ensure `DB_POOL_PRE_PING=true`
2. Reduce `DB_POOL_RECYCLE` time
3. Check network stability between app and database

#### Slow Response Times
**Symptoms**: High latency on database operations
**Solutions**:
1. Check pool utilization - may need larger pool
2. Monitor connection checkout times
3. Optimize database queries
4. Check for connection leaks

### Connection Leak Detection

```python
import time
from services.database import ConnectionPoolMonitor

def detect_connection_leaks():
    """Monitor for connection leaks over time."""
    initial_status = ConnectionPoolMonitor.get_pool_status()
    initial_checked_out = initial_status['checked_out']
    
    time.sleep(60)  # Wait 1 minute
    
    final_status = ConnectionPoolMonitor.get_pool_status()
    final_checked_out = final_status['checked_out']
    
    if final_checked_out > initial_checked_out:
        print(f"Potential connection leak: {final_checked_out - initial_checked_out} connections not returned")
    else:
        print("No connection leaks detected")
```

### Performance Testing

```python
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from services.database import get_db_session

def test_pool_performance():
    """Test connection pool performance under load."""
    def make_request():
        start_time = time.time()
        with get_db_session() as db:
            result = db.execute("SELECT 1").scalar()
        end_time = time.time()
        return end_time - start_time
    
    # Test with 50 concurrent requests
    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = [executor.submit(make_request) for _ in range(50)]
        times = [future.result() for future in futures]
    
    avg_time = sum(times) / len(times)
    max_time = max(times)
    
    print(f"Average response time: {avg_time:.3f}s")
    print(f"Maximum response time: {max_time:.3f}s")
    
    if avg_time > 0.1:  # 100ms
        print("WARNING: Average response time is high - check pool configuration")
```

## Best Practices

### Code Patterns

#### Always Use Context Managers
```python
# Good: Automatic connection management
def get_patient(patient_id: str):
    with get_db_session() as db:
        return db.query(Patient).filter_by(patient_id=patient_id).first()

# Bad: Manual connection management (error-prone)
def get_patient_bad(patient_id: str):
    db = SessionLocal()
    try:
        return db.query(Patient).filter_by(patient_id=patient_id).first()
    finally:
        db.close()  # Easy to forget in complex code
```

#### Use Dependency Injection for FastAPI
```python
# Good: FastAPI dependency injection
@app.get("/patients/{patient_id}")
def get_patient(patient_id: str, db: Session = Depends(get_db)):
    return db.query(Patient).filter_by(patient_id=patient_id).first()
```

#### Handle Exceptions Properly
```python
# Good: Proper exception handling
def create_appointment(appointment_data: dict):
    with get_db_session() as db:
        try:
            appointment = Appointment(**appointment_data)
            db.add(appointment)
            db.commit()
            return appointment
        except Exception as e:
            db.rollback()
            raise
```

### Production Deployment

#### Environment-Specific Configuration
```bash
# Development
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10

# Staging
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20

# Production
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=40
```

#### Monitoring Setup
1. Set up alerts for pool utilization >90%
2. Monitor connection timeout rates
3. Track response times for database operations
4. Set up dashboards for pool metrics

#### Load Testing
1. Test with expected production load
2. Gradually increase load to find breaking point
3. Monitor pool behavior under stress
4. Adjust configuration based on results

## Security Considerations

### Connection Security
- Use encrypted connections (SSL/TLS) to database
- Implement proper authentication and authorization
- Use connection pooling to limit database access points
- Monitor for suspicious connection patterns

### Resource Protection
- Set appropriate pool limits to prevent resource exhaustion
- Implement rate limiting to prevent abuse
- Monitor for connection leaks and unusual patterns
- Use connection timeouts to prevent hanging requests

## Migration from Non-Pooled Setup

If migrating from a system without connection pooling:

1. **Start Conservative**: Begin with small pool sizes
2. **Monitor Closely**: Watch for connection issues
3. **Gradual Increase**: Increase pool size based on monitoring
4. **Test Thoroughly**: Load test with realistic traffic patterns
5. **Have Rollback Plan**: Keep old configuration available

## Conclusion

Proper connection pooling is essential for production database applications. The CallCenterAI system includes comprehensive connection pooling with monitoring and health checks to ensure reliable performance under load.

Key takeaways:
- Always use connection pooling in production
- Monitor pool utilization and health
- Configure pool size based on expected load
- Test thoroughly before deployment
- Have monitoring and alerting in place
