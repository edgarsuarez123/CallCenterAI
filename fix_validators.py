#!/usr/bin/env python3
"""
Script to fix Pydantic v2 validators in configuration.py
"""

import re

def fix_validators():
    """Fix all validators in configuration.py"""
    
    with open('gateway/services/configuration.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Replace @validator with @field_validator and add @classmethod
    content = re.sub(
        r'@validator\(([^)]+)\)\n    def validate_([^(]+)\(cls, v\):',
        r'@field_validator(\1)\n    @classmethod\n    def validate_\2(cls, v):',
        content
    )
    
    # Update Config classes to use model_config
    content = re.sub(
        r'class Config:\n        env_prefix = "([^"]+)"\n        case_sensitive = False',
        r'model_config = SettingsConfigDict(\n        env_prefix="\1",\n        case_sensitive=False\n    )',
        content
    )
    
    with open('gateway/services/configuration.py', 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("Validators fixed successfully!")

if __name__ == "__main__":
    fix_validators()
