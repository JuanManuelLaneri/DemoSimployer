"""
Manual test to verify RabbitMQ messaging works with docker-compose RabbitMQ.
Run this after: docker-compose up -d rabbitmq
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agents.shared.messaging import RabbitMQClient
from agents.shared.schemas import TaskMessage


async def test_messaging():
    """Test basic RabbitMQ messaging functionality"""
    print("[TEST] Connecting to RabbitMQ...")

    # Connect to docker-compose RabbitMQ
    client = RabbitMQClient(host="localhost", port=5672)
    await client.connect()
    await client.setup_project_topology()

    print("[PASS] Connected successfully!")
    print(f"       Exchanges created: {list(client.exchanges.keys())}")

    # Test creating a queue
    print("\n[TEST] Creating test queue...")
    await client.declare_queue("test.manual.queue", durable=True)
    print("[PASS] Queue created!")

    # Test binding to exchange
    print("\n[TEST] Binding queue to exchange...")
    await client.bind_queue(
        "test.manual.queue",
        "agent.tasks",
        "test.manual.*"
    )
    print("[PASS] Queue bound!")

    # Test publishing a message
    print("\n[TEST] Publishing test message...")
    test_msg = TaskMessage(
        message_type="task",
        correlation_id="test-manual-123",
        sender="manual_test",
        recipient="test_agent",
        tool="test_tool",
        input={"test": "data"},
        reply_to="test.reply"
    )

    await client.publish(
        exchange_name="agent.tasks",
        routing_key="test.manual.task",
        message_body=test_msg.to_json(),
        correlation_id=test_msg.correlation_id
    )
    print("[PASS] Message published!")

    # Test consuming a message
    print("\n[TEST] Setting up consumer...")
    received_messages = []

    async def message_handler(message):
        async with message.process():
            body = message.body.decode()
            msg = TaskMessage.from_json(body)
            received_messages.append(msg)
            print(f"[PASS] Received message: correlation_id={msg.correlation_id}")

    await client.consume("test.manual.queue", message_handler)

    # Wait a bit for message to be consumed
    print("[WAIT] Waiting for message to be consumed...")
    await asyncio.sleep(2)

    # Verify
    if received_messages:
        print(f"\n[SUCCESS] Received {len(received_messages)} message(s)")
        print(f"          Correlation ID: {received_messages[0].correlation_id}")
        print(f"          Tool: {received_messages[0].tool}")
        print(f"          Input: {received_messages[0].input}")
    else:
        print("\n[FAILED] No messages received")
        return False

    # Cleanup
    await client.disconnect()
    print("\n[PASS] Disconnected from RabbitMQ")
    print("\n[SUCCESS] All messaging tests passed!")
    return True


if __name__ == "__main__":
    try:
        result = asyncio.run(test_messaging())
        sys.exit(0 if result else 1)
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
