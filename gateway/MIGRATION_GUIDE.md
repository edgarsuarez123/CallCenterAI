# Database Migration Guide

This guide explains how to manage database schema changes using Alembic migrations in the CallCenterAI system.

## Why Migrations Are Critical

### Problems with `create_all()`
The previous approach using `Base.metadata.create_all()` was dangerous because:

1. **Data Loss**: Drops and recreates all tables, destroying existing data
2. **No Version Control**: No tracking of schema changes over time
3. **Deployment Issues**: Schema mismatches between environments
4. **No Rollback**: Cannot undo problematic changes
5. **Compliance Violations**: No audit trail for HIPAA compliance

### Benefits of Alembic Migrations

1. **Schema Version Control**: Every change is tracked with timestamps and descriptions
2. **Zero-Downtime Deployments**: Migrate schema before deploying code
3. **Data Safety**: Preserve existing data while changing structure
4. **Rollback Capability**: Can undo problematic migrations
5. **Audit Trail**: Complete history for compliance requirements
6. **Team Coordination**: Everyone gets identical schemas

## Migration Commands

### Using the Migration Script

We provide a convenient `migrate.py` script for common operations:

```bash
# Apply all pending migrations
python migrate.py upgrade

# Create a new migration (auto-generate from model changes)
python migrate.py revision "Add new column to patients table"

# Show migration history
python migrate.py history

# Show current migration version
python migrate.py current

# Rollback last migration
python migrate.py downgrade

# Reset database (DEVELOPMENT ONLY - DESTROYS ALL DATA)
python migrate.py reset
```

### Direct Alembic Commands

You can also use Alembic directly:

```bash
# Apply all pending migrations
alembic upgrade head

# Create new migration
alembic revision --autogenerate -m "Description of changes"

# Show history
alembic history --verbose

# Show current version
alembic current

# Rollback one migration
alembic downgrade -1

# Rollback to specific version
alembic downgrade 0001
```

### Critical Migration: Constraints and Indexes

The second migration (0002) adds comprehensive database constraints and indexes:

```bash
# Apply the constraints and indexes migration
alembic upgrade head

# This migration adds:
# - Double booking prevention (unique constraint)
# - Data validation constraints (check constraints)
# - Performance indexes for common queries
# - Business rule enforcement
```

**⚠️ IMPORTANT**: This migration is critical for production systems. It prevents:
- Double booking of appointments
- Invalid data entry
- Performance issues with large datasets
- Business rule violations

See `DATABASE_CONSTRAINTS_GUIDE.md` for detailed information about all constraints and indexes.

### Critical Migration: Soft Delete Implementation

The third migration (0003) adds comprehensive soft delete functionality for HIPAA compliance:

```bash
# Apply the soft delete migration
alembic upgrade head

# This migration adds:
# - Soft delete fields to all PHI-containing models
# - HIPAA 7-year retention compliance
# - Data recovery capabilities
# - Comprehensive audit trails
```

**⚠️ CRITICAL**: This migration is essential for HIPAA compliance. It provides:
- **7-Year Retention**: Prevents hard deletion of patient records (HIPAA requirement)
- **Data Recovery**: Enables recovery of accidentally deleted records
- **Audit Trail**: Maintains complete history of all deletion operations
- **Legal Protection**: Ensures historical records are available for legal requests

**Without this migration**:
- Hard deletion of PHI violates HIPAA regulations (fines up to $50,000 per violation)
- No recovery mechanism for accidentally deleted patient records
- Missing audit trail for compliance requirements
- Legal liability from data loss

See `SOFT_DELETE_GUIDE.md` for comprehensive documentation on the soft delete implementation.

## Development Workflow

### 1. Making Schema Changes

1. **Modify Models**: Update your SQLAlchemy models in `models/`
2. **Generate Migration**: Run `python migrate.py revision "Description"`
3. **Review Migration**: Check the generated migration file in `migrations/versions/`
4. **Test Migration**: Apply to development database
5. **Commit Changes**: Include both model changes and migration file

### 2. Example: Adding a New Column

```python
# In models/models.py - add new column
class Patient(Base):
    # ... existing columns ...
    emergency_contact_token = Column(String(64), nullable=True)  # NEW
```

```bash
# Generate migration
python migrate.py revision "Add emergency contact to patients"

# Review the generated migration file
# Apply the migration
python migrate.py upgrade
```

### 3. Example: Renaming a Column

```python
# In models/models.py - rename column
class Patient(Base):
    # ... existing columns ...
    phone_token = Column(String(64), nullable=True)  # Renamed from phone_number_token
```

```bash
# Generate migration
python migrate.py revision "Rename phone_number_token to phone_token"

# The generated migration will include:
# op.alter_column('patients', 'phone_number_token', new_column_name='phone_token')
```

## Production Deployment

### 1. Pre-Deployment Checklist

- [ ] All migrations tested in staging environment
- [ ] Migration duration measured (important for large tables)
- [ ] Rollback procedure tested
- [ ] Database backup created
- [ ] Team notified of deployment window

