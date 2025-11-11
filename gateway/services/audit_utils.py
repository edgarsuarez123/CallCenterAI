"""
Audit Utilities
Shared audit logging functions extracted from multiple services.
"""

from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import AuditLog
from services.crypto import make_unique_audit_log_id, get_request_context


async def log_audit_trail(
    db: AsyncSession,
    table_name: str,
    record_id: str,
    action_type: str,
    old_values: Optional[Dict[str, Any]] = None,
    new_values: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    service_name: Optional[str] = None
) -> None:
    """
    Log audit trail for changes.
    
    Args:
        db: Database session
        table_name: Name of the table being audited
        record_id: ID of the record being audited
        action_type: Type of action (CREATE, UPDATE, DELETE, etc.)
        old_values: Previous values (for UPDATE/DELETE)
        new_values: New values (for CREATE/UPDATE)
        user_id: User ID (optional, will try to get from request context)
        ip_address: IP address (optional, will try to get from request context)
        user_agent: User agent string (optional, defaults to service_name)
        service_name: Name of the service making the audit log (optional)
    """
    try:
        # Build details string
        details = ""
        if old_values:
            details += f"Old values: {old_values}. "
        if new_values:
            details += f"New values: {new_values}"
        if not details:
            details = f"{action_type} on {table_name}"
        
        # Try to get request context if user_id/ip_address not provided
        if user_id is None or ip_address is None:
            try:
                ctx = get_request_context()
                if user_id is None:
                    user_id = ctx.user_id if hasattr(ctx, 'user_id') else "system"
                if ip_address is None:
                    ip_address = ctx.ip_address if hasattr(ctx, 'ip_address') else "127.0.0.1"
            except Exception:
                # Fallback if request context not available
                if user_id is None:
                    user_id = "system"
                if ip_address is None:
                    ip_address = "127.0.0.1"
        
        # Use service_name as user_agent if not provided
        if user_agent is None:
            user_agent = service_name or "SystemService"
        
        # Create audit log
        audit_log = AuditLog(
            log_id=make_unique_audit_log_id(),
            table_name=table_name,
            record_id=record_id,
            action_type=action_type,
            details=details,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        db.add(audit_log)
        # Note: Audit log will be committed with the transaction
        
    except Exception as e:
        # Don't raise - audit logging failures shouldn't break the main operation
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to log audit: {e}")

