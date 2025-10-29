import os
import logging
import time
from typing import Generator
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import QueuePool
from sqlalchemy.engine import Engine
from contextlib import contextmanager, asynccontextmanager
from urllib.parse import quote_plus
from services.configuration import get_settings

# Configure logging
logger = logging.getLogger(__name__)

# Get configuration
settings = get_settings()

# Database connection parameters from configuration
DB_USER = settings.database.user
DB_PASS = settings.database.password.get_secret_value()
DB_NAME = settings.database.name
DB_HOST = settings.database.host
DB_PORT = settings.database.port

# Connection pooling configuration from configuration
POOL_SIZE = settings.database.pool_size
MAX_OVERFLOW = settings.database.max_overflow
POOL_TIMEOUT = settings.database.pool_timeout
POOL_RECYCLE = settings.database.pool_recycle
POOL_PRE_PING = settings.database.pool_pre_ping

# Auto-detect SSL requirement based on database host
is_azure = "azure.com" in DB_HOST or "database.windows.net" in DB_HOST
is_local = DB_HOST in ["localhost", "postgres", "127.0.0.1", "db"]

if is_azure:
    ssl_mode = "require"
    logger.info(f"Detected Azure database ({DB_HOST}), SSL required")
elif is_local:
    ssl_mode = "disable"
    logger.info(f"Detected local database ({DB_HOST}), SSL disabled")
else:
    # Default to prefer (tries SSL, falls back to non-SSL)
    ssl_mode = "prefer"
    logger.info(f"Unknown database type ({DB_HOST}), using SSL prefer mode")

# URL encode password to handle special characters
DB_PASS_ENCODED = quote_plus(DB_PASS)

# Build connection string with appropriate SSL mode
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS_ENCODED}@{DB_HOST}:{DB_PORT}/{DB_NAME}?sslmode={ssl_mode}"

logger.info(f"Database connection: postgresql://{DB_USER}:***@{DB_HOST}:{DB_PORT}/{DB_NAME} (SSL: {ssl_mode})")

# Create engine with comprehensive connection pooling
engine = create_engine(
    DATABASE_URL,
    # Connection Pool Configuration
    poolclass=QueuePool,
    pool_size=POOL_SIZE,                    # Base number of connections to maintain
    max_overflow=MAX_OVERFLOW,              # Additional connections during spikes
    pool_timeout=POOL_TIMEOUT,              # Seconds to wait for connection
    pool_recycle=POOL_RECYCLE,              # Recycle connections after 1 hour
    pool_pre_ping=POOL_PRE_PING,            # Test connections before use
    
    # Connection Configuration
    connect_args={
        "connect_timeout": settings.database.connect_timeout,  # Connection timeout in seconds
        "application_name": settings.database.application_name, # Identify connections in PostgreSQL
    },
    
    # Performance Configuration
    echo=False,                             # Set to True for SQL debugging
    echo_pool=False,                        # Set to True for pool debugging
    future=True,                           # Use SQLAlchemy 2.0 style
    
    # Error Handling
    pool_reset_on_return="commit",          # Reset connection state on return
)

# Session configuration
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False  # Prevent lazy loading issues
)

# Async engine and session configuration
ASYNC_DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASS_ENCODED}@{DB_HOST}:{DB_PORT}/{DB_NAME}?sslmode={ssl_mode}"

async_engine = create_async_engine(
    ASYNC_DATABASE_URL,
    # Connection Pool Configuration
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_timeout=POOL_TIMEOUT,
    pool_recycle=POOL_RECYCLE,
    pool_pre_ping=POOL_PRE_PING,
    
    # Connection Configuration
    connect_args={
        "connect_timeout": settings.database.connect_timeout,
        "application_name": settings.database.application_name,
    },
    
    # Performance Configuration
    echo=False,
    echo_pool=False,
    future=True,
    
    # Error Handling
    pool_reset_on_return="commit",
)

AsyncSessionLocal = async_sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=async_engine,
    expire_on_commit=False,
    class_=AsyncSession
)

Base = declarative_base()

# Connection pool monitoring
class ConnectionPoolMonitor:
    """Monitor connection pool health and statistics."""
    
    @staticmethod
    def get_pool_status() -> dict:
        """Get current connection pool status."""
        pool = engine.pool
        return {
            "pool_size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "total_connections": pool.size() + pool.overflow(),
            "available_connections": pool.checkedin(),
            "utilization_percent": round((pool.checkedout() / (pool.size() + pool.overflow())) * 100, 2) if (pool.size() + pool.overflow()) > 0 else 0
        }
    
    @staticmethod
    def is_pool_healthy() -> bool:
        """Check if connection pool is healthy."""
        status = ConnectionPoolMonitor.get_pool_status()
        # Pool is healthy if utilization is below 90%
        return status["utilization_percent"] < 90
    
    @staticmethod
    def get_pool_warnings() -> list:
        """Get any warnings about pool health."""
        warnings = []
        status = ConnectionPoolMonitor.get_pool_status()
        
        if status["utilization_percent"] > 90:
            warnings.append(f"High pool utilization: {status['utilization_percent']}%")
        
        if status["checked_out"] > status["pool_size"]:
            warnings.append(f"Using overflow connections: {status['checked_out']}/{status['pool_size']}")
        
        return warnings

