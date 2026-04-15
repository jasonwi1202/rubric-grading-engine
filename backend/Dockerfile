FROM python:3.12-slim

# System dependencies for python-magic and pdfplumber
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (better layer caching)
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

# Copy application code
COPY . .

# Default command — overridden in docker-compose.yml per service
# backend:  uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
# worker:   celery -A app.tasks.celery_app worker --loglevel=info
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

EXPOSE 8000
