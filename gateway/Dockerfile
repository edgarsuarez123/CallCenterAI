FROM python:3.11-slim

# System libs for psycopg2 (Postgres), Azure Speech SDK, and build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev build-essential ca-certificates tzdata \
    libasound2 libasound2-dev libpulse0 libsndfile1 \
    libssl-dev libffi-dev libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev libgstreamer-plugins-bad1.0-dev \
    gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly \
    gstreamer1.0-libav gstreamer1.0-tools gstreamer1.0-x \
    gstreamer1.0-alsa gstreamer1.0-gl gstreamer1.0-gtk3 \
    gstreamer1.0-qt5 gstreamer1.0-pulseaudio && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONPATH=/app

# Install Python dependencies from requirements.txt
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . /app/

# Create logs directory (file logging disabled by default)
# RUN mkdir -p /app/logs && touch /app/logs/callcenter_ai.log

# Make startup script executable
RUN chmod +x start.sh

# Install pg_isready for database health checks
RUN apt-get update && apt-get install -y postgresql-client && rm -rf /var/lib/apt/lists/*

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8080/healthz', timeout=5)" || exit 1

CMD ["./start.sh"]
