"""
Log Analyzer Agent

Analyzes log data to extract insights, categorize errors, and detect patterns.
- Parse JSON log entries
- Extract errors by level
- Categorize error types
- Generate summary statistics
- Detect PII and call Data Sanitizer when needed
"""

import asyncio
import re
import json
import sys
from pathlib import Path
from typing import Dict, Any, List
from collections import Counter

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from agents.shared.base_agent import BaseAgent
from agents.shared.schemas import (
    AgentCapabilities,
    ToolSchema,
    TaskMessage
)


class LogAnalyzer(BaseAgent):
    """
    Log Analyzer Agent - Analyzes log data for insights.

    Capabilities:
    - Parse JSON log entries
    - Analyze logs by level and generate statistics
    - Categorize errors by pattern/keyword
    - Detect PII in logs
    - Call Data Sanitizer agent when PII detected
    """

    def __init__(self):
        """Initialize Log Analyzer agent"""
        super().__init__(
            agent_name="log_analyzer",
            agent_version="1.0.0"
        )

        # Error categorization patterns
        self.error_patterns = {
            "connection": r'(connection|connect|disconnect|timeout|refused)',
            "database": r'(database|db|sql|query|table)',
            "file": r'(file|directory|path|not found)',
            "permission": r'(permission|access|denied|forbidden|unauthorized)',
            "memory": r'(memory|allocation|oom|out of memory)',
            "network": r'(network|socket|host|dns)',
            "authentication": r'(auth|login|password|credential|token)'
        }

        # PII detection patterns (same as sanitizer)
        self.pii_patterns = {
            "email": r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            "ip_address": r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
            "phone": r'\b(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}\b',
        }

    def get_capabilities(self) -> AgentCapabilities:
        """
        Define agent capabilities.

        Returns:
            AgentCapabilities object
        """
        return AgentCapabilities(
            description="Analyzes log data, categorizes errors, and detects patterns",
            tools=[
                ToolSchema(
                    name="analyze_logs",
                    description="Analyze log entries and generate summary statistics",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "logs": {
                                "type": "array",
                                "description": "Array of log entry objects"
                            }
                        },
                        "required": ["logs"]
                    },
                    output_schema={
                        "type": "object",
                        "properties": {
                            "summary": {
                                "type": "object",
                                "description": "Summary statistics of log analysis"
                            },
                            "errors": {
                                "type": "array",
                                "description": "List of error entries"
                            },
                            "pii_detected": {
                                "type": "boolean",
                                "description": "Whether PII was detected in logs"
                            },
                            "agent_calls_made": {
                                "type": "array",
                                "description": "List of agent-to-agent calls made during analysis (e.g., calling sanitizer for PII removal)"
                            }
                        }
                    }
                ),
                ToolSchema(
                    name="categorize_errors",
                    description="Categorize error log entries by pattern/type",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "logs": {
                                "type": "array",
                                "description": "Array of log entry objects"
                            }
                        },
                        "required": ["logs"]
                    },
                    output_schema={
                        "type": "object",
                        "properties": {
                            "categories": {
                                "type": "object",
                                "description": "Error counts by category"
                            },
                            "total_errors": {
                                "type": "integer",
                                "description": "Total number of errors"
                            }
                        }
                    }
                )
            ]
        )

    def parse_logs(self, logs: List[Any]) -> Dict[str, Any]:
        """
        Parse log entries and validate structure.

        Args:
            logs: List of log entry objects

        Returns:
            Dict containing:
                - total_entries: Total number of entries
                - parsed_successfully: Number of valid entries
                - parsing_errors: Number of invalid entries
                - entries: List of valid log entries
        """
        if not logs:
            return {
                "total_entries": 0,
                "parsed_successfully": 0,
                "parsing_errors": 0,
                "entries": []
            }

        valid_entries = []
        errors = 0

        for log in logs:
            # Validate log entry structure
            if not isinstance(log, dict):
                errors += 1
                continue

            if "level" not in log or "message" not in log:
                errors += 1
                continue

            valid_entries.append(log)

        return {
            "total_entries": len(logs),
            "parsed_successfully": len(valid_entries),
            "parsing_errors": errors,
            "entries": valid_entries
        }

    def analyze_logs(self, logs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Analyze log entries and generate statistics.

        Args:
            logs: List of log entry dicts

        Returns:
            Dict containing:
                - summary: Statistics summary
                - errors: List of error entries
        """
        # Parse logs first
        parsed = self.parse_logs(logs)
        entries = parsed["entries"]

        if not entries:
            return {
                "summary": {
                    "total_entries": 0,
                    "error_count": 0,
                    "error_rate": 0.0,
                    "by_level": {}
                },
                "errors": []
            }

        # Count by level
        level_counts = Counter()
        errors = []

        for entry in entries:
            level = entry.get("level", "UNKNOWN")
            level_counts[level] += 1

            if level == "ERROR":
                errors.append(entry)

        total = len(entries)
        error_count = level_counts.get("ERROR", 0)
        error_rate = error_count / total if total > 0 else 0.0

        return {
            "summary": {
                "total_entries": total,
                "error_count": error_count,
                "error_rate": error_rate,
                "by_level": dict(level_counts)
            },
            "errors": errors
        }

    def categorize_errors(self, logs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Categorize error entries by pattern/keyword.

        Args:
            logs: List of log entry dicts

        Returns:
            Dict containing:
                - categories: Dict of category -> count
                - total_errors: Total error count
        """
        # Parse logs and extract errors
        parsed = self.parse_logs(logs)
        entries = parsed["entries"]

        errors = [e for e in entries if e.get("level") == "ERROR"]

        if not errors:
            return {
                "categories": {},
                "total_errors": 0
            }

        # Categorize by pattern matching
        category_counts = Counter()

        for error in errors:
            message = error.get("message", "").lower()
            categorized = False

            for category, pattern in self.error_patterns.items():
                if re.search(pattern, message, re.IGNORECASE):
                    category_counts[category] += 1
                    categorized = True
                    break  # Only count first matching category

            if not categorized:
                category_counts["uncategorized"] += 1

        return {
            "categories": dict(category_counts),
            "total_errors": len(errors)
        }

    def detect_pii(self, logs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Detect PII in log messages.

        Args:
            logs: List of log entry dicts

        Returns:
            Dict containing:
                - pii_detected: Boolean
                - pii_count: Number of PII items found
                - pii_types: List of PII types detected
        """
        parsed = self.parse_logs(logs)
        entries = parsed["entries"]

        pii_found = []
        pii_types = set()

        for entry in entries:
            message = entry.get("message", "")

            # Check for each PII type
            for pii_type, pattern in self.pii_patterns.items():
                matches = re.findall(pattern, message)
                if matches:
                    pii_found.extend(matches)
                    pii_types.add(pii_type)

        return {
            "pii_detected": len(pii_found) > 0,
            "pii_count": len(pii_found),
            "pii_types": list(pii_types)
        }

    async def should_sanitize(self, logs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Use LLM to decide if logs need sanitization.

        Args:
            logs: List of log entry dicts

        Returns:
            Dict containing:
                - sanitize_needed: Boolean
                - reasoning: LLM reasoning
        """
        # First, do basic PII detection
        pii_result = self.detect_pii(logs)

        if not pii_result["pii_detected"]:
            return {
                "sanitize_needed": False,
                "reasoning": "No PII detected in logs"
            }

        # Future: Use LLM to make more sophisticated decision
        # For now, always recommend sanitization if PII detected
        return {
            "sanitize_needed": True,
            "reasoning": f"Detected {pii_result['pii_count']} PII items of types: {pii_result['pii_types']}"
        }

    async def handle_task(self, task: TaskMessage) -> Dict[str, Any]:
        """
        Handle a task assigned to this agent.

        Args:
            task: TaskMessage to process

        Returns:
            Dict containing task results
        """
        print(f"[ANALYZER] Handling task: {task.tool}")

        if task.tool == "analyze_logs":
            # Extract logs from input
            logs = task.input.get("logs", [])

            print(f"[ANALYZER] Analyzing {len(logs)} log entries...")

            # Check for PII BEFORE analysis
            pii_result = self.detect_pii(logs)
            agent_calls_made = []

            # AGENT-TO-AGENT COMMUNICATION: Call sanitizer if PII detected
            if pii_result["pii_detected"]:
                self.logger.warning(f"PII DETECTED: Found {pii_result['pii_count']} PII items of types: {', '.join(pii_result['pii_types'])}")
                self.logger.info("AGENT-TO-AGENT CALL: Initiating call to data_sanitizer agent")
                print(f"[ANALYZER] Detected {pii_result['pii_count']} PII items ({', '.join(pii_result['pii_types'])})")
                print(f"[ANALYZER] → Calling data_sanitizer agent to clean logs...")

                # Convert logs to JSON string for sanitization
                logs_text = json.dumps(logs, indent=2)
                self.logger.info(f"Prepared {len(logs)} log entries for sanitization (text size: {len(logs_text)} bytes)")

                try:
                    # Call Data Sanitizer agent directly (agent-to-agent)
                    # Simplified: directly call using known agent name
                    self.logger.info("Creating TaskMessage for data_sanitizer.sanitize")
                    print(f"[ANALYZER] Preparing to call data_sanitizer.sanitize...")

                    # Create task message for sanitizer
                    from agents.shared.schemas import TaskMessage
                    import uuid

                    sanitizer_task = TaskMessage(
                        message_type="task",
                        correlation_id=task.correlation_id,
                        sender=self.agent_name,
                        recipient="data_sanitizer",
                        tool="sanitize",
                        input={"text": logs_text},
                        reply_to=self.reply_queue_name,
                        timeout_seconds=60
                    )
                    self.logger.info(f"Created task message with task_id: {sanitizer_task.task_id}")

                    # Create future for response
                    response_future = asyncio.Future()

                    # Handler for sanitizer response
                    async def handle_sanitizer_result(message):
                        async with message.process():
                            try:
                                from agents.shared.schemas import ResultMessage
                                result = ResultMessage.from_json(message.body.decode())
                                if result.task_id == sanitizer_task.task_id:
                                    self.logger.info(f"Received response from data_sanitizer for task {result.task_id} with status: {result.status}")
                                    if not response_future.done():
                                        response_future.set_result(result)
                            except Exception as e:
                                self.logger.error(f"Error processing sanitizer result: {e}", exc_info=True)
                                print(f"[ANALYZER] Error processing sanitizer result: {e}")
                                if not response_future.done():
                                    response_future.set_exception(e)

                    # Consume from reply queue
                    self.logger.info(f"Setting up consumer on reply queue: {self.reply_queue_name}")
                    consumer_tag = await self.rabbitmq.consume(
                        self.reply_queue_name,
                        handle_sanitizer_result
                    )

                    # Send task to sanitizer's inbox
                    self.logger.info(f"Publishing task to data_sanitizer.inbox queue (correlation_id: {task.correlation_id})")
                    await self.rabbitmq.publish(
                        exchange_name="",  # Default exchange for direct queue routing
                        routing_key="data_sanitizer.inbox",
                        message_body=sanitizer_task.to_json(),
                        correlation_id=task.correlation_id,
                        reply_to=self.reply_queue_name
                    )
                    self.logger.info("Task published successfully, waiting for response from data_sanitizer...")
                    print(f"[ANALYZER] Task sent to data_sanitizer, waiting for response...")

                    # Wait for result
                    result_message = await asyncio.wait_for(response_future, timeout=60)
                    self.logger.info(f"Response received from data_sanitizer after {result_message.execution_details.duration_ms:.0f}ms")

                    # Extract result
                    sanitized_result = result_message.result if result_message.status == "success" else None

                    if sanitized_result:
                        # Parse sanitized logs back to objects
                        logs = json.loads(sanitized_result["sanitized_text"])
                        pii_removed_count = len(sanitized_result.get('pii_found', []))
                        self.logger.info(f"SANITIZATION SUCCESS: Received cleaned logs from data_sanitizer, removed {pii_removed_count} PII items")
                        self.logger.info(f"Agent-to-agent call completed successfully (data_sanitizer processed {len(logs)} log entries)")
                        print(f"[ANALYZER] ← Received sanitized data from data_sanitizer")
                        print(f"[ANALYZER] Sanitization complete: removed {pii_removed_count} PII items")

                        # Track the agent-to-agent call
                        agent_calls_made.append({
                            "called_agent": "data_sanitizer",
                            "tool": "sanitize",
                            "reason": f"PII detected in logs ({pii_result['pii_count']} items)",
                            "pii_types": pii_result['pii_types'],
                            "pii_count": pii_result['pii_count'],
                            "sanitization_success": True,
                            "items_removed": len(sanitized_result.get('pii_found', []))
                        })
                    else:
                        self.logger.warning("SANITIZATION FAILED: Sanitizer returned None, proceeding with original logs")
                        print(f"[ANALYZER] Warning: Sanitization returned None, proceeding with original logs")
                        agent_calls_made.append({
                            "called_agent": "data_sanitizer",
                            "tool": "sanitize",
                            "reason": f"PII detected in logs ({pii_result['pii_count']} items)",
                            "pii_types": pii_result['pii_types'],
                            "pii_count": pii_result['pii_count'],
                            "sanitization_success": False,
                            "error": "Sanitizer returned None"
                        })

                except Exception as e:
                    self.logger.error(f"AGENT-TO-AGENT CALL FAILED: Error calling data_sanitizer: {e}", exc_info=True)
                    self.logger.warning("Proceeding with original logs (PII still present)")
                    print(f"[ANALYZER] Error calling sanitizer: {e}")
                    print(f"[ANALYZER] Proceeding with original logs")
                    agent_calls_made.append({
                        "called_agent": "data_sanitizer",
                        "tool": "sanitize",
                        "reason": f"PII detected in logs ({pii_result['pii_count']} items)",
                        "pii_types": pii_result['pii_types'],
                        "pii_count": pii_result['pii_count'],
                        "sanitization_success": False,
                        "error": str(e)
                    })
            else:
                self.logger.info("No PII detected in logs, proceeding directly to analysis")
                print(f"[ANALYZER] No PII detected, proceeding with analysis")

            # Perform analysis (on sanitized logs if PII was found)
            result = self.analyze_logs(logs)
            result["pii_detected"] = pii_result["pii_detected"]

            print(f"[ANALYZER] Analysis complete: {result['summary']}")

            return {
                **result,
                "agent_calls_made": agent_calls_made,  # Track agent-to-agent calls
                "llm_calls": 0,  # No LLM calls for basic analysis
                "reasoning": f"Analyzed {result['summary']['total_entries']} entries, found {result['summary']['error_count']} errors"
            }

        elif task.tool == "categorize_errors":
            # Extract logs from input
            logs = task.input.get("logs", [])

            print(f"[ANALYZER] Categorizing errors in {len(logs)} log entries...")

            # Categorize errors
            result = self.categorize_errors(logs)

            print(f"[ANALYZER] Categorized {result['total_errors']} errors into {len(result['categories'])} categories")

            return {
                **result,
                "llm_calls": 0,
                "reasoning": f"Categorized {result['total_errors']} errors"
            }

        else:
            raise ValueError(f"Unknown tool: {task.tool}")


async def main():
    """Main entry point for running analyzer agent"""
    print("[ANALYZER] Starting Log Analyzer Agent...")

    agent = LogAnalyzer()

    try:
        await agent.start()
    except KeyboardInterrupt:
        print("\n[ANALYZER] Shutting down...")
        await agent.stop()
    except Exception as e:
        print(f"[ANALYZER] Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
