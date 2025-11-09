"""
Message Handlers - Process registration, discovery, and task results

Handles incoming messages from RabbitMQ and coordinates with the registry.
"""

import asyncio
import sys
from pathlib import Path
from typing import Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agents.shared.messaging import RabbitMQClient
from agents.shared.schemas import (
    RegistrationMessage,
    DiscoveryQuery,
    DiscoveryResponse,
    ResultMessage
)
from orchestrator.registry import AgentRegistry


class RegistrationHandler:
    """
    Handles agent registration and service discovery.

    Listens to registration messages from agents and updates the registry.
    Responds to service discovery queries.
    """

    def __init__(self, registry: AgentRegistry, rabbitmq: RabbitMQClient):
        """
        Initialize registration handler.

        Args:
            registry: AgentRegistry instance
            rabbitmq: RabbitMQ client for message handling
        """
        self.registry = registry
        self.rabbitmq = rabbitmq

    async def handle_registration(self, registration: RegistrationMessage) -> None:
        """
        Process an agent registration message.

        Args:
            registration: RegistrationMessage from agent

        Updates the registry with agent information.
        """
        self.registry.register(registration)
        print(f"[REGISTRY] Agent registered: {registration.agent_name}")
        print(f"           Capabilities: {registration.capabilities}")
        print(f"           Queue: {registration.queue_name}")

    async def handle_discovery(self, query: DiscoveryQuery) -> DiscoveryResponse:
        """
        Process a service discovery query.

        Args:
            query: DiscoveryQuery message

        Returns:
            DiscoveryResponse with matching agents
        """
        agents = []

        if query.query_type == "agent_name":
            # Find specific agent by name
            agent_info = self.registry.get_agent(query.query_value)
            if agent_info:
                agents = [agent_info]

        elif query.query_type == "capability":
            # Find agents by capability
            agents = self.registry.find_by_capability(query.query_value)

        elif query.query_type == "all":
            # Return all active agents
            agents = self.registry.get_active_agents()

        response = DiscoveryResponse(
            message_type="discovery_response",
            query_id=query.message_id,
            agents=agents,
            total_count=len(agents)
        )

        return response

    async def start_consuming(self, queue_name: str) -> None:
        """
        Start consuming registration messages from a queue.

        Args:
            queue_name: Name of queue to consume from

        Runs indefinitely until cancelled.
        """
        async def message_handler(message):
            async with message.process():
                body = message.body.decode()
                registration = RegistrationMessage.from_json(body)
                await self.handle_registration(registration)

        await self.rabbitmq.consume(queue_name, message_handler)

        # Keep consuming
        while True:
            await asyncio.sleep(1)

    async def start_discovery_responder(self, queue_name: str) -> None:
        """
        Start responding to discovery queries.

        Args:
            queue_name: Name of queue to consume discovery queries from

        Runs indefinitely until cancelled.
        """
        async def message_handler(message):
            async with message.process():
                body = message.body.decode()
                query = DiscoveryQuery.from_json(body)
                response = await self.handle_discovery(query)

                # Send response to reply_to queue
                if message.reply_to:
                    await self.rabbitmq.publish(
                        exchange_name="",  # Default exchange for direct queue routing
                        routing_key=message.reply_to,
                        message_body=response.to_json(),
                        correlation_id=message.correlation_id
                    )

        await self.rabbitmq.consume(queue_name, message_handler)

        # Keep consuming
        while True:
            await asyncio.sleep(1)


class TaskResultHandler:
    """
    Handles task result messages from agents.

    Collects results and notifies the orchestrator's ReAct loop.
    """

    def __init__(self, rabbitmq: RabbitMQClient):
        """
        Initialize task result handler.

        Args:
            rabbitmq: RabbitMQ client for message handling
        """
        self.rabbitmq = rabbitmq
        self.pending_results = {}  # task_id -> asyncio.Future
        self._lock = asyncio.Lock()

    async def register_task(self, task_id: str) -> None:
        """
        Register a task and create its future immediately.

        This prevents race conditions where results arrive before wait_for_result is called.

        Args:
            task_id: Task ID to register
        """
        async with self._lock:
            if task_id not in self.pending_results:
                self.pending_results[task_id] = asyncio.Future()
                print(f"[RESULT] Registered task {task_id}, ready to receive result")

    async def wait_for_result(
        self, correlation_id: str, timeout: float = 120.0
    ) -> Optional[ResultMessage]:
        """
        Wait for a task result with specific task ID.

        Args:
            correlation_id: Task ID to wait for (named correlation_id for backwards compatibility)
            timeout: Maximum time to wait in seconds

        Returns:
            ResultMessage if received, None if timeout

        Raises:
            asyncio.TimeoutError: If result not received within timeout
        """
        task_id = correlation_id  # Parameter name kept for backwards compatibility

        # Get existing future (should already exist from register_task)
        async with self._lock:
            if task_id not in self.pending_results:
                # Shouldn't happen if register_task was called, but create one just in case
                print(f"[RESULT] Warning: Task {task_id} not pre-registered, creating future now")
                self.pending_results[task_id] = asyncio.Future()
            future = self.pending_results[task_id]

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            # Clean up after successful result
            async with self._lock:
                if task_id in self.pending_results:
                    del self.pending_results[task_id]
            return result
        except asyncio.TimeoutError:
            async with self._lock:
                if task_id in self.pending_results:
                    del self.pending_results[task_id]
            raise

    async def handle_result(self, result: ResultMessage) -> None:
        """
        Process a task result message.

        Args:
            result: ResultMessage from agent

        Resolves any waiting futures for this task ID.
        """
        print(f"[RESULT] Task result received: {result.task_id}")
        print(f"         Correlation ID: {result.correlation_id}")
        print(f"         Status: {result.status}")
        if result.error:
            print(f"         Error: {result.error}")

        async with self._lock:
            # Index by task_id, not correlation_id
            if result.task_id in self.pending_results:
                future = self.pending_results[result.task_id]
                if not future.done():
                    future.set_result(result)
                # Don't delete here - let wait_for_result() handle cleanup
                # This prevents race condition where result arrives before wait_for_result() is called
            else:
                print(f"[RESULT] Warning: No pending future for task_id {result.task_id}")

    async def start_consuming(self, queue_name: str) -> None:
        """
        Start consuming task result messages from a queue.

        Args:
            queue_name: Name of queue to consume from

        Runs indefinitely until cancelled.
        """
        async def message_handler(message):
            async with message.process():
                body = message.body.decode()
                result = ResultMessage.from_json(body)
                await self.handle_result(result)

        await self.rabbitmq.consume(queue_name, message_handler)

        # Keep consuming
        while True:
            await asyncio.sleep(1)
