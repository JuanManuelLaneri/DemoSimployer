"""
Integration tests for Orchestration Request Handler

Tests the handler that consumes user requests and triggers the ReAct loop.
Following TDD approach - tests written first, then implementation.
"""

import pytest
import asyncio
from datetime import datetime, UTC
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from orchestrator.request_handler import OrchestrationRequestHandler
from orchestrator.react_loop import ReactLoop
from orchestrator.registry import AgentRegistry
from agents.shared.llm_client import LLMClient
from agents.shared.messaging import RabbitMQClient
from agents.shared.schemas import (
    OrchestrationRequest,
    OrchestrationResult,
    RegistrationMessage,
    AgentCapabilities,
    ToolSchema
)


class TestRequestHandlerBasics:
    """Test basic request handler functionality"""

    def test_request_handler_initialization(self):
        """Test that request handler initializes properly"""
        llm_client = LLMClient(api_key="test-key")
        rabbitmq = RabbitMQClient(host="localhost", port=5672)
        registry = AgentRegistry()
        react_loop = ReactLoop(llm_client, rabbitmq, registry)

        handler = OrchestrationRequestHandler(
            react_loop=react_loop,
            rabbitmq=rabbitmq
        )

        assert handler.react_loop == react_loop
        assert handler.rabbitmq == rabbitmq


@pytest.mark.asyncio
class TestRequestHandling:
    """Test request handling logic"""

    async def test_handle_orchestration_request(self):
        """Test handling a single orchestration request"""
        llm_client = LLMClient(api_key="test-key")
        rabbitmq = RabbitMQClient(host="localhost", port=5672)
        registry = AgentRegistry()
        react_loop = ReactLoop(llm_client, rabbitmq, registry)

        handler = OrchestrationRequestHandler(
            react_loop=react_loop,
            rabbitmq=rabbitmq
        )

        # Create test request
        request = OrchestrationRequest(
            message_type="orchestration_request",
            correlation_id="test-corr-123",
            request="Test request",
            data={},
            reply_to="test.reply.queue"
        )

        # Mock the ReAct loop to return immediately
        async def mock_execute(user_request, correlation_id, data=None):
            return {
                "status": "completed",
                "correlation_id": correlation_id,
                "summary": "Mock execution complete",
                "iterations": 1,
                "execution_steps": [],
                "results": {}
            }

        react_loop.execute = mock_execute

        # Handle the request
        result = await handler.handle_request(request)

        assert result is not None
        assert result["status"] == "completed"
        assert result["correlation_id"] == "test-corr-123"

    async def test_parse_orchestration_request(self):
        """Test parsing orchestration request from JSON"""
        llm_client = LLMClient(api_key="test-key")
        rabbitmq = RabbitMQClient(host="localhost", port=5672)
        registry = AgentRegistry()
        react_loop = ReactLoop(llm_client, rabbitmq, registry)

        handler = OrchestrationRequestHandler(
            react_loop=react_loop,
            rabbitmq=rabbitmq
        )

        # Create request JSON
        request_json = """
        {
            "message_type": "orchestration_request",
            "correlation_id": "test-123",
            "request": "Sanitize these logs",
            "data": {"logs": "sample data"},
            "reply_to": "test.reply",
            "timestamp": "2025-11-08T00:00:00Z"
        }
        """

        request = OrchestrationRequest.from_json(request_json)

        assert request.correlation_id == "test-123"
        assert request.request == "Sanitize these logs"
        assert request.data == {"logs": "sample data"}

    async def test_build_orchestration_result(self):
        """Test building orchestration result message"""
        llm_client = LLMClient(api_key="test-key")
        rabbitmq = RabbitMQClient(host="localhost", port=5672)
        registry = AgentRegistry()
        react_loop = ReactLoop(llm_client, rabbitmq, registry)

        handler = OrchestrationRequestHandler(
            react_loop=react_loop,
            rabbitmq=rabbitmq
        )

        # Mock ReAct result
        react_result = {
            "status": "completed",
            "correlation_id": "test-123",
            "summary": "Task completed successfully",
            "iterations": 3,
            "execution_steps": [
                {"step": 1, "action": "call_agent", "agent": "test_agent"}
            ],
            "results": {"output": "test output"}
        }

        # Build OrchestrationResult
        result = handler.build_orchestration_result(react_result)

        assert isinstance(result, OrchestrationResult)
        assert result.correlation_id == "test-123"
        assert result.status == "completed"


