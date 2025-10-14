#!/usr/bin/env python3
"""
Development Setup Script

This script helps set up the development environment for CallCenterAI Gateway.
It handles database initialization, sample data creation, and environment setup.

Usage:
    python setup_dev.py init          # Initialize database with migrations
    python setup_dev.py demo          # Create demo data
    python setup_dev.py reset         # Reset database (DANGEROUS)
    python setup_dev.py status        # Show database status
"""

import os
import sys
import subprocess
from pathlib import Path

# Add the current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

def run_command(cmd, description):
    """Run a command and handle errors."""
    print(f"\n{description}...")
    print(f"Running: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        if result.stdout:
            print(result.stdout)
        print(f"✓ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ {description} failed")
        if e.stdout:
            print("STDOUT:", e.stdout)
        if e.stderr:
            print("STDERR:", e.stderr)
        return False

def check_database_connection():
    """Check if database is accessible."""
    try:
        from services.database import engine
        with engine.connect() as conn:
            conn.execute("SELECT 1")
        print("✓ Database connection successful")
        return True
    except Exception as e:
        print(f"✗ Database connection failed: {e}")
        return False

def init_database():
    """Initialize database with migrations."""
    print("Initializing database...")
    
    # Check database connection
    if not check_database_connection():
        print("Please ensure the database is running and accessible")
        return False
    
    # Run migrations
    if not run_command(['python', 'migrate.py', 'upgrade'], "Running database migrations"):
        return False
    
    print("✓ Database initialization completed")
    return True

def create_demo_data():
    """Create demo data for development."""
    print("Creating demo data...")
    
    try:
        from demo_setup import main as create_demo
        create_demo()
        print("✓ Demo data created successfully")
        return True
    except Exception as e:
        print(f"✗ Failed to create demo data: {e}")
        return False

def reset_database():
    """Reset database (DANGEROUS - for development only)."""
    confirm = input("WARNING: This will DROP ALL TABLES and data! Type 'yes' to confirm: ")
    if confirm.lower() != 'yes':
        print("Reset cancelled.")
        return False
    
    print("Resetting database...")
    
    # Reset using migration script
    if not run_command(['python', 'migrate.py', 'reset'], "Resetting database"):
        return False
    
    # Create demo data
    if not create_demo_data():
        return False
    
    print("✓ Database reset completed")
    return True

def show_status():
    """Show database and application status."""
    print("CallCenterAI Gateway Status")
    print("=" * 40)
    
    # Check database connection
    if check_database_connection():
        # Show current migration
        run_command(['python', 'migrate.py', 'current'], "Current migration version")
        
        # Show migration history
        run_command(['python', 'migrate.py', 'history'], "Migration history")
    else:
        print("Database is not accessible")
    
    # Check environment variables
    print("\nEnvironment Variables:")
    env_vars = [
        'POSTGRES_HOST', 'POSTGRES_PORT', 'POSTGRES_USER', 
        'POSTGRES_PASSWORD', 'POSTGRES_DB'
    ]
    
    for var in env_vars:
        value = os.getenv(var, 'NOT SET')
        if 'PASSWORD' in var and value != 'NOT SET':
            value = '***'  # Hide password
        print(f"  {var}: {value}")

def show_help():
    """Show help information."""
    print(__doc__)

def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        show_help()
        return
    
    command = sys.argv[1].lower()
    
    if command == 'init':
        success = init_database()
    elif command == 'demo':
        success = create_demo_data()
    elif command == 'reset':
        success = reset_database()
    elif command == 'status':
        show_status()
        return
    elif command in ['help', '-h', '--help']:
        show_help()
        return
    else:
        print(f"Unknown command: {command}")
        show_help()
        return
    
    if success:
        print("\n✓ Command completed successfully.")
    else:
        print("\n✗ Command failed.")
        sys.exit(1)

if __name__ == '__main__':
    main()
