# Soft Delete Implementation Guide

## Overview

The CallCenterAI application implements a comprehensive soft delete system to ensure HIPAA compliance, data recovery capabilities, and maintain audit trails. This system prevents hard deletion of PHI-containing records while providing mechanisms for data recovery and automated retention policy enforcement.

## Why Soft Delete is Critical

### 1. HIPAA 7-Year Retention Requirement
- **Regulatory Compliance**: HIPAA mandates keeping patient records for 7 years
- **Legal Protection**: Hard delete violates regulatory requirements and can result in fines up to $50,000 per violation
- **Audit Trail**: Maintains complete history of all patient interactions and data access

### 2. Accidental Deletion Recovery
- **Human Error Protection**: Prevents permanent data loss from user mistakes
- **Recovery Mechanism**: Allows restoration of accidentally deleted patient records
- **Customer Service**: Enables quick resolution of "oops, I didn't mean to delete that" situations

### 3. Legal Discovery Protection
- **Litigation Support**: Ensures historical records are available for legal requests
- **Compliance Evidence**: Proves adherence to retention policies
- **Data Integrity**: Maintains referential integrity across related records

### 4. Business Intelligence
- **Historical Analysis**: Enables analysis of patient churn and deletion patterns
- **Reporting**: Includes deleted records in historical reporting
- **Data Mining**: Allows identification of patterns in patient data management

### 5. Prevents Cascading Failures
- **Referential Integrity**: Keeps foreign key relationships intact
- **Application Stability**: Prevents crashes from broken references
- **Data Consistency**: Maintains data relationships even after "deletion"

## Models with Soft Delete Support

The following models implement soft delete functionality:

### PHI-Containing Models
- **`patients`**: Patient records with tokenized PHI
- **`calls`**: Call records containing caller information
- **`appointments`**: Appointment records with patient details
- **`call_notes`**: AI-generated summaries and notes
- **`mappings`**: Encrypted PHI tokens

### Compliance-Critical Models
- **`audit_logs`**: Audit trail for all PHI access
- **`clinic_usage`**: Usage metrics (may contain PHI patterns)

### Models WITHOUT Soft Delete
- **`providers`**: Non-PHI business data
- **`clinics`**: Non-PHI business data
- **`appointment_slots`**: Non-PHI scheduling data
- **`appointment_blocks`**: Non-PHI scheduling data
- **`call_queue`**: Non-PHI routing data
- **`system_config`**: Non-PHI configuration data
- **`clinic_licenses`**: Non-PHI business data
- **`google_calendar_credentials`**: Encrypted OAuth tokens (not PHI)

## Soft Delete Fields

Each model with soft delete support includes these fields:

```sql
is_deleted VARCHAR(10) DEFAULT 'no' NOT NULL
deleted_at TIMESTAMP WITH TIME ZONE
deleted_by VARCHAR(64)
deletion_reason VARCHAR(200)
```

### Field Descriptions
- **`is_deleted`**: Flag indicating soft delete status ('yes' or 'no')
- **`deleted_at`**: Timestamp when the record was soft deleted
- **`deleted_by`**: User ID or system identifier who deleted the record
- **`deletion_reason`**: Human-readable reason for deletion

## Database Constraints and Indexes

### Check Constraints
```sql
CHECK (is_deleted IN ('yes', 'no'))
```

### Performance Indexes
- **Active Records**: Partial indexes for `is_deleted = 'no'`
- **Deletion Tracking**: Indexes on `deleted_at` and `deleted_by`
- **Recovery Queries**: Optimized for finding deleted records

### Partial Indexes
```sql
CREATE INDEX idx_patients_active_only ON patients (patient_id) 
WHERE is_deleted = 'no';

CREATE INDEX idx_calls_active_only ON calls (call_id) 
WHERE is_deleted = 'no';
```

## Soft Delete Service

The `SoftDeleteService` class provides comprehensive soft delete functionality:

### Key Methods

#### `soft_delete_record()`
```python
soft_delete_service.soft_delete_record(
    model_class=Patient,
    record_id="PATIENT_001",
    deleted_by="admin_user",
    deletion_reason="Patient requested account closure"
)
```

