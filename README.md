# Multi-Agent Orchestration System

A distributed multi-agent system with autonomous agents that can call each other directly. Uses the ReAct pattern for LLM-driven orchestration.

## What You Need

- Python 3.11+
- Docker Desktop
- DeepSeek API Key (free at https://platform.deepseek.com)

## Quick Start

**1. Clone and configure:**

```bash
git clone https://github.com/JuanManuelLaneri/Demo.git
cd Demo
cp .env.example .env
```

Edit `.env` and add your DeepSeek API key:
```
DEEPSEEK_API_KEY=sk-your-key-here
```

**2. Start everything:**

```bash
docker-compose up --build
```

Wait for "Application startup complete". This spins up:
- RabbitMQ (message broker)
- Redis (state storage)
- Orchestrator + 3 agents (sanitizer, analyzer, generator)
- API server on localhost:8000

**3. Test it:**

```bash
curl http://localhost:8000/
# Should return: {"status": "ok", "service": "chimera-api"}
```

## Running Analysis

**Option 1: Browser UI**

Go to `http://localhost:8000/docs` and try the `/plan-and-run` endpoint:

```json
{
  "request": "Analyze data/sample_logs.json and create a security report"
}
```

**Option 2: curl**

```bash
curl -X POST http://localhost:8000/plan-and-run \
  -H "Content-Type: application/json" \
  -d '{"request": "Analyze logs in data/sample_logs.json"}'
```

This gives you a `correlation_id`. Check progress:

```bash
curl http://localhost:8000/status/<correlation_id>
```

## Alternative:
Invoke-RestMethod -Uri "http://localhost:8000/plan-and-run" -Method POST -ContentType "application/json" -Body '{"request": "Analyze the system logs", "data": {"logs_file": "sample_logs.json"}}'

## Results

Everything gets saved to `output/`:

- `analysis_summary_*.json` - Full analysis results
- `chart_*.png` - Visualizations
- `*_*.log` - Application logs (includes agent-to-agent calls)

**View latest analysis:**
```bash
# PowerShell
Get-Content (Get-ChildItem output\analysis_summary_*.json | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName

# Linux/Mac
cat output/analysis_summary_*.json | tail -50
```

## How It Works

```
User Request
    ↓
API (REST/WebSocket)
    ↓
Orchestrator (ReAct loop - plans and coordinates)
    ↓
Agents execute autonomously:
  - Log Analyzer (detects PII, calls Sanitizer directly)
  - Data Sanitizer (removes PII)
  - Report Generator (creates charts and summaries)
```

**The interesting part:** Agents call each other directly without going through the orchestrator. When the Log Analyzer finds PII in logs, it automatically calls the Data Sanitizer agent, gets cleaned data back, then continues. No orchestrator involvement needed.

Check the log files to see this in action - search for "AGENT-TO-AGENT CALL" in the analyzer logs.

## Stopping

```bash
docker-compose down        # Stop services
docker-compose down -v     # Stop and clean everything
```
