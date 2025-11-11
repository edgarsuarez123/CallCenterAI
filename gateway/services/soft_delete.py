"""
Soft Delete Service for HIPAA Compliance

This service provides soft delete functionality for the CallCenterAI application.
It ensures HIPAA compliance by preventing hard deletes of PHI-containing records.

Key Features:
- Soft delete with basic logging
- Recovery functionality
- HIPAA 7-year retention policy enforcement
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Type
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, select, delete as sql_delete

from services.structured_logging import get_logger, LogCategory
from models.models import (
    Mapping, Call, Patient, Appointment, CallNotes, AuditLog, ClinicUsage
)

logger = get_logger("soft_delete")


class SoftDeleteService:
    """
    Service for managing soft delete operations across all PHI-containing models.
    
    This service ensures that:
    1. No PHI is ever hard deleted (HIPAA compliance)
    2. All deletions are logged
    3. Deleted records can be recovered if needed
    4. Retention policies are enforced automatically
    """
    
    # Models that support soft delete (contain PHI or are critical for compliance)
    SOFT_DELETE_MODELS = {
        'mappings': Mapping,
        'calls': Call,
        'patients': Patient,
        'appointments': Appointment,
        'call_notes': CallNotes,
        'audit_logs': AuditLog,
        'clinic_usage': ClinicUsage
    }
    
    # HIPAA retention period (7 years)
    HIPAA_RETENTION_DAYS = 2555  # 7 years * 365 days
    
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
    
    async def soft_delete_record(
        self,
        model_class: Type,
        record_id: str,
        deleted_by: str,
        deletion_reason: str,
        table_name: Optional[str] = None
    ) -> bool:
        """
        Soft delete a single record.
        
        Args:
            model_class: SQLAlchemy model class
            record_id: Primary key of the record to delete
            deleted_by: User ID or system identifier who deleted the record
            deletion_reason: Reason for deletion (compliance, cleanup, etc.)
            table_name: Optional table name for logging
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Validate model has required soft delete fields
            required_fields = ['is_deleted', 'deleted_at', 'deleted_by', 'deletion_reason']
            missing_fields = [field for field in required_fields if not hasattr(model_class, field)]
            if missing_fields:
                logger.error(
                    f"Model {model_class.__tablename__} missing required soft delete fields: {missing_fields}",
                    LogCategory.DATABASE
                )
                return False
            
            # Get primary key column
            primary_key_columns = model_class.__table__.primary_key.columns.keys()
            if not primary_key_columns:
                logger.error(
                    f"Model {model_class.__tablename__} has no primary key",
                    LogCategory.DATABASE
                )
                return False
            
            primary_key_column = primary_key_columns[0]
            
            # Get the record
            record_result = await self.db.execute(select(model_class).where(
                getattr(model_class, primary_key_column) == record_id
            ))
            record = record_result.scalar_one_or_none()
            
            if not record:
                logger.warning(
                    f"Record {record_id} not found in {model_class.__tablename__}",
                    LogCategory.DATABASE
                )
                return False
            
            # Check if already soft deleted
            if record.is_deleted == 'yes':
                logger.warning(
                    f"Record {record_id} already soft deleted",
                    LogCategory.DATABASE
                )
                return False
            
            # Perform soft delete
            record.is_deleted = 'yes'
            record.deleted_at = datetime.now(timezone.utc)
            record.deleted_by = deleted_by
            record.deletion_reason = deletion_reason
            
            # Commit the change
            try:
                await self.db.commit()
            except Exception as commit_error:
                await self.db.rollback()
                logger.error(
                    f"Failed to commit soft delete for {model_class.__tablename__} record {record_id}",
                    LogCategory.DATABASE,
                    exception=commit_error
                )
                return False
            
            # Log the deletion
            table_name_str = table_name or model_class.__tablename__
            logger.info(
                f"Soft deleted {table_name_str} record {record_id}",
                LogCategory.AUDIT,
                extra_data={
                    "table_name": table_name_str,
                    "record_id": record_id,
                    "deleted_by": deleted_by,
                    "deletion_reason": deletion_reason
                }
            )
            return True
            
        except Exception as e:
            logger.error(
                f"Failed to soft delete {model_class.__tablename__} record {record_id}",
                LogCategory.DATABASE,
                exception=e
            )
            await self.db.rollback()
            return False
    
    async def soft_delete_multiple_records(
        self,
        model_class: Type,
        record_ids: List[str],
        deleted_by: str,
        deletion_reason: str,
        table_name: Optional[str] = None
    ) -> Dict[str, bool]:
        """
        Soft delete multiple records in a single transaction.
        
        Args:
            model_class: SQLAlchemy model class
            record_ids: List of primary keys to delete
            deleted_by: User ID or system identifier
            deletion_reason: Reason for deletion
            table_name: Optional table name for logging
            
        Returns:
            Dict mapping record_id to success status
        """
        results = {}
        
        # Validate model has required soft delete fields
        required_fields = ['is_deleted', 'deleted_at', 'deleted_by', 'deletion_reason']
        missing_fields = [field for field in required_fields if not hasattr(model_class, field)]
        if missing_fields:
            logger.error(
                f"Model {model_class.__tablename__} missing required soft delete fields: {missing_fields}",
                LogCategory.DATABASE
            )
            return {record_id: False for record_id in record_ids}
        
        # Get primary key column
        primary_key_columns = model_class.__table__.primary_key.columns.keys()
        if not primary_key_columns:
            logger.error(
                f"Model {model_class.__tablename__} has no primary key",
                LogCategory.DATABASE
            )
            return {record_id: False for record_id in record_ids}
        
        primary_key_column = primary_key_columns[0]
        
        try:
            # Get all records
            records_result = await self.db.execute(select(model_class).where(
                getattr(model_class, primary_key_column).in_(record_ids)
            ))
            records = list(records_result.scalars().all())
            
            current_time = datetime.now(timezone.utc)
            
            for record in records:
                record_id = getattr(record, primary_key_column)
                
                # Check if already soft deleted
                if record.is_deleted == 'yes':
                    results[record_id] = False
                    continue
                
                # Perform soft delete
                record.is_deleted = 'yes'
                record.deleted_at = current_time
                record.deleted_by = deleted_by
                record.deletion_reason = deletion_reason
                
                results[record_id] = True
            
            # Commit all changes
            try:
                await self.db.commit()
            except Exception as commit_error:
                await self.db.rollback()
                logger.error(
                    f"Failed to commit soft delete multiple records from {model_class.__tablename__}",
                    LogCategory.DATABASE,
                    exception=commit_error
                )
                return {record_id: False for record_id in record_ids}
            
            # Log the deletions
            successful_count = sum(results.values())
            table_name_str = table_name or model_class.__tablename__
            logger.info(
                f"Soft deleted {successful_count} records from {table_name_str}",
                LogCategory.AUDIT,
                extra_data={
                    "table_name": table_name_str,
                    "deleted_count": successful_count,
                    "total_count": len(record_ids),
                    "deleted_by": deleted_by,
                    "deletion_reason": deletion_reason
                }
            )
            return results
            
        except Exception as e:
            logger.error(
                f"Failed to soft delete multiple records from {model_class.__tablename__}",
                LogCategory.DATABASE,
                exception=e
            )
            await self.db.rollback()
            return {record_id: False for record_id in record_ids}
    
    async def recover_record(
        self,
        model_class: Type,
        record_id: str,
        recovered_by: str,
        recovery_reason: str
    ) -> bool:
        """
        Recover a soft deleted record.
        
        Args:
            model_class: SQLAlchemy model class
            record_id: Primary key of the record to recover
            recovered_by: User ID who recovered the record
            recovery_reason: Reason for recovery
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Validate model has required soft delete fields
            required_fields = ['is_deleted', 'deleted_at', 'deleted_by', 'deletion_reason']
            missing_fields = [field for field in required_fields if not hasattr(model_class, field)]
            if missing_fields:
                logger.error(
                    f"Model {model_class.__tablename__} missing required soft delete fields: {missing_fields}",
                    LogCategory.DATABASE
                )
                return False
            
            # Get primary key column
            primary_key_columns = model_class.__table__.primary_key.columns.keys()
            if not primary_key_columns:
                logger.error(
                    f"Model {model_class.__tablename__} has no primary key",
                    LogCategory.DATABASE
                )
                return False
            
            primary_key_column = primary_key_columns[0]
            
            # Get the soft deleted record
            record_result = await self.db.execute(select(model_class).where(
                and_(
                    getattr(model_class, primary_key_column) == record_id,
                    model_class.is_deleted == 'yes'
                )
            ))
            record = record_result.scalar_one_or_none()
            
            if not record:
                logger.warning(
                    f"Soft deleted record {record_id} not found in {model_class.__tablename__}",
                    LogCategory.DATABASE
                )
                return False
            
            # Recover the record
            record.is_deleted = 'no'
            record.deleted_at = None
            record.deleted_by = None
            record.deletion_reason = None
            
            # Commit the change
            try:
                await self.db.commit()
            except Exception as commit_error:
                await self.db.rollback()
                logger.error(
                    f"Failed to commit recovery for {model_class.__tablename__} record {record_id}",
                    LogCategory.DATABASE,
                    exception=commit_error
                )
                return False
            
            # Log the recovery
            logger.info(
                f"Recovered {model_class.__tablename__} record {record_id}",
                LogCategory.AUDIT,
                extra_data={
                    "table_name": model_class.__tablename__,
                    "record_id": record_id,
                    "recovered_by": recovered_by,
                    "recovery_reason": recovery_reason
                }
            )
            return True
            
        except Exception as e:
            logger.error(
                f"Failed to recover {model_class.__tablename__} record {record_id}",
                LogCategory.DATABASE,
                exception=e
            )
            await self.db.rollback()
            return False
    
    async def enforce_retention_policy(self, dry_run: bool = True) -> Dict[str, Any]:
        """
        Enforce HIPAA retention policy by permanently deleting records older than 7 years.
        
        Args:
            dry_run: If True, only report what would be deleted without actually deleting
            
        Returns:
            Dictionary with retention policy enforcement results
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=self.HIPAA_RETENTION_DAYS)
        results = {}
        
        for table_name, model_class in self.SOFT_DELETE_MODELS.items():
            try:
                # Find records eligible for permanent deletion
                eligible_records_result = await self.db.execute(select(model_class).where(
                    and_(
                        getattr(model_class, 'is_deleted') == 'yes',
                        getattr(model_class, 'deleted_at') < cutoff_date
                    )
                ))
                eligible_records = list(eligible_records_result.scalars().all())
                
                record_count = len(eligible_records)
                
                if not dry_run and record_count > 0:
                    # Actually delete the records using async delete statement
                    # Get primary key column for delete statement
                    primary_key_columns = model_class.__table__.primary_key.columns.keys()
                    if primary_key_columns:
                        primary_key_column = primary_key_columns[0]
                        record_ids = [getattr(record, primary_key_column) for record in eligible_records]
                        
                        # Use async delete statement
                        await self.db.execute(
                            sql_delete(model_class).where(
                                getattr(model_class, primary_key_column).in_(record_ids)
                            )
                        )
                    else:
                        # Fallback: delete records using delete statement without primary key filter
                        # This is rare - most models have primary keys
                        await self.db.execute(
                            sql_delete(model_class).where(
                                model_class.is_deleted == 'yes',
                                model_class.deleted_at < cutoff_date
                            )
                        )
                    
                    try:
                        await self.db.commit()
                    except Exception as commit_error:
                        await self.db.rollback()
                        logger.error(
                            f"Failed to commit retention policy enforcement for {table_name}",
                            LogCategory.DATABASE,
                            exception=commit_error
                        )
                        results[table_name] = {'error': str(commit_error)}
                        continue
                    
                    # Log the permanent deletion
                    logger.info(
                        f"Permanently deleted {record_count} records from {table_name} older than {cutoff_date} (HIPAA retention policy)",
                        LogCategory.AUDIT,
                        extra_data={
                            "table_name": table_name,
                            "deleted_count": record_count,
                            "cutoff_date": cutoff_date.isoformat(),
                            "retention_days": self.HIPAA_RETENTION_DAYS
                        }
                    )
                
                results[table_name] = {
                    'eligible_for_deletion': record_count,
                    'cutoff_date': cutoff_date,
                    'action_taken': 'deleted' if not dry_run and record_count > 0 else 'none'
                }
                
            except Exception as e:
                logger.error(
                    f"Failed to enforce retention policy for {table_name}",
                    LogCategory.DATABASE,
                    exception=e
                )
                results[table_name] = {'error': str(e)}
        
        return results


def get_soft_delete_service(db_session: AsyncSession) -> SoftDeleteService:
    """Factory function to get a SoftDeleteService instance."""
    return SoftDeleteService(db_session)
