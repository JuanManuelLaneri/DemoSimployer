"""
Orchestrator Main Entry Point

Starts the orchestrator service:
1. Connects to RabbitMQ
2. Initializes agent registry
3. Starts registration listener
4. Starts result collector
5. Ready to receive orchestration requests
"""

import asyncio
import os
import sys
from pathlib import Path
import signal

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

from agents.shared.messaging import RabbitMQClient
from agents.shared.llm_client import LLMClient
from agents.shared.file_logger import setup_file_logger
from orchestrator.registry import AgentRegistry
from orchestrator.handlers import RegistrationHandler, TaskResultHandler
from orchestrator.react_loop import ReactLoop
from orchestrator.progress_publisher import ProgressPublisher
from orchestrator.request_handler import OrchestrationRequestHandler

# Initialize file logging
log_level = os.getenv("LOG_LEVEL", "INFO")
logger = setup_file_logger("orchestrator", log_level=log_level)


class Orchestrator:
    """Main orchestrator service"""

    def __init__(self):
        """Initialize orchestrator components"""
        logger.info("Initializing...")
        print("[ORCHESTRATOR] Initializing...")

        # Load environment variables
        self.rabbitmq_host = os.getenv("RABBITMQ_HOST", "localhost")
        self.rabbitmq_port = int(os.getenv("RABBITMQ_PORT", "5672"))
        self.rabbitmq_user = os.getenv("RABBITMQ_USER", "guest")
        self.rabbitmq_password = os.getenv("RABBITMQ_PASSWORD", "guest")

        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
        self.deepseek_base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.deepseek_model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

        # Initialize components
        self.rabbitmq = None
        self.llm = None
        self.registry = None
        self.registration_handler = None
        self.result_handler = None
        self.progress_publisher = None
        self.react_loop = None
        self.request_handler = None

        # Task handles
        self.tasks = []
        self.shutdown_event = asyncio.Event()

    async def start(self):
        """Start the orchestrator service"""
        logger.info("Starting...")
        print("[ORCHESTRATOR] Starting...")

        try:
            # Connect to RabbitMQ
            logger.info(f"Connecting to RabbitMQ at {self.rabbitmq_host}:{self.rabbitmq_port}...")
            print(f"[ORCHESTRATOR] Connecting to RabbitMQ at {self.rabbitmq_host}:{self.rabbitmq_port}...")
            self.rabbitmq = RabbitMQClient(
                host=self.rabbitmq_host,
                port=self.rabbitmq_port,
                user=self.rabbitmq_user,
                password=self.rabbitmq_password
            )
            await self.rabbitmq.connect()
            await self.rabbitmq.setup_project_topology()
            logger.info("Connected to RabbitMQ")
            print("[ORCHESTRATOR] Connected to RabbitMQ ✓")

            # Initialize LLM client
            logger.info("Initializing LLM client...")
            print("[ORCHESTRATOR] Initializing LLM client...")
            self.llm = LLMClient(
                api_key=self.deepseek_api_key,
                base_url=self.deepseek_base_url,
                model=self.deepseek_model
            )
            logger.info("LLM client ready")
            print("[ORCHESTRATOR] LLM client ready ✓")

            # Initialize registry
            logger.info("Initializing agent registry...")
            print("[ORCHESTRATOR] Initializing agent registry...")
            self.registry = AgentRegistry()
            logger.info("Registry ready")
            print("[ORCHESTRATOR] Registry ready ✓")

            # Initialize handlers
            logger.info("Initializing message handlers...")
            print("[ORCHESTRATOR] Initializing message handlers...")
            self.registration_handler = RegistrationHandler(self.registry, self.rabbitmq)
            self.result_handler = TaskResultHandler(self.rabbitmq)
            logger.info("Handlers ready")
            print("[ORCHESTRATOR] Handlers ready ✓")

            # Initialize progress publisher
            logger.info("Initializing progress publisher...")
            print("[ORCHESTRATOR] Initializing progress publisher...")
            self.progress_publisher = ProgressPublisher(rabbitmq=self.rabbitmq)
            logger.info("Progress publisher ready")
            print("[ORCHESTRATOR] Progress publisher ready ✓")

            # Initialize ReAct loop
            logger.info("Initializing ReAct loop...")
            print("[ORCHESTRATOR] Initializing ReAct loop...")
            self.react_loop = ReactLoop(
                llm_client=self.llm,
                rabbitmq=self.rabbitmq,
                registry=self.registry,
                progress_publisher=self.progress_publisher
            )
            # Wire result handler to ReAct loop
            self.react_loop.result_handler = self.result_handler
            logger.info("ReAct loop ready")
            print("[ORCHESTRATOR] ReAct loop ready ✓")

            # Initialize request handler
            logger.info("Initializing request handler...")
            print("[ORCHESTRATOR] Initializing request handler...")
            self.request_handler = OrchestrationRequestHandler(
                react_loop=self.react_loop,
                rabbitmq=self.rabbitmq
            )
            logger.info("Request handler ready")
            print("[ORCHESTRATOR] Request handler ready ✓")

            # Declare orchestrator queues
            logger.info("Declaring queues...")
            print("[ORCHESTRATOR] Declaring queues...")
            await self.rabbitmq.declare_queue("orchestrator.registrations", durable=True)
            await self.rabbitmq.bind_queue(
                "orchestrator.registrations",
                "orchestrator.register",
                "register.*"
            )

            await self.rabbitmq.declare_queue("orchestrator.results", durable=True)
            await self.rabbitmq.bind_queue(
                "orchestrator.results",
                "orchestrator.responses",
                "result.*"
            )

            await self.rabbitmq.declare_queue("orchestrator.requests", durable=True)
            await self.rabbitmq.bind_queue(
                "orchestrator.requests",
                "orchestrator.requests",
                "request.*"
            )
            logger.info("Queues ready")
            print("[ORCHESTRATOR] Queues ready ✓")

            # Start consuming registration messages
            logger.info("Starting registration listener...")
            print("[ORCHESTRATOR] Starting registration listener...")
            registration_task = asyncio.create_task(
                self.registration_handler.start_consuming("orchestrator.registrations")
            )
            self.tasks.append(registration_task)

            # Start consuming result messages
            logger.info("Starting result collector...")
            print("[ORCHESTRATOR] Starting result collector...")
            result_task = asyncio.create_task(
                self.result_handler.start_consuming("orchestrator.results")
            )
            self.tasks.append(result_task)

            # Start consuming orchestration requests
            logger.info("Starting request handler...")
            print("[ORCHESTRATOR] Starting request handler...")
            request_task = asyncio.create_task(
                self.request_handler.start_consuming("orchestrator.requests")
            )
            self.tasks.append(request_task)

            logger.info("Orchestrator is READY")
            print("[ORCHESTRATOR] ✓ Orchestrator is READY")
            print("[ORCHESTRATOR] Waiting for agents to register...")
            print("[ORCHESTRATOR] Press Ctrl+C to shutdown")

            # Wait for shutdown signal
            await self.shutdown_event.wait()

        except Exception as e:
            logger.error(f"Error during startup: {e}", exc_info=True)
            print(f"[ORCHESTRATOR] Error during startup: {e}")
            import traceback
            traceback.print_exc()
            await self.shutdown()

    async def shutdown(self):
        """Gracefully shutdown the orchestrator"""
        logger.info("Shutting down...")
        print("\n[ORCHESTRATOR] Shutting down...")

        # Cancel all tasks
        for task in self.tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Disconnect from RabbitMQ
        if self.rabbitmq:
            await self.rabbitmq.disconnect()
            logger.info("Disconnected from RabbitMQ")
            print("[ORCHESTRATOR] Disconnected from RabbitMQ")

        logger.info("Shutdown complete")
        print("[ORCHESTRATOR] Shutdown complete")

    def signal_handler(self, sig, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {sig}")
        print(f"\n[ORCHESTRATOR] Received signal {sig}")
        self.shutdown_event.set()


async def main():
    """Main entry point"""
    orchestrator = Orchestrator()

    # Setup signal handlers
    signal.signal(signal.SIGINT, orchestrator.signal_handler)
    signal.signal(signal.SIGTERM, orchestrator.signal_handler)

    # Start orchestrator
    await orchestrator.start()

    # Shutdown
    await orchestrator.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[ORCHESTRATOR] Interrupted")
    except Exception as e:
        print(f"[ORCHESTRATOR] Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
