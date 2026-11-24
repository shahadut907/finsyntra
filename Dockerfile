# FinSyntra RAG Chatbot - Production Dockerfile
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies including poppler-utils for PDF OCR
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create runtime directories. Database, uploads, and Chroma are mounted as
# persistent volumes by the production Compose topology.
RUN mkdir -p logs data uploads chroma && chmod +x /app/scripts/docker-entrypoint.sh

# Expose ports
# 8000 for FastAPI backend
EXPOSE 8000

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENVIRONMENT=production

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Apply the usable Alembic chain before serving traffic.
ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]

