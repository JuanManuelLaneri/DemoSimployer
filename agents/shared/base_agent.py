"""
Project Chimera - Base Agent Class

Abstract base class for all autonomous agents.
"""

import asyncio
import logging
import json
import time
import os
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from datetime import datetime

from .messaging import RabbitMQClient
from .llm_client import LLMClient
from .file_logger import setup_file_logger
from .schemas import (
    RegistrationMessage,
    RegistrationAckMessage,
    TaskMessage,
    ResultMessage,
    ExecutionDetails,
    DiscoveryQuery,
    DiscoveryResponse,
    AgentCapabilities,
    ToolSchema
)

# Default logger (will be replaced by agent-specific logger)
logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """
    Abstract base class for all Project Chimera agents.

    Provides:
    - RabbitMQ connection and messaging
    - Self-registration with orchestrator
    - Task listening and handling
    - LLM integration
    - Service discovery for calling other agents
    """

    def __init__(
        self,
        agent_name: str,
        agent_version: str = "1.0.0"
    ):
        """
        Initialize base agent.

        Args:
            agent_name: Unique agent identifier
            agent_version: Agent version
        """
        self.agent_name = agent_name
        self.agent_version = agent_version

        # Set up file logging for this agent
        log_level = os.getenv("LOG_LEVEL", "INFO")
        self.logger = setup_file_logger(agent_name, log_level=log_level)

        # Messaging
        self.rabbitmq: Optional[RabbitMQClient] = None
        self.inbox_queue_name = f"{agent_name}.inbox"
        self.reply_queue_name = f"replies.{agent_name}"

        # LLM
        self.llm: Optional[LLMClient] = None

        # Registration status
        self.registered = False

        self.logger.info(f"Agent '{agent_name}' initialized (version: {agent_version})")
        print(f"[{agent_name.upper()}] Agent initialized (version: {agent_version})")

    @abstractmethod
    def get_capabilities(self) -> AgentCapabilities:
        """
        Define agent capabilities and tools.
        Must be implemented by subclasses.

        Returns:
            AgentCapabilities object
        """
        pass

    @abstractmethod
    async def handle_task(self, task: TaskMessage) -> Dict[str, Any]:
        """
        Handle a task assigned to this agent.
        Must be implemented by subclasses.

        Args:
            task: TaskMessage to process

        Returns:
            Dict containing task results
        """
        pass

    async def initialize(self) -> None:
        """
        Initialize agent: connect to RabbitMQ, set up LLM client, register.
        """
        self.logger.info(f"Initializing agent '{self.agent_name}'...")
        print(f"[{self.agent_name.upper()}] Initializing...")

        # Initialize LLM client
        self.llm = LLMClient()

        # Connect to RabbitMQ
        self.rabbitmq = RabbitMQClient()
        await self.rabbitmq.connect()
        await self.rabbitmq.setup_project_topology()

        # Declare agent queues
        await self.rabbitmq.declare_queue(self.inbox_queue_name, durable=True)
        await self.rabbitmq.declare_queue(self.reply_queue_name, durable=True)

        # Bind inbox to agent.tasks exchange
        await self.rabbitmq.bind_queue(
            self.inbox_queue_name,
            "agent.tasks",
            f"{self.agent_name}.*"
        )

        # Register with orchestrator
        await self.register()

        self.logger.info(f"Agent '{self.agent_name}' initialized successfully")
        print(f"[{self.agent_name.upper()}] Initialized successfully")

    async def register(self) -> None:
        """
        Self-register with the orchestrator.
        """
        self.logger.info(f"Registering agent '{self.agent_name}' with orchestrator...")
        print(f"[{self.agent_name.upper()}] Registering with orchestrator...")

        capabilities = self.get_capabilities()

        registration_msg = RegistrationMessage(
            message_type="registration",
            agent_name=self.agent_name,
            agent_version=self.agent_version,
            capabilities=capabilities,
            queue_name=self.inbox_queue_name,
            reply_queue_name=self.reply_queue_name,
            status="ready"
        )

        # Publish registration
        await self.rabbitmq.publish(
            exchange_name="orchestrator.register",
            routing_key=f"register.{self.agent_name}",
            message_body=registration_msg.to_json()
        )

        self.registered = True
        self.logger.info(f"Agent '{self.agent_name}' registration sent")
        print(f"[{self.agent_name.upper()}] Registration sent")

    async def discover_agent(self, target_agent: str) -> Optional[Dict[str, Any]]:
        """
        Discover another agent's information via orchestrator.

        Args:
            target_agent: Name of agent to find

        Returns:
            Agent info dict or None if not found
        """
        logger.info(f"Discovering agent '{target_agent}'...")

        query = DiscoveryQuery(
            message_type="discovery_query",
            correlation_id=f"disc-{self.agent_name}-{int(time.time())}",
            requester=self.agent_name,
            target_agent=target_agent,
            reply_to=self.reply_queue_name
        )

        # Create a future to wait for response
        response_future = asyncio.Future()

        # Temporary handler for discovery response
        async def handle_discovery_response(message):
            async with message.process():
                try:
                    response = DiscoveryResponse.from_json(message.body.decode())
                    if response.query_id == query.query_id:
                        if not response_future.done():
                            response_future.set_result(response)
                except Exception as e:
                    logger.error(f"Error processing discovery response: {e}")
                    if not response_future.done():
                        response_future.set_exception(e)

        # Temporarily consume from reply queue
        consumer_tag = await self.rabbitmq.consume(
            self.reply_queue_name,
            handle_discovery_response
        )

        try:
            # Publish discovery query
            await self.rabbitmq.publish(
                exchange_name="orchestrator.discover",
                routing_key=f"discover.{target_agent}",
                message_body=query.to_json(),
                correlation_id=query.correlation_id,
                reply_to=self.reply_queue_name
            )

            # Wait for response (with timeout)
            response = await asyncio.wait_for(response_future, timeout=10)

            if response.found:
                logger.info(f"Found agent '{target_agent}': {response.agent_info}")
                return response.agent_info.model_dump()
            else:
                logger.warning(f"Agent '{target_agent}' not found")
                return None

        except asyncio.TimeoutError:
            logger.error(f"Timeout waiting for discovery response for '{target_agent}'")
            return None

    async def call_agent(
        self,
        target_agent: str,
        tool: str,
        input_data: Dict[str, Any],
        correlation_id: str,
        timeout: int = 120
    ) -> Optional[Dict[str, Any]]:
        """
        Call another agent directly (agent-to-agent communication).

        Args:
            target_agent: Name of agent to call
            tool: Tool/function to invoke on target agent
            input_data: Input parameters for the tool
            correlation_id: Correlation ID for tracking
            timeout: Timeout in seconds

        Returns:
            Result from target agent or None if failed
        """
        logger.info(f"Calling agent '{target_agent}' tool '{tool}'...")

        # Discover target agent
        agent_info = await self.discover_agent(target_agent)
        if not agent_info:
            logger.error(f"Cannot call agent '{target_agent}' - not found")
            return None

        # Create task message
        task = TaskMessage(
            message_type="task",
            correlation_id=correlation_id,
            sender=self.agent_name,
            recipient=target_agent,
            tool=tool,
            input=input_data,
            reply_to=self.reply_queue_name,
            timeout_seconds=timeout
        )

        # Create future for response
        response_future = asyncio.Future()

        # Handler for task result
        async def handle_task_result(message):
            async with message.process():
                try:
                    result = ResultMessage.from_json(message.body.decode())
                    if result.task_id == task.task_id:
                        if not response_future.done():
                            response_future.set_result(result)
                except Exception as e:
                    logger.error(f"Error processing task result: {e}")
                    if not response_future.done():
                        response_future.set_exception(e)

        # Consume from reply queue
        consumer_tag = await self.rabbitmq.consume(
            self.reply_queue_name,
            handle_task_result
        )

        try:
            # Publish task
            await self.rabbitmq.publish(
                exchange_name="agent.tasks",
                routing_key=f"{target_agent}.{tool}",
                message_body=task.to_json(),
                correlation_id=correlation_id,
                reply_to=self.reply_queue_name
            )

            # Wait for result
            result = await asyncio.wait_for(response_future, timeout=timeout)

            if result.status == "success":
                logger.info(f"Successfully received result from '{target_agent}'")
                return result.result
            else:
                logger.error(f"Agent '{target_agent}' returned error: {result.error}")
                return None

        except asyncio.TimeoutError:
            logger.error(f"Timeout waiting for result from '{target_agent}'")
            return None

    async def _handle_incoming_message(self, message) -> None:
        """
        Internal handler for incoming task messages.

        Args:
            message: RabbitMQ message
        """
        async with message.process():
            start_time = time.time()

            try:
                # Parse task
                task = TaskMessage.from_json(message.body.decode())
                self.logger.info(f"Received task: {task.tool} (task_id: {task.task_id})")
                print(f"[{self.agent_name.upper()}] Received task: {task.tool} (task_id: {task.task_id})")

                # Handle task (implemented by subclass)
                result = await self.handle_task(task)

                duration_ms = (time.time() - start_time) * 1000

                self.logger.info(f"Task handler completed, creating result message...")
                print(f"[{self.agent_name.upper()}] Task handler completed, creating result message...")

                # Create success result
                result_msg = ResultMessage(
                    message_type="result",
                    correlation_id=task.correlation_id,
                    task_id=task.task_id,
                    status="success",
                    result=result,
                    execution_details=ExecutionDetails(
                        agent_name=self.agent_name,
                        duration_ms=duration_ms,
                        called_agents=result.get("called_agents", []),
                        llm_calls=result.get("llm_calls", 0),
                        llm_model=self.llm.model if self.llm else None,
                        reasoning=result.get("reasoning", None)
                    )
                )

                self.logger.info(f"Publishing result for task {task.task_id}...")
                print(f"[{self.agent_name.upper()}] Publishing result for task {task.task_id}...")

                # Check if this is agent-to-agent communication
                # If sender is an agent (not orchestrator), publish directly to reply_to queue
                is_agent_to_agent = task.sender and task.sender != "orchestrator"

                if is_agent_to_agent and task.reply_to:
                    # Direct agent-to-agent communication: publish to reply_to queue
                    self.logger.info(f"Sending result directly to {task.sender} via {task.reply_to}")
                    print(f"[{self.agent_name.upper()}] Sending result directly to {task.sender} via {task.reply_to}")
                    await self.rabbitmq.publish(
                        exchange_name="",  # Default exchange for direct routing
                        routing_key=task.reply_to,
                        message_body=result_msg.to_json(),
                        correlation_id=task.correlation_id,
                        reply_to=self.inbox_queue_name
                    )
                else:
                    # Orchestrator-mediated communication: publish to orchestrator.responses exchange
                    await self.rabbitmq.publish(
                        exchange_name="orchestrator.responses",
                        routing_key=f"result.{self.agent_name}",
                        message_body=result_msg.to_json(),
                        correlation_id=task.correlation_id,
                        reply_to=task.reply_to
                    )

                self.logger.info(f"Task {task.task_id} completed successfully ({duration_ms:.0f}ms)")
                print(f"[{self.agent_name.upper()}] Task {task.task_id} completed successfully ({duration_ms:.0f}ms)")

            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                self.logger.error(f"Error handling task: {e}", exc_info=True)
                print(f"[{self.agent_name.upper()}] ERROR handling task: {e}")
                import traceback
                traceback.print_exc()

                try:
                    task = TaskMessage.from_json(message.body.decode())

                    error_result = ResultMessage(
                        message_type="result",
                        correlation_id=task.correlation_id,
                        task_id=task.task_id,
                        status="error",
                        error=str(e),
                        execution_details=ExecutionDetails(
                            agent_name=self.agent_name,
                            duration_ms=duration_ms,
                            called_agents=[],
                            llm_calls=0
                        )
                    )

                    await self.rabbitmq.publish(
                        exchange_name="orchestrator.responses",
                        routing_key=f"result.{self.agent_name}",
                        message_body=error_result.to_json(),
                        correlation_id=task.correlation_id,
                        reply_to=task.reply_to
                    )

                except Exception as inner_e:
                    self.logger.error(f"Failed to send error result: {inner_e}")

    async def start(self) -> None:
        """
        Start the agent: initialize and begin listening for tasks.
        """
        await self.initialize()

        self.logger.info(f"Agent '{self.agent_name}' starting to listen for tasks...")
        print(f"[{self.agent_name.upper()}] Starting to listen for tasks...")

        # Start consuming from inbox
        await self.rabbitmq.consume(
            self.inbox_queue_name,
            self._handle_incoming_message
        )

        self.logger.info(f"Agent '{self.agent_name}' is running")
        print(f"[{self.agent_name.upper()}] Agent is running")

        # Keep running
        try:
            await asyncio.Future()  # Run forever
        except KeyboardInterrupt:
            self.logger.info(f"Agent '{self.agent_name}' shutting down...")
            print(f"[{self.agent_name.upper()}] Shutting down...")
        finally:
            await self.rabbitmq.disconnect()

    async def stop(self) -> None:
        """Stop the agent and cleanup resources."""
        if self.rabbitmq:
            await self.rabbitmq.disconnect()
        self.logger.info(f"Agent '{self.agent_name}' stopped")
        print(f"[{self.agent_name.upper()}] Stopped")
