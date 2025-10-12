#!/usr/bin/env python3
"""
Script to safely clean the CallCenterAI repository before pushing to GitHub.
This script removes sensitive files and directories that should not be committed.
"""

import os
import shutil
import sys
from pathlib import Path

def remove_file_or_dir(path):
    """Safely remove a file or directory"""
    try:
        if os.path.isfile(path):
            os.remove(path)
            print(f"✅ Removed file: {path}")
        elif os.path.isdir(path):
            shutil.rmtree(path)
            print(f"✅ Removed directory: {path}")
        else:
            print(f"⚠️  Path not found: {path}")
    except Exception as e:
        print(f"❌ Error removing {path}: {e}")

def clean_python_cache():
    """Remove Python cache files and directories"""
    print("\n🧹 Cleaning Python cache files...")
    
    # Remove __pycache__ directories
    for root, dirs, files in os.walk('.'):
        for dir_name in dirs[:]:  # Use slice to avoid modifying list while iterating
            if dir_name == '__pycache__':
                full_path = os.path.join(root, dir_name)
                remove_file_or_dir(full_path)
                dirs.remove(dir_name)  # Don't recurse into removed directory
    
    # Remove .pyc files
    for root, dirs, files in os.walk('.'):
        for file_name in files:
            if file_name.endswith('.pyc'):
                full_path = os.path.join(root, file_name)
                remove_file_or_dir(full_path)

def main():
    """Main cleaning function"""
    print("🔒 CallCenterAI Repository Cleaner")
    print("=" * 50)
    print("This script will remove sensitive files before GitHub push")
    print()
    
    # Confirm before proceeding
    response = input("Do you want to proceed? (yes/no): ").lower().strip()
    if response not in ['yes', 'y']:
        print("❌ Operation cancelled")
        sys.exit(0)
    
    print("\n🚨 Removing sensitive files...")
    
    # List of sensitive files and directories to remove
    sensitive_paths = [
        # Google credentials
        'gateway/google_credentials.json',
        
        # Environment files
        '.env',
        '.env.local',
        '.env.development',
        '.env.production',
        
        # Database data
        'data/',
        
        # Any other sensitive files
        '*.pem',
        '*.key',
        '*.crt',
        '*.p12',
        '*.pfx',
    ]
    
    # Remove sensitive files and directories
    for path in sensitive_paths:
        if os.path.exists(path):
            remove_file_or_dir(path)
        else:
            print(f"ℹ️  Path not found (already clean): {path}")
    
    # Clean Python cache files
    clean_python_cache()
    
    # Check for any remaining sensitive files
    print("\n🔍 Checking for remaining sensitive files...")
    sensitive_patterns = [
        'google_credentials',
        '.env',
        'credentials.json',
        'service-account.json',
        '*.pem',
        '*.key',
    ]
    
    found_sensitive = False
    for root, dirs, files in os.walk('.'):
        for file_name in files:
            for pattern in sensitive_patterns:
                if pattern.replace('*', '') in file_name.lower():
                    print(f"⚠️  Potentially sensitive file found: {os.path.join(root, file_name)}")
                    found_sensitive = True
    
    if not found_sensitive:
        print("✅ No sensitive files found")
    
    print("\n📋 Next steps:")
    print("1. Review the changes: git status")
    print("2. Add files to git: git add .")
    print("3. Commit changes: git commit -m 'Initial commit'")
    print("4. Push to GitHub: git push origin main")
    print("\n⚠️  Remember to:")
    print("- Set up environment variables in your deployment")
    print("- Configure Google Calendar OAuth credentials")
    print("- Use secure encryption keys in production")
    print("- Keep the repository private")
    
    print("\n✅ Repository cleaning complete!")

if __name__ == "__main__":
    main()
