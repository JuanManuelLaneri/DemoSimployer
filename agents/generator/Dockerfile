FROM python:3.12-slim

WORKDIR /app

# Copy requirements with directory structure preserved
COPY agents/shared/requirements.txt /app/agents/shared/requirements.txt
COPY agents/generator/requirements.txt /app/agents/generator/requirements.txt

# Install dependencies
RUN pip install --no-cache-dir -r /app/agents/generator/requirements.txt

# Copy shared code
COPY agents/shared/ /app/agents/shared/

# Copy generator code
COPY agents/generator/ /app/agents/generator/

# Set Python path
ENV PYTHONPATH=/app

CMD ["python", "-u", "agents/generator/agent.py"]