### 2. Deployment Steps

1. **Backup Database**: Create full backup before migration
2. **Run Migrations**: `alembic upgrade head`
3. **Deploy Code**: Deploy new application code
4. **Verify**: Check application health and functionality
5. **Monitor**: Watch for any issues

### 3. Rollback Procedure

If issues occur after deployment:

1. **Stop Application**: Prevent further issues
2. **Rollback Code**: Deploy previous version
3. **Rollback Schema**: `alembic downgrade -1` (or specific version)
4. **Verify**: Ensure system is working
5. **Investigate**: Fix issues before re-deploying

## Migration Best Practices

### 1. Migration Naming

Use descriptive names that explain what changed:

```bash
# Good
python migrate.py revision "Add appointment_reminder_sent column to appointments"
python migrate.py revision "Create index on patient phone tokens for faster lookups"
python migrate.py revision "Add foreign key constraint between calls and clinics"

# Bad
python migrate.py revision "Update schema"
python migrate.py revision "Fix stuff"
python migrate.py revision "Changes"
```

### 2. Data Migrations

For complex data changes, create custom migration logic:

```python
def upgrade() -> None:
    # Add new column
    op.add_column('patients', sa.Column('new_field', sa.String(100), nullable=True))
    
    # Migrate existing data
    connection = op.get_bind()
    connection.execute(
        "UPDATE patients SET new_field = 'default_value' WHERE new_field IS NULL"
    )
    
    # Make column non-nullable
    op.alter_column('patients', 'new_field', nullable=False)
```

### 3. Large Table Migrations

For tables with millions of rows:

1. **Add Column as Nullable**: Allow gradual population
2. **Populate in Batches**: Use background jobs
3. **Add Constraints**: After data is populated
4. **Monitor Performance**: Watch for locks and timeouts

### 4. Breaking Changes

When making breaking changes:

1. **Deprecation Period**: Keep old column/table for a while
2. **Gradual Migration**: Move data over time
3. **Application Updates**: Update code to use new structure
4. **Cleanup**: Remove old structure in later migration

## Environment Configuration

### Development

```bash
# Local development with Docker
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_USER=callcenterai
export POSTGRES_PASSWORD=ChangeThisNow_!
export POSTGRES_DB=callcenterai

python migrate.py upgrade
```

### Staging

```bash
# Staging environment
export POSTGRES_HOST=staging-db.example.com
export POSTGRES_PORT=5432
export POSTGRES_USER=callcenterai_staging
export POSTGRES_PASSWORD=staging_password
export POSTGRES_DB=callcenterai_staging

python migrate.py upgrade
```

### Production

```bash
# Production environment (use secrets management)
export POSTGRES_HOST=prod-db.example.com
export POSTGRES_PORT=5432
export POSTGRES_USER=callcenterai_prod
export POSTGRES_PASSWORD=$(vault kv get -field=password secret/callcenterai/db)
export POSTGRES_DB=callcenterai_prod

python migrate.py upgrade
```

## Troubleshooting

### Common Issues

1. **Migration Fails**: Check database connection and permissions
2. **Schema Drift**: Ensure all environments run same migrations
3. **Foreign Key Errors**: Check migration order and dependencies
4. **Lock Timeouts**: Use smaller batches for large tables

### Recovery Procedures

1. **Failed Migration**: Fix the migration file and re-run
2. **Partial Migration**: Check migration history and current state
3. **Data Corruption**: Restore from backup and re-run migrations
4. **Schema Mismatch**: Compare current schema with expected state

## Security Considerations

### 1. Sensitive Data

- Never include actual PHI in migration files
- Use tokenization for sensitive columns
- Encrypt migration files if they contain secrets

### 2. Access Control

- Limit who can run migrations in production
- Use service accounts with minimal required permissions
- Log all migration activities for audit

### 3. Backup Strategy

- Always backup before migrations
- Test restore procedures regularly
- Keep multiple backup copies

## Monitoring and Alerting

### 1. Migration Monitoring

- Track migration duration
- Monitor for failed migrations
- Alert on schema drift

### 2. Performance Impact

- Measure query performance before/after
- Monitor for increased lock contention
- Watch for storage usage changes

## Compliance and Audit

### 1. HIPAA Requirements

- Document all schema changes
- Maintain migration history
- Track PHI-related modifications

### 2. Audit Trail

- Log who ran migrations
- Record when migrations were applied
- Track rollback activities

## Integration with CI/CD

### 1. Automated Testing

```yaml
# Example GitHub Actions workflow
- name: Run Database Migrations
  run: |
    python migrate.py upgrade
    python migrate.py current
    
- name: Test Migration Rollback
  run: |
    python migrate.py downgrade -1
    python migrate.py upgrade
```

### 2. Deployment Pipeline

1. **Test Migrations**: Run in staging first
2. **Validate Schema**: Check migration results
3. **Deploy Code**: After successful migration
4. **Health Check**: Verify application functionality

This migration system ensures safe, trackable, and reversible database schema changes while maintaining HIPAA compliance and operational reliability.
