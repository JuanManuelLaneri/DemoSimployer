"""
Integration tests for Orchestrator Core

Following TDD approach - tests written first, then implementation.
Tests use real RabbitMQ (via testcontainers or docker-compose).
"""

import pytest
import asyncio
from datetime import datetime, UTC
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from orchestrator.registry import AgentRegistry
from agents.shared.schemas import (
    RegistrationMessage,
    DiscoveryQuery,
    DiscoveryResponse,
    AgentCapabilities,
    ToolSchema
)


class TestAgentRegistry:
    """Test the agent registry functionality"""

    def test_registry_initialization(self):
        """Test that registry initializes empty"""
        registry = AgentRegistry()
        assert len(registry.list_all()) == 0

    def test_register_single_agent(self):
        """Test registering a single agent"""
        registry = AgentRegistry()

        capabilities = AgentCapabilities(
            description="Test agent",
            tools=[
                ToolSchema(
                    name="test_capability",
                    description="Test tool",
                    input_schema={"type": "object"},
                    output_schema={"type": "object"}
                )
            ]
        )

        registration = RegistrationMessage(
            message_type="registration",
            agent_name="test_agent",
            capabilities=capabilities,
            queue_name="test.agent.tasks",
            reply_queue_name="test.agent.replies"
        )

        registry.register(registration)

        # Verify agent is registered
        assert "test_agent" in registry.list_all()
        agent_info = registry.get_agent("test_agent")
        assert agent_info is not None
        assert agent_info["agent_name"] == "test_agent"
        assert agent_info["capabilities"] == ["test_capability"]
        assert agent_info["queue_name"] == "test.agent.tasks"
        assert agent_info["reply_queue_name"] == "test.agent.replies"
        assert agent_info["status"] == "active"

    def test_register_multiple_agents(self):
        """Test registering multiple agents"""
        registry = AgentRegistry()

        agents = []
        for i in range(3):
            capabilities = AgentCapabilities(
                description=f"Agent {i}",
                tools=[
                    ToolSchema(
                        name=f"capability_{i}",
                        description=f"Tool {i}",
                        input_schema={"type": "object"},
                        output_schema={"type": "object"}
                    )
                ]
            )
            agents.append(
                RegistrationMessage(
                    message_type="registration",
                    agent_name=f"agent_{i}",
                    capabilities=capabilities,
                    queue_name=f"agent.{i}.tasks",
                    reply_queue_name=f"agent.{i}.replies"
                )
            )

        for agent in agents:
            registry.register(agent)

        # Verify all agents registered
        all_agents = registry.list_all()
        assert len(all_agents) == 3
        assert "agent_0" in all_agents
        assert "agent_1" in all_agents
        assert "agent_2" in all_agents

    def test_get_nonexistent_agent(self):
        """Test getting an agent that doesn't exist"""
        registry = AgentRegistry()

        agent_info = registry.get_agent("nonexistent")
        assert agent_info is None

    def test_find_agents_by_capability(self):
        """Test finding agents by capability"""
        registry = AgentRegistry()

        # Register agents with different capabilities
        registry.register(RegistrationMessage(
            message_type="registration",
            agent_name="sanitizer",
            capabilities=AgentCapabilities(
                description="Sanitizer agent",
                tools=[
                    ToolSchema(name="sanitize_pii", description="Remove PII",
                              input_schema={}, output_schema={}),
                    ToolSchema(name="remove_sensitive_data", description="Remove sensitive data",
                              input_schema={}, output_schema={})
                ]
            ),
            queue_name="sanitizer.tasks",
            reply_queue_name="sanitizer.replies"
        ))

        registry.register(RegistrationMessage(
            message_type="registration",
            agent_name="analyzer",
            capabilities=AgentCapabilities(
                description="Analyzer agent",
                tools=[
                    ToolSchema(name="analyze_logs", description="Analyze logs",
                              input_schema={}, output_schema={}),
                    ToolSchema(name="find_errors", description="Find errors",
                              input_schema={}, output_schema={})
                ]
            ),
            queue_name="analyzer.tasks",
            reply_queue_name="analyzer.replies"
        ))

        registry.register(RegistrationMessage(
            message_type="registration",
            agent_name="generator",
            capabilities=AgentCapabilities(
                description="Generator agent",
                tools=[
                    ToolSchema(name="generate_report", description="Generate report",
                              input_schema={}, output_schema={}),
                    ToolSchema(name="create_summary", description="Create summary",
                              input_schema={}, output_schema={})
                ]
            ),
            queue_name="generator.tasks",
            reply_queue_name="generator.replies"
        ))

        # Find agents by capability
        sanitizers = registry.find_by_capability("sanitize_pii")
        assert len(sanitizers) == 1
        assert sanitizers[0]["agent_name"] == "sanitizer"

        analyzers = registry.find_by_capability("analyze_logs")
        assert len(analyzers) == 1
        assert analyzers[0]["agent_name"] == "analyzer"

        # Capability that doesn't exist
        notfound = registry.find_by_capability("nonexistent_capability")
        assert len(notfound) == 0

    def test_update_agent_registration(self):
        """Test updating an existing agent's registration"""
        registry = AgentRegistry()

        # Initial registration
        registry.register(RegistrationMessage(
            message_type="registration",
            agent_name="test_agent",
            capabilities=AgentCapabilities(
                description="Test agent v1",
                tools=[
                    ToolSchema(name="capability_1", description="Cap 1",
                              input_schema={}, output_schema={})
                ]
            ),
            queue_name="test.tasks",
            reply_queue_name="test.replies"
        ))

        # Update with new capabilities
        registry.register(RegistrationMessage(
            message_type="registration",
            agent_name="test_agent",
            capabilities=AgentCapabilities(
                description="Test agent v2",
                tools=[
                    ToolSchema(name="capability_1", description="Cap 1",
                              input_schema={}, output_schema={}),
                    ToolSchema(name="capability_2", description="Cap 2",
                              input_schema={}, output_schema={})
                ]
            ),
            queue_name="test.tasks.v2",
            reply_queue_name="test.replies.v2"
        ))

        # Verify update
        agent_info = registry.get_agent("test_agent")
        assert len(agent_info["capabilities"]) == 2
        assert "capability_2" in agent_info["capabilities"]
        assert agent_info["queue_name"] == "test.tasks.v2"

    def test_unregister_agent(self):
        """Test unregistering an agent"""
        registry = AgentRegistry()

        registry.register(RegistrationMessage(
            message_type="registration",
            agent_name="test_agent",
            capabilities=AgentCapabilities(
                description="Test agent",
                tools=[ToolSchema(name="test", description="Test",
                                input_schema={}, output_schema={})]
            ),
            queue_name="test.tasks",
            reply_queue_name="test.replies"
        ))

        assert "test_agent" in registry.list_all()

        registry.unregister("test_agent")

        assert "test_agent" not in registry.list_all()
        assert registry.get_agent("test_agent") is None

    def test_agent_heartbeat_tracking(self):
        """Test that agent last_seen timestamp is tracked"""
        registry = AgentRegistry()

        before_registration = datetime.now(UTC)

        registry.register(RegistrationMessage(
            message_type="registration",
            agent_name="test_agent",
            capabilities=AgentCapabilities(
                description="Test agent",
                tools=[ToolSchema(name="test", description="Test",
                                input_schema={}, output_schema={})]
            ),
            queue_name="test.tasks",
            reply_queue_name="test.replies"
        ))

        after_registration = datetime.now(UTC)

        agent_info = registry.get_agent("test_agent")
        last_seen = agent_info["last_seen"]

        # Verify timestamp is recent
        assert before_registration <= last_seen <= after_registration

    def test_list_all_returns_agent_names(self):
        """Test that list_all returns agent names only"""
        registry = AgentRegistry()

        for i in range(3):
            registry.register(RegistrationMessage(
                message_type="registration",
                agent_name=f"agent_{i}",
                capabilities=AgentCapabilities(
                    description=f"Agent {i}",
                    tools=[ToolSchema(name=f"cap_{i}", description=f"Capability {i}",
                                    input_schema={}, output_schema={})]
                ),
                queue_name=f"agent.{i}.tasks",
                reply_queue_name=f"agent.{i}.replies"
            ))

        all_agents = registry.list_all()
        assert isinstance(all_agents, list)
        assert len(all_agents) == 3
        assert all(isinstance(name, str) for name in all_agents)


