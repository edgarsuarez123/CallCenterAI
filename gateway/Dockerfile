FROM python:3.11-slim

# System libs for psycopg2 (Postgres) and build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev build-essential && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONPATH=/app

# Install Python dependencies from requirements.txt
COPY gateway/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY gateway/ /app/

# Create logs directory (file logging disabled by default)
# RUN mkdir -p /app/logs && touch /app/logs/callcenter_ai.log

# Make startup script executable
RUN chmod +x start.sh

# Install pg_isready for database health checks
RUN apt-get update && apt-get install -y postgresql-client && rm -rf /var/lib/apt/lists/*

EXPOSE 8443

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8443/health/database', timeout=5)" || exit 1

CMD ["./start.sh"]