@pytest.mark.asyncio
class TestRequestConsumer:
    """Test request consumption from RabbitMQ"""

    async def test_consume_orchestration_requests(self, rabbitmq_client):
        """Test consuming requests from queue"""
        llm_client = LLMClient(api_key="test-key")
        registry = AgentRegistry()
        react_loop = ReactLoop(llm_client, rabbitmq_client, registry)

        handler = OrchestrationRequestHandler(
            react_loop=react_loop,
            rabbitmq=rabbitmq_client
        )

        # Track received requests
        received_requests = []

        async def mock_handle(request):
            received_requests.append(request)
            return {
                "status": "completed",
                "correlation_id": request.correlation_id,
                "summary": "Mock handled",
                "iterations": 1,
                "execution_steps": [],
                "results": {}
            }

        handler.handle_request = mock_handle

        # Declare test queue
        await rabbitmq_client.declare_queue("test.orchestration.requests", durable=True)
        await rabbitmq_client.bind_queue(
            "test.orchestration.requests",
            "orchestrator.requests",
            "request.*"
        )

        # Publish test request
        test_request = OrchestrationRequest(
            message_type="orchestration_request",
            correlation_id="test-consume-123",
            request="Test consume request",
            data={},
            reply_to="test.reply"
        )

        await rabbitmq_client.publish(
            exchange_name="orchestrator.requests",
            routing_key="request.test",
            message_body=test_request.to_json(),
            correlation_id=test_request.correlation_id
        )

        # Start consuming (in background)
        consume_task = asyncio.create_task(
            handler.start_consuming("test.orchestration.requests")
        )

        # Wait for message to be processed
        await asyncio.sleep(1)

        # Verify request was received
        assert len(received_requests) == 1
        assert received_requests[0].correlation_id == "test-consume-123"

        # Cleanup
        consume_task.cancel()
        try:
            await consume_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
class TestResultPublishing:
    """Test publishing orchestration results"""

    async def test_publish_orchestration_result(self, rabbitmq_client):
        """Test publishing result to reply queue"""
        llm_client = LLMClient(api_key="test-key")
        registry = AgentRegistry()
        react_loop = ReactLoop(llm_client, rabbitmq_client, registry)

        handler = OrchestrationRequestHandler(
            react_loop=react_loop,
            rabbitmq=rabbitmq_client
        )

        # Declare reply queue
        await rabbitmq_client.declare_queue("test.reply.queue", durable=True)

        # Create test result
        react_result = {
            "status": "completed",
            "correlation_id": "test-publish-123",
            "summary": "Test completed",
            "iterations": 2,
            "execution_steps": [],
            "results": {"output": "test"}
        }

        # Publish result
        await handler.publish_result(
            react_result=react_result,
            reply_to="test.reply.queue",
            correlation_id="test-publish-123"
        )

        # Verify message was published (would need to consume to fully verify)
        # For now, just verify no errors
        await asyncio.sleep(0.5)


@pytest.mark.asyncio
class TestErrorHandling:
    """Test request handler error handling"""

    async def test_handle_request_with_react_loop_error(self):
        """Test handling when ReAct loop raises error"""
        llm_client = LLMClient(api_key="test-key")
        rabbitmq = RabbitMQClient(host="localhost", port=5672)
        registry = AgentRegistry()
        react_loop = ReactLoop(llm_client, rabbitmq, registry)

        handler = OrchestrationRequestHandler(
            react_loop=react_loop,
            rabbitmq=rabbitmq
        )

        # Mock ReAct loop to raise error
        async def mock_execute_error(user_request, correlation_id, data=None):
            raise Exception("ReAct loop error")

        react_loop.execute = mock_execute_error

        # Create test request
        request = OrchestrationRequest(
            message_type="orchestration_request",
            correlation_id="test-error-123",
            request="Test error handling",
            data={},
            reply_to="test.reply"
        )

        # Handle request
        result = await handler.handle_request(request)

        # Should return error result
        assert result is not None
        assert result["status"] == "error"
        assert "error" in result or "message" in result

    async def test_handle_invalid_request_message(self):
        """Test handling invalid/malformed request"""
        llm_client = LLMClient(api_key="test-key")
        rabbitmq = RabbitMQClient(host="localhost", port=5672)
        registry = AgentRegistry()
        react_loop = ReactLoop(llm_client, rabbitmq, registry)

        handler = OrchestrationRequestHandler(
            react_loop=react_loop,
            rabbitmq=rabbitmq
        )

        # Invalid JSON should be caught by Pydantic
        invalid_json = '{"invalid": "data"}'

        with pytest.raises(Exception):
            OrchestrationRequest.from_json(invalid_json)
