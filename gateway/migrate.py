#!/usr/bin/env python3
"""
Database Migration Management Script

This script provides a convenient interface for managing database migrations
using Alembic. It handles environment setup and provides common migration operations.

Usage:
    python migrate.py upgrade          # Apply all pending migrations
    python migrate.py downgrade        # Rollback last migration
    python migrate.py revision         # Create new migration
    python migrate.py history          # Show migration history
    python migrate.py current          # Show current migration
    python migrate.py reset            # Reset database (DANGEROUS - for development only)
"""

import os
import sys
import subprocess
from pathlib import Path

# Add the current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

def get_database_url():
    """Get database URL from configuration system."""
    # Check for explicit DATABASE_URL first
    database_url = os.getenv('DATABASE_URL')
    if database_url:
        return database_url
    
    # Use configuration system
    from services.configuration import get_settings
    from urllib.parse import quote_plus
    
    settings = get_settings()
    db_host = settings.database.host
    db_port = settings.database.port
    db_name = settings.database.name
    db_user = settings.database.user
    db_password = settings.database.password.get_secret_value()
    
    # URL encode password
    db_password_encoded = quote_plus(db_password)
    
    # Auto-detect SSL
    is_azure = "azure.com" in db_host or "database.windows.net" in db_host
    ssl_mode = "require" if is_azure else "disable"
    
    return f"postgresql://{db_user}:{db_password_encoded}@{db_host}:{db_port}/{db_name}?sslmode={ssl_mode}"

def run_alembic_command(command, *args):
    """Run an alembic command with proper environment setup."""
    env = os.environ.copy()
    
    # Get database URL and set it for Alembic
    database_url = get_database_url()
    
    # Set up environment variables for database connection
    env.update({
        'DATABASE_URL': database_url,
    })
    
    cmd = ['alembic'] + [command] + list(args)
    print(f"Running: {' '.join(cmd)}")
    print(f"Using database: {database_url.split('@')[1].split('/')[0]}")
    
    try:
        result = subprocess.run(cmd, env=env, check=True, capture_output=True, text=True)
        if result.stdout:
            print(result.stdout)
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        print(f"Error running alembic command: {e}")
        if e.stdout:
            print("STDOUT:", e.stdout)
        if e.stderr:
            print("STDERR:", e.stderr)
        return False

def upgrade():
    """Apply all pending migrations."""
    print("Applying all pending migrations...")
    return run_alembic_command('upgrade', 'head')

def downgrade():
    """Rollback the last migration."""
    print("Rolling back last migration...")
    return run_alembic_command('downgrade', '-1')

def revision(message=None):
    """Create a new migration."""
    if not message:
        message = input("Enter migration message: ")
    
    print(f"Creating new migration: {message}")
    return run_alembic_command('revision', '--autogenerate', '-m', message)

def history():
    """Show migration history."""
    print("Migration history:")
    return run_alembic_command('history', '--verbose')

def current():
    """Show current migration."""
    print("Current migration:")
    return run_alembic_command('current')

def reset():
    """Reset database to initial state (DANGEROUS - for development only)."""
    confirm = input("WARNING: This will DROP ALL TABLES and data! Type 'yes' to confirm: ")
    if confirm.lower() != 'yes':
        print("Reset cancelled.")
        return False
    
    print("Resetting database...")
    # First downgrade to base
    if not run_alembic_command('downgrade', 'base'):
        print("Failed to downgrade to base")
        return False
    
    # Then upgrade to head
    if not run_alembic_command('upgrade', 'head'):
        print("Failed to upgrade to head")
        return False
    
    print("Database reset complete.")
    return True

def show_help():
    """Show help information."""
    print(__doc__)

def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        show_help()
        return
    
    command = sys.argv[1].lower()
    
    if command == 'upgrade':
        success = upgrade()
    elif command == 'downgrade':
        success = downgrade()
    elif command == 'revision':
        message = sys.argv[2] if len(sys.argv) > 2 else None
        success = revision(message)
    elif command == 'history':
        success = history()
    elif command == 'current':
        success = current()
    elif command == 'reset':
        success = reset()
    elif command in ['help', '-h', '--help']:
        show_help()
        return
    else:
        print(f"Unknown command: {command}")
        show_help()
        return
    
    if success:
        print("Command completed successfully.")
    else:
        print("Command failed.")
        sys.exit(1)

if __name__ == '__main__':
    main()
