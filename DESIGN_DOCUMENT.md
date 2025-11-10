# Design Document

## 1. System Overview

This system demonstrates a multi-agent orchestration pattern using the ReAct (Reasoning + Action) loop. 
A central orchestrator coordinates specialized agents (sanitizer, analyzer, report generator) through RabbitMQ messaging. 
The FastAPI layer accepts HTTP/WebSocket requests and streams progress updates back to clients. 
Agents are autonomous, with the ability to call other agents directly without orchestrator mediation.

---

## 2. Architecture Diagram

```
+--------------------------+        HTTP/WebSocket         +-----------------------+
|      User/Client         | <---------------------------> |   FastAPI API         |
| (Browser, CLI, curl)     |                                | - Request validation  |
+-------------+------------+                                | - In-memory state     |
              |                                             | - WebSocket streaming |
              |                                             +-----------+-----------+
              | POST /plan-and-run                                     |
              v                                                        publishes
+-------------+------------+                                           |
|     RabbitMQ Queues      |<------------------------------------------+
| - orchestrator.requests  |
| - orchestrator.results   |
| - agent.tasks exchange   |
| - {agent}.inbox queues   |
+-------------+------------+
              |
              v
+-------------+------------+
|   Orchestrator Service   |
| - ReAct loop (DeepSeek)  |
| - Dispatches agents      |
| - Aggregates results     |
+------+------+------+-----+
       |      |      |
       |      |      +-------------------------------------------+
       |      +---------------------------+                      |
       |                                  |                      |
       v                                  v                      v
+--------------+               +-----------------+         +------------------+
| Sanitizer    |               | Analyzer        |         | Report Generator |
| Agent        |<------------->| Agent           |         | Agent            |
| (regex PII)  | agent-to-agent| (statistics)    |         | (matplotlib)     |
+--------------+               +-----------------+         +------------------+
```

**Key Interactions**
- API exposes `/plan-and-run` (POST) and `/status/{id}` (GET) endpoints plus WebSocket at `/ws/{id}`
- Orchestrator uses DeepSeek LLM for ReAct reasoning
- Agents use deterministic code (regex, statistics, charting) - no LLMs in agents
- Analyzer can directly call Sanitizer (agent-to-agent) without orchestrator involvement

---

## 3. Component Responsibilities

| Component | Responsibilities | Implementation Details |
|-----------|------------------|------------------------|
| **FastAPI API** | HTTP/WebSocket endpoints, request validation, correlation ID tracking, in-memory state storage, progress streaming | Stateless except for in-memory state dict. Can scale behind load balancer if state moved to Redis. |
| **RabbitMQ** | Message transport between services via queues (`orchestrator.requests`, `{agent}.inbox`, `orchestrator.results`) | Provides durability, message acknowledgments, and delivery guarantees. |
| **Orchestrator** | ReAct loop reasoning (DeepSeek LLM), task dispatch, result aggregation, progress events | Maintains per-request execution state in memory during processing. Max 10 iterations per request. |
| **Sanitizer Agent** | PII removal using regex patterns (emails, IPs, phone numbers) | Deterministic, no LLM. Can be called by orchestrator or directly by other agents. |
| **Analyzer Agent** | Statistical log analysis, error counting, PII detection. Autonomously calls Sanitizer when PII found. | Deterministic analysis with autonomous agent-to-agent calls. |
| **Report Generator** | Creates matplotlib charts (bar, pie) and JSON summary files saved to `output/` | Deterministic visualization generation. |

---

## 4. Orchestration & Communication Strategy

### Request Flow

1. **Request Ingestion**
   - User sends POST to `/plan-and-run` with natural language request
   - API generates unique `correlation_id` (UUID)
   - Stores initial state in memory: `request_states[correlation_id] = {status: "pending", ...}`
   - Publishes `OrchestrationRequest` to `orchestrator.requests` queue
   - Returns `correlation_id` immediately to user

2. **ReAct Loop Execution**
   - Orchestrator consumes request from queue
   - Iteratively performs: **Reason** (LLM decides next action) → **Act** (dispatch agent task) → **Observe** (receive result)
   - Continues until LLM decides task is complete or max iterations (10) reached
   - Timeout: 120 seconds per agent task, 300 seconds total orchestration