# Add connection pool event listeners for monitoring
@event.listens_for(engine, "connect")
def receive_connect(dbapi_connection, connection_record):
    """Log when new connections are created."""
    logger.info(f"New database connection created: {connection_record.info}")

@event.listens_for(engine, "checkout")
def receive_checkout(dbapi_connection, connection_record, connection_proxy):
    """Log when connections are checked out from pool."""
    pool_status = ConnectionPoolMonitor.get_pool_status()
    logger.debug(f"Connection checked out from pool - Pool utilization: {pool_status['utilization_percent']}%")

@event.listens_for(engine, "checkin")
def receive_checkin(dbapi_connection, connection_record):
    """Log when connections are returned to pool."""
    logger.debug(f"Connection returned to pool")

@event.listens_for(engine, "invalidate")
def receive_invalidate(dbapi_connection, connection_record, exception):
    """Log when connections are invalidated."""
    logger.warning(f"Database connection invalidated: {exception}")

def get_db() -> Generator[Session, None, None]:
    """
    Dependency to get database session with proper connection management.
    
    This function ensures:
    - Connections are properly returned to the pool
    - Exceptions don't leave connections hanging
    - Pool health is monitored
    """
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error(f"Database session error: {e}")
        db.rollback()
        raise
    finally:
        db.close()

@asynccontextmanager
async def get_async_db_session():
    """Async context manager for database sessions."""
    db = AsyncSessionLocal()
    try:
        yield db
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()

def get_db_with_retry(max_retries: int = 3) -> Generator[Session, None, None]:
    """
    Get database session with retry logic for connection failures.
    
    Args:
        max_retries: Maximum number of retry attempts (default: 3)
    
    Yields:
        Database session with automatic retry on connection failures
    """
    for attempt in range(max_retries):
        try:
            db = SessionLocal()
            yield db
            return
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"Database connection failed after {max_retries} attempts: {e}")
                raise
            logger.warning(f"Database connection attempt {attempt + 1} failed: {e}")
            time.sleep(1)  # Wait before retry

@contextmanager
def get_db_session():
    """
    Context manager for database sessions with explicit transaction control.
    
    Usage:
        with get_db_session() as db:
            # Database operations
            db.commit()  # or db.rollback()
    """
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error(f"Database session error: {e}")
        db.rollback()
        raise
    finally:
        db.close()

def test_database_connection(max_retries: int = 5) -> bool:
    """Test database connection with retry limit."""
    retry_count = 0
    last_error = None
    
    while retry_count < max_retries:
        try:
            with get_db_session() as db:
                # Simple query to test connection
                from sqlalchemy import text
                result = db.execute(text("SELECT 1")).scalar()
                if result == 1:
                    logger.info("Database connection test successful")
                    return True
                else:
                    logger.error("Database connection test failed: unexpected result")
                    return False
        except Exception as e:
            retry_count += 1
            last_error = e
            if retry_count >= max_retries:
                logger.error(f"Database connection failed after {max_retries} retries: {e}")
                raise
            wait_time = min(2 ** retry_count, 30)  # Exponential backoff with 30s cap
            logger.warning(f"Database connection attempt {retry_count} failed, retrying in {wait_time}s...")
            time.sleep(wait_time)
    
    return False

def get_database_health() -> dict:
    """Get comprehensive database health information."""
    try:
        # Test basic connectivity
        connection_healthy = test_database_connection()
        
        # Get pool status
        pool_status = ConnectionPoolMonitor.get_pool_status()
        pool_healthy = ConnectionPoolMonitor.is_pool_healthy()
        pool_warnings = ConnectionPoolMonitor.get_pool_warnings()
        
        return {
            "database_connection": "healthy" if connection_healthy else "unhealthy",
            "connection_pool": "healthy" if pool_healthy else "degraded",
            "pool_status": pool_status,
            "warnings": pool_warnings,
            "configuration": {
                "pool_size": POOL_SIZE,
                "max_overflow": MAX_OVERFLOW,
                "pool_timeout": POOL_TIMEOUT,
                "pool_recycle": POOL_RECYCLE,
                "pool_pre_ping": POOL_PRE_PING,
                "ssl_mode": ssl_mode,
                "database_host": DB_HOST
            }
        }
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return {
            "database_connection": "error",
            "connection_pool": "error",
            "error": str(e)
        }