#### `soft_delete_multiple_records()`
```python
results = soft_delete_service.soft_delete_multiple_records(
    model_class=Call,
    record_ids=["CALL_001", "CALL_002"],
    deleted_by="system",
    deletion_reason="Bulk cleanup of test data"
)
```

#### `recover_record()`
```python
success = soft_delete_service.recover_record(
    model_class=Patient,
    record_id="PATIENT_001",
    recovered_by="admin_user",
    recovery_reason="Patient requested account reactivation"
)
```

#### `get_deleted_records()`
```python
deleted_patients = soft_delete_service.get_deleted_records(
    model_class=Patient,
    limit=50,
    deleted_after=datetime(2025, 1, 1),
    deleted_by="admin_user"
)
```

#### `enforce_retention_policy()`
```python
# Dry run to see what would be deleted
results = soft_delete_service.enforce_retention_policy(dry_run=True)

# Actually enforce the policy
results = soft_delete_service.enforce_retention_policy(dry_run=False)
```

## Query Patterns

### Active Records Only (Default)
```python
# Only get active (non-deleted) patients
active_patients = db.query(Patient).filter(Patient.is_deleted == 'no').all()

# Using the mixin
active_patients = Patient.active_records(db).all()
```

### Include Deleted Records
```python
# Get all patients (active and deleted)
all_patients = db.query(Patient).all()

# Using the mixin
all_patients = Patient.all_records(db).all()
```

### Only Deleted Records
```python
# Get only soft deleted patients
deleted_patients = db.query(Patient).filter(Patient.is_deleted == 'yes').all()

# Using the mixin
deleted_patients = Patient.deleted_records(db).all()
```

## HIPAA Retention Policy

### 7-Year Retention Period
- **Duration**: 2555 days (7 years × 365 days)
- **Enforcement**: Automated cleanup of records older than 7 years
- **Audit Trail**: All retention policy actions are logged

### Automated Cleanup
```python
# Run retention policy enforcement (dry run)
results = soft_delete_service.enforce_retention_policy(dry_run=True)

# Actually delete old records
results = soft_delete_service.enforce_retention_policy(dry_run=False)
```

### Retention Policy Schedule
- **Frequency**: Monthly
- **Time**: During maintenance window
- **Monitoring**: All actions logged in audit trail

## Audit Trail

### Deletion Audit Logs
Every soft delete operation creates an audit log entry:
```python
{
    "action_type": "soft_delete",
    "table_name": "patients",
    "record_id": "PATIENT_001",
    "user_id": "admin_user",
    "details": "Soft deleted record. Reason: Patient requested account closure",
    "success": "yes"
}
```

### Recovery Audit Logs
Every recovery operation creates an audit log entry:
```python
{
    "action_type": "recover",
    "table_name": "patients",
    "record_id": "PATIENT_001",
    "user_id": "admin_user",
    "details": "Recovered soft deleted record. Reason: Patient requested account reactivation",
    "success": "yes"
}
```

### Retention Policy Audit Logs
Every retention policy enforcement creates an audit log entry:
```python
{
    "action_type": "retention_policy",
    "table_name": "patients",
    "record_id": null,
    "user_id": "system",
    "details": "Permanently deleted 150 records older than 2025-01-15 (HIPAA retention policy)",
    "success": "yes"
}
```

## API Endpoints

### Soft Delete Endpoints
```python
# Soft delete a patient
DELETE /api/patients/{patient_id}
{
    "deletion_reason": "Patient requested account closure"
}

# Recover a patient
POST /api/patients/{patient_id}/recover
{
    "recovery_reason": "Patient requested account reactivation"
}

# Get deleted patients
GET /api/patients/deleted?limit=50&offset=0

# Get deletion statistics
GET /api/admin/deletion-statistics
```

### Admin Endpoints
```python
# Enforce retention policy (dry run)
POST /api/admin/retention-policy/enforce?dry_run=true

# Enforce retention policy (actual)
POST /api/admin/retention-policy/enforce?dry_run=false
```

## Migration Guide

