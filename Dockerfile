FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    tcpdump \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir fastapi uvicorn pyyaml requests cryptography

# Copy application code
COPY stable/ stable/
COPY remote/relay/ relay/
COPY remote/srs_spectator/ spectator/
COPY remote/extractor/ extractor/
COPY game/ game/
COPY config/ config/

# Expose all three mode ports
EXPOSE 8000 8001 8002

# Default: start all three modes
CMD ["python", "relay/main.py", "--all"]
