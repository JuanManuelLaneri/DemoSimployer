"""
Project Chimera - Message Schemas

Pydantic models for all RabbitMQ messages exchanged between services.
Based on MESSAGE_SCHEMAS.md specification.
"""

from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime, UTC
from typing import Optional, Dict, Any, List, Literal
import uuid


class ChimeraBaseMessage(BaseModel):
    """Base class for all Chimera messages"""
    model_config = ConfigDict(
        populate_by_name=True,
        use_enum_values=True
    )

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def to_json(self) -> str:
        """Serialize to JSON string"""
        return self.model_dump_json()

    @classmethod
    def from_json(cls, json_str: str):
        """Deserialize from JSON string"""
        return cls.model_validate_json(json_str)


# ============================================
# Tool and Capability Schemas
# ============================================

class ToolSchema(BaseModel):
    """Schema defining an agent's tool/capability"""
    name: str
    description: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]


class AgentCapabilities(BaseModel):
    """Agent capabilities and available tools"""
    description: str
    tools: List[ToolSchema]


# ============================================
# Registration Messages
# ============================================

class RegistrationMessage(ChimeraBaseMessage):
    """Agent self-registration message"""
    message_type: Literal["registration"]
    agent_name: str
    agent_version: str = "1.0.0"
    capabilities: AgentCapabilities
    queue_name: str
    reply_queue_name: str
    status: Literal["ready", "busy", "error"] = "ready"


class RegistrationAckMessage(ChimeraBaseMessage):
    """Orchestrator registration acknowledgment"""
    message_type: Literal["registration_ack"]
    agent_name: str
    status: Literal["registered", "rejected"]
    message: str
    registered_tools: List[str]


# ============================================
# Orchestration Messages
# ============================================

class OrchestrationRequest(ChimeraBaseMessage):
    """User request for orchestration"""
    message_type: Literal["orchestration_request"]
    correlation_id: str = Field(default_factory=lambda: f"corr-{uuid.uuid4()}")
    request: str  # Natural language request
    data: Dict[str, Any] = {}
    reply_to: str
    websocket_session_id: Optional[str] = None
    metadata: Dict[str, Any] = {}


# ============================================
# Task Messages
# ============================================

class ExecutionStep(BaseModel):
    """Single step in execution history"""
    step: int
    action: str
    agent: str
    status: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TaskMessage(ChimeraBaseMessage):
    """Task assignment to agent"""
    message_type: Literal["task"]
    correlation_id: str
    task_id: str = Field(default_factory=lambda: f"task-{uuid.uuid4()}")
    parent_task_id: Optional[str] = None
    sender: str
    recipient: str
    tool: str
    input: Dict[str, Any]
    context: Dict[str, Any] = {}
    reply_to: str
    timeout_seconds: int = 120


# ============================================
# Result Messages
# ============================================

class ExecutionDetails(BaseModel):
    """Details about task execution"""
    agent_name: str
    duration_ms: float
    called_agents: List[str] = []
    llm_calls: int = 0
    llm_model: str = "deepseek-chat"
    reasoning: Optional[str] = None


class ResultMessage(ChimeraBaseMessage):
    """Agent task result"""
    message_type: Literal["result"]
    correlation_id: str
    task_id: str
    status: Literal["success", "error", "timeout"]
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    execution_details: ExecutionDetails


# ============================================
# Service Discovery Messages
# ============================================

class DiscoveryQuery(ChimeraBaseMessage):
    """Query to find another agent"""
    message_type: Literal["discovery_query"]
    correlation_id: str
    query_id: str = Field(default_factory=lambda: f"query-{uuid.uuid4()}")
    requester: str
    target_agent: str
    reply_to: str


class AgentInfo(BaseModel):
    """Information about a registered agent"""
    queue_name: str
    reply_queue_name: str
    available_tools: List[str]
    status: str


class DiscoveryResponse(ChimeraBaseMessage):
    """Response to service discovery query"""
    message_type: Literal["discovery_response"]
    query_id: str
    target_agent: str
    found: bool
    agent_info: Optional[AgentInfo] = None
    error: Optional[str] = None


# ============================================
# Progress Update Messages (for WebSocket)
# ============================================

class ProgressUpdate(ChimeraBaseMessage):
    """Real-time progress update"""
    message_type: Literal["progress_update"]
    correlation_id: str
    event_type: Literal[
        "started",
        "reasoning",
        "agent_called",
        "agent_completed",
        "error",
        "completed"
    ]
    data: Dict[str, Any]
    message: str


# ============================================
# Final Result Messages
# ============================================

class ExecutionFlowStep(BaseModel):
    """Step in execution flow"""
    step: int
    agent: str
    action: str
    details: Optional[Dict[str, Any]] = None
    output_files: List[str] = []
    duration_ms: float


class VisualAsset(BaseModel):
    """Visual asset metadata"""
    type: str
    path: str
    description: str


class AgentCall(BaseModel):
    """Record of agent-to-agent call"""
    from_agent: str = Field(alias="from")
    to_agent: str = Field(alias="to")

    model_config = ConfigDict(populate_by_alias=True)


class OrchestrationResult(ChimeraBaseMessage):
    """Final orchestration result"""
    message_type: Literal["orchestration_result"]
    correlation_id: str
    status: Literal["completed", "failed", "timeout"]
    results: Dict[str, Any]
    total_duration_ms: float
    total_llm_calls: int
    agents_involved: List[str]
    agent_to_agent_calls: List[AgentCall]
