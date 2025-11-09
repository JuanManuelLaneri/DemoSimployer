"""
Orchestration Request Handler

Consumes orchestration requests from the API, triggers the ReAct loop,
and publishes results back to the requester.
"""

import asyncio
import sys
from pathlib import Path
from typing import Dict, Any, Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agents.shared.messaging import RabbitMQClient
from agents.shared.schemas import OrchestrationRequest, OrchestrationResult
from orchestrator.react_loop import ReactLoop


class OrchestrationRequestHandler:
    """
    Handles orchestration requests from users/API.

    Consumes requests from RabbitMQ, triggers ReAct loop execution,
    and publishes results.
    """

    def __init__(self, react_loop: ReactLoop, rabbitmq: RabbitMQClient):
        """
        Initialize request handler.

        Args:
            react_loop: ReAct loop instance
            rabbitmq: RabbitMQ client for messaging
        """
        self.react_loop = react_loop
        self.rabbitmq = rabbitmq

    async def handle_request(
        self,
        request: OrchestrationRequest
    ) -> Dict[str, Any]:
        """
        Handle a single orchestration request.

        Args:
            request: OrchestrationRequest message

        Returns:
            Dict with orchestration result
        """
        print(f"[REQUEST] Handling orchestration request: {request.correlation_id}")
        print(f"[REQUEST] User request: {request.request}")

        try:
            # Execute ReAct loop
            result = await self.react_loop.execute(
                user_request=request.request,
                correlation_id=request.correlation_id,
                data=request.data
            )

            print(f"[REQUEST] Orchestration complete: {result.get('status')}")

            return result

        except Exception as e:
            print(f"[REQUEST] Error during orchestration: {e}")
            import traceback
            traceback.print_exc()

            return {
                "status": "error",
                "correlation_id": request.correlation_id,
                "error": str(e),
                "message": "Orchestration failed with error"
            }

    def build_orchestration_result(
        self,
        react_result: Dict[str, Any]
    ) -> OrchestrationResult:
        """
        Build OrchestrationResult message from ReAct loop result.

        Args:
            react_result: Result dict from ReAct loop

        Returns:
            OrchestrationResult message
        """
        # Map status
        status_map = {
            "completed": "completed",
            "error": "failed",
            "max_iterations_exceeded": "timeout"
        }
        status = status_map.get(react_result.get("status"), "failed")

        # Extract execution steps
        execution_steps = react_result.get("execution_steps", [])

        # Build agents_involved list
        agents_involved = list(set([
            step.get("agent")
            for step in execution_steps
            if step.get("action") == "call_agent" and step.get("agent")
        ]))

        # Build agent-to-agent calls (simplified for now)
        agent_calls = []

        # Get results
        results = react_result.get("results", {})

        # Calculate total duration (simplified - would need actual timing)
        total_duration_ms = 0.0

        # Count LLM calls (number of iterations)
        total_llm_calls = react_result.get("iterations", 0)

        return OrchestrationResult(
            message_type="orchestration_result",
            correlation_id=react_result.get("correlation_id", "unknown"),
            status=status,
            results=results,
            total_duration_ms=total_duration_ms,
            total_llm_calls=total_llm_calls,
            agents_involved=agents_involved,
            agent_to_agent_calls=agent_calls
        )

    async def publish_result(
        self,
        react_result: Dict[str, Any],
        reply_to: str,
        correlation_id: str
    ) -> None:
        """
        Publish orchestration result to reply queue.

        Args:
            react_result: Result dict from ReAct loop
            reply_to: Queue to publish result to
            correlation_id: Correlation ID for tracking
        """
        print(f"[REQUEST] Publishing result to {reply_to}")

        # Build OrchestrationResult message
        result_message = self.build_orchestration_result(react_result)

        # Publish to reply queue
        await self.rabbitmq.publish(
            exchange_name="",  # Default exchange for direct queue routing
            routing_key=reply_to,
            message_body=result_message.to_json(),
            correlation_id=correlation_id
        )

        print(f"[REQUEST] Result published successfully")

    async def start_consuming(self, queue_name: str) -> None:
        """
        Start consuming orchestration requests from a queue.

        Args:
            queue_name: Name of queue to consume from

        Runs indefinitely until cancelled.
        """
        print(f"[REQUEST] Starting to consume from {queue_name}")

        async def message_handler(message):
            async with message.process():
                try:
                    # Parse request
                    body = message.body.decode()
                    request = OrchestrationRequest.from_json(body)

                    print(f"[REQUEST] Received request: {request.correlation_id}")

                    # Handle request
                    result = await self.handle_request(request)

                    # Publish result to reply queue
                    if request.reply_to:
                        await self.publish_result(
                            react_result=result,
                            reply_to=request.reply_to,
                            correlation_id=request.correlation_id
                        )

                except Exception as e:
                    print(f"[REQUEST] Error processing message: {e}")
                    import traceback
                    traceback.print_exc()

        await self.rabbitmq.consume(queue_name, message_handler)

        # Keep consuming
        while True:
            await asyncio.sleep(1)
