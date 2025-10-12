#!/usr/bin/env python3
"""
Database Migration: Add email field to Provider model
"""

import os
import sys
import logging
from sqlalchemy import inspect, text
from services.database import engine, Base, get_db
from models.models import Provider

# Configure logging
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)

def add_provider_email_column():
    """
    Adds the email column to the providers table if it doesn't exist.
    """
    logger.info("Starting Provider email column migration...")
    
    try:
        # Check if column already exists
        inspector = inspect(engine)
        columns = inspector.get_columns('providers')
        column_names = [col['name'] for col in columns]
        
        if 'email' in column_names:
            logger.info("✅ Email column already exists in providers table")
            return
        
        # Add the email column
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE providers ADD COLUMN email VARCHAR(255)"))
            conn.commit()
        
        logger.info("✅ Email column added successfully to providers table")
        
        # Verify the column was added
        inspector = inspect(engine)
        columns = inspector.get_columns('providers')
        column_names = [col['name'] for col in columns]
        
        if 'email' in column_names:
            logger.info("✅ Column verification successful - email column exists")
        else:
            logger.error("❌ Column verification failed - email column not found")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"🚨 An error occurred during migration: {e}")
        sys.exit(1)

def update_existing_providers():
    """
    Update existing providers with clinic-specific email addresses.
    """
    logger.info("Updating existing providers with email addresses...")
    
    try:
        with engine.connect() as conn:
            # Get all providers without email addresses
            result = conn.execute(text("""
                SELECT provider_id, name_token, title 
                FROM providers 
                WHERE email IS NULL OR email = ''
            """))
            
            providers = result.fetchall()
            logger.info(f"Found {len(providers)} providers without email addresses")
            
            for provider in providers:
                provider_id = provider[0]
                name_token = provider[1]
                title = provider[2]
                
                # Generate clinic-specific email
                # Extract clinic ID from provider ID (format: PROVIDER_{clinic_id}_{token})
                parts = provider_id.split('_')
                if len(parts) >= 3:
                    clinic_id = parts[1]
                    # Create email based on clinic and provider info
                    email = f"{title.lower().replace('.', '')}.{name_token.lower()}@{clinic_id.lower()}.com"
                else:
                    # Fallback email format
                    email = f"provider.{provider_id.lower()}@clinic.com"
                
                # Update the provider with the email
                conn.execute(text("""
                    UPDATE providers 
                    SET email = :email 
                    WHERE provider_id = :provider_id
                """), {"email": email, "provider_id": provider_id})
                
                logger.info(f"Updated provider {provider_id} with email: {email}")
            
            conn.commit()
            logger.info("✅ All providers updated with email addresses")
            
    except Exception as e:
        logger.error(f"🚨 An error occurred updating providers: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # Set up environment variables for database connection if not already set
    if 'DATABASE_URL' not in os.environ:
        os.environ['DATABASE_URL'] = "postgresql://user:password@localhost:5432/callcenter_db"
    
    try:
        add_provider_email_column()
        update_existing_providers()
        logger.info("🎉 Provider email migration completed successfully!")
        logger.info("Providers now have email addresses for Google Calendar integration.")
    except Exception as e:
        logger.error(f"🚨 Migration failed: {e}")
        sys.exit(1)
