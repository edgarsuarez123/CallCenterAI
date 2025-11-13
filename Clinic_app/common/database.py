import os
import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from dotenv import load_dotenv

# Configure logging
logger = logging.getLogger(__name__)

# Load .env for local development
load_dotenv()

# Get database connection from environment variables
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

# Build async connection string (uses asyncpg driver)
DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Log connection info (without password)
logger.info(f"Initializing database connection to {DB_HOST}:{DB_PORT}/{DB_NAME}")

# Create async engine with pool settings and SSL
engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,  # Test connections before using
    echo=False,  # Set to True for SQL query logging
    future=True,
    connect_args={
        "ssl": True  # Require SSL for secure connections (Azure PostgreSQL)
    }
)

logger.info("Database engine created successfully")

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# Base for models
Base = declarative_base()

# Async dependency for FastAPI
async def get_db():
    """Dependency to get database session."""
    async with AsyncSessionLocal() as session:
        yield session

