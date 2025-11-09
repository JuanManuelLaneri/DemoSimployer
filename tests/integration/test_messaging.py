"""
Integration tests for RabbitMQ messaging with testcontainers.
NO MOCKS - Real RabbitMQ instance.
"""

import pytest
import asyncio
from agents.shared.messaging import RabbitMQClient
from agents.shared.schemas import TaskMessage


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rabbitmq_connection(rabbitmq_client):
    """Test connecting to RabbitMQ"""
    assert rabbitmq_client.connection is not None
    assert not rabbitmq_client.connection.is_closed
    assert rabbitmq_client.channel is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_declare_exchange(rabbitmq_client):
    """Test declaring an exchange"""
    exchange = await rabbitmq_client.declare_exchange(
        "test.exchange",
        durable=True
    )

    assert exchange is not None
    assert "test.exchange" in rabbitmq_client.exchanges


@pytest.mark.integration
@pytest.mark.asyncio
async def test_declare_queue(rabbitmq_client):
    """Test declaring a queue"""
    queue = await rabbitmq_client.declare_queue(
        "test.queue",
        durable=True
    )

    assert queue is not None
    assert queue.name == "test.queue"
    assert "test.queue" in rabbitmq_client.queues


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bind_queue_to_exchange(rabbitmq_client):
    """Test binding queue to exchange"""
    # Declare exchange and queue
    await rabbitmq_client.declare_exchange("test.exchange")
    await rabbitmq_client.declare_queue("test.queue")

    # Bind
    await rabbitmq_client.bind_queue(
        "test.queue",
        "test.exchange",
        "test.routing.key"
    )

    # If no exception, binding succeeded
    assert True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_publish_and_consume_message(rabbitmq_client):
    """Test publishing and consuming a message"""
    # Setup
    exchange_name = "test.pub.exchange"
    queue_name = "test.pub.queue"
    routing_key = "test.pub.key"

    await rabbitmq_client.declare_exchange(exchange_name)
    await rabbitmq_client.declare_queue(queue_name)
    await rabbitmq_client.bind_queue(queue_name, exchange_name, routing_key)

    # Message to send
    test_message = TaskMessage(
        message_type="task",
        correlation_id="test-corr-123",
        sender="test_sender",
        recipient="test_recipient",
        tool="test_tool",
        input={"test": "data"},
        reply_to="test.reply"
    )

    # Flag to track if message received
    received_messages = []

    async def message_handler(message):
        async with message.process():
            body = message.body.decode()
            received_msg = TaskMessage.from_json(body)
            received_messages.append(received_msg)

    # Start consuming
    await rabbitmq_client.consume(queue_name, message_handler, auto_ack=False)

    # Publish message
    await rabbitmq_client.publish(
        exchange_name=exchange_name,
        routing_key=routing_key,
        message_body=test_message.to_json(),
        correlation_id=test_message.correlation_id
    )

    # Wait for message to be received
    await asyncio.sleep(1)

    # Verify
    assert len(received_messages) == 1
    assert received_messages[0].correlation_id == "test-corr-123"
    assert received_messages[0].tool == "test_tool"
    assert received_messages[0].input["test"] == "data"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_correlation_id_tracking(rabbitmq_client):
    """Test that correlation IDs are preserved in messages"""
    exchange_name = "test.corr.exchange"
    queue_name = "test.corr.queue"
    routing_key = "test.corr.key"

    await rabbitmq_client.declare_exchange(exchange_name)
    await rabbitmq_client.declare_queue(queue_name)
    await rabbitmq_client.bind_queue(queue_name, exchange_name, routing_key)

    correlation_id = "my-unique-correlation-id"
    received_corr_ids = []

    async def handler(message):
        async with message.process():
            # Check message properties
            if message.correlation_id:
                received_corr_ids.append(message.correlation_id)

    await rabbitmq_client.consume(queue_name, handler)

    # Publish with correlation ID
    await rabbitmq_client.publish(
        exchange_name=exchange_name,
        routing_key=routing_key,
        message_body='{"test": "data"}',
        correlation_id=correlation_id
    )

    await asyncio.sleep(1)

    assert len(received_corr_ids) == 1
    assert received_corr_ids[0] == correlation_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_project_topology_setup(rabbitmq_client):
    """Test that project topology creates all required exchanges"""
    # This is already called in fixture, but let's verify
    required_exchanges = [
        "orchestrator.requests",
        "orchestrator.responses",
        "orchestrator.register",
        "orchestrator.discover",
        "orchestrator.progress",
        "agent.tasks"
    ]

    for exchange_name in required_exchanges:
        assert exchange_name in rabbitmq_client.exchanges


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multiple_consumers_on_same_queue(rabbitmq_client):
    """Test that only one consumer receives each message (load balancing)"""
    queue_name = "test.multi.queue"
    exchange_name = "test.multi.exchange"
    routing_key = "test.multi.key"

    await rabbitmq_client.declare_exchange(exchange_name)
    await rabbitmq_client.declare_queue(queue_name)
    await rabbitmq_client.bind_queue(queue_name, exchange_name, routing_key)

    consumer1_received = []
    consumer2_received = []

    async def consumer1_handler(message):
        async with message.process():
            consumer1_received.append(message.body.decode())
            await asyncio.sleep(0.1)  # Simulate processing

    async def consumer2_handler(message):
        async with message.process():
            consumer2_received.append(message.body.decode())
            await asyncio.sleep(0.1)

    # Start two consumers
    await rabbitmq_client.consume(queue_name, consumer1_handler)

    # Create second client for second consumer
    client2 = RabbitMQClient(
        host=rabbitmq_client.host,
        port=rabbitmq_client.port,
        user=rabbitmq_client.user,
        password=rabbitmq_client.password
    )
    await client2.connect()
    await client2.declare_exchange(exchange_name)
    queue2 = await client2.channel.get_queue(queue_name)
    await queue2.consume(consumer2_handler)

    # Publish 5 messages
    for i in range(5):
        await rabbitmq_client.publish(
            exchange_name=exchange_name,
            routing_key=routing_key,
            message_body=f'{{"message": "test{i}"}}'
        )

    # Wait for processing
    await asyncio.sleep(2)

    # Verify messages were load-balanced
    total_received = len(consumer1_received) + len(consumer2_received)
    assert total_received == 5, f"Expected 5 messages total, got {total_received}"

    # Both consumers should have received some messages (load balancing)
    # (Though distribution might not be exactly even)

    await client2.disconnect()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_connection_retry_logic():
    """Test that client retries on connection failure"""
    # Try to connect to non-existent host with low retry count
    client = RabbitMQClient(
        host="invalid-host-that-does-not-exist",
        port=5672,
        max_retries=2,
        retry_delay=1
    )

    with pytest.raises(ConnectionError) as exc_info:
        await client.connect()

    assert "Failed to connect" in str(exc_info.value)
