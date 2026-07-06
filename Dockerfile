# InsureIQ Dockerfile
# Python 3.11 on slim Debian — keeps image small for Cloud Run

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system deps needed by pdfplumber (poppler-utils for PDF rendering)
RUN apt-get update && apt-get install -y \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies first (layer caching — faster rebuilds)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Never run as root in production
RUN useradd --create-home appuser
USER appuser

# Expose API port
EXPOSE 8000

# Container-level health check. The slim image has no curl, so probe with the
# Python stdlib (urllib) — exit non-zero if /health is not 200. Cloud Run and
# docker-compose both surface this status.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=4).status==200 else 1)"]

# Start FastAPI via uvicorn
CMD ["python", "main.py"]
