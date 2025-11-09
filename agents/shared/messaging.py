"""
Project Chimera - RabbitMQ Messaging Utilities

Handles all RabbitMQ connections, publishing, and consuming.
"""

import os
import asyncio
import logging
from typing import Optional, Callable, Dict, Any
import aio_pika
from aio_pika import connect_robust, Message, ExchangeType
from aio_pika.abc import AbstractConnection, AbstractChannel, AbstractExchange, AbstractQueue

logger = logging.getLogger(__name__)


class RabbitMQClient:
    """
    Async RabbitMQ client for Project Chimera.
    Handles connections, exchanges, queues, and message routing.
    """

    def __init__(
        self,
        host: str = None,
        port: int = None,
        user: str = None,
        password: str = None,
        vhost: str = None,
        max_retries: int = 5,
        retry_delay: int = 5
    ):
        """
        Initialize RabbitMQ client.

        Args:
            host: RabbitMQ host (defaults to RABBITMQ_HOST env var)
            port: RabbitMQ port (defaults to RABBITMQ_PORT env var)
            user: Username (defaults to RABBITMQ_USER env var)
            password: Password (defaults to RABBITMQ_PASSWORD env var)
            vhost: Virtual host (defaults to RABBITMQ_VHOST env var)
            max_retries: Maximum connection retry attempts
            retry_delay: Delay between retries in seconds
        """
        self.host = host or os.getenv("RABBITMQ_HOST", "localhost")
        self.port = port or int(os.getenv("RABBITMQ_PORT", "5672"))
        self.user = user or os.getenv("RABBITMQ_USER", "guest")
        self.password = password or os.getenv("RABBITMQ_PASSWORD", "guest")
        self.vhost = vhost or os.getenv("RABBITMQ_VHOST", "/")
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        self.connection: Optional[AbstractConnection] = None
        self.channel: Optional[AbstractChannel] = None
        self.exchanges: Dict[str, AbstractExchange] = {}
        self.queues: Dict[str, AbstractQueue] = {}

        logger.info(f"RabbitMQ Client initialized: {self.host}:{self.port}")

    @property
    def connection_url(self) -> str:
        """Get RabbitMQ connection URL"""
        return f"amqp://{self.user}:{self.password}@{self.host}:{self.port}/{self.vhost}"

    async def connect(self) -> None:
        """
        Establish connection to RabbitMQ with retry logic.
        """
        last_error = None

        for attempt in range(self.max_retries):
            try:
                logger.info(f"Connecting to RabbitMQ (attempt {attempt + 1}/{self.max_retries})...")

                self.connection = await connect_robust(
                    self.connection_url,
                    timeout=10
                )

                self.channel = await self.connection.channel()
                await self.channel.set_qos(prefetch_count=1)

                logger.info("Successfully connected to RabbitMQ")
                return

            except Exception as e:
                last_error = e
                logger.warning(f"Connection attempt {attempt + 1} failed: {e}")

                if attempt < self.max_retries - 1:
                    logger.info(f"Retrying in {self.retry_delay} seconds...")
                    await asyncio.sleep(self.retry_delay)

        error_msg = f"Failed to connect to RabbitMQ after {self.max_retries} attempts: {last_error}"
        logger.error(error_msg)
        raise ConnectionError(error_msg)

    async def disconnect(self) -> None:
        """Close RabbitMQ connection"""
        if self.connection and not self.connection.is_closed:
            await self.connection.close()
            logger.info("Disconnected from RabbitMQ")

    async def declare_exchange(
        self,
        name: str,
        exchange_type: ExchangeType = ExchangeType.TOPIC,
        durable: bool = True
    ) -> AbstractExchange:
        """
        Declare an exchange.

        Args:
            name: Exchange name
            exchange_type: Exchange type (topic, direct, fanout, headers)
            durable: Whether exchange survives broker restart

        Returns:
            Exchange object
        """
        if name in self.exchanges:
            return self.exchanges[name]

        if not self.channel:
            raise RuntimeError("Not connected to RabbitMQ")

        exchange = await self.channel.declare_exchange(
            name,
            exchange_type,
            durable=durable
        )

        self.exchanges[name] = exchange
        logger.info(f"Declared exchange: {name} (type: {exchange_type.value})")

        return exchange

    async def declare_queue(
        self,
        name: str,
        durable: bool = True,
        exclusive: bool = False,
        auto_delete: bool = False
    ) -> AbstractQueue:
        """
        Declare a queue.

        Args:
            name: Queue name (empty string for auto-generated name)
            durable: Whether queue survives broker restart
            exclusive: Whether queue is exclusive to this connection
            auto_delete: Whether queue deletes when no consumers

        Returns:
            Queue object
        """
        if name and name in self.queues:
            return self.queues[name]

        if not self.channel:
            raise RuntimeError("Not connected to RabbitMQ")

        queue = await self.channel.declare_queue(
            name,
            durable=durable,
            exclusive=exclusive,
            auto_delete=auto_delete
        )

        if name:
            self.queues[name] = queue
            logger.info(f"Declared queue: {name} (durable: {durable})")
        else:
            logger.info(f"Declared queue: {queue.name} (auto-generated)")

        return queue

    async def bind_queue(
        self,
        queue_name: str,
        exchange_name: str,
        routing_key: str = ""
    ) -> None:
        """
        Bind queue to exchange with routing key.

        Args:
            queue_name: Queue name
            exchange_name: Exchange name
            routing_key: Routing key pattern
        """
        if queue_name not in self.queues:
            raise ValueError(f"Queue {queue_name} not declared")

        if exchange_name not in self.exchanges:
            raise ValueError(f"Exchange {exchange_name} not declared")

        queue = self.queues[queue_name]
        exchange = self.exchanges[exchange_name]

        await queue.bind(exchange, routing_key=routing_key)
        logger.info(f"Bound queue '{queue_name}' to exchange '{exchange_name}' with routing key '{routing_key}'")

    async def publish(
        self,
        exchange_name: str,
        routing_key: str,
        message_body: str,
        correlation_id: Optional[str] = None,
        reply_to: Optional[str] = None,
        content_type: str = "application/json"
    ) -> None:
        """
        Publish a message to an exchange.

        Args:
            exchange_name: Target exchange (empty string for default exchange)
            routing_key: Routing key
            message_body: Message content (JSON string)
            correlation_id: Optional correlation ID for request tracking
            reply_to: Optional reply queue name
            content_type: Content type (default: application/json)
        """
        # Handle default exchange (empty string) as special case
        if exchange_name == "":
            if not self.channel:
                raise RuntimeError("Not connected to RabbitMQ")
            exchange = self.channel.default_exchange
        elif exchange_name in self.exchanges:
            exchange = self.exchanges[exchange_name]
        else:
            raise ValueError(f"Exchange {exchange_name} not declared")

        message = Message(
            body=message_body.encode(),
            content_type=content_type,
            correlation_id=correlation_id,
            reply_to=reply_to
        )

        await exchange.publish(message, routing_key=routing_key)

        logger.debug(f"Published to {exchange_name or 'default'}/{routing_key} (correlation_id: {correlation_id})")

    async def consume(
        self,
        queue_name: str,
        callback: Callable,
        auto_ack: bool = False
    ) -> str:
        """
        Start consuming messages from a queue.

        Args:
            queue_name: Queue to consume from
            callback: Async callback function(message) to handle messages
            auto_ack: Whether to auto-acknowledge messages

        Returns:
            Consumer tag
        """
        if queue_name not in self.queues:
            raise ValueError(f"Queue {queue_name} not declared")

        queue = self.queues[queue_name]

        consumer_tag = await queue.consume(callback, no_ack=auto_ack)

        logger.info(f"Started consuming from queue '{queue_name}' (consumer_tag: {consumer_tag})")

        return consumer_tag

    async def setup_project_topology(self) -> None:
        """
        Set up the complete RabbitMQ topology for Project Chimera.
        Creates all exchanges needed by the system.
        """
        logger.info("Setting up Project Chimera RabbitMQ topology...")

        # Declare all exchanges
        await self.declare_exchange("orchestrator.requests", ExchangeType.TOPIC)
        await self.declare_exchange("orchestrator.responses", ExchangeType.TOPIC)
        await self.declare_exchange("orchestrator.register", ExchangeType.TOPIC)
        await self.declare_exchange("orchestrator.discover", ExchangeType.TOPIC)
        await self.declare_exchange("orchestrator.progress", ExchangeType.TOPIC)
        await self.declare_exchange("agent.tasks", ExchangeType.TOPIC)

        logger.info("RabbitMQ topology setup complete")


async def create_rabbitmq_client() -> RabbitMQClient:
    """`\

    Factory function to create and connect RabbitMQ client.

    Returns:
        Connected RabbitMQClient instance
    """
    client = RabbitMQClient()
    await client.connect()
    await client.setup_project_topology()
    return client
