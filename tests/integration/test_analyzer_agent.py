"""
Integration tests for Log Analyzer Agent

Tests the analyzer agent that parses and analyzes log data.
Following TDD approach - tests written first, then implementation.
"""

import pytest
import asyncio
import json
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


class TestAnalyzerAgentBasics:
    """Test basic analyzer agent functionality"""

    def test_analyzer_agent_initialization(self):
        """Test that analyzer agent initializes properly"""
        from agents.analyzer.agent import LogAnalyzer

        agent = LogAnalyzer()

        assert agent.agent_name == "log_analyzer"
        assert agent.agent_version == "1.0.0"
        assert agent.inbox_queue_name == "log_analyzer.inbox"

    def test_analyzer_capabilities(self):
        """Test that analyzer defines correct capabilities"""
        from agents.analyzer.agent import LogAnalyzer

        agent = LogAnalyzer()
        capabilities = agent.get_capabilities()

        assert isinstance(capabilities, AgentCapabilities)
        assert "log" in capabilities.description.lower()
        assert len(capabilities.tools) >= 2

        # Check for analyze_logs tool
        analyze_tool = next(
            (t for t in capabilities.tools if t.name == "analyze_logs"),
            None
        )
        assert analyze_tool is not None
        assert "properties" in analyze_tool.input_schema
        assert "logs" in analyze_tool.input_schema["properties"]

        # Check for categorize_errors tool
        categorize_tool = next(
            (t for t in capabilities.tools if t.name == "categorize_errors"),
            None
        )
        assert categorize_tool is not None


class TestLogParsingLogic:
    """Test log parsing and analysis logic"""

    def test_parse_json_logs(self):
        """Test parsing JSON log entries"""
        from agents.analyzer.agent import LogAnalyzer

        agent = LogAnalyzer()

        logs = [
            {"level": "INFO", "message": "Server started", "timestamp": "2025-01-01T10:00:00"},
            {"level": "ERROR", "message": "Connection failed", "timestamp": "2025-01-01T10:01:00"}
        ]

        result = agent.parse_logs(logs)

        assert result["total_entries"] == 2
        assert result["parsed_successfully"] == 2
        assert len(result["entries"]) == 2

    def test_extract_errors_by_level(self):
        """Test extracting errors by log level"""
        from agents.analyzer.agent import LogAnalyzer

        agent = LogAnalyzer()

        logs = [
            {"level": "INFO", "message": "Server started"},
            {"level": "ERROR", "message": "Connection failed"},
            {"level": "ERROR", "message": "Database timeout"},
            {"level": "WARNING", "message": "Memory high"},
            {"level": "INFO", "message": "Request processed"}
        ]

        result = agent.analyze_logs(logs)

        assert result["summary"]["total_entries"] == 5
        assert result["summary"]["by_level"]["ERROR"] == 2
        assert result["summary"]["by_level"]["INFO"] == 2
        assert result["summary"]["by_level"]["WARNING"] == 1

    def test_categorize_error_types(self):
        """Test categorizing errors by type/pattern"""
        from agents.analyzer.agent import LogAnalyzer

        agent = LogAnalyzer()

        logs = [
            {"level": "ERROR", "message": "Connection failed to database"},
            {"level": "ERROR", "message": "Connection timeout"},
            {"level": "ERROR", "message": "File not found: config.json"},
            {"level": "ERROR", "message": "Memory allocation failed"}
        ]

        result = agent.categorize_errors(logs)

        assert "categories" in result
        # Should detect connection-related errors
        assert any("connection" in cat.lower() for cat in result["categories"])
        assert result["total_errors"] == 4

    def test_generate_statistics(self):
        """Test generating summary statistics"""
        from agents.analyzer.agent import LogAnalyzer

        agent = LogAnalyzer()

        logs = [
            {"level": "INFO", "message": "Request 1"},
            {"level": "INFO", "message": "Request 2"},
            {"level": "ERROR", "message": "Error 1"},
            {"level": "ERROR", "message": "Error 2"},
            {"level": "ERROR", "message": "Error 3"},
            {"level": "WARNING", "message": "Warning 1"}
        ]

        result = agent.analyze_logs(logs)

        assert result["summary"]["total_entries"] == 6
        assert result["summary"]["error_count"] == 3
        assert result["summary"]["error_rate"] == 0.5  # 3 errors / 6 total

    def test_handle_malformed_logs(self):
        """Test handling malformed log entries"""
        from agents.analyzer.agent import LogAnalyzer

        agent = LogAnalyzer()

        logs = [
            {"level": "INFO", "message": "Valid log"},
            {"invalid": "structure"},  # Missing level and message
            {"level": "ERROR"},  # Missing message
            None,  # Null entry
            "not a dict"  # Wrong type
        ]

        result = agent.parse_logs(logs)

        # Should handle gracefully
        assert result["total_entries"] == 5
        assert result["parsed_successfully"] == 1  # Only first one is valid
        assert result["parsing_errors"] == 4

    def test_empty_logs(self):
        """Test handling empty log list"""
        from agents.analyzer.agent import LogAnalyzer

        agent = LogAnalyzer()

        result = agent.analyze_logs([])

        assert result["summary"]["total_entries"] == 0
        assert result["summary"]["error_count"] == 0


