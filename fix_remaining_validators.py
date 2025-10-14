#!/usr/bin/env python3
"""
Script to fix remaining Pydantic v2 validators
"""

import re

def fix_schemas_validators():
    """Fix validators in schemas.py"""
    
    with open('gateway/models/schemas.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Add missing import
    if 'import re' not in content:
        content = content.replace(
            'from pydantic import BaseModel, Field, field_validator',
            'import re\nfrom pydantic import BaseModel, Field, field_validator'
        )
    
    # Replace @validator with @field_validator and add @classmethod
    content = re.sub(
        r'@validator\(([^)]+)\)\n    def validate_([^(]+)\(cls, v\):',
        r'@field_validator(\1)\n    @classmethod\n    def validate_\2(cls, v):',
        content
    )
    
    with open('gateway/models/schemas.py', 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("Schemas validators fixed!")

def fix_models_validators():
    """Fix any remaining validators in models.py"""
    
    with open('gateway/models/models.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check if there are any regex validators that need to be updated
    if 'regex=' in content:
        # Replace regex= with pattern=
        content = content.replace('regex=', 'pattern=')
        print("Updated regex validators to pattern in models.py")
    
    with open('gateway/models/models.py', 'w', encoding='utf-8') as f:
        f.write(content)

if __name__ == "__main__":
    fix_schemas_validators()
    fix_models_validators()
    print("All validators fixed!")
