FROM python:3.12-slim

WORKDIR /app

# Copy requirements with directory structure preserved
COPY agents/shared/requirements.txt /app/agents/shared/requirements.txt
COPY agents/sanitizer/requirements.txt /app/agents/sanitizer/requirements.txt

# Install dependencies
RUN pip install --no-cache-dir -r /app/agents/sanitizer/requirements.txt

# Copy shared code
COPY agents/shared/ /app/agents/shared/

# Copy sanitizer code
COPY agents/sanitizer/ /app/agents/sanitizer/

# Set Python path
ENV PYTHONPATH=/app

CMD ["python", "-u", "agents/sanitizer/agent.py"]