class TestPIIDetection:
    """Test PII detection in logs"""

    def test_detect_pii_in_logs(self):
        """Test detecting PII in log messages"""
        from agents.analyzer.agent import LogAnalyzer

        agent = LogAnalyzer()

        logs = [
            {"level": "INFO", "message": "User john.doe@example.com logged in"},
            {"level": "ERROR", "message": "Connection from 192.168.1.100 failed"}
        ]

        result = agent.detect_pii(logs)

        assert result["pii_detected"] is True
        assert result["pii_count"] >= 2
        assert any("email" in item.lower() for item in result["pii_types"])

    def test_no_pii_in_clean_logs(self):
        """Test logs without PII"""
        from agents.analyzer.agent import LogAnalyzer

        agent = LogAnalyzer()

        logs = [
            {"level": "INFO", "message": "Server started successfully"},
            {"level": "INFO", "message": "Request processed"}
        ]

        result = agent.detect_pii(logs)

        assert result["pii_detected"] is False
        assert result["pii_count"] == 0


@pytest.mark.asyncio
class TestAnalyzerTaskHandling:
    """Test task message handling"""

    async def test_handle_analyze_logs_task(self):
        """Test handling an analyze_logs task"""
        from agents.analyzer.agent import LogAnalyzer

        agent = LogAnalyzer()

        logs = [
            {"level": "ERROR", "message": "Database connection failed"},
            {"level": "INFO", "message": "Request processed"}
        ]

        task = TaskMessage(
            message_type="task",
            correlation_id="test-123",
            task_id="task-456",
            sender="orchestrator",
            recipient="log_analyzer",
            tool="analyze_logs",
            input={"logs": logs},
            reply_to="test.reply"
        )

        result = await agent.handle_task(task)

        assert "summary" in result
        assert result["summary"]["total_entries"] == 2
        assert result["summary"]["error_count"] == 1

    async def test_handle_categorize_errors_task(self):
        """Test handling a categorize_errors task"""
        from agents.analyzer.agent import LogAnalyzer

        agent = LogAnalyzer()

        logs = [
            {"level": "ERROR", "message": "Connection timeout"},
            {"level": "ERROR", "message": "Connection refused"}
        ]

        task = TaskMessage(
            message_type="task",
            correlation_id="test-123",
            task_id="task-456",
            sender="orchestrator",
            recipient="log_analyzer",
            tool="categorize_errors",
            input={"logs": logs},
            reply_to="test.reply"
        )

        result = await agent.handle_task(task)

        assert "categories" in result
        assert result["total_errors"] == 2

    async def test_handle_task_with_empty_logs(self):
        """Test handling task with empty logs"""
        from agents.analyzer.agent import LogAnalyzer

        agent = LogAnalyzer()

        task = TaskMessage(
            message_type="task",
            correlation_id="test-123",
            task_id="task-456",
            sender="orchestrator",
            recipient="log_analyzer",
            tool="analyze_logs",
            input={"logs": []},
            reply_to="test.reply"
        )

        result = await agent.handle_task(task)

        assert result["summary"]["total_entries"] == 0

    async def test_handle_unknown_tool(self):
        """Test handling unknown tool request"""
        from agents.analyzer.agent import LogAnalyzer

        agent = LogAnalyzer()

        task = TaskMessage(
            message_type="task",
            correlation_id="test-123",
            task_id="task-456",
            sender="orchestrator",
            recipient="log_analyzer",
            tool="unknown_tool",
            input={},
            reply_to="test.reply"
        )

        with pytest.raises(ValueError, match="Unknown tool"):
            await agent.handle_task(task)


