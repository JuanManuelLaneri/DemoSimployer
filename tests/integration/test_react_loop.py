"""
Integration tests for ReAct Loop

Tests the orchestrator's ReAct (Reasoning + Acting) loop.
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

from orchestrator.react_loop import ReactLoop
from orchestrator.registry import AgentRegistry
from agents.shared.llm_client import LLMClient
from agents.shared.messaging import RabbitMQClient
from agents.shared.schemas import (
    RegistrationMessage,
    AgentCapabilities,
    ToolSchema,
    TaskMessage,
    ResultMessage,
    ExecutionDetails
)


class TestReactLoopBasics:
    """Test basic ReAct loop functionality"""

    def test_react_loop_initialization(self):
        """Test that ReAct loop initializes with required components"""
        # Mock components (no external dependencies)
        llm_client = LLMClient(api_key="test-key")
        rabbitmq = RabbitMQClient(host="localhost", port=5672)
        registry = AgentRegistry()

        react_loop = ReactLoop(
            llm_client=llm_client,
            rabbitmq=rabbitmq,
            registry=registry,
            max_iterations=10
        )

        assert react_loop.llm == llm_client
        assert react_loop.rabbitmq == rabbitmq
        assert react_loop.registry == registry
        assert react_loop.max_iterations == 10

    def test_react_loop_custom_max_iterations(self):
        """Test setting custom max iterations"""
        llm_client = LLMClient(api_key="test-key")
        rabbitmq = RabbitMQClient(host="localhost", port=5672)
        registry = AgentRegistry()

        react_loop = ReactLoop(
            llm_client=llm_client,
            rabbitmq=rabbitmq,
            registry=registry,
            max_iterations=5
        )

        assert react_loop.max_iterations == 5


@pytest.mark.asyncio
class TestReactLoopExecution:
    """Test ReAct loop execution logic"""

    async def test_parse_llm_decision_call_agent(self):
        """Test parsing LLM decision to call an agent"""
        from orchestrator.react_loop import ReactLoop

        llm_client = LLMClient(api_key="test-key")
        rabbitmq = RabbitMQClient(host="localhost", port=5672)
        registry = AgentRegistry()

        react_loop = ReactLoop(llm_client, rabbitmq, registry)

        # Sample LLM response
        llm_response = """
REASONING:
The user wants to sanitize logs. I'll call the sanitizer agent.

ACTION: call_agent
AGENT: data_sanitizer
TOOL: sanitize
INPUT: {"text": "test data"}
"""

        decision = react_loop.parse_llm_decision(llm_response)

        assert decision["action"] == "call_agent"
        assert decision["agent"] == "data_sanitizer"
        assert decision["tool"] == "sanitize"
        assert decision["input"] == {"text": "test data"}

    async def test_parse_llm_decision_wait(self):
        """Test parsing LLM decision to wait"""
        from orchestrator.react_loop import ReactLoop

        llm_client = LLMClient(api_key="test-key")
        rabbitmq = RabbitMQClient(host="localhost", port=5672)
        registry = AgentRegistry()

        react_loop = ReactLoop(llm_client, rabbitmq, registry)

        llm_response = """
REASONING:
Waiting for sanitizer to complete.

ACTION: wait
REASON: Waiting for data_sanitizer to finish
"""

        decision = react_loop.parse_llm_decision(llm_response)

        assert decision["action"] == "wait"
        assert "wait_reason" in decision

    async def test_parse_llm_decision_complete(self):
        """Test parsing LLM decision to complete"""
        from orchestrator.react_loop import ReactLoop

        llm_client = LLMClient(api_key="test-key")
        rabbitmq = RabbitMQClient(host="localhost", port=5672)
        registry = AgentRegistry()

        react_loop = ReactLoop(llm_client, rabbitmq, registry)

        llm_response = """
REASONING:
All tasks completed successfully.

