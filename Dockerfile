FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy pyproject.toml and install raas-core package
COPY pyproject.toml /app/
COPY src/ /app/src/
RUN pip install --no-cache-dir -e ".[mcp]"

# Copy alembic migration files
COPY alembic/ /app/alembic/
COPY alembic.ini /app/

# Expose API port
EXPOSE 8000

# Run migrations and start server
CMD alembic upgrade head && \
    uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
