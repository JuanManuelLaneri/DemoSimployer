"""
Project Chimera - Test Fixtures

Provides testcontainers and shared fixtures for integration testing.
NO MOCKS - Real RabbitMQ, real LLM calls.

HYBRID MODE: Supports both testcontainers (automatic) and external RabbitMQ (manual).
- Linux/Mac: Uses testcontainers automatically
- Windows: Can use external RabbitMQ by setting RABBITMQ_HOST environment variable
"""

import pytest
import asyncio
import os
import sys
import platform
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load .env file for tests
load_dotenv(project_root / ".env")

from agents.shared.messaging import RabbitMQClient
from agents.shared.llm_client import LLMClient


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def rabbitmq_connection_info():
    """
    Provides RabbitMQ connection information.

    HYBRID MODE:
    - If RABBITMQ_HOST is set: Uses external RabbitMQ (e.g., docker-compose)
    - Otherwise: Uses testcontainers (automatic isolation)

    This solves the Windows testcontainers networking issue while maintaining
    automatic testing on Linux/Mac.

    Usage on Windows:
        1. Start RabbitMQ: docker-compose up rabbitmq
        2. Set environment: set RABBITMQ_HOST=localhost (PowerShell: $env:RABBITMQ_HOST="localhost")
        3. Run tests: pytest tests/integration/ -v

    Usage on Linux/Mac:
        1. Run tests: pytest tests/integration/ -v
        (testcontainers starts RabbitMQ automatically)
    """
    external_host = os.getenv("RABBITMQ_HOST")

    if external_host:
        # Use external RabbitMQ (docker-compose or manual)
        print(f"\n[TEST FIXTURE] Using external RabbitMQ at {external_host}")
        connection_info = {
            "host": external_host,
            "port": int(os.getenv("RABBITMQ_PORT", "5672")),
            "user": os.getenv("RABBITMQ_USER", "guest"),
            "password": os.getenv("RABBITMQ_PASS", "guest"),
            "source": "external"
        }
        yield connection_info
    else:
        # Use testcontainers (automatic)
        print(f"\n[TEST FIXTURE] Using testcontainers for RabbitMQ (platform: {platform.system()})")

        try:
            from testcontainers.rabbitmq import RabbitMqContainer
        except ImportError:
            pytest.skip("testcontainers not available and RABBITMQ_HOST not set")

        with RabbitMqContainer("rabbitmq:3.12-management") as rabbitmq:
            # Wait for RabbitMQ to be ready
            connection_url = rabbitmq.get_connection_url()

            # Parse connection URL
            # Format: amqp://guest:guest@localhost:port
            parts = connection_url.replace("amqp://", "").split("@")
            auth = parts[0].split(":")
            host_port = parts[1].split(":")

            connection_info = {
                "host": host_port[0],
                "port": int(host_port[1]),
                "user": auth[0],
                "password": auth[1],
                "source": "testcontainers"
            }

            print(f"[TEST FIXTURE] Testcontainers RabbitMQ ready at {connection_info['host']}:{connection_info['port']}")
            yield connection_info


@pytest.fixture(scope="session")
def rabbitmq_container(rabbitmq_connection_info):
    """
    DEPRECATED: Use rabbitmq_connection_info instead.

    This fixture is maintained for backwards compatibility.
    Returns a mock object with get_connection_url() method.
    """
    class MockContainer:
        def __init__(self, connection_info):
            self.connection_info = connection_info

        def get_connection_url(self):
            return f"amqp://{self.connection_info['user']}:{self.connection_info['password']}@{self.connection_info['host']}:{self.connection_info['port']}"

    return MockContainer(rabbitmq_connection_info)


@pytest.fixture
async def rabbitmq_client(rabbitmq_connection_info):
    """
    Create a RabbitMQ client connected to RabbitMQ.

    Works with both testcontainers and external RabbitMQ.
    """
    client = RabbitMQClient(
        host=rabbitmq_connection_info["host"],
        port=rabbitmq_connection_info["port"],
        user=rabbitmq_connection_info["user"],
        password=rabbitmq_connection_info["password"]
    )

    await client.connect()
    await client.setup_project_topology()

    yield client

    await client.disconnect()


@pytest.fixture
def llm_client():
    """
    Create an LLM client for testing.
    Uses real API if DEEPSEEK_API_KEY is set.
    """
    api_key = os.getenv("DEEPSEEK_API_KEY")

    if not api_key:
        pytest.skip("DEEPSEEK_API_KEY not set - skipping LLM test")

    return LLMClient(api_key=api_key)


@pytest.fixture
def sample_log_data():
    """Sample log entries for testing"""
    return [
        {
            "timestamp": "2025-01-08T10:15:23.456Z",
            "level": "ERROR",
            "component": "authentication-service",
            "message": "Login failed for user john.doe@example.com from IP 192.168.1.45",
            "metadata": {"request_id": "req-001", "attempt_count": 3}
        },
        {
            "timestamp": "2025-01-08T10:16:01.123Z",
            "level": "CRITICAL",
            "component": "database-connector",
            "message": "Database connection timeout to server db.internal.local:5432",
            "metadata": {"request_id": "req-002", "duration_ms": 30000}
        },
        {
            "timestamp": "2025-01-08T10:16:15.789Z",
            "level": "WARNING",
            "component": "api-gateway",
            "message": "Rate limit approaching for client 10.0.0.100: 450/500 requests",
            "metadata": {"request_id": "req-003", "client_ip": "10.0.0.100"}
        }
    ]
