"""
Integration tests for Progress Update Publisher

Tests the publisher that sends real-time progress updates during orchestration.
Following TDD approach - tests written first, then implementation.
"""

import pytest
import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from orchestrator.progress_publisher import ProgressPublisher
from agents.shared.messaging import RabbitMQClient
from agents.shared.schemas import ProgressUpdate


class TestProgressPublisherBasics:
    """Test basic progress publisher functionality"""

    def test_progress_publisher_initialization(self):
        """Test that progress publisher initializes properly"""
        rabbitmq = RabbitMQClient(host="localhost", port=5672)

        publisher = ProgressPublisher(rabbitmq=rabbitmq)

        assert publisher.rabbitmq == rabbitmq


@pytest.mark.asyncio
class TestProgressEvents:
    """Test publishing different progress event types"""

    async def test_publish_started_event(self):
        """Test publishing orchestration started event"""
        rabbitmq = RabbitMQClient(host="localhost", port=5672)
        publisher = ProgressPublisher(rabbitmq=rabbitmq)

        # Track published messages
        published_messages = []

        async def mock_publish(exchange_name, routing_key, message_body, correlation_id=None):
            published_messages.append({
                "exchange": exchange_name,
                "routing_key": routing_key,
                "message": message_body,
                "correlation_id": correlation_id
            })

        publisher.rabbitmq.publish = mock_publish

        # Publish started event
        await publisher.publish_started(
            correlation_id="test-123",
            user_request="Test request"
        )

        assert len(published_messages) == 1

        # Parse the message
        msg = ProgressUpdate.from_json(published_messages[0]["message"])
        assert msg.message_type == "progress_update"
        assert msg.correlation_id == "test-123"
        assert msg.event_type == "started"
        assert "user_request" in msg.data

    async def test_publish_reasoning_event(self):
        """Test publishing reasoning event"""
        rabbitmq = RabbitMQClient(host="localhost", port=5672)
        publisher = ProgressPublisher(rabbitmq=rabbitmq)

        published_messages = []
        async def mock_publish(exchange_name, routing_key, message_body, correlation_id=None):
            published_messages.append({"message": message_body})
        publisher.rabbitmq.publish = mock_publish

        await publisher.publish_reasoning(
            correlation_id="test-123",
            iteration=1,
            reasoning="Analyzing the request..."
        )

        msg = ProgressUpdate.from_json(published_messages[0]["message"])
        assert msg.event_type == "reasoning"
        assert msg.data["iteration"] == 1
        assert "reasoning" in msg.data

    async def test_publish_agent_called_event(self):
        """Test publishing agent called event"""
        rabbitmq = RabbitMQClient(host="localhost", port=5672)
        publisher = ProgressPublisher(rabbitmq=rabbitmq)

        published_messages = []
        async def mock_publish(exchange_name, routing_key, message_body, correlation_id=None):
            published_messages.append({"message": message_body})
        publisher.rabbitmq.publish = mock_publish

        await publisher.publish_agent_called(
            correlation_id="test-123",
            agent_name="data_sanitizer",
            tool="sanitize",
            task_id="task-456"
        )

        msg = ProgressUpdate.from_json(published_messages[0]["message"])
        assert msg.event_type == "agent_called"
        assert msg.data["agent"] == "data_sanitizer"
        assert msg.data["tool"] == "sanitize"
        assert msg.data["task_id"] == "task-456"

    async def test_publish_agent_completed_event(self):
        """Test publishing agent completed event"""
        rabbitmq = RabbitMQClient(host="localhost", port=5672)
        publisher = ProgressPublisher(rabbitmq=rabbitmq)

        published_messages = []
        async def mock_publish(exchange_name, routing_key, message_body, correlation_id=None):
            published_messages.append({"message": message_body})
        publisher.rabbitmq.publish = mock_publish

        await publisher.publish_agent_completed(
            correlation_id="test-123",
            agent_name="data_sanitizer",
            task_id="task-456",
            status="success"
        )

        msg = ProgressUpdate.from_json(published_messages[0]["message"])
        assert msg.event_type == "agent_completed"
        assert msg.data["agent"] == "data_sanitizer"
        assert msg.data["status"] == "success"

    async def test_publish_completed_event(self):
        """Test publishing orchestration completed event"""
        rabbitmq = RabbitMQClient(host="localhost", port=5672)
        publisher = ProgressPublisher(rabbitmq=rabbitmq)

        published_messages = []
        async def mock_publish(exchange_name, routing_key, message_body, correlation_id=None):
            published_messages.append({"message": message_body})
        publisher.rabbitmq.publish = mock_publish

        await publisher.publish_completed(
            correlation_id="test-123",
            status="completed",
            summary="Task completed successfully"
        )

        msg = ProgressUpdate.from_json(published_messages[0]["message"])
        assert msg.event_type == "completed"
        assert msg.data["status"] == "completed"
        assert "summary" in msg.data

    async def test_publish_error_event(self):
        """Test publishing error event"""
        rabbitmq = RabbitMQClient(host="localhost", port=5672)
        publisher = ProgressPublisher(rabbitmq=rabbitmq)

        published_messages = []
        async def mock_publish(exchange_name, routing_key, message_body, correlation_id=None):
            published_messages.append({"message": message_body})
        publisher.rabbitmq.publish = mock_publish

        await publisher.publish_error(
            correlation_id="test-123",
            error="Something went wrong",
            details={"iteration": 5}
        )

        msg = ProgressUpdate.from_json(published_messages[0]["message"])
        assert msg.event_type == "error"
        assert msg.data["error"] == "Something went wrong"
        assert msg.data["details"]["iteration"] == 5


