#!/bin/bash
set -e

echo "=== CallCenterAI Startup ==="

# Wait for PostgreSQL to be ready
echo "Waiting for PostgreSQL at $DB_HOST:$DB_PORT..."
while ! python -c "import socket; s = socket.socket(); s.settimeout(2); s.connect(('$DB_HOST', ${DB_PORT:-5432})); s.close()" 2>/dev/null; do
    echo "PostgreSQL not ready, retrying in 2s..."
    sleep 2
done
echo "PostgreSQL is ready!"

# Run database migrations
echo "Running database migrations..."
cd /app/Clinic_app
alembic upgrade head
cd /app

echo "Migrations complete!"

# Start the application
echo "Starting uvicorn server..."
exec uvicorn Clinic_app.main:app \
    --host 0.0.0.0 \
    --port ${APP_PORT:-8000} \
    --workers ${APP_WORKERS:-4}