@pytest.mark.asyncio
class TestRegistrationHandler:
    """Test registration message handling"""

    async def test_handler_initialization(self, rabbitmq_client):
        """Test that registration handler initializes properly"""
        from orchestrator.handlers import RegistrationHandler

        registry = AgentRegistry()
        handler = RegistrationHandler(registry, rabbitmq_client)

        assert handler.registry == registry
        assert handler.rabbitmq == rabbitmq_client

    async def test_handle_registration_message(self, rabbitmq_client):
        """Test handling a registration message"""
        from orchestrator.handlers import RegistrationHandler

        registry = AgentRegistry()
        handler = RegistrationHandler(registry, rabbitmq_client)

        registration = RegistrationMessage(
            message_type="registration",
            agent_name="test_agent",
            capabilities=AgentCapabilities(
                description="Test agent",
                tools=[ToolSchema(name="test_capability", description="Test",
                                input_schema={}, output_schema={})]
            ),
            queue_name="test.tasks",
            reply_queue_name="test.replies"
        )

        await handler.handle_registration(registration)

        # Verify agent was registered
        assert "test_agent" in registry.list_all()
        agent_info = registry.get_agent("test_agent")
        assert agent_info["agent_name"] == "test_agent"

    async def test_consume_registration_messages(self, rabbitmq_client):
        """Test consuming registration messages from RabbitMQ"""
        from orchestrator.handlers import RegistrationHandler

        registry = AgentRegistry()
        handler = RegistrationHandler(registry, rabbitmq_client)

        # Declare queue for registration messages
        await rabbitmq_client.declare_queue("orchestrator.registrations", durable=True)
        await rabbitmq_client.bind_queue(
            "orchestrator.registrations",
            "orchestrator.register",
            "register.*"
        )

        # Publish a registration message
        registration = RegistrationMessage(
            message_type="registration",
            agent_name="test_agent",
            capabilities=AgentCapabilities(
                description="Test agent",
                tools=[ToolSchema(name="test", description="Test",
                                input_schema={}, output_schema={})]
            ),
            queue_name="test.tasks",
            reply_queue_name="test.replies"
        )

        await rabbitmq_client.publish(
            exchange_name="orchestrator.register",
            routing_key="register.test_agent",
            message_body=registration.to_json()
        )

        # Start consuming (will run in background)
        consume_task = asyncio.create_task(
            handler.start_consuming("orchestrator.registrations")
        )

        # Wait for message to be processed
        await asyncio.sleep(1)

        # Verify agent was registered
        assert "test_agent" in registry.list_all()

        # Cleanup
        consume_task.cancel()
        try:
            await consume_task
        except asyncio.CancelledError:
            pass


# TODO: Implement service discovery tests that match MESSAGE_SCHEMAS.md
# The DiscoveryQuery/Response schemas need to be updated to match the spec
# Current spec has: requester, target_agent, reply_to
# We need to support: find by name, find by capability, list all
#
# @pytest.mark.asyncio
# class TestServiceDiscovery:
#     """Test service discovery functionality"""
#     pass
