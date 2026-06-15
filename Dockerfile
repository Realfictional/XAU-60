# XAU-60 Trading Bot - Dockerfile
#
# IMPORTANT: For MT5 support (live trading), use Windows containers:
# 1. In Docker Desktop: Settings → Resources → WSL Integration → Enable Windows containers
# 2. Then uncomment the Windows base image below
# 3. For Linux/demo mode, this image works as-is
#
# Windows Container Version (requires Docker Desktop set to Windows containers):
# FROM python:3.11-slim-windowsservercore
#
# Linux Version (default - for demo/backtesting):
FROM python:3.11-slim

WORKDIR /app

# Copy requirements first (layer caching)
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Expose Streamlit default port
EXPOSE 8501

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8501')" || exit 1

# Run Streamlit app
CMD ["streamlit", "run", "streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
