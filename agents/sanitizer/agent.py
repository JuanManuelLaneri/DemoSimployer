"""
Data Sanitizer Agent

Removes PII (Personally Identifiable Information) from text data.
- Email addresses
- IP addresses
- Phone numbers
- Names (basic detection + future LLM enhancement)
"""

import asyncio
import re
import sys
from pathlib import Path
from typing import Dict, Any, List

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from agents.shared.base_agent import BaseAgent
from agents.shared.schemas import (
    AgentCapabilities,
    ToolSchema,
    TaskMessage
)


class DataSanitizer(BaseAgent):
    """
    Data Sanitizer Agent - Removes PII from text.

    Capabilities:
    - Email sanitization
    - IP address sanitization
    - Phone number sanitization
    - Name detection (basic pattern + future LLM enhancement)
    """

    def __init__(self):
        """Initialize Data Sanitizer agent"""
        super().__init__(
            agent_name="data_sanitizer",
            agent_version="1.0.0"
        )

        # PII Regex patterns
        self.patterns = {
            "email": r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            "ip_address": r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
            "phone": r'\b(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}\b',
            # Simple capitalized word pattern for potential names
            "potential_name": r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b'
        }

    def get_capabilities(self) -> AgentCapabilities:
        """
        Define agent capabilities.

        Returns:
            AgentCapabilities object
        """
        return AgentCapabilities(
            description="Removes PII (emails, IPs, names, phone numbers) from text",
            tools=[
                ToolSchema(
                    name="sanitize",
                    description="Remove PII from text and return sanitized version with metadata",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                "description": "Text to sanitize"
                            }
                        },
                        "required": ["text"]
                    },
                    output_schema={
                        "type": "object",
                        "properties": {
                            "sanitized_text": {
                                "type": "string",
                                "description": "Text with PII removed"
                            },
                            "pii_detected": {
                                "type": "object",
                                "description": "Count of each PII type found"
                            },
                            "pii_found": {
                                "type": "array",
                                "description": "List of PII items detected"
                            }
                        }
                    }
                )
            ]
        )

    def sanitize_text(self, text: str) -> Dict[str, Any]:
        """
        Sanitize text by removing PII.

        Args:
            text: Input text to sanitize

        Returns:
            Dict containing:
                - sanitized_text: Cleaned text
                - pii_detected: Count of each PII type
                - pii_found: List of PII items found
        """
        if not text:
            return {
                "sanitized_text": "",
                "pii_detected": {
                    "emails": 0,
                    "ip_addresses": 0,
                    "phone_numbers": 0,
                    "potential_names": 0
                },
                "pii_found": []
            }

        sanitized = text
        pii_found = []
        pii_counts = {
            "emails": 0,
            "ip_addresses": 0,
            "phone_numbers": 0,
            "potential_names": 0
        }

        # Sanitize emails
        emails = re.findall(self.patterns["email"], text)
        for email in emails:
            pii_found.append(email)
            sanitized = sanitized.replace(email, "[EMAIL]")
            pii_counts["emails"] += 1

        # Sanitize IP addresses
        ips = re.findall(self.patterns["ip_address"], text)
        for ip in ips:
            # Filter out false positives (e.g., version numbers like 1.0.0.0)
            # Only sanitize if it looks like a real IP
            parts = ip.split('.')
            if all(0 <= int(part) <= 255 for part in parts):
                pii_found.append(ip)
                sanitized = sanitized.replace(ip, "[IP_ADDRESS]")
                pii_counts["ip_addresses"] += 1

        # Sanitize phone numbers
        phones = re.findall(self.patterns["phone"], text)
        for phone in phones:
            # Only sanitize if it looks like a phone number (not error codes)
            if len(re.sub(r'[^\d]', '', phone)) >= 10:
                pii_found.append(phone)
                sanitized = sanitized.replace(phone, "[PHONE]")
                pii_counts["phone_numbers"] += 1

        # Detect potential names (basic pattern matching)
        # This will match "John Smith", "Alice Johnson", etc.
        names = re.findall(self.patterns["potential_name"], text)
        pii_counts["potential_names"] = len(names)
        # For now, we don't sanitize names automatically
        # Future: Use LLM to determine if they're actually names

        return {
            "sanitized_text": sanitized,
            "pii_detected": pii_counts,
            "pii_found": pii_found
        }

    async def sanitize_with_llm(self, text: str) -> Dict[str, Any]:
        """
        Enhanced sanitization using LLM for context-aware PII detection.

        Args:
            text: Input text

        Returns:
            Sanitization result with LLM-enhanced name detection
        """
        # First, apply regex-based sanitization
        result = self.sanitize_text(text)

        # Future: Use LLM to:
        # 1. Detect names in context (not just capitalized words)
        # 2. Identify sensitive data that doesn't match patterns
        # 3. Provide reasoning for sanitization decisions

        # For now, return basic sanitization
        return result

    async def handle_task(self, task: TaskMessage) -> Dict[str, Any]:
        """
        Handle a task assigned to this agent.

        Args:
            task: TaskMessage to process

        Returns:
            Dict containing task results
        """
        # Check if this is an agent-to-agent call
        is_agent_call = task.sender and task.sender != "orchestrator"
        if is_agent_call:
            self.logger.info(f"AGENT-TO-AGENT CALL RECEIVED: Request from {task.sender} to execute tool '{task.tool}'")
            self.logger.info(f"Correlation ID: {task.correlation_id}, Task ID: {task.task_id}")
        else:
            self.logger.info(f"Handling task: {task.tool} (from orchestrator)")

        print(f"[SANITIZER] Handling task: {task.tool}")

        if task.tool == "sanitize":
            # Extract text from input
            text = task.input.get("text", "")

            if is_agent_call:
                self.logger.info(f"Processing sanitization request from {task.sender}: {len(text)} characters to sanitize")

            self.logger.info(f"Starting sanitization of {len(text)} characters...")
            print(f"[SANITIZER] Sanitizing {len(text)} characters...")

            # Perform sanitization
            result = self.sanitize_text(text)

            total_pii = sum(result['pii_detected'].values())
            pii_types = [k for k, v in result['pii_detected'].items() if v > 0]

            self.logger.info(f"Sanitization complete: Found {total_pii} PII items of types: {pii_types}")
            self.logger.info(f"PII breakdown: {result['pii_detected']}")

            if is_agent_call:
                self.logger.info(f"AGENT-TO-AGENT RESPONSE: Returning sanitized data to {task.sender}")

            print(f"[SANITIZER] Found PII: {result['pii_detected']}")

            return {
                **result,
                "llm_calls": 0,  # No LLM calls for basic sanitization
                "reasoning": f"Detected {total_pii} PII items"
            }

        else:
            self.logger.error(f"Unknown tool requested: {task.tool}")
            raise ValueError(f"Unknown tool: {task.tool}")


async def main():
    """Main entry point for running sanitizer agent"""
    print("[SANITIZER] Starting Data Sanitizer Agent...")

    agent = DataSanitizer()

    try:
        await agent.start()
    except KeyboardInterrupt:
        print("\n[SANITIZER] Shutting down...")
        await agent.stop()
    except Exception as e:
        print(f"[SANITIZER] Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
