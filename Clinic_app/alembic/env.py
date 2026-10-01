import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from dotenv import load_dotenv

from alembic import context

# Add project root to path to enable imports
# alembic/env.py -> alembic -> Clinic_app -> CallCenterAI (project root)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

# Load environment variables
load_dotenv()

# Set dummy database env vars if not set (needed for database.py import to not fail)
# These are only used during import - actual migration URL is set below
if not os.getenv("DB_HOST"):
    os.environ["DB_HOST"] = "localhost"
if not os.getenv("DB_NAME"):
    os.environ["DB_NAME"] = "dummy"
if not os.getenv("DB_USER"):
    os.environ["DB_USER"] = "dummy"
if not os.getenv("DB_PASSWORD"):
    os.environ["DB_PASSWORD"] = "dummy"

# Import Base and all models
# Note: database.py will try to create engine, but it will fail gracefully if connection fails
# For migrations, we only need Base.metadata, not a working engine
from Clinic_app.common.database import Base

# Import all models to ensure they're registered with Base.metadata
# Models must use the same Base instance
from Clinic_app.data.models import (
    Clinic,
    License,
    ClinicIntegration,
    Provider,
    Patient,
    Booking,
    AvailabilitySlot,
    BookingAudit,
    PhoneRoute,
    CallLog,
    Campaign,
    CampaignContact,
)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target_metadata for autogenerate support
target_metadata = Base.metadata

# Build sync database URL for migrations (use psycopg2, not asyncpg)
# Migrations run synchronously, so we need a sync connection
db_host = os.getenv("DB_HOST")
db_port = os.getenv("DB_PORT", "5432")
db_name = os.getenv("DB_NAME")
db_user = os.getenv("DB_USER")
db_password = os.getenv("DB_PASSWORD")

if db_host and db_name and db_user and db_password:
    # Use sync connection (postgresql+psycopg2) for migrations
    sync_database_url = f"postgresql+psycopg2://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}?sslmode=require"
    config.set_main_option("sqlalchemy.url", sync_database_url)

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    # Get database URL - if not set, use a dummy URL (for autogenerate without connection)
    database_url = config.get_main_option("sqlalchemy.url")
    if not database_url or database_url.startswith("driver://"):
        # No database URL configured - use dummy URL for autogenerate
        # This allows migration generation without a database connection
        database_url = "postgresql+psycopg2://dummy:dummy@localhost/dummy"
        config.set_main_option("sqlalchemy.url", database_url)
    
    try:
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                compare_server_default=True,
            )

            with context.begin_transaction():
                context.run_migrations()
    except Exception as e:
        # Re-raise the actual error instead of falling back to offline mode
        import logging
        logging.error(f"Migration failed: {e}")
        raise


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
