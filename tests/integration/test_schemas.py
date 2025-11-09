"""
Integration tests for Pydantic message schemas.
"""

import pytest
from datetime import datetime
from agents.shared.schemas import (
    RegistrationMessage,
    TaskMessage,
    ResultMessage,
    DiscoveryQuery,
    DiscoveryResponse,
    OrchestrationRequest,
    ToolSchema,
    AgentCapabilities,
    ExecutionDetails,
    AgentInfo
)


def test_registration_message_creation():
    """Test creating and serializing RegistrationMessage"""
    capabilities = AgentCapabilities(
        description="Test agent",
        tools=[
            ToolSchema(
                name="test_tool",
                description="A test tool",
                input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
                output_schema={"type": "object", "properties": {"result": {"type": "string"}}}
            )
        ]
    )

    msg = RegistrationMessage(
        message_type="registration",
        agent_name="test_agent",
        capabilities=capabilities,
        queue_name="test_agent.inbox",
        reply_queue_name="replies.test_agent"
    )

    assert msg.agent_name == "test_agent"
    assert msg.status == "ready"
    assert len(msg.capabilities.tools) == 1

    # Test serialization
    json_str = msg.to_json()
    assert "test_agent" in json_str

    # Test deserialization
    restored = RegistrationMessage.from_json(json_str)
    assert restored.agent_name == msg.agent_name
    assert restored.capabilities.tools[0].name == "test_tool"


def test_task_message_creation():
    """Test creating TaskMessage with auto-generated IDs"""
    task = TaskMessage(
        message_type="task",
        correlation_id="corr-123",
        sender="orchestrator",
        recipient="test_agent",
        tool="test_tool",
        input={"text": "Hello"},
        reply_to="orchestrator.responses"
    )

    assert task.task_id.startswith("task-")
    assert task.correlation_id == "corr-123"
    assert task.timeout_seconds == 120  # default

    # Test serialization round-trip
    json_str = task.to_json()
    restored = TaskMessage.from_json(json_str)
    assert restored.task_id == task.task_id
    assert restored.input["text"] == "Hello"


def test_result_message_success():
    """Test ResultMessage for successful task"""
    result = ResultMessage(
        message_type="result",
        correlation_id="corr-123",
        task_id="task-456",
        status="success",
        result={"output": "Success!"},
        execution_details=ExecutionDetails(
            agent_name="test_agent",
            duration_ms=150.5,
            called_agents=["other_agent"],
            llm_calls=2
        )
    )

    assert result.status == "success"
    assert result.error is None
    assert result.execution_details.duration_ms == 150.5
    assert "other_agent" in result.execution_details.called_agents


def test_result_message_error():
    """Test ResultMessage for failed task"""
    result = ResultMessage(
        message_type="result",
        correlation_id="corr-123",
        task_id="task-456",
        status="error",
        error="Something went wrong",
        execution_details=ExecutionDetails(
            agent_name="test_agent",
            duration_ms=50.0,
            llm_calls=0
        )
    )

    assert result.status == "error"
    assert result.result is None
    assert "Something went wrong" in result.error


def test_discovery_query_and_response():
    """Test service discovery messages"""
    query = DiscoveryQuery(
        message_type="discovery_query",
        correlation_id="corr-123",
        requester="agent_a",
        target_agent="agent_b",
        reply_to="replies.agent_a"
    )

    assert query.query_id.startswith("query-")
    assert query.target_agent == "agent_b"

    # Response when found
    response_found = DiscoveryResponse(
        message_type="discovery_response",
        query_id=query.query_id,
        target_agent="agent_b",
        found=True,
        agent_info=AgentInfo(
            queue_name="agent_b.inbox",
            reply_queue_name="replies.agent_b",
            available_tools=["tool1", "tool2"],
            status="ready"
        )
    )

    assert response_found.found
    assert response_found.agent_info.queue_name == "agent_b.inbox"

    # Response when not found
    response_not_found = DiscoveryResponse(
        message_type="discovery_response",
        query_id=query.query_id,
        target_agent="agent_b",
        found=False,
        error="Agent not registered"
    )

    assert not response_not_found.found
    assert response_not_found.agent_info is None


def test_orchestration_request():
    """Test OrchestrationRequest message"""
    request = OrchestrationRequest(
        message_type="orchestration_request",
        request="Analyze logs and generate report",
        data={"logs_file": "sample_logs.json"},
        reply_to="api.results",
        websocket_session_id="ws-session-123"
    )

    assert request.correlation_id.startswith("corr-")
    assert request.request == "Analyze logs and generate report"
    assert request.data["logs_file"] == "sample_logs.json"
    assert request.websocket_session_id == "ws-session-123"


def test_message_validation():
    """Test Pydantic validation catches invalid messages"""
    # Missing required fields
    with pytest.raises(Exception):
        TaskMessage(
            message_type="task"
            # Missing required fields
        )

    # Invalid message_type
    with pytest.raises(Exception):
        RegistrationMessage(
            message_type="invalid_type",  # Should be "registration"
            agent_name="test",
            capabilities=AgentCapabilities(description="test", tools=[]),
            queue_name="test",
            reply_queue_name="test"
        )


def test_timestamp_auto_generation():
    """Test that timestamps are auto-generated"""
    msg1 = TaskMessage(
        message_type="task",
        correlation_id="corr-1",
        sender="a",
        recipient="b",
        tool="test",
        input={},
        reply_to="test"
    )

    assert isinstance(msg1.timestamp, datetime)

    # Different messages have different timestamps (though very close)
    msg2 = TaskMessage(
        message_type="task",
        correlation_id="corr-2",
        sender="a",
        recipient="b",
        tool="test",
        input={},
        reply_to="test"
    )

    # Timestamps should exist
    assert msg1.timestamp is not None
    assert msg2.timestamp is not None
