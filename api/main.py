"""
FastAPI Service for Multi-Agent Orchestration System

Provides REST and WebSocket endpoints for submitting requests
and receiving orchestration results.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from datetime import datetime, UTC
from typing import Dict, Any, Optional
from contextlib import asynccontextmanager
import uuid

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agents.shared.messaging import RabbitMQClient
from agents.shared.schemas import OrchestrationRequest
from agents.shared.file_logger import setup_file_logger

# Initialize file logging
log_level = os.getenv("LOG_LEVEL", "INFO")
logger = setup_file_logger("api", log_level=log_level)

# Global state
rabbitmq_client: Optional[RabbitMQClient] = None
request_states: Dict[str, Dict[str, Any]] = {}  # correlation_id -> state
websocket_connections: Dict[str, list] = {}  # correlation_id -> [websockets]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown"""
    global rabbitmq_client

    # Startup
    logger.info("Starting up...")
    print("[API] Starting up...")

    # Get RabbitMQ connection details from environment
    rabbitmq_host = os.getenv("RABBITMQ_HOST", "localhost")
    rabbitmq_port = int(os.getenv("RABBITMQ_PORT", "5672"))
    rabbitmq_user = os.getenv("RABBITMQ_USER", "guest")
    rabbitmq_password = os.getenv("RABBITMQ_PASSWORD", "guest")

    result_consumer_task = None

    try:
        # Connect to RabbitMQ
        rabbitmq_client = RabbitMQClient(
            host=rabbitmq_host,
            port=rabbitmq_port,
            user=rabbitmq_user,
            password=rabbitmq_password
        )
        await rabbitmq_client.connect()

        # Declare orchestrator requests queue
        await rabbitmq_client.declare_queue("orchestrator.requests", durable=True)

        logger.info(f"Connected to RabbitMQ at {rabbitmq_host}:{rabbitmq_port}")
        print(f"[API] Connected to RabbitMQ at {rabbitmq_host}:{rabbitmq_port}")

        # Start result consumer as background task
        result_consumer_task = asyncio.create_task(consume_results())
        logger.info("Result consumer task started")
        print("[API] Result consumer task started")

    except Exception as e:
        logger.warning(f"Could not connect to RabbitMQ: {e}")
        print(f"[API] Warning: Could not connect to RabbitMQ: {e}")
        # Continue without RabbitMQ for testing
        rabbitmq_client = None

    yield

    # Shutdown
    logger.info("Shutting down...")
    print("[API] Shutting down...")

    # Cancel result consumer task
    if result_consumer_task:
        result_consumer_task.cancel()
        try:
            await result_consumer_task
        except asyncio.CancelledError:
            logger.info("Result consumer task cancelled")
            print("[API] Result consumer task cancelled")

    if rabbitmq_client:
        await rabbitmq_client.close()
        logger.info("RabbitMQ connection closed")
        print("[API] RabbitMQ connection closed")