3. **Agent Task Dispatch**
   - Orchestrator creates `TaskMessage` with task_id, correlation_id, tool name, input data
   - Publishes to `agent.tasks` exchange with routing key `{agent_name}.task`
   - Agent consumes from its `{agent_name}.inbox` queue
   - Agent processes task and returns `ResultMessage` to `orchestrator.results` queue

4. **Agent-to-Agent Communication**
   - Agents can call other agents directly without orchestrator mediation
   - **Example**: Analyzer detects PII → creates TaskMessage with `sender="log_analyzer"` → publishes to `data_sanitizer.inbox` → waits on `replies.log_analyzer` queue for response
   - Sanitizer checks `sender` field: if not "orchestrator", knows it's agent-to-agent call
   - Publishes result directly to `task.reply_to` queue (bypassing orchestrator)
   - Calling agent includes audit trail in final result: `agent_calls_made` array
   - **Benefits**: Faster execution (no orchestrator roundtrip), reduced orchestrator load, agent autonomy

5. **Progress Updates**
   - API stores progress events in `request_states[correlation_id]["progress"]` array
   - WebSocket clients subscribed to `/ws/{correlation_id}` receive real-time broadcasts
   - Events: started, reasoning, agent_called, agent_completed, completed, error

6. **Result Return**
   - Orchestrator publishes final result to `api.responses` queue
   - API updates `request_states[correlation_id]` with results
   - Broadcasts to any connected WebSocket clients
   - User polls `/status/{correlation_id}` or receives via WebSocket

### Message Schemas

**TaskMessage** (Orchestrator → Agent, Agent → Agent)
```json
{
  "message_type": "task",
  "correlation_id": "uuid",
  "task_id": "task-uuid",
  "sender": "orchestrator",  // or agent name for agent-to-agent
  "recipient": "log_analyzer",
  "tool": "analyze_logs",
  "input": {"logs": [...]},
  "reply_to": "orchestrator.results",  // or "replies.{agent_name}" for agent-to-agent
  "timeout_seconds": 120
}
```

**ResultMessage** (Agent → Orchestrator, Agent → Agent)
```json
{
  "message_type": "result",
  "task_id": "task-uuid",
  "correlation_id": "uuid",
  "status": "success",  // or "failed", "timeout"
  "result": {...},
  "execution_details": {
    "duration_ms": 3247,
    "agent_name": "log_analyzer"
  }
}
```

### Communication Guarantees

- All messages carry `correlation_id` for end-to-end tracing
- RabbitMQ acknowledgments prevent message loss (at-least-once delivery)
- Idempotent consumers handle duplicate messages gracefully
- Failed messages (after retries) moved to dead-letter queue for manual review
- Timeouts enforced at multiple levels (task, iteration, total request)

---

## 5. Scaling, Reliability, and Production Readiness

### 5.1 Scaling Strategies

**Horizontal Scaling**

The architecture supports horizontal scaling with some caveats:

- **API Layer**: Multiple FastAPI instances behind load balancer work if state moved from in-memory dict to shared Redis. Current in-memory state only works with single instance or sticky sessions.

- **Orchestrator**: Multiple instances consume from same `orchestrator.requests` queue with RabbitMQ round-robin. Each handles different requests in parallel. Orchestration is sequential (ReAct loop), so scaling increases throughput by handling more concurrent requests, not faster individual requests.

- **Agents**: Fully horizontally scalable. Multiple instances of same agent type share inbox queue. RabbitMQ distributes tasks across available workers. Scale agents independently based on bottlenecks (e.g., 5 sanitizer instances, 2 analyzer instances).

**State Management for Scaling**

Current implementation (demo):
- API state: In-memory Python dict `request_states{}`
- Orchestrator state: In-memory per-execution
- **Limitation**: API state lost on restart, can't scale API beyond 1 instance

Production approach:
- Move API state to Redis with TTL (e.g., 1 hour expiration)
- Key pattern: `request:{correlation_id}` → `{status, result, progress[]}`
- Multiple API instances share same Redis
- Orchestrator execution state remains in-memory (OK because each request handled by one orchestrator)

