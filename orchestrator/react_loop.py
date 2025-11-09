"""
ReAct Loop - Reasoning and Acting loop for orchestration

Implements the ReAct pattern:
1. Reason - LLM decides what to do next
2. Act - Execute the action (call agent, return result, etc.)
3. Observe - Process the result
4. Repeat until done

This is the core intelligence of the orchestrator.
"""

import asyncio
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, UTC

# Configuration constants
AGENT_TASK_TIMEOUT = 120.0  # 2 minutes timeout for agent tasks

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agents.shared.llm_client import LLMClient
from agents.shared.messaging import RabbitMQClient
from agents.shared.schemas import TaskMessage, ResultMessage
from orchestrator.registry import AgentRegistry
from orchestrator.handlers import TaskResultHandler
from orchestrator.progress_publisher import ProgressPublisher


class ReactLoop:
    """
    ReAct loop orchestrator.

    Coordinates LLM reasoning with agent execution.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        rabbitmq: RabbitMQClient,
        registry: AgentRegistry,
        max_iterations: int = 10,
        progress_publisher: Optional[ProgressPublisher] = None
    ):
        """
        Initialize ReAct loop.

        Args:
            llm_client: LLM client for reasoning
            rabbitmq: RabbitMQ client for agent communication
            registry: Agent registry for service discovery
            max_iterations: Maximum reasoning iterations
            progress_publisher: Optional progress publisher for real-time updates
        """
        self.llm = llm_client
        self.rabbitmq = rabbitmq
        self.registry = registry
        self.max_iterations = max_iterations
        self.progress_publisher = progress_publisher
        self.result_handler = None  # Will be set by orchestrator main
        self.execution_steps = []

    async def execute(
        self,
        user_request: str,
        correlation_id: str,
        data: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Execute the ReAct loop for a user request.

        Args:
            user_request: Natural language request from user
            correlation_id: Correlation ID for tracking
            data: Optional input data

        Returns:
            Final orchestration result
        """
        if data is None:
            data = {}

        self.execution_steps = []
        iteration = 0
        pending_tasks = {}
        task_dispatch_times = {}  # Track when each task was dispatched for timeout detection

        print(f"[REACT] Starting orchestration: {user_request}")
        print(f"[REACT] Correlation ID: {correlation_id}")

        # Publish started event
        if self.progress_publisher:
            await self.progress_publisher.publish_started(
                correlation_id=correlation_id,
                user_request=user_request
            )

        try:
            while iteration < self.max_iterations:
                iteration += 1
                print(f"\n[REACT] === Iteration {iteration}/{self.max_iterations} ===")

                # Build context for LLM
                system_prompt = self.build_system_prompt(user_request)
                decision_prompt = self.build_decision_prompt(
                    user_request,
                    pending_tasks
                )

                # Get LLM decision
                print("[REACT] Asking LLM for next action...")
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": decision_prompt}
                ]

                llm_response = self.llm.chat_completion(messages, temperature=0.7)
                llm_text = llm_response["choices"][0]["message"]["content"]

                print(f"[REACT] LLM Response:\n{llm_text}")

                # Parse decision
                decision = self.parse_llm_decision(llm_text)

                # Publish reasoning event
                if self.progress_publisher:
                    # Extract reasoning from LLM response
                    reasoning_match = re.search(r'REASONING:(.*?)(?:ACTION:|$)', llm_text, re.DOTALL | re.IGNORECASE)
                    reasoning = reasoning_match.group(1).strip() if reasoning_match else llm_text[:200]

                    await self.progress_publisher.publish_reasoning(
                        correlation_id=correlation_id,
                        iteration=iteration,
                        reasoning=reasoning
                    )

                if decision["action"] == "call_agent":
                    # Dispatch task to agent
                    agent_name = decision["agent"]
                    tool = decision["tool"]
                    input_data = decision["input"]

                    # Resolve references to previous step results
                    input_data = self.resolve_input_references(input_data)

                    print(f"[REACT] Action: Call {agent_name}.{tool}")

                    task_id = await self.dispatch_task(
                        agent_name=agent_name,
                        tool=tool,
                        input_data=input_data,
                        correlation_id=correlation_id
                    )

                    # Create future IMMEDIATELY to avoid race condition
                    # (result might arrive before wait_for_result is called)
                    if self.result_handler:
                        await self.result_handler.register_task(task_id)

                    pending_tasks[task_id] = {
                        "agent": agent_name,
                        "tool": tool,
                        "status": "pending"
                    }

                    # Record dispatch time for timeout tracking
                    task_dispatch_times[task_id] = datetime.now(UTC)

                    # Publish agent called event
                    if self.progress_publisher:
                        await self.progress_publisher.publish_agent_called(
                            correlation_id=correlation_id,
                            agent_name=agent_name,
                            tool=tool,
                            task_id=task_id,
                            input_data=input_data
                        )

                    # Record step
                    self.execution_steps.append({
                        "step": iteration,
                        "action": "call_agent",
                        "agent": agent_name,
                        "tool": tool,
                        "task_id": task_id,
                        "status": "dispatched"
                    })

                elif decision["action"] == "wait":
                    # Wait for pending tasks
                    print(f"[REACT] Action: Wait for {len(pending_tasks)} pending tasks")

                    if not pending_tasks:
                        print("[REACT] Warning: No pending tasks to wait for!")
                        continue

                    # Check for timed-out tasks before waiting
                    current_time = datetime.now(UTC)
                    timed_out_tasks = []

                    for task_id, task_info in list(pending_tasks.items()):
                        dispatch_time = task_dispatch_times.get(task_id)
                        if dispatch_time:
                            elapsed = (current_time - dispatch_time).total_seconds()
                            if elapsed > AGENT_TASK_TIMEOUT:
                                print(f"[REACT] Task {task_id} timed out after {elapsed:.1f}s")
                                timed_out_tasks.append(task_id)

                                # Mark as timed out
                                task_info["status"] = "timeout"

                                # Publish timeout event
                                if self.progress_publisher:
                                    await self.progress_publisher.publish_error(
                                        correlation_id=correlation_id,
                                        error=f"Task {task_id} timed out",
                                        details={
                                            "task_id": task_id,
                                            "agent": task_info["agent"],
                                            "tool": task_info["tool"],
                                            "elapsed_seconds": elapsed,
                                            "timeout_seconds": AGENT_TASK_TIMEOUT
                                        }
                                    )

                                # Record timeout in execution history
                                self.execution_steps.append({
                                    "step": iteration,
                                    "action": "task_timeout",
                                    "agent": task_info["agent"],
                                    "tool": task_info["tool"],
                                    "task_id": task_id,
                                    "status": "timeout",
                                    "elapsed_seconds": elapsed
                                })

                    # Remove timed-out tasks from pending
                    for task_id in timed_out_tasks:
                        del pending_tasks[task_id]
                        if task_id in task_dispatch_times:
                            del task_dispatch_times[task_id]

                    # If all tasks timed out, log and continue
                    if timed_out_tasks and not pending_tasks:
                        print(f"[REACT] All pending tasks timed out, continuing orchestration")

                    if not self.result_handler:
                        print("[REACT] Warning: No result handler configured, using fallback sleep")
                        await asyncio.sleep(1)
                    elif pending_tasks:  # Only wait if there are still pending tasks
                        # Wait for at least one task to complete
                        # Create list of task_ids to wait for
                        task_ids = list(pending_tasks.keys())
                        print(f"[REACT] Waiting for results from tasks: {task_ids}")

                        # Wait for first result (or timeout after 30 seconds)
                        completed_task_id = None
                        for task_id in task_ids:
                            try:
                                # Try to get result for this task (short timeout)
                                result = await self.result_handler.wait_for_result(
                                    correlation_id=task_id,
                                    timeout=5.0
                                )

                                if result:
                                    print(f"[REACT] Received result for task {task_id}")
                                    completed_task_id = task_id

                                    # Update pending task
                                    task_info = pending_tasks[task_id]
                                    task_info["status"] = result.status
                                    task_info["result"] = result.result

                                    # Publish agent completed event
                                    if self.progress_publisher:
                                        await self.progress_publisher.publish_agent_completed(
                                            correlation_id=correlation_id,
                                            agent_name=task_info["agent"],
                                            task_id=task_id,
                                            status=result.status,
                                            result=result.result
                                        )

                                    # Record in execution history
                                    self.execution_steps.append({
                                        "step": iteration,
                                        "action": "agent_result",
                                        "agent": task_info["agent"],
                                        "task_id": task_id,
                                        "status": result.status,
                                        "result": result.result
                                    })

                                    # Remove from pending and dispatch tracking
                                    del pending_tasks[task_id]
                                    if task_id in task_dispatch_times:
                                        del task_dispatch_times[task_id]
                                    break

                            except asyncio.TimeoutError:
                                # This task isn't ready yet, try next one
                                continue

                        if not completed_task_id:
                            print("[REACT] No results received yet, tasks still pending")

                    # Record step
                    self.execution_steps.append({
                        "step": iteration,
                        "action": "wait",
                        "reason": decision.get("wait_reason", "Waiting for pending tasks"),
                        "status": "waiting",
                        "pending_count": len(pending_tasks)
                    })

                elif decision["action"] == "complete":
                    # Orchestration complete
                    summary = decision.get("summary", "Task completed")
                    print(f"[REACT] Action: Complete - {summary}")

                    # Publish completed event
                    if self.progress_publisher:
                        await self.progress_publisher.publish_completed(
                            correlation_id=correlation_id,
                            status="completed",
                            summary=summary,
                            iterations=iteration
                        )

                    return {
                        "status": "completed",
                        "correlation_id": correlation_id,
                        "summary": summary,
                        "iterations": iteration,
                        "execution_steps": self.execution_steps,
                        "results": self.aggregate_results()
                    }

                else:
                    print(f"[REACT] Unknown action: {decision['action']}")
                    continue

            # Max iterations exceeded
            print(f"[REACT] Max iterations ({self.max_iterations}) exceeded")

            # Publish error event
            if self.progress_publisher:
                await self.progress_publisher.publish_error(
                    correlation_id=correlation_id,
                    error="Max iterations exceeded",
                    details={
                        "max_iterations": self.max_iterations,
                        "iterations": self.max_iterations
                    }
                )

            return {
                "status": "max_iterations_exceeded",
                "correlation_id": correlation_id,
                "iterations": self.max_iterations,
                "execution_steps": self.execution_steps,
                "message": "Orchestration did not complete within maximum iterations"
            }

        except Exception as e:
            print(f"[REACT] Error during execution: {e}")
            import traceback
            traceback.print_exc()

            # Publish error event
            if self.progress_publisher:
                await self.progress_publisher.publish_error(
                    correlation_id=correlation_id,
                    error=str(e),
                    details={
                        "iteration": iteration,
                        "execution_steps_count": len(self.execution_steps)
                    }
                )

            return {
                "status": "error",
                "correlation_id": correlation_id,
                "error": str(e),
                "iterations": iteration,
                "execution_steps": self.execution_steps
            }

    def parse_llm_decision(self, llm_response: str) -> Dict[str, Any]:
        """
        Parse LLM response to extract decision.

        Args:
            llm_response: Raw LLM response text

        Returns:
            Dict with action and parameters
        """
        decision = {}

        # Extract ACTION
        action_match = re.search(r'ACTION:\s*(\w+)', llm_response, re.IGNORECASE)
        if action_match:
            decision["action"] = action_match.group(1).lower()
        else:
            decision["action"] = "unknown"

        # If call_agent, extract agent, tool, and input
        if decision["action"] == "call_agent":
            agent_match = re.search(r'AGENT:\s*(\w+)', llm_response, re.IGNORECASE)
            tool_match = re.search(r'TOOL:\s*(\w+)', llm_response, re.IGNORECASE)
            input_match = re.search(r'INPUT:\s*(\{.*?\})', llm_response, re.DOTALL | re.IGNORECASE)

            if agent_match:
                decision["agent"] = agent_match.group(1)
            if tool_match:
                decision["tool"] = tool_match.group(1)
            if input_match:
                try:
                    decision["input"] = json.loads(input_match.group(1))
                except json.JSONDecodeError:
                    decision["input"] = {}

        # If wait, extract reason
        elif decision["action"] == "wait":
            reason_match = re.search(r'REASON:\s*(.+?)(?:\n|$)', llm_response, re.IGNORECASE)
            if reason_match:
                decision["wait_reason"] = reason_match.group(1).strip()

        # If complete, extract summary
        elif decision["action"] == "complete":
            summary_match = re.search(r'SUMMARY:\s*(.+?)(?:\n|$)', llm_response, re.IGNORECASE)
            if summary_match:
                decision["summary"] = summary_match.group(1).strip()

        return decision

    def build_system_prompt(self, user_request: str) -> str:
        """
        Build system prompt for LLM.

        Args:
            user_request: User's request

        Returns:
            System prompt string
        """
        # Load system prompt template
        prompt_file = Path(__file__).parent.parent / "prompts" / "orchestrator_system.txt"

        with open(prompt_file, 'r') as f:
            template = f.read()

        # Get agent registry description
        agent_registry = self.build_agent_registry_description()

        # Format template
        prompt = template.replace("{agent_registry}", agent_registry)
        prompt = prompt.replace("{user_request}", user_request)
        prompt = prompt.replace("{execution_history}", self.build_execution_history())
        prompt = prompt.replace("{available_tools}", agent_registry)

        return prompt

    def build_decision_prompt(
        self,
        user_request: str,
        pending_tasks: Dict[str, Any]
    ) -> str:
        """
        Build decision prompt for LLM.

        Args:
            user_request: User's request
            pending_tasks: Currently pending tasks

        Returns:
            Decision prompt string
        """
        # Load decision prompt template
        prompt_file = Path(__file__).parent.parent / "prompts" / "orchestrator_react_decision.txt"

        with open(prompt_file, 'r') as f:
            template = f.read()

        # Build task lists
        pending_list = "\n".join([
            f"- Task {task_id}: {info['agent']}.{info['tool']} ({info['status']})"
            for task_id, info in pending_tasks.items()
        ]) if pending_tasks else "None"

        completed_list = "\n".join([
            f"- Step {step['step']}: {step.get('agent', 'N/A')} - {step.get('status', 'unknown')}"
            for step in self.execution_steps
            if step.get('status') in ['completed', 'success']
        ]) if self.execution_steps else "None"

        # Format template
        prompt = template.replace("{user_request}", user_request)
        prompt = prompt.replace("{execution_history}", self.build_execution_history())
        prompt = prompt.replace("{pending_tasks}", pending_list)
        prompt = prompt.replace("{completed_tasks}", completed_list)
        prompt = prompt.replace("{available_agents}", self.build_agent_registry_description())

        return prompt

    def build_agent_registry_description(self) -> str:
        """
        Build human-readable description of available agents.

        Returns:
            Formatted string describing all agents
        """
        agents = self.registry.get_active_agents()

        if not agents:
            return "No agents registered yet."

        descriptions = []
        for agent in agents:
            agent_name = agent["agent_name"]
            capabilities = agent.get("capabilities", [])

            # Get full capabilities if available
            full_caps = agent.get("capabilities_full")
            if full_caps:
                desc = f"\n**{agent_name}**\n"
                desc += f"Description: {full_caps.description}\n"
                desc += "Tools:\n"
                for tool in full_caps.tools:
                    desc += f"  - {tool.name}: {tool.description}\n"
            else:
                desc = f"\n**{agent_name}**\n"
                desc += f"Capabilities: {', '.join(capabilities)}\n"

            descriptions.append(desc)

        return "\n".join(descriptions)

    def build_execution_history(self) -> str:
        """
        Build human-readable execution history.

        Returns:
            Formatted string describing execution steps
        """
        if not self.execution_steps:
            return "No steps executed yet."

        history = []
        for step in self.execution_steps:
            step_num = step.get("step", "?")
            action = step.get("action", "unknown")
            status = step.get("status", "unknown")

            if action == "call_agent":
                agent = step.get("agent", "?")
                tool = step.get("tool", "?")
                history.append(f"Step {step_num}: Called {agent}.{tool} - {status}")
            elif action == "wait":
                reason = step.get("reason", "Unknown reason")
                history.append(f"Step {step_num}: Waited - {reason}")
            else:
                history.append(f"Step {step_num}: {action} - {status}")

        return "\n".join(history)

    def load_data_file(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform file references in input_data to actual data.

        If input contains 'logs_file', load the file and return {'logs': [...]}
        If logs_file is null/None, default to sample_logs.json

        Args:
            input_data: Original input with potential file references

        Returns:
            Transformed input with actual data
        """
        if "logs_file" in input_data:
            logs_file = input_data["logs_file"]

            # Default to sample logs if null/None or empty
            if not logs_file:
                logs_file = "data/sample_logs.json"

            # Remove 'data/' prefix if present
            file_path = Path("data") / logs_file.replace("data/", "")

            try:
                with open(file_path, 'r') as f:
                    logs = json.load(f)

                print(f"[REACT] Loaded {len(logs)} log entries from {file_path}")

                # Return transformed input
                return {"logs": logs}
            except FileNotFoundError:
                print(f"[REACT] Warning: File {file_path} not found, using empty logs")
                return {"logs": []}
            except json.JSONDecodeError as e:
                print(f"[REACT] Warning: Failed to parse {file_path}: {e}")
                return {"logs": []}

        return input_data

    def resolve_input_references(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolve references to previous step results in input data.

        Replaces string references like "from_previous_steps" or "results_from_log_analyzer"
        with actual result data from execution history.

        Args:
            input_data: Input data that may contain references

        Returns:
            Input data with references replaced by actual data
        """
        resolved_data = {}

        for key, value in input_data.items():
            # Check if value is a string reference to previous results
            if isinstance(value, str) and any(ref in value.lower() for ref in [
                "previous", "from_", "result", "analysis", "data"
            ]):
                # Find the most recent result from execution history
                # Look for results from log_analyzer for analysis_data
                if "analysis" in key.lower():
                    # Find most recent log_analyzer result
                    for step in reversed(self.execution_steps):
                        if step.get("action") == "agent_result" and \
                           step.get("agent") == "log_analyzer" and \
                           step.get("status") == "success":
                            resolved_data[key] = step.get("result", {})
                            print(f"[REACT] Resolved '{key}' reference to log_analyzer result from step {step.get('step')}")
                            break
                    else:
                        # No result found, use empty dict
                        resolved_data[key] = {}
                        print(f"[REACT] Warning: Could not resolve reference for '{key}', using empty dict")
                else:
                    # Generic reference - use most recent successful result
                    for step in reversed(self.execution_steps):
                        if step.get("action") == "agent_result" and \
                           step.get("status") == "success":
                            resolved_data[key] = step.get("result", {})
                            print(f"[REACT] Resolved '{key}' reference to {step.get('agent')} result from step {step.get('step')}")
                            break
                    else:
                        resolved_data[key] = {}
                        print(f"[REACT] Warning: Could not resolve reference for '{key}', using empty dict")
            else:
                # Not a reference, keep as-is
                resolved_data[key] = value

        return resolved_data

    async def dispatch_task(
        self,
        agent_name: str,
        tool: str,
        input_data: Dict[str, Any],
        correlation_id: str
    ) -> str:
        """
        Dispatch a task to an agent.

        Args:
            agent_name: Name of target agent
            tool: Tool/capability to invoke
            input_data: Input parameters
            correlation_id: Correlation ID for tracking

        Returns:
            Task ID

        Raises:
            Exception: If agent not found
        """
        # Transform file references to actual data
        input_data = self.load_data_file(input_data)

        # Get agent info from registry
        agent_info = self.registry.get_agent(agent_name)
        if not agent_info:
            raise Exception(f"Agent '{agent_name}' not found in registry")

        # Generate task ID
        task_id = f"task-{uuid.uuid4()}"

        # Create task message
        task_message = TaskMessage(
            message_type="task",
            correlation_id=correlation_id,
            task_id=task_id,
            sender="orchestrator",
            recipient=agent_name,
            tool=tool,
            input=input_data,
            reply_to="orchestrator.results"
        )

        # Publish to agent's queue
        queue_name = agent_info["queue_name"]

        await self.rabbitmq.publish(
            exchange_name="agent.tasks",
            routing_key=f"{agent_name}.task",
            message_body=task_message.to_json(),
            correlation_id=correlation_id
        )

        print(f"[REACT] Dispatched task {task_id} to {agent_name}")

        return task_id

    async def wait_for_result(
        self,
        correlation_id: str,
        timeout: float = 120.0
    ) -> Optional[ResultMessage]:
        """
        Wait for a result with specific correlation ID.

        Args:
            correlation_id: Correlation ID to wait for
            timeout: Timeout in seconds

        Returns:
            ResultMessage if received

        Raises:
            asyncio.TimeoutError: If timeout exceeded
        """
        if not self.result_handler:
            raise Exception("Result handler not initialized")

        return await self.result_handler.wait_for_result(correlation_id, timeout)

    def aggregate_results(self) -> Dict[str, Any]:
        """
        Aggregate results from all execution steps.

        Returns:
            Dict with aggregated results
        """
        results = {}

        for step in self.execution_steps:
            if "result" in step:
                step_num = step.get("step", "?")
                results[f"step_{step_num}"] = step["result"]

        return results
