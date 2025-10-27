#!/bin/bash

echo "=== DEBUG CONTAINER STARTUP ==="

echo "Step 1: Testing Python imports..."
python -c "import sys; print(f'Python version: {sys.version}')"
python -c "import fastapi; print('FastAPI import OK')"
python -c "import sqlalchemy; print('SQLAlchemy import OK')"
python -c "import psycopg2; print('psycopg2 import OK')"
python -c "import pydantic; print('Pydantic import OK')"

echo "Step 2: Testing configuration loading..."
python -c "from services.configuration import get_settings; settings = get_settings(); print(f'Configuration loaded: {settings.environment}')"

echo "Step 3: Testing database connection..."
python -c "from services.database import test_database_connection; result = test_database_connection(); print(f'Database connection: {result}')"

echo "Step 4: Testing configuration validation..."
python -c "from services.configuration import validate_configuration; results = validate_configuration(); print(f'Validation results: {results}')"

echo "Step 5: Testing migrations..."
python migrate.py upgrade

echo "Step 6: Testing application startup..."
python -c "from main import app; print('FastAPI app created successfully')"

echo "=== ALL TESTS COMPLETED ==="
sleep 3600
