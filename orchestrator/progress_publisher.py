"""
Progress Update Publisher

Publishes real-time progress updates during orchestration execution.
Updates are sent to orchestrator.progress exchange for WebSocket streaming.
"""

from typing import Dict, Any, Optional
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agents.shared.messaging import RabbitMQClient
from agents.shared.schemas import ProgressUpdate


class ProgressPublisher:
    """
    Publishes progress updates during orchestration.

    Sends real-time events to WebSocket clients via RabbitMQ.
    Event types: started, reasoning, agent_called, agent_completed, error, completed
    """

    def __init__(self, rabbitmq: RabbitMQClient):
        """
        Initialize progress publisher.

        Args:
            rabbitmq: RabbitMQ client for messaging
        """
        self.rabbitmq = rabbitmq
        self.exchange_name = "orchestrator.progress"

    async def _publish_update(
        self,
        correlation_id: str,
        event_type: str,
        message: str,
        data: Dict[str, Any]
    ) -> None:
        """
        Publish a progress update message.

        Args:
            correlation_id: Correlation ID for tracking
            event_type: Type of event (started, reasoning, etc.)
            message: Human-readable message
            data: Additional event data
        """
        progress_update = ProgressUpdate(
            message_type="progress_update",
            correlation_id=correlation_id,
            event_type=event_type,
            message=message,
            data=data
        )

        routing_key = f"progress.{event_type}"

        await self.rabbitmq.publish(
            exchange_name=self.exchange_name,
            routing_key=routing_key,
            message_body=progress_update.to_json(),
            correlation_id=correlation_id
        )

        print(f"[PROGRESS] {event_type}: {message}")

    async def publish_started(
        self,
        correlation_id: str,
        user_request: str
    ) -> None:
        """
        Publish orchestration started event.

        Args:
            correlation_id: Correlation ID
            user_request: The user's original request
        """
        await self._publish_update(
            correlation_id=correlation_id,
            event_type="started",
            message=f"Orchestration started: {user_request[:50]}...",
            data={
                "user_request": user_request
            }
        )

    async def publish_reasoning(
        self,
        correlation_id: str,
        iteration: int,
        reasoning: str
    ) -> None:
        """
        Publish LLM reasoning event.

        Args:
            correlation_id: Correlation ID
            iteration: Current iteration number
            reasoning: LLM's reasoning text
        """
        await self._publish_update(
            correlation_id=correlation_id,
            event_type="reasoning",
            message=f"Iteration {iteration}: {reasoning[:100]}...",
            data={
                "iteration": iteration,
                "reasoning": reasoning
            }
        )

    async def publish_agent_called(
        self,
        correlation_id: str,
        agent_name: str,
        tool: str,
        task_id: str,
        input_data: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Publish agent called event.

        Args:
            correlation_id: Correlation ID
            agent_name: Name of agent being called
            tool: Tool being invoked
            task_id: Task ID
            input_data: Input parameters for the tool
        """
        await self._publish_update(
            correlation_id=correlation_id,
            event_type="agent_called",
            message=f"Calling {agent_name}.{tool}",
            data={
                "agent": agent_name,
                "tool": tool,
                "task_id": task_id,
                "input": input_data or {}
            }
        )

    async def publish_agent_completed(
        self,
        correlation_id: str,
        agent_name: str,
        task_id: str,
        status: str,
        result: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Publish agent completed event.

        Args:
            correlation_id: Correlation ID
            agent_name: Name of agent that completed
            task_id: Task ID
            status: Result status (success, error, etc.)
            result: Result data
        """
        await self._publish_update(
            correlation_id=correlation_id,
            event_type="agent_completed",
            message=f"{agent_name} completed with {status}",
            data={
                "agent": agent_name,
                "task_id": task_id,
                "status": status,
                "result": result or {}
            }
        )

    async def publish_completed(
        self,
        correlation_id: str,
        status: str,
        summary: str,
        iterations: Optional[int] = None
    ) -> None:
        """
        Publish orchestration completed event.

        Args:
            correlation_id: Correlation ID
            status: Final status (completed, failed, timeout)
            summary: Summary of orchestration
            iterations: Number of iterations executed
        """
        await self._publish_update(
            correlation_id=correlation_id,
            event_type="completed",
            message=f"Orchestration {status}: {summary}",
            data={
                "status": status,
                "summary": summary,
                "iterations": iterations
            }
        )

    async def publish_error(
        self,
        correlation_id: str,
        error: str,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Publish error event.

        Args:
            correlation_id: Correlation ID
            error: Error message
            details: Additional error details
        """
        await self._publish_update(
            correlation_id=correlation_id,
            event_type="error",
            message=f"Error: {error}",
            data={
                "error": error,
                "details": details or {}
            }
        )