@pytest.mark.asyncio
class TestProgressPublishing:
    """Test actual message publishing to RabbitMQ"""

    async def test_publish_to_correct_exchange(self, rabbitmq_client):
        """Test that progress updates are published to correct exchange"""
        publisher = ProgressPublisher(rabbitmq=rabbitmq_client)

        # Declare exchange and queue for testing
        await rabbitmq_client.declare_exchange("orchestrator.progress", "topic")
        await rabbitmq_client.declare_queue("test.progress.updates", durable=True)
        await rabbitmq_client.bind_queue(
            "test.progress.updates",
            "orchestrator.progress",
            "progress.*"
        )

        # Publish event
        await publisher.publish_started(
            correlation_id="test-publish-123",
            user_request="Test publishing"
        )

        # Give message time to be delivered
        await asyncio.sleep(0.5)

        # Consume and verify (simplified - would need proper consumer)
        # For now, just verify no errors occurred

    async def test_message_routing_key(self):
        """Test that messages use correct routing key"""
        rabbitmq = RabbitMQClient(host="localhost", port=5672)
        publisher = ProgressPublisher(rabbitmq=rabbitmq)

        published_messages = []
        async def mock_publish(exchange_name, routing_key, message_body, correlation_id=None):
            published_messages.append({
                "exchange": exchange_name,
                "routing_key": routing_key
            })
        publisher.rabbitmq.publish = mock_publish

        await publisher.publish_started("test-123", "Test")

        # Verify routing key format
        assert published_messages[0]["routing_key"] == "progress.started"
        assert published_messages[0]["exchange"] == "orchestrator.progress"


@pytest.mark.asyncio
class TestProgressPublisherIntegration:
    """Test progress publisher integration with other components"""

    async def test_correlation_id_propagation(self):
        """Test that correlation_id is properly propagated"""
        rabbitmq = RabbitMQClient(host="localhost", port=5672)
        publisher = ProgressPublisher(rabbitmq=rabbitmq)

        correlation_id = "integration-test-456"

        published_messages = []
        async def mock_publish(exchange_name, routing_key, message_body, correlation_id=None):
            published_messages.append({"correlation_id": correlation_id})
        publisher.rabbitmq.publish = mock_publish

        await publisher.publish_started(correlation_id, "Test")
        await publisher.publish_reasoning(correlation_id, 1, "Thinking...")
        await publisher.publish_completed(correlation_id, "completed", "Done")

        # All messages should have same correlation_id
        assert all(
            msg["correlation_id"] == correlation_id
            for msg in published_messages
        )

    async def test_progress_event_sequence(self):
        """Test publishing a sequence of progress events"""
        rabbitmq = RabbitMQClient(host="localhost", port=5672)
        publisher = ProgressPublisher(rabbitmq=rabbitmq)

        published_messages = []
        async def mock_publish(exchange_name, routing_key, message_body, correlation_id=None):
            msg = ProgressUpdate.from_json(message_body)
            published_messages.append(msg.event_type)
        publisher.rabbitmq.publish = mock_publish

        # Simulate orchestration flow
        await publisher.publish_started("test-123", "Process logs")
        await publisher.publish_reasoning("test-123", 1, "Need to sanitize")
        await publisher.publish_agent_called("test-123", "data_sanitizer", "sanitize", "task-1")
        await publisher.publish_agent_completed("test-123", "data_sanitizer", "task-1", "success")
        await publisher.publish_completed("test-123", "completed", "Done")

        # Verify event sequence
        expected_sequence = [
            "started",
            "reasoning",
            "agent_called",
            "agent_completed",
            "completed"
        ]
        assert published_messages == expected_sequence
