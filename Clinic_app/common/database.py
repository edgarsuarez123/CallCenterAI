import os
import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from Clinic_app.common.env import load_project_dotenv

# Configure logging
logger = logging.getLogger(__name__)

# Load .env from repository root (works with Docker / uvicorn cwd)
load_project_dotenv()

# Get database connection from environment variables
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_SSL = os.getenv("DB_SSL", "require").strip().lower()

# Build async connection string (uses asyncpg driver)
DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Create async engine with pool settings and SSL
# Only create engine if all required env vars are set and asyncpg is available
# This allows imports to work even when env vars aren't configured (e.g., for migrations)
engine = None
if DB_HOST and DB_NAME and DB_USER and DB_PASSWORD:
    try:
        # Log connection info (without password)
        logger.info(f"Initializing database connection to {DB_HOST}:{DB_PORT}/{DB_NAME}")

        # Local Docker Postgres typically does not support TLS by default, while Azure
        # PostgreSQL requires it. Make this explicit and configurable.
        # Supported DB_SSL values:
        #   - "require" / "true" / "1" → enable TLS
        #   - "disable" / "false" / "0" → disable TLS
        ssl_enabled = DB_SSL in ("require", "true", "1", "yes", "on")

        engine = create_async_engine(
            DATABASE_URL,
            pool_pre_ping=True,  # Test connections before using
            echo=False,  # Set to True for SQL query logging
            future=True,
            connect_args={"ssl": ssl_enabled},
        )

        logger.info("Database engine created successfully")
    except Exception as e:
        # If engine creation fails (e.g., asyncpg not installed), log warning but continue
        # This allows imports to work for migrations even if asyncpg isn't available
        logger.warning(
            f"Could not create database engine: {e}. This is OK for migration generation."
        )
        engine = None
else:
    logger.debug(
        "Database environment variables not set. Engine creation skipped (OK for migration generation)."
    )

# Create async session factory (only if engine was created)
AsyncSessionLocal = None
if engine is not None:
    AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Base for models
Base = declarative_base()


# Async dependency for FastAPI
async def get_db():
    """Dependency to get database session."""
    if AsyncSessionLocal is None:
        raise RuntimeError(
            "Database engine not initialized. Please set DB_HOST, DB_NAME, DB_USER, and DB_PASSWORD environment variables."
        )
    async with AsyncSessionLocal() as session:
        yield session
