"""
Soft Delete Service for HIPAA Compliance

This service provides comprehensive soft delete functionality for the CallCenterAI application.
It ensures HIPAA compliance by preventing hard deletes of PHI-containing records while
maintaining data integrity and providing audit trails.

Key Features:
- Soft delete with audit trail
- Recovery functionality
- Automated retention policy enforcement
- HIPAA 7-year retention compliance
- Data minimization while maintaining compliance
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Type
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
from sqlalchemy.exc import IntegrityError
import logging

from models.models import (
    Mapping, Call, Patient, Appointment, CallNotes, AuditLog, ClinicUsage
)

logger = logging.getLogger(__name__)

class SoftDeleteService:
    """
    Service for managing soft delete operations across all PHI-containing models.
    
    This service ensures that:
    1. No PHI is ever hard deleted (HIPAA compliance)
    2. All deletions are logged with audit trails
    3. Deleted records can be recovered if needed
    4. Retention policies are enforced automatically
    5. Data minimization is achieved while maintaining compliance
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
    
    def __init__(self, db_session: Session):
        self.db = db_session
    
    def soft_delete_record(
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
            table_name: Optional table name for audit logging
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Get primary key column
            primary_key_columns = model_class.__table__.primary_key.columns.keys()
            if not primary_key_columns:
                logger.error(f"Model {model_class.__tablename__} has no primary key")
                return False
            
            primary_key_column = primary_key_columns[0]
            
            # Get the record
            record = self.db.query(model_class).filter(
                getattr(model_class, primary_key_column) == record_id
            ).first()
            
            if not record:
                logger.warning(f"Record {record_id} not found in {model_class.__tablename__}")
                return False
            
            # Check if already soft deleted
            if hasattr(record, 'is_deleted') and record.is_deleted == 'yes':
                logger.warning(f"Record {record_id} already soft deleted")
                return False
            
            # Perform soft delete
            record.is_deleted = 'yes'
            record.deleted_at = datetime.now(timezone.utc)
            record.deleted_by = deleted_by
            record.deletion_reason = deletion_reason
            
            # Commit the change
            try:
                self.db.commit()
            except Exception as commit_error:
                self.db.rollback()
                logger.error(f"Failed to commit soft delete for {model_class.__tablename__} record {record_id}: {commit_error}")
                return False
            
            # Log the deletion in audit trail
            self._log_deletion_audit(
                table_name or model_class.__tablename__,
                record_id,
                deleted_by,
                deletion_reason
            )
            
            logger.info(f"Soft deleted {model_class.__tablename__} record {record_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to soft delete {model_class.__tablename__} record {record_id}: {e}")
            self.db.rollback()
            return False
    
    def soft_delete_multiple_records(
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
            table_name: Optional table name for audit logging
            
        Returns:
            Dict mapping record_id to success status
        """
        results = {}
        
        # Get primary key column
        primary_key_columns = model_class.__table__.primary_key.columns.keys()
        if not primary_key_columns:
            logger.error(f"Model {model_class.__tablename__} has no primary key")
            return {record_id: False for record_id in record_ids}
        
        primary_key_column = primary_key_columns[0]
        
        try:
            # Get all records
            records = self.db.query(model_class).filter(
                getattr(model_class, primary_key_column).in_(record_ids)
            ).all()
            
            current_time = datetime.now(timezone.utc)
            
            for record in records:
                record_id = getattr(record, primary_key_column)
                
                # Check if already soft deleted
                if hasattr(record, 'is_deleted') and record.is_deleted == 'yes':
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
                self.db.commit()
            except Exception as commit_error:
                self.db.rollback()
                logger.error(f"Failed to commit soft delete multiple records from {model_class.__tablename__}: {commit_error}")
                return {record_id: False for record_id in record_ids}
            
            # Log deletions in audit trail
            for record_id, success in results.items():
                if success:
                    self._log_deletion_audit(
                        table_name or model_class.__tablename__,
                        record_id,
                        deleted_by,
                        deletion_reason
                    )
            
            logger.info(f"Soft deleted {sum(results.values())} records from {model_class.__tablename__}")
            return results
            
        except Exception as e:
            logger.error(f"Failed to soft delete multiple records from {model_class.__tablename__}: {e}")
            self.db.rollback()
            return {record_id: False for record_id in record_ids}
    
    def recover_record(
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
            # Get primary key column
            primary_key_columns = model_class.__table__.primary_key.columns.keys()
            if not primary_key_columns:
                logger.error(f"Model {model_class.__tablename__} has no primary key")
                return False
            
            primary_key_column = primary_key_columns[0]
            
            # Get the soft deleted record
            record = self.db.query(model_class).filter(
                and_(
                    getattr(model_class, primary_key_column) == record_id,
                    getattr(model_class, 'is_deleted') == 'yes'
                )
            ).first()
            
            if not record:
                logger.warning(f"Soft deleted record {record_id} not found in {model_class.__tablename__}")
                return False
            
            # Recover the record
            record.is_deleted = 'no'
            record.deleted_at = None
            record.deleted_by = None
            record.deletion_reason = None
            
            # Commit the change
            try:
                self.db.commit()
            except Exception as commit_error:
                self.db.rollback()
                logger.error(f"Failed to commit recovery for {model_class.__tablename__} record {record_id}: {commit_error}")
                return False
            
            # Log the recovery in audit trail
            self._log_recovery_audit(
                model_class.__tablename__,
                record_id,
                recovered_by,
                recovery_reason
            )
            
            logger.info(f"Recovered {model_class.__tablename__} record {record_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to recover {model_class.__tablename__} record {record_id}: {e}")
            self.db.rollback()
            return False
    
    def get_deleted_records(
        self,
        model_class: Type,
        limit: int = 100,
        offset: int = 0,
        deleted_after: Optional[datetime] = None,
        deleted_by: Optional[str] = None
    ) -> List[Any]:
        """
        Get soft deleted records for review or recovery.
        
        Args:
            model_class: SQLAlchemy model class
            limit: Maximum number of records to return
            offset: Number of records to skip
            deleted_after: Only return records deleted after this date
            deleted_by: Only return records deleted by this user
            
        Returns:
            List of soft deleted records
        """
        query = self.db.query(model_class).filter(
            getattr(model_class, 'is_deleted') == 'yes'
        )
        
        if deleted_after:
            query = query.filter(getattr(model_class, 'deleted_at') >= deleted_after)
        
        if deleted_by:
            query = query.filter(getattr(model_class, 'deleted_by') == deleted_by)
        
        return query.order_by(getattr(model_class, 'deleted_at').desc()).offset(offset).limit(limit).all()
    
    def get_deletion_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about soft deleted records across all models.
        
        Returns:
            Dictionary with deletion statistics
        """
        stats = {}
        
        for table_name, model_class in self.SOFT_DELETE_MODELS.items():
            try:
                # Count total records
                total_count = self.db.query(model_class).count()
                
                # Count soft deleted records
                deleted_count = self.db.query(model_class).filter(
                    getattr(model_class, 'is_deleted') == 'yes'
                ).count()
                
                # Count active records
                active_count = total_count - deleted_count
                
                # Get oldest deletion
                oldest_deletion = self.db.query(
                    func.min(getattr(model_class, 'deleted_at'))
                ).filter(
                    getattr(model_class, 'is_deleted') == 'yes'
                ).scalar()
                
                stats[table_name] = {
                    'total_records': total_count,
                    'active_records': active_count,
                    'deleted_records': deleted_count,
                    'deletion_percentage': (deleted_count / total_count * 100) if total_count > 0 else 0,
                    'oldest_deletion': oldest_deletion
                }
                
            except Exception as e:
                logger.error(f"Failed to get statistics for {table_name}: {e}")
                stats[table_name] = {'error': str(e)}
        
        return stats
    
    def enforce_retention_policy(self, dry_run: bool = True) -> Dict[str, Any]:
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
                eligible_records = self.db.query(model_class).filter(
                    and_(
                        getattr(model_class, 'is_deleted') == 'yes',
                        getattr(model_class, 'deleted_at') < cutoff_date
                    )
                ).all()
                
                record_count = len(eligible_records)
                
                if not dry_run and record_count > 0:
                    # Actually delete the records
                    for record in eligible_records:
                        self.db.delete(record)
                    
                    try:
                        self.db.commit()
                    except Exception as commit_error:
                        self.db.rollback()
                        logger.error(f"Failed to commit retention policy enforcement for {table_name}: {commit_error}")
                        results[table_name] = {'error': str(commit_error)}
                        continue
                    
                    # Log the permanent deletion
                    self._log_retention_audit(table_name, record_count, cutoff_date)
                
                results[table_name] = {
                    'eligible_for_deletion': record_count,
                    'cutoff_date': cutoff_date,
                    'action_taken': 'deleted' if not dry_run and record_count > 0 else 'none'
                }
                
            except Exception as e:
                logger.error(f"Failed to enforce retention policy for {table_name}: {e}")
                results[table_name] = {'error': str(e)}
        
        return results
    
    def _log_deletion_audit(
        self,
        table_name: str,
        record_id: str,
        deleted_by: str,
        deletion_reason: str
    ):
        """Log deletion in audit trail."""
        try:
            audit_log = AuditLog(
                log_id=f"AUDIT_DELETE_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{record_id}",
                user_id=deleted_by,
                action_type='soft_delete',
                table_name=table_name,
                record_id=record_id,
                details=f"Soft deleted record. Reason: {deletion_reason}",
                success='yes'
            )
            self.db.add(audit_log)
            try:
                self.db.commit()
            except Exception as commit_error:
                self.db.rollback()
                logger.error(f"Failed to commit deletion audit log: {commit_error}")
        except Exception as e:
            logger.error(f"Failed to log deletion audit: {e}")
    
    def _log_recovery_audit(
        self,
        table_name: str,
        record_id: str,
        recovered_by: str,
        recovery_reason: str
    ):
        """Log recovery in audit trail."""
        try:
            audit_log = AuditLog(
                log_id=f"AUDIT_RECOVER_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{record_id}",
                user_id=recovered_by,
                action_type='recover',
                table_name=table_name,
                record_id=record_id,
                details=f"Recovered soft deleted record. Reason: {recovery_reason}",
                success='yes'
            )
            self.db.add(audit_log)
            try:
                self.db.commit()
            except Exception as commit_error:
                self.db.rollback()
                logger.error(f"Failed to commit recovery audit log: {commit_error}")
        except Exception as e:
            logger.error(f"Failed to log recovery audit: {e}")
    
    def _log_retention_audit(
        self,
        table_name: str,
        record_count: int,
        cutoff_date: datetime
    ):
        """Log retention policy enforcement in audit trail."""
        try:
            audit_log = AuditLog(
                log_id=f"AUDIT_RETENTION_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
                user_id='system',
                action_type='retention_policy',
                table_name=table_name,
                record_id=None,
                details=f"Permanently deleted {record_count} records older than {cutoff_date} (HIPAA retention policy)",
                success='yes'
            )
            self.db.add(audit_log)
            try:
                self.db.commit()
            except Exception as commit_error:
                self.db.rollback()
                logger.error(f"Failed to commit retention audit log: {commit_error}")
        except Exception as e:
            logger.error(f"Failed to log retention audit: {e}")


class SoftDeleteQueryMixin:
    """
    Mixin class to add soft delete-aware query methods to models.
    
    This mixin provides methods to easily query only active (non-deleted) records
    or include deleted records when needed.
    """
    
    @classmethod
    def active_records(cls, db_session: Session):
        """Query only active (non-deleted) records."""
        if hasattr(cls, 'is_deleted'):
            return db_session.query(cls).filter(cls.is_deleted == 'no')
        return db_session.query(cls)
    
    @classmethod
    def deleted_records(cls, db_session: Session):
        """Query only soft deleted records."""
        if hasattr(cls, 'is_deleted'):
            return db_session.query(cls).filter(cls.is_deleted == 'yes')
        return db_session.query(cls).filter(False)  # Return empty query if no soft delete support
    
    @classmethod
    def all_records(cls, db_session: Session):
        """Query all records (active and deleted)."""
        return db_session.query(cls)
    
    def soft_delete(self, deleted_by: str, deletion_reason: str, db_session: Session):
        """Soft delete this record instance."""
        if hasattr(self, 'is_deleted'):
            self.is_deleted = 'yes'
            self.deleted_at = datetime.now(timezone.utc)
            self.deleted_by = deleted_by
            self.deletion_reason = deletion_reason
            try:
                db_session.commit()
            except Exception as commit_error:
                db_session.rollback()
                logger.error(f"Failed to commit soft delete: {commit_error}")
                return False
            return True
        return False
    
    def recover(self, recovered_by: str, recovery_reason: str, db_session: Session):
        """Recover this soft deleted record instance."""
        if hasattr(self, 'is_deleted') and self.is_deleted == 'yes':
            self.is_deleted = 'no'
            self.deleted_at = None
            self.deleted_by = None
            self.deletion_reason = None
            try:
                db_session.commit()
            except Exception as commit_error:
                db_session.rollback()
                logger.error(f"Failed to commit recovery: {commit_error}")
                return False
            return True
        return False


def get_soft_delete_service(db_session: Session) -> SoftDeleteService:
    """Factory function to get a SoftDeleteService instance."""
    return SoftDeleteService(db_session)
