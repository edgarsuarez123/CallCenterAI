# CallCenterAI - Production Dockerfile
FROM python:3.11-slim

# Set environment variables
# PLAYWRIGHT_BROWSERS_PATH: fixed path so non-root appuser can read the Chromium binary
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers

# Set working directory
WORKDIR /app

# Install base system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better layer caching
COPY requirements.txt .

# Install Python dependencies (includes playwright + agentql)
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium system dependencies for this distro, then download
# the Chromium browser binary into the shared PLAYWRIGHT_BROWSERS_PATH.
# Both steps run as root (before USER appuser) so they have apt-get + write access.
# playwright install-deps resolves the exact system packages needed for this OS version.
RUN apt-get update \
    && playwright install-deps chromium \
    && rm -rf /var/lib/apt/lists/* \
    && playwright install chromium \
    && chmod -R 755 /opt/playwright-browsers

# Copy application code
COPY . .

# Make start script executable
RUN chmod +x start.sh

# Create non-root user for security
RUN adduser --disabled-password --gecos '' appuser && \
    chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Run the application via start script
CMD ["./start.sh"]

