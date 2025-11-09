FROM python:3.12-slim

WORKDIR /app

# Copy requirements with directory structure preserved
COPY agents/shared/requirements.txt /app/agents/shared/requirements.txt
COPY api/requirements.txt /app/api/requirements.txt

# Install dependencies
RUN pip install --no-cache-dir -r /app/api/requirements.txt

# Copy shared code
COPY agents/shared/ /app/agents/shared/

# Copy API code
COPY api/ /app/api/

# Set Python path
ENV PYTHONPATH=/app

# Expose API port
EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
