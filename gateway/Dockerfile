FROM python:3.11-slim

# System libs for psycopg2 (Postgres) and build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev build-essential && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONPATH=/app

# Add all required Python deps (include cryptography for AES-GCM)
RUN pip install --no-cache-dir \
    fastapi \
    uvicorn[standard] \
    sqlalchemy \
    psycopg2-binary \
    cryptography

# Copy app code
COPY . /app

EXPOSE 8443
CMD ["uvicorn","main:app","--host","0.0.0.0","--port","8443"]