**Queue Partitioning**

For high volume:
- Partition queues by tenant or priority (`premium.analyzer.inbox`, `standard.analyzer.inbox`)
- Route high-priority requests to dedicated agent pools
- Implement rate limiting per tenant to prevent resource monopolization


### 5.2 Reliability Patterns

**Message Durability**

- Queues declared with `durable=true` (survive broker restart)
- Messages published with `persistent=true` (written to disk)
- Consumer acknowledgments: agents only ACK after successful processing
- If agent crashes mid-processing, message redelivered to another instance

**Retry Logic**

Three-tier approach:

1. **LLM API retries**: 3 attempts with exponential backoff (1s, 2s, 4s) for transient network issues
2. **Task retries**: Failed agent tasks republished with incremented retry count, max 3 attempts
3. **Dead-letter queues**: After exhausting retries, message moved to DLQ with original payload and failure reason

**Timeout Handling**

- Agent task timeout: 120 seconds (configurable per task)
- Orchestrator iteration timeout: Based on task timeout + overhead
- Total orchestration timeout: 300 seconds (5 minutes)
- Max iterations: 10 (prevents infinite reasoning loops)
- If timeout occurs: Task marked as failed, orchestrator continues with partial results if possible

**Graceful Degradation**

System continues under partial failure:

- **Sanitizer fails**: Analyzer proceeds with unsanitized logs, logs warning in results
- **Analyzer fails**: Return error to user, no report generated
- **Generator fails**: Return analysis results without visualizations
- **Orchestrator LLM fails**: After retries, return error with partial execution history

**Health Monitoring**

Current implementation:
- `/health` endpoint returns `{"status": "healthy"}` (basic)
- No dependency health checks (RabbitMQ, Redis)

Production additions needed:
- Check RabbitMQ connection health
- Check Redis connectivity (if added)
- Check LLM API accessibility
- Expose metrics 
- Kubernetes liveness/readiness probes

### 5.3 Extending 

**Current Architecture vs Production AI**

| Component | Current Demo | With Real AI Models                           |
|-----------|--------------|-----------------------------------------------|
| **Orchestrator** | DeepSeek API (real LLM) | ✅ Already Smart          |
| **Sanitizer** | Regex patterns | LLM-based NER (Named Entity Recognition)      |
| **Analyzer** | Statistical counting | LLM root cause analysis, correlation detection |
| **Generator** | Matplotlib charts | LLM-generated insights + visualizations       |

**Upgrading Agents to LLM-Powered**

**1. Sanitizer Agent - PII Detection**

Current approach:
```
Regex: user@example.com → [EMAIL]
       192.168.1.1 → [IP_ADDRESS]
```

With LLM:
```
Prompt: "Identify and redact all PII in the following logs while preserving structure.
         PII includes: names, emails, IPs, phone numbers, SSNs, addresses.
         Replace with [TYPE] placeholders."

Input: Raw logs
Output: Sanitized logs + PII locations
```

Benefits:
- Context-aware: "Email john about the server" (not PII) vs "john@company.com" (PII)
- Catches obfuscated data: "Contact me at john[at]example[dot]com"
- Identifies names in natural language: "John Smith reported the issue"


**2. Analyzer Agent - Root Cause Analysis**

Current approach:
```
Count errors by level
Calculate error rate
Extract error messages
```

With LLM:
```
Prompt: "Analyze these error logs and identify:
         1. Root causes (what's actually failing)
         2. Correlated errors (which errors happen together)
         3. Suggested fixes
         4. Severity assessment"

Input: Error logs + system context
Output: Analysis with insights
```

Benefits:
- Pattern recognition beyond simple counting
- Correlation: "Database timeout → API failures → User logout spike"
- Actionable suggestions: "Increase connection pool size" not just "many timeouts"

**3. Generator Agent - Narrative Reports**

Current approach:
```
Template-based JSON output
Pre-defined matplotlib charts
```

With LLM:
```
Prompt: "Generate an executive summary of this log analysis.
         Include: severity, impact, recommended actions.
         Format as markdown with bullet points."

Input: Analysis results
Output: Human-readable narrative + visualization recommendations
```