ACTION: complete
SUMMARY: Successfully sanitized and analyzed logs
"""

        decision = react_loop.parse_llm_decision(llm_response)

        assert decision["action"] == "complete"
        assert "summary" in decision

    async def test_build_agent_registry_description(self):
        """Test building agent registry description for LLM"""
        from orchestrator.react_loop import ReactLoop

        llm_client = LLMClient(api_key="test-key")
        rabbitmq = RabbitMQClient(host="localhost", port=5672)
        registry = AgentRegistry()

        # Register a test agent
        registry.register(RegistrationMessage(
            message_type="registration",
            agent_name="test_agent",
            capabilities=AgentCapabilities(
                description="Test agent for testing",
                tools=[
                    ToolSchema(
                        name="test_tool",
                        description="Does test things",
                        input_schema={"type": "object", "properties": {"input": {"type": "string"}}},
                        output_schema={"type": "object", "properties": {"output": {"type": "string"}}}
                    )
                ]
            ),
            queue_name="test.agent.tasks",
            reply_queue_name="test.agent.replies"
        ))

        react_loop = ReactLoop(llm_client, rabbitmq, registry)
        description = react_loop.build_agent_registry_description()

        assert "test_agent" in description
        assert "test_tool" in description
        assert "Does test things" in description

    async def test_build_execution_history(self):
        """Test building execution history for LLM"""
        from orchestrator.react_loop import ReactLoop

        llm_client = LLMClient(api_key="test-key")
        rabbitmq = RabbitMQClient(host="localhost", port=5672)
        registry = AgentRegistry()

        react_loop = ReactLoop(llm_client, rabbitmq, registry)

        # Simulate some execution history
        react_loop.execution_steps = [
            {
                "step": 1,
                "action": "call_agent",
                "agent": "test_agent",
                "tool": "test_tool",
                "status": "completed",
                "result": {"output": "test result"}
            }
        ]

        history = react_loop.build_execution_history()

        assert "Step 1" in history
        assert "test_agent" in history
        assert "completed" in history


@pytest.mark.asyncio
class TestReactLoopAgentCalls:
    """Test ReAct loop agent calling functionality"""

    async def test_dispatch_task_to_agent(self, rabbitmq_client):
        """Test dispatching a task to an agent"""
        from orchestrator.react_loop import ReactLoop

        llm_client = LLMClient(api_key="test-key")
        registry = AgentRegistry()

        # Register a test agent
        registry.register(RegistrationMessage(
            message_type="registration",
            agent_name="test_agent",
            capabilities=AgentCapabilities(
                description="Test agent",
                tools=[
                    ToolSchema(
                        name="test_tool",
                        description="Test",
                        input_schema={},
                        output_schema={}
                    )
                ]
            ),
            queue_name="test.agent.tasks",
            reply_queue_name="test.agent.replies"
        ))

        react_loop = ReactLoop(llm_client, rabbitmq_client, registry)

        # Declare test queue
        await rabbitmq_client.declare_queue("test.agent.tasks", durable=True)

        # Dispatch task
        task_id = await react_loop.dispatch_task(
            agent_name="test_agent",
            tool="test_tool",
            input_data={"test": "data"},
            correlation_id="test-corr-123"
        )

        assert task_id is not None
        assert task_id.startswith("task-")

    async def test_wait_for_agent_result(self, rabbitmq_client):
        """Test waiting for an agent result"""
        from orchestrator.react_loop import ReactLoop
        from orchestrator.handlers import TaskResultHandler

        llm_client = LLMClient(api_key="test-key")
        registry = AgentRegistry()
        result_handler = TaskResultHandler(rabbitmq_client)

        react_loop = ReactLoop(llm_client, rabbitmq_client, registry)
        react_loop.result_handler = result_handler

        # Simulate sending a result
        async def send_result():
            await asyncio.sleep(0.5)
            result = ResultMessage(
                message_type="result",
                correlation_id="test-corr-123",
                task_id="task-123",
                status="success",
                result={"output": "test output"},
                execution_details=ExecutionDetails(
                    agent_name="test_agent",
                    duration_ms=100
                )
            )
            await result_handler.handle_result(result)

        # Start waiting and sending concurrently
        send_task = asyncio.create_task(send_result())

        result = await react_loop.wait_for_result("test-corr-123", timeout=2.0)

        await send_task

        assert result is not None
        assert result.status == "success"
        assert result.result == {"output": "test output"}


@pytest.mark.asyncio
class TestReactLoopIntegration:
    """Test full ReAct loop integration (requires LLM)"""

    @pytest.mark.skip(reason="Requires real LLM - expensive")
    async def test_full_react_loop_execution(self, rabbitmq_client, llm_client):
        """Test complete ReAct loop with real LLM"""
        from orchestrator.react_loop import ReactLoop

        registry = AgentRegistry()

        # Register test agents
        registry.register(RegistrationMessage(
            message_type="registration",
            agent_name="data_sanitizer",
            capabilities=AgentCapabilities(
                description="Removes PII from text",
                tools=[
                    ToolSchema(
                        name="sanitize",
                        description="Remove PII",
                        input_schema={"type": "object"},
                        output_schema={"type": "object"}
                    )
                ]
            ),
            queue_name="sanitizer.tasks",
            reply_queue_name="sanitizer.replies"
        ))

        react_loop = ReactLoop(llm_client, rabbitmq_client, registry)

        # Execute orchestration
        result = await react_loop.execute(
            user_request="Sanitize this text: john@example.com",
            correlation_id="test-integration-123"
        )

        assert result is not None
        assert result["status"] in ["completed", "not_implemented"]


@pytest.mark.asyncio
class TestReactLoopErrorHandling:
    """Test ReAct loop error handling"""

    async def test_max_iterations_exceeded(self):
        """Test that loop stops after max iterations"""
        from orchestrator.react_loop import ReactLoop

        llm_client = LLMClient(api_key="test-key")
        rabbitmq = RabbitMQClient(host="localhost", port=5672)
        registry = AgentRegistry()

        react_loop = ReactLoop(llm_client, rabbitmq, registry, max_iterations=2)

        # Mock the LLM to always return "wait" (infinite loop)
        async def mock_execute(request, correlation_id, data=None):
            # This would loop forever without max_iterations
            return {
                "status": "max_iterations_exceeded",
                "iterations": 2
            }

        # Test will be implemented when we have the actual loop

    async def test_agent_not_found_error(self):
        """Test handling when requested agent doesn't exist"""
        from orchestrator.react_loop import ReactLoop

        llm_client = LLMClient(api_key="test-key")
        rabbitmq = RabbitMQClient(host="localhost", port=5672)
        registry = AgentRegistry()

        react_loop = ReactLoop(llm_client, rabbitmq, registry)

        # Try to dispatch to non-existent agent
        with pytest.raises(Exception) as exc_info:
            await react_loop.dispatch_task(
                agent_name="nonexistent_agent",
                tool="some_tool",
                input_data={},
                correlation_id="test-123"
            )

        assert "not found" in str(exc_info.value).lower() or "nonexistent" in str(exc_info.value).lower()

    async def test_timeout_waiting_for_result(self, rabbitmq_client):
        """Test timeout when waiting for agent result"""
        from orchestrator.react_loop import ReactLoop
        from orchestrator.handlers import TaskResultHandler

        llm_client = LLMClient(api_key="test-key")
        registry = AgentRegistry()
        result_handler = TaskResultHandler(rabbitmq_client)

        react_loop = ReactLoop(llm_client, rabbitmq_client, registry)
        react_loop.result_handler = result_handler

        # Wait for result that never comes
        with pytest.raises(asyncio.TimeoutError):
            await react_loop.wait_for_result("never-coming-123", timeout=0.5)
