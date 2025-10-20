import os
import sys
from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context

# Add the parent directory to the path so we can import our models
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

# Import all models to ensure they're registered with SQLAlchemy
from models.models import Base
from models.call_flow_models import *  # Import all call flow models

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def get_database_url():
    """Get database URL from environment variables with Azure support."""
    # Try DATABASE_URL first (for Azure and production)
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url
    
    # Try DB_* variables (Azure naming convention)
    db_host = os.getenv("DB_HOST")
    db_port = os.getenv("DB_PORT")
    db_name = os.getenv("DB_NAME")
    db_user = os.getenv("DB_USER")
    db_pass = os.getenv("DB_PASSWORD")
    
    # Fall back to POSTGRES_* variables (local Docker naming)
    if not db_host:
        db_host = os.getenv("POSTGRES_HOST", "postgres")
    if not db_port:
        db_port = os.getenv("POSTGRES_PORT", "5432")
    if not db_name:
        db_name = os.getenv("POSTGRES_DB", "callcenterai")
    if not db_user:
        db_user = os.getenv("POSTGRES_USER", "callcenterai")
    if not db_pass:
        db_pass = os.getenv("POSTGRES_PASSWORD", "ChangeThisNow_!")
    
    # Add SSL mode for Azure PostgreSQL
    if 'azure.com' in db_host or 'postgres.database.azure.com' in db_host:
        return f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}?sslmode=require"
    
    return f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    # Override the sqlalchemy.url in the config with our dynamic URL
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_database_url()
    
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
