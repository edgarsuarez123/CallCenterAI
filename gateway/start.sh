#!/bin/bash

# CallCenter AI Gateway startup script
# Handles both development and production environments

set -e

# Logging function
log_with_timestamp() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

log_with_timestamp "Starting CallCenter AI Gateway..."

# Wait for database to be ready
log_with_timestamp "Waiting for database to be ready..."
until pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME"; do
    log_with_timestamp "Database not ready, waiting..."
    sleep 2
done

log_with_timestamp "Database is ready!"

# Run database migrations
log_with_timestamp "Running database migrations..."
cd /app
python migrate.py upgrade head

log_with_timestamp "Database migrations completed!"

# Start the application
if [ "$APP_ENVIRONMENT" = "development" ]; then
    log_with_timestamp "Starting in development mode with hot reload..."
    exec uvicorn main:app --host "$APP_HOST" --port "$APP_PORT" --reload
else
    log_with_timestamp "Starting in production mode..."
    exec uvicorn main:app --host "$APP_HOST" --port "$APP_PORT" --workers "$APP_WORKERS"
fi