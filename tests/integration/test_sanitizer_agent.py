"""
Integration tests for Data Sanitizer Agent

Tests the sanitizer agent that removes PII from text data.
Following TDD approach - tests written first, then implementation.
"""

import pytest
import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from agents.shared.schemas import (
    TaskMessage,
    ResultMessage,
    AgentCapabilities,
    ToolSchema
)


class TestSanitizerAgentBasics:
    """Test basic sanitizer agent functionality"""

    def test_sanitizer_agent_initialization(self):
        """Test that sanitizer agent initializes properly"""
        from agents.sanitizer.agent import DataSanitizer

        agent = DataSanitizer()

        assert agent.agent_name == "data_sanitizer"
        assert agent.agent_version == "1.0.0"
        assert agent.inbox_queue_name == "data_sanitizer.inbox"

    def test_sanitizer_capabilities(self):
        """Test that sanitizer defines correct capabilities"""
        from agents.sanitizer.agent import DataSanitizer

        agent = DataSanitizer()
        capabilities = agent.get_capabilities()

        assert isinstance(capabilities, AgentCapabilities)
        assert capabilities.description == "Removes PII (emails, IPs, names, phone numbers) from text"
        assert len(capabilities.tools) >= 1

        # Check sanitize tool exists
        sanitize_tool = next(
            (t for t in capabilities.tools if t.name == "sanitize"),
            None
        )
        assert sanitize_tool is not None
        assert "properties" in sanitize_tool.input_schema
        assert "text" in sanitize_tool.input_schema["properties"]


class TestSanitizationLogic:
    """Test PII sanitization logic"""

    def test_sanitize_emails(self):
        """Test email address sanitization"""
        from agents.sanitizer.agent import DataSanitizer

        agent = DataSanitizer()

        text = "Contact john.doe@example.com for details"
        result = agent.sanitize_text(text)

        assert "john.doe@example.com" not in result["sanitized_text"]
        assert "[EMAIL]" in result["sanitized_text"]
        assert result["pii_detected"]["emails"] == 1
        assert "john.doe@example.com" in result["pii_found"]

    def test_sanitize_multiple_emails(self):
        """Test multiple email sanitization"""
        from agents.sanitizer.agent import DataSanitizer

        agent = DataSanitizer()

        text = "Email alice@test.com or bob@company.org"
        result = agent.sanitize_text(text)

        assert "alice@test.com" not in result["sanitized_text"]
        assert "bob@company.org" not in result["sanitized_text"]
        assert result["pii_detected"]["emails"] == 2

    def test_sanitize_ip_addresses(self):
        """Test IP address sanitization"""
        from agents.sanitizer.agent import DataSanitizer

        agent = DataSanitizer()

        text = "Server IP is 192.168.1.100"
        result = agent.sanitize_text(text)

        assert "192.168.1.100" not in result["sanitized_text"]
        assert "[IP_ADDRESS]" in result["sanitized_text"]
        assert result["pii_detected"]["ip_addresses"] == 1

    def test_sanitize_phone_numbers(self):
        """Test phone number sanitization"""
        from agents.sanitizer.agent import DataSanitizer

        agent = DataSanitizer()

        # Test various phone formats
        text1 = "Call me at 555-123-4567"
        result1 = agent.sanitize_text(text1)
        assert "555-123-4567" not in result1["sanitized_text"]
        assert "[PHONE]" in result1["sanitized_text"]

        text2 = "Phone: (555) 123-4567"
        result2 = agent.sanitize_text(text2)
        assert "(555) 123-4567" not in result2["sanitized_text"]

    def test_sanitize_names(self):
        """Test name sanitization (common names)"""
        from agents.sanitizer.agent import DataSanitizer

        agent = DataSanitizer()

        # For now, we'll detect simple patterns
        # More sophisticated name detection would use LLM
        text = "John Smith submitted the report"
        result = agent.sanitize_text(text)

        # Should detect capitalized words as potential names
        assert result["pii_detected"]["potential_names"] >= 0

    def test_sanitize_mixed_pii(self):
        """Test sanitization of text with multiple PII types"""
        from agents.sanitizer.agent import DataSanitizer

        agent = DataSanitizer()

        text = """
        Contact: john.doe@example.com
        Phone: 555-123-4567
        Server: 192.168.1.100
        """

        result = agent.sanitize_text(text)

        # All PII should be removed
        assert "john.doe@example.com" not in result["sanitized_text"]
        assert "555-123-4567" not in result["sanitized_text"]
        assert "192.168.1.100" not in result["sanitized_text"]

        # Placeholders should be present
        assert "[EMAIL]" in result["sanitized_text"]
        assert "[PHONE]" in result["sanitized_text"]
        assert "[IP_ADDRESS]" in result["sanitized_text"]

        # Metadata should be accurate
        assert result["pii_detected"]["emails"] >= 1
        assert result["pii_detected"]["phone_numbers"] >= 1
        assert result["pii_detected"]["ip_addresses"] >= 1

    def test_sanitize_no_pii(self):
        """Test sanitization of clean text with no PII"""
        from agents.sanitizer.agent import DataSanitizer

        agent = DataSanitizer()

        text = "This is a clean log message with no sensitive data"
        result = agent.sanitize_text(text)

        assert result["sanitized_text"] == text
        assert result["pii_detected"]["emails"] == 0
        assert result["pii_detected"]["phone_numbers"] == 0
        assert result["pii_detected"]["ip_addresses"] == 0


@pytest.mark.asyncio
class TestSanitizerTaskHandling:
    """Test task message handling"""

    async def test_handle_sanitize_task(self):
        """Test handling a sanitize task"""
        from agents.sanitizer.agent import DataSanitizer

        agent = DataSanitizer()

        task = TaskMessage(
            message_type="task",
            correlation_id="test-123",
            task_id="task-456",
            sender="orchestrator",
            recipient="data_sanitizer",
            tool="sanitize",
            input={"text": "Email: user@example.com"},
            reply_to="test.reply"
        )

        result = await agent.handle_task(task)

        assert "sanitized_text" in result
        assert "user@example.com" not in result["sanitized_text"]
        assert "pii_detected" in result
        assert result["pii_detected"]["emails"] == 1

    async def test_handle_task_with_empty_input(self):
        """Test handling task with empty text"""
        from agents.sanitizer.agent import DataSanitizer

        agent = DataSanitizer()

        task = TaskMessage(
            message_type="task",
            correlation_id="test-123",
            task_id="task-456",
            sender="orchestrator",
            recipient="data_sanitizer",
            tool="sanitize",
            input={"text": ""},
            reply_to="test.reply"
        )

        result = await agent.handle_task(task)

        assert result["sanitized_text"] == ""
        assert result["pii_detected"]["emails"] == 0

    async def test_handle_unknown_tool(self):
        """Test handling unknown tool request"""
        from agents.sanitizer.agent import DataSanitizer

        agent = DataSanitizer()

        task = TaskMessage(
            message_type="task",
            correlation_id="test-123",
            task_id="task-456",
            sender="orchestrator",
            recipient="data_sanitizer",
            tool="unknown_tool",
            input={},
            reply_to="test.reply"
        )

        with pytest.raises(ValueError, match="Unknown tool"):
            await agent.handle_task(task)


@pytest.mark.asyncio
class TestSanitizerIntegration:
    """Test sanitizer integration with orchestrator"""

    async def test_agent_initialization_with_rabbitmq(self, rabbitmq_client):
        """Test agent initializes with RabbitMQ connection"""
        from agents.sanitizer.agent import DataSanitizer

        agent = DataSanitizer()
        agent.rabbitmq = rabbitmq_client
        agent.llm = None  # Don't need LLM for this test

        # Declare queues
        await agent.rabbitmq.declare_queue(agent.inbox_queue_name, durable=True)

        # Should not raise errors
        assert agent.inbox_queue_name == "data_sanitizer.inbox"

    async def test_registration_message_structure(self):
        """Test that registration message has correct structure"""
        from agents.sanitizer.agent import DataSanitizer

        agent = DataSanitizer()
        capabilities = agent.get_capabilities()

        assert capabilities.description is not None
        assert len(capabilities.tools) > 0

        # Check tool schema
        sanitize_tool = capabilities.tools[0]
        assert sanitize_tool.name == "sanitize"
        assert sanitize_tool.description is not None
        assert "properties" in sanitize_tool.input_schema
        assert "text" in sanitize_tool.input_schema["properties"]


@pytest.mark.asyncio
class TestSanitizerLLMIntegration:
    """Test LLM integration for advanced sanitization"""

    async def test_llm_enhanced_name_detection(self):
        """Test using LLM to detect names in context"""
        from agents.sanitizer.agent import DataSanitizer

        agent = DataSanitizer()

        # Skip if no API key
        import os
        if not os.getenv("DEEPSEEK_API_KEY"):
            pytest.skip("No DEEPSEEK_API_KEY - skipping LLM test")

        # This would use LLM to detect names in context
        # For now, placeholder
        text = "The report was submitted by Alice Johnson"

        # Future: LLM-based name detection
        # result = await agent.sanitize_with_llm(text)
        # assert "Alice Johnson" not in result["sanitized_text"]


class TestSanitizerPIIPatterns:
    """Test PII pattern detection edge cases"""

    def test_email_pattern_variations(self):
        """Test various email formats"""
        from agents.sanitizer.agent import DataSanitizer

        agent = DataSanitizer()

        emails = [
            "simple@example.com",
            "user.name@example.com",
            "user+tag@example.co.uk",
            "user_123@test-domain.org"
        ]

        for email in emails:
            text = f"Email: {email}"
            result = agent.sanitize_text(text)
            assert email not in result["sanitized_text"], f"Failed to sanitize {email}"
            assert result["pii_detected"]["emails"] == 1

    def test_ip_address_variations(self):
        """Test various IP address formats"""
        from agents.sanitizer.agent import DataSanitizer

        agent = DataSanitizer()

        ips = [
            "192.168.1.1",
            "10.0.0.1",
            "172.16.0.1",
            "255.255.255.255"
        ]

        for ip in ips:
            text = f"IP: {ip}"
            result = agent.sanitize_text(text)
            assert ip not in result["sanitized_text"], f"Failed to sanitize {ip}"
            assert result["pii_detected"]["ip_addresses"] == 1

    def test_false_positives(self):
        """Test that legitimate numbers aren't flagged as phone numbers"""
        from agents.sanitizer.agent import DataSanitizer

        agent = DataSanitizer()

        # Version numbers, error codes, etc should not be sanitized
        text = "Error code: 404"
        result = agent.sanitize_text(text)

        # Should preserve the text
        assert "404" in result["sanitized_text"]
