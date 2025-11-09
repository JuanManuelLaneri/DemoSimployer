# Orchestrator Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Copy shared dependencies
COPY agents/shared/requirements.txt /app/shared-requirements.txt
RUN pip install --no-cache-dir -r /app/shared-requirements.txt

# Copy shared utilities
COPY agents/shared /app/agents/shared

# Copy orchestrator code
COPY orchestrator /app/orchestrator

# Copy prompts
COPY prompts /app/prompts

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import sys; sys.exit(0)"

# Run orchestrator
CMD ["python", "-u", "orchestrator/main.py"]