# FastAPI app
app = FastAPI(
    title="Multi-Agent Orchestration API",
    version="1.0.0",
    description="API for submitting orchestration requests and receiving results",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify allowed origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Pydantic models
class PlanAndRunRequest(BaseModel):
    """Request model for /plan-and-run endpoint"""
    request: str = Field(..., min_length=1, max_length=10000, description="User request text")


class PlanAndRunResponse(BaseModel):
    """Response model for /plan-and-run endpoint"""
    correlation_id: str
    status: str
    message: str


class StatusResponse(BaseModel):
    """Response model for /status endpoint"""
    correlation_id: str
    status: str
    progress: Optional[list] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# Endpoints
@app.get("/")
async def root():
    """Root endpoint - API info"""
    return {
        "message": "Multi-Agent Orchestration API",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "plan_and_run": "/plan-and-run",
            "status": "/status/{correlation_id}",
            "websocket": "/ws/{correlation_id}"
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now(UTC).isoformat(),
        "rabbitmq": "connected" if rabbitmq_client else "disconnected"
    }


@app.post("/plan-and-run", response_model=PlanAndRunResponse)
async def plan_and_run(request: PlanAndRunRequest):
    """
    Submit an orchestration request.

    The request will be sent to the orchestrator, which will use the ReAct loop
    to plan and execute tasks using available agents.

    Returns a correlation_id that can be used to check status and receive updates.
    """
    global rabbitmq_client, request_states

    # Generate correlation ID
    correlation_id = str(uuid.uuid4())

    logger.info(f"Received request {correlation_id}: {request.request[:50]}...")
    print(f"[API] Received request {correlation_id}: {request.request[:50]}...")

    # Initialize request state
    request_states[correlation_id] = {
        "correlation_id": correlation_id,
        "status": "pending",
        "request": request.request,
        "progress": [],
        "result": None,
        "error": None,
        "created_at": datetime.now(UTC).isoformat()
    }

    # Publish to orchestrator
    if rabbitmq_client:
        try:
            # Create OrchestrationRequest message
            orchestration_request = OrchestrationRequest(
                message_type="orchestration_request",
                correlation_id=correlation_id,
                request=request.request,
                reply_to="api.responses"
            )

            # Publish to orchestrator.requests queue
            await rabbitmq_client.publish(
                exchange_name="",
                routing_key="orchestrator.requests",
                message_body=orchestration_request.model_dump_json(),
                correlation_id=correlation_id
            )

            logger.info(f"Published request {correlation_id} to orchestrator")
            print(f"[API] Published request {correlation_id} to orchestrator")

            # Update state to processing
            request_states[correlation_id]["status"] = "processing"

            return PlanAndRunResponse(
                correlation_id=correlation_id,
                status="processing",
                message="Request submitted to orchestrator"
            )

        except Exception as e:
            logger.error(f"Error publishing request: {e}", exc_info=True)
            print(f"[API] Error publishing request: {e}")
            request_states[correlation_id]["status"] = "failed"
            request_states[correlation_id]["error"] = str(e)

            raise HTTPException(status_code=500, detail=f"Failed to submit request: {e}")

    else:
        # RabbitMQ not connected - return mock response for testing
        logger.warning("RabbitMQ not connected, returning mock response")
        print("[API] Warning: RabbitMQ not connected, returning mock response")

        return PlanAndRunResponse(
            correlation_id=correlation_id,
            status="pending",
            message="Request received (RabbitMQ not connected)"
        )


@app.get("/status/{correlation_id}", response_model=StatusResponse)
async def get_status(correlation_id: str):
    """
    Get the status of an orchestration request.

    Returns the current state, progress updates, and results (if completed).
    """
    global request_states

    # Check if correlation_id exists
    if correlation_id not in request_states:
        raise HTTPException(status_code=404, detail="Request not found")

    state = request_states[correlation_id]

    return StatusResponse(
        correlation_id=correlation_id,
        status=state["status"],
        progress=state.get("progress"),
        result=state.get("result"),
        error=state.get("error")
    )


@app.websocket("/ws/{correlation_id}")
async def websocket_endpoint(websocket: WebSocket, correlation_id: str):
    """
    WebSocket endpoint for real-time progress updates.

    Clients can connect to receive live updates as the orchestration progresses.
    """
    global websocket_connections, request_states

    await websocket.accept()
    print(f"[API] WebSocket connected for {correlation_id}")

    # Register websocket
    if correlation_id not in websocket_connections:
        websocket_connections[correlation_id] = []
    websocket_connections[correlation_id].append(websocket)

    try:
        # Send initial status
        if correlation_id in request_states:
            state = request_states[correlation_id]
            await websocket.send_json({
                "type": "status",
                "status": state["status"],
                "progress": state.get("progress", [])
            })
        else:
            await websocket.send_json({
                "type": "status",
                "status": "not_found"
            })

        # Keep connection alive and listen for messages
        while True:
            try:
                # Wait for messages from client (or timeout)
                data = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                # Echo back for now
                await websocket.send_json({"type": "echo", "data": data})
            except asyncio.TimeoutError:
                # No message received, continue
                continue

    except WebSocketDisconnect:
        print(f"[API] WebSocket disconnected for {correlation_id}")
        # Remove from connections
        if correlation_id in websocket_connections:
            websocket_connections[correlation_id].remove(websocket)
            if not websocket_connections[correlation_id]:
                del websocket_connections[correlation_id]


async def broadcast_update(correlation_id: str, update: Dict[str, Any]):
    """
    Broadcast an update to all WebSocket connections for a correlation_id.

    Args:
        correlation_id: Request correlation ID
        update: Update data to broadcast
    """
    global websocket_connections

    if correlation_id in websocket_connections:
        for websocket in websocket_connections[correlation_id]:
            try:
                await websocket.send_json(update)
            except Exception as e:
                print(f"[API] Error broadcasting to websocket: {e}")


async def consume_results():
    """
    Consume orchestration results from the api.responses queue.

    Updates request states and broadcasts to WebSocket connections.
    """
    global rabbitmq_client, request_states

    if not rabbitmq_client:
        print("[API] RabbitMQ not connected, skipping result consumer")
        return

    # Declare api.responses queue
    await rabbitmq_client.declare_queue("api.responses", durable=True)

    print("[API] Starting result consumer on api.responses queue")

    async def handle_result(message):
        """Handle incoming orchestration results"""
        async with message.process():
            try:
                # Parse result message
                body = message.body.decode()
                result_data = json.loads(body)

                correlation_id = result_data.get("correlation_id")
                if not correlation_id:
                    print(f"[API] Result missing correlation_id: {result_data}")
                    return

                print(f"[API] Received result for {correlation_id}")

                # Update request state
                if correlation_id in request_states:
                    state = request_states[correlation_id]

                    # Determine status based on result
                    if result_data.get("status") == "completed":
                        state["status"] = "completed"
                        state["result"] = result_data.get("results", {})
                    elif result_data.get("status") == "failed":
                        state["status"] = "failed"
                        state["error"] = result_data.get("error", "Unknown error")
                    else:
                        # Update progress
                        if "progress" in result_data:
                            state["progress"].append(result_data["progress"])

                    # Broadcast to WebSocket connections
                    await broadcast_update(correlation_id, {
                        "type": "update",
                        "status": state["status"],
                        "result": state.get("result"),
                        "error": state.get("error"),
                        "progress": state.get("progress", [])
                    })

                    print(f"[API] Updated state for {correlation_id}: {state['status']}")
                else:
                    print(f"[API] Received result for unknown correlation_id: {correlation_id}")

            except Exception as e:
                print(f"[API] Error processing result: {e}")
                import traceback
                traceback.print_exc()

    # Start consuming
    await rabbitmq_client.consume("api.responses", handle_result)

    # Keep consuming
    while True:
        await asyncio.sleep(1)


# For running with uvicorn
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
