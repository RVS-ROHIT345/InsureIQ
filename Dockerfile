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

# Start FastAPI via uvicorn
CMD ["python", "main.py"]