@pytest.mark.asyncio
class TestAgentToAgentCalls:
    """Test agent-to-agent communication"""

    async def test_decision_to_call_sanitizer(self):
        """Test LLM decision to call Data Sanitizer when PII detected"""
        from agents.analyzer.agent import LogAnalyzer

        agent = LogAnalyzer()

        logs = [
            {"level": "ERROR", "message": "User john.doe@example.com authentication failed"},
            {"level": "INFO", "message": "Server started"}
        ]

        # This would use LLM to decide if sanitization is needed
        decision = await agent.should_sanitize(logs)

        assert "sanitize_needed" in decision
        # If PII is detected, should recommend sanitization

    async def test_call_sanitizer_agent(self):
        """Test calling Data Sanitizer agent"""
        from agents.analyzer.agent import LogAnalyzer

        agent = LogAnalyzer()

        # Mock the agent call (will be real in integration)
        log_text = "User email: test@example.com logged in from 192.168.1.1"

        # This is a placeholder - real implementation would:
        # 1. Publish TaskMessage to sanitizer.inbox
        # 2. Wait for ResultMessage on reply queue
        # 3. Return sanitized result

        # For now, test the structure
        assert hasattr(agent, 'call_agent'), "Agent should have call_agent method from BaseAgent"


@pytest.mark.asyncio
class TestAnalyzerIntegration:
    """Test analyzer integration with orchestrator"""

    async def test_agent_initialization_with_rabbitmq(self, rabbitmq_client):
        """Test agent initializes with RabbitMQ connection"""
        from agents.analyzer.agent import LogAnalyzer

        agent = LogAnalyzer()
        agent.rabbitmq = rabbitmq_client
        agent.llm = None  # Don't need LLM for this test

        # Declare queues
        await agent.rabbitmq.declare_queue(agent.inbox_queue_name, durable=True)

        # Should not raise errors
        assert agent.inbox_queue_name == "log_analyzer.inbox"

    async def test_registration_message_structure(self):
        """Test that registration message has correct structure"""
        from agents.analyzer.agent import LogAnalyzer

        agent = LogAnalyzer()
        capabilities = agent.get_capabilities()

        assert capabilities.description is not None
        assert len(capabilities.tools) >= 2

        # Check tool schemas
        for tool in capabilities.tools:
            assert tool.name in ["analyze_logs", "categorize_errors"]
            assert tool.description is not None
            assert "properties" in tool.input_schema


class TestErrorCategorization:
    """Test error categorization logic"""

    def test_categorize_by_keywords(self):
        """Test categorization using keyword patterns"""
        from agents.analyzer.agent import LogAnalyzer

        agent = LogAnalyzer()

        logs = [
            {"level": "ERROR", "message": "Database connection timeout"},
            {"level": "ERROR", "message": "Database query failed"},
            {"level": "ERROR", "message": "File not found"},
            {"level": "ERROR", "message": "Permission denied"}
        ]

        result = agent.categorize_errors(logs)

        # Should group database errors together
        categories = result["categories"]
        assert len(categories) >= 1

    def test_uncategorized_errors(self):
        """Test handling of uncategorized errors"""
        from agents.analyzer.agent import LogAnalyzer

        agent = LogAnalyzer()

        logs = [
            {"level": "ERROR", "message": "Something went wrong"},
            {"level": "ERROR", "message": "Unknown error occurred"}
        ]

        result = agent.categorize_errors(logs)

        # Should still categorize, even if generic
        assert "total_errors" in result
        assert result["total_errors"] == 2


class TestLogStatistics:
    """Test statistics generation"""

    def test_time_based_analysis(self):
        """Test analyzing logs by time if timestamps present"""
        from agents.analyzer.agent import LogAnalyzer

        agent = LogAnalyzer()

        logs = [
            {"level": "ERROR", "message": "Error 1", "timestamp": "2025-01-01T10:00:00"},
            {"level": "ERROR", "message": "Error 2", "timestamp": "2025-01-01T10:05:00"},
            {"level": "INFO", "message": "Info 1", "timestamp": "2025-01-01T10:10:00"}
        ]

        result = agent.analyze_logs(logs)

        # Should handle timestamps if present
        assert result["summary"]["total_entries"] == 3

    def test_component_analysis(self):
        """Test analyzing logs by component if field present"""
        from agents.analyzer.agent import LogAnalyzer

        agent = LogAnalyzer()

        logs = [
            {"level": "ERROR", "message": "DB error", "component": "database"},
            {"level": "ERROR", "message": "API error", "component": "api"},
            {"level": "ERROR", "message": "DB timeout", "component": "database"}
        ]

        result = agent.analyze_logs(logs)

        # Should handle component field if present
        assert result["summary"]["total_entries"] == 3
        # Future: might include component breakdown