### Running the Migration
```bash
# Apply the soft delete migration
python migrate.py upgrade

# Verify the migration
python migrate.py current
```

### Migration Contents
The `0003_add_soft_delete_fields.py` migration:
1. Adds soft delete fields to all PHI-containing models
2. Creates check constraints for data validation
3. Adds performance indexes for soft delete queries
4. Creates partial indexes for active records

### Rollback
```bash
# Rollback the soft delete migration
python migrate.py downgrade 0002
```

## Best Practices

### 1. Always Use Soft Delete Service
```python
# Good: Use the service
soft_delete_service.soft_delete_record(Patient, patient_id, user_id, reason)

# Bad: Direct database manipulation
patient.is_deleted = 'yes'  # Missing audit trail
```

### 2. Provide Meaningful Deletion Reasons
```python
# Good: Specific reason
deletion_reason = "Patient requested account closure due to moving out of state"

# Bad: Generic reason
deletion_reason = "Deleted"
```

### 3. Regular Retention Policy Enforcement
```python
# Schedule monthly retention policy enforcement
# This should be automated via cron job or scheduled task
```

### 4. Monitor Deletion Statistics
```python
# Regularly check deletion statistics
stats = soft_delete_service.get_deletion_statistics()
# Alert if deletion rates are unusually high
```

### 5. Backup Before Retention Enforcement
```python
# Always backup before running retention policy enforcement
# This provides an additional safety net
```

## Troubleshooting

### Common Issues

#### 1. Records Not Appearing in Queries
**Problem**: Records not showing up in application queries
**Solution**: Check if records are soft deleted and adjust query filters

#### 2. Foreign Key Constraint Violations
**Problem**: Cannot delete record due to foreign key constraints
**Solution**: Use soft delete instead of hard delete

#### 3. Performance Issues with Large Datasets
**Problem**: Queries slow due to large number of soft deleted records
**Solution**: Use partial indexes and regular retention policy enforcement

#### 4. Audit Trail Missing
**Problem**: Deletion not logged in audit trail
**Solution**: Always use SoftDeleteService methods

### Monitoring and Alerts

#### Key Metrics to Monitor
- **Deletion Rate**: Number of records soft deleted per day
- **Recovery Rate**: Number of records recovered per day
- **Retention Policy**: Number of records permanently deleted monthly
- **Audit Log Growth**: Size of audit log table

#### Alert Conditions
- **High Deletion Rate**: > 100 records deleted per day
- **Missing Audit Logs**: Deletion without corresponding audit log
- **Retention Policy Failures**: Errors during retention policy enforcement
- **Database Size Growth**: Unusual growth in database size

## Security Considerations

### Access Control
- **Soft Delete**: Requires appropriate permissions
- **Recovery**: Requires admin-level permissions
- **Retention Policy**: Requires system-level permissions

### Audit Trail Protection
- **Immutable Logs**: Audit logs cannot be modified
- **Secure Storage**: Audit logs stored in separate, secure location
- **Access Logging**: All access to audit logs is logged

### Data Minimization
- **Gradual Exposure Reduction**: Soft deleted records not accessible via normal queries
- **Retention Enforcement**: Automatic cleanup after 7 years
- **Encryption**: All PHI remains encrypted even when soft deleted

## Compliance Benefits

### HIPAA Compliance
- **7-Year Retention**: Automatic compliance with retention requirements
- **Audit Trail**: Complete record of all data access and modifications
- **Data Integrity**: Prevents accidental data loss

### Legal Protection
- **Discovery Support**: Historical records available for legal requests
- **Compliance Evidence**: Proof of proper data governance
- **Risk Mitigation**: Reduces legal liability from data loss

### Business Continuity
- **Recovery Capability**: Quick restoration of accidentally deleted data
- **Customer Service**: Better support for customer requests
- **Data Analytics**: Historical data available for business intelligence

## Conclusion

The soft delete implementation provides a robust, HIPAA-compliant solution for data management in the CallCenterAI application. It ensures data integrity, provides recovery capabilities, and maintains comprehensive audit trails while supporting business operations and regulatory compliance.

For questions or issues with the soft delete implementation, refer to the troubleshooting section or contact the development team.
