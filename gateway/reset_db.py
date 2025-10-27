#!/usr/bin/env python3
"""
Reset database and run clean migration
"""
import os
import sys
import subprocess
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

def reset_database():
    """Reset the database and run clean migration"""
    
    # Database connection
    db_host = os.getenv('DB_HOST')
    db_port = os.getenv('DB_PORT', '5432')
    db_name = os.getenv('DB_NAME')
    db_user = os.getenv('DB_USER')
    db_password = os.getenv('DB_PASSWORD')
    
    connection_string = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    
    print(f"Connecting to database: {db_host}:{db_port}/{db_name}")
    
    try:
        # Connect to database
        engine = create_engine(connection_string)
        
        with engine.connect() as conn:
            # Drop alembic version table if it exists
            print("Dropping alembic version table...")
            conn.execute(text("DROP TABLE IF EXISTS alembic_version CASCADE"))
            conn.commit()
            
            # Drop all existing tables
            print("Dropping all existing tables...")
            conn.execute(text("""
                DO $$ DECLARE
                    r RECORD;
                BEGIN
                    FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP
                        EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.tablename) || ' CASCADE';
                    END LOOP;
                END $$;
            """))
            conn.commit()
            
            print("Database reset complete!")
            
    except Exception as e:
        print(f"Error resetting database: {e}")
        sys.exit(1)
    
    # Run alembic migration
    print("Running clean migration...")
    try:
        result = subprocess.run(['alembic', 'upgrade', 'head'], 
                              capture_output=True, text=True, check=True)
        print("Migration completed successfully!")
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Migration failed: {e}")
        print(f"Error output: {e.stderr}")
        sys.exit(1)

if __name__ == "__main__":
    reset_database()