Benefits:
- Natural language explanations for non-technical stakeholders
- Prioritized action items
- Adapts tone based on severity (urgent vs informational)



**Optimization Techniques:**

1. **Caching**: Cache LLM responses for identical inputs
   - Common error patterns seen repeatedly
   - Cache key: hash(prompt + input)
   - TTL: 1 hour
   - Hit rate: 30-40% in production systems

2. **Batch Processing**: Group similar tasks
   - Sanitize 10 log files in one LLM call vs 10 separate calls
   - Reduces per-call overhead
   - Tradeoff: Longer latency per request

3. **Progressive Analysis**: Start cheap, escalate if needed
   - Run regex PII detection first (free)
   - Only call LLM if regex finds potential PII that needs context
   - Reduces LLM calls by 60-70%

4. **Rate Limiting**: Prevent runaway costs
   - Per-user token budget (e.g., 1M tokens/day)
   - Queue requests if budget exceeded
   - Alert on unusual usage patterns

**Latency Implications**

Current demo timing:
- Total: 15-25 seconds
- Breakdown: 3 LLM calls (orchestrator only), 5s each

With LLM-powered agents:
- Total: 45-90 seconds
- Breakdown: 3 orchestrator calls + 3 agent calls, 5-10s each

Mitigation strategies:

1. **Streaming Results**: Don't wait for completion
   - Stream partial analysis as it completes
   - User sees progress: "Sanitizing... Analyzing... Generating report..."
   - Perceived latency reduced even if total time same

2. **Parallel Execution**: Where possible
   - If tasks independent, dispatch agents in parallel
   - Example: Generate 3 different visualizations simultaneously
   - Requires orchestrator logic updates

3. **Model Tier Selection**: Fast models for non-critical paths
   - Sanitizer: Fast model (2-3s per call)
   - Analyzer: Slower, more accurate (8-10s)
   - Generator: Fast model for text (2-3s)

4. **Connection Pooling**: Reduce overhead
   - Maintain persistent HTTP/2 connections to LLM APIs
   - Reuse connections across requests
   - Saves 200-500ms per call

**Agent-to-Agent**

Current implementation (analyzer → sanitizer) extends naturally:

**Benefit: Specialized Model per Agent**
```
User Request
    ↓
Orchestrator 
    ↓
Analyzer Agent
    ├─ Detects PII
    └─ Calls Sanitizer Agent (Local BERT NER - fast, cheap, private)
        ├─ Processes PII removal
        └─ Returns clean data
    ├─ Continues analysis on clean data
    └─ Returns results
```

**Cost Optimization:**
- Sanitizer uses local model (free after initial deployment)
- Analyzer uses expensive model only for complex reasoning
- Orchestrator doesn't pay for sanitization at all (agent-to-agent)

**Scaling:**
- Multiple sanitizer instances handle concurrent PII detection
- Sanitizer becomes shared service used by multiple analyzers
- Can swap sanitizer implementation (regex → LLM → local model) without changing analyzer

**Production Deployment Roadmap**

Phased approach to transition from demo to production:

**Phase 1: State Persistence** (Week 1)
- Move API state from in-memory dict to Redis
- Enables multi-instance API deployment
- Retain all other components as-is

**Phase 2: Sanitizer LLM Upgrade** (Week 2)
- Replace regex patterns with GPT-3.5-turbo NER
- A/B test: 50% regex, 50% LLM
- Measure: PII detection accuracy improvement
- Cost: ~$50/month for typical usage

**Phase 3: Analyzer Intelligence** (Week 3-4)
- Add GPT-4 root cause analysis
- Keep statistical analysis as baseline
- Prompt engineering and tuning
- Cost: ~$200/month

**Phase 4: Generator Enhancement** (Week 5)
- Add LLM-generated narrative reports
- Keep matplotlib visualizations
- Cost: ~$30/month

**Phase 5: Optimization** (Week 6-8)
- Implement caching layer
- Progressive analysis (regex first, LLM if needed)
- Model selection optimization
- Target: 50% cost reduction while maintaining quality

Each phase is independently deployable due to message-based architecture. Can roll back any phase without affecting others.

---


