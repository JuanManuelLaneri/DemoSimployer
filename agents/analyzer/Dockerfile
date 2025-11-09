FROM python:3.12-slim

WORKDIR /app

# Copy requirements with directory structure preserved
COPY agents/shared/requirements.txt /app/agents/shared/requirements.txt
COPY agents/analyzer/requirements.txt /app/agents/analyzer/requirements.txt

# Install dependencies
RUN pip install --no-cache-dir -r /app/agents/analyzer/requirements.txt

# Copy shared code
COPY agents/shared/ /app/agents/shared/

# Copy analyzer code
COPY agents/analyzer/ /app/agents/analyzer/

# Set Python path
ENV PYTHONPATH=/app

CMD ["python", "-u", "agents/analyzer/agent.py"]
