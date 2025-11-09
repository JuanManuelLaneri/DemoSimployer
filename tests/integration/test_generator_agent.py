"""
Integration tests for Report Generator Agent

Tests the generator agent that creates summaries and visualizations.
Following TDD approach - tests written first, then implementation.
"""

import pytest
import asyncio
import json
import sys
from pathlib import Path
import os

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from agents.shared.schemas import (
    TaskMessage,
    ResultMessage,
    AgentCapabilities,
    ToolSchema
)


class TestGeneratorAgentBasics:
    """Test basic generator agent functionality"""

    def test_generator_agent_initialization(self):
        """Test that generator agent initializes properly"""
        from agents.generator.agent import ReportGenerator

        agent = ReportGenerator()

        assert agent.agent_name == "report_generator"
        assert agent.agent_version == "1.0.0"
        assert agent.inbox_queue_name == "report_generator.inbox"

    def test_generator_capabilities(self):
        """Test that generator defines correct capabilities"""
        from agents.generator.agent import ReportGenerator

        agent = ReportGenerator()
        capabilities = agent.get_capabilities()

        assert isinstance(capabilities, AgentCapabilities)
        assert "report" in capabilities.description.lower() or "summary" in capabilities.description.lower()
        assert len(capabilities.tools) >= 2

        # Check for generate_summary tool
        summary_tool = next(
            (t for t in capabilities.tools if t.name == "generate_summary"),
            None
        )
        assert summary_tool is not None
        assert "properties" in summary_tool.input_schema

        # Check for create_visualization tool
        viz_tool = next(
            (t for t in capabilities.tools if t.name == "create_visualization"),
            None
        )
        assert viz_tool is not None


class TestSummaryGeneration:
    """Test summary generation logic"""

    def test_generate_basic_summary(self):
        """Test generating summary from analysis data"""
        from agents.generator.agent import ReportGenerator

        agent = ReportGenerator()

        analysis_data = {
            "summary": {
                "total_entries": 100,
                "error_count": 25,
                "error_rate": 0.25,
                "by_level": {"ERROR": 25, "INFO": 60, "WARNING": 15}
            },
            "errors": [
                {"level": "ERROR", "message": "Database connection failed"}
            ]
        }

        result = agent.generate_summary(analysis_data)

        assert "summary" in result
        assert "key_findings" in result
        assert len(result["summary"]) > 0

    def test_summary_includes_statistics(self):
        """Test that summary includes key statistics"""
        from agents.generator.agent import ReportGenerator

        agent = ReportGenerator()

        analysis_data = {
            "summary": {
                "total_entries": 50,
                "error_count": 10,
                "error_rate": 0.2
            }
        }

        result = agent.generate_summary(analysis_data)

        assert result["total_logs"] == 50
        assert result["error_count"] == 10
        assert result["error_rate"] == 0.2

    def test_summary_with_empty_data(self):
        """Test handling empty analysis data"""
        from agents.generator.agent import ReportGenerator

        agent = ReportGenerator()

        result = agent.generate_summary({})

        assert "summary" in result
        assert result["total_logs"] == 0


class TestVisualization:
    """Test visualization creation"""

    def test_create_error_distribution_chart(self):
        """Test creating error distribution bar chart"""
        from agents.generator.agent import ReportGenerator

        agent = ReportGenerator()

        categories = {
            "connection": 10,
            "database": 5,
            "file": 3
        }

        result = agent.create_visualization(categories, chart_type="bar")

        assert "file_path" in result
        assert result["chart_type"] == "bar"
        # Check file was created
        assert Path(result["file_path"]).exists()

        # Cleanup
        if Path(result["file_path"]).exists():
            os.remove(result["file_path"])

    def test_create_level_distribution_chart(self):
        """Test creating log level distribution pie chart"""
        from agents.generator.agent import ReportGenerator

        agent = ReportGenerator()

        by_level = {
            "ERROR": 25,
            "INFO": 60,
            "WARNING": 15
        }

        result = agent.create_visualization(by_level, chart_type="pie")

        assert "file_path" in result
        assert result["chart_type"] == "pie"
        assert Path(result["file_path"]).exists()

        # Cleanup
        if Path(result["file_path"]).exists():
            os.remove(result["file_path"])

    def test_visualization_saves_to_output_dir(self):
        """Test that visualizations are saved to output directory"""
        from agents.generator.agent import ReportGenerator

        agent = ReportGenerator()

        data = {"test": 5}
        result = agent.create_visualization(data)

        file_path = Path(result["file_path"])
        assert file_path.parent.name == "output"

        # Cleanup
        if file_path.exists():
            os.remove(file_path)

    def test_empty_data_visualization(self):
        """Test handling empty data for visualization"""
        from agents.generator.agent import ReportGenerator

        agent = ReportGenerator()

        result = agent.create_visualization({})

        # Should still create a chart (empty or message)
        assert "file_path" in result

        # Cleanup
        if Path(result["file_path"]).exists():
            os.remove(result["file_path"])


@pytest.mark.asyncio
class TestGeneratorTaskHandling:
    """Test task message handling"""

    async def test_handle_generate_summary_task(self):
        """Test handling a generate_summary task"""
        from agents.generator.agent import ReportGenerator

        agent = ReportGenerator()

        analysis_data = {
            "summary": {
                "total_entries": 100,
                "error_count": 20,
                "error_rate": 0.2
            }
        }

        task = TaskMessage(
            message_type="task",
            correlation_id="test-123",
            task_id="task-456",
            sender="orchestrator",
            recipient="report_generator",
            tool="generate_summary",
            input={"analysis_data": analysis_data},
            reply_to="test.reply"
        )

        result = await agent.handle_task(task)

        assert "summary" in result
        assert "key_findings" in result

    async def test_handle_create_visualization_task(self):
        """Test handling a create_visualization task"""
        from agents.generator.agent import ReportGenerator

        agent = ReportGenerator()

        categories = {
            "connection": 10,
            "database": 5
        }

        task = TaskMessage(
            message_type="task",
            correlation_id="test-123",
            task_id="task-456",
            sender="orchestrator",
            recipient="report_generator",
            tool="create_visualization",
            input={"data": categories, "chart_type": "bar"},
            reply_to="test.reply"
        )

        result = await agent.handle_task(task)

        assert "file_path" in result
        assert "chart_type" in result

        # Cleanup
        if Path(result["file_path"]).exists():
            os.remove(result["file_path"])

    async def test_handle_unknown_tool(self):
        """Test handling unknown tool request"""
        from agents.generator.agent import ReportGenerator

        agent = ReportGenerator()

        task = TaskMessage(
            message_type="task",
            correlation_id="test-123",
            task_id="task-456",
            sender="orchestrator",
            recipient="report_generator",
            tool="unknown_tool",
            input={},
            reply_to="test.reply"
        )

        with pytest.raises(ValueError, match="Unknown tool"):
            await agent.handle_task(task)


@pytest.mark.asyncio
class TestAgentToAgentCalls:
    """Test agent-to-agent communication"""

    async def test_decision_to_call_analyzer(self):
        """Test LLM decision to call Log Analyzer when needed"""
        from agents.generator.agent import ReportGenerator

        agent = ReportGenerator()

        # When generating a report without analysis data,
        # should decide to call analyzer
        decision = await agent.should_call_analyzer()

        assert "call_needed" in decision

    async def test_call_analyzer_agent(self):
        """Test calling Log Analyzer agent"""
        from agents.generator.agent import ReportGenerator

        agent = ReportGenerator()

        # This is a placeholder - real implementation would:
        # 1. Publish TaskMessage to log_analyzer.inbox
        # 2. Wait for ResultMessage on reply queue
        # 3. Return analysis result

        # For now, test the structure
        assert hasattr(agent, 'call_agent'), "Agent should have call_agent method from BaseAgent"


@pytest.mark.asyncio
class TestGeneratorIntegration:
    """Test generator integration with orchestrator"""

    async def test_agent_initialization_with_rabbitmq(self, rabbitmq_client):
        """Test agent initializes with RabbitMQ connection"""
        from agents.generator.agent import ReportGenerator

        agent = ReportGenerator()
        agent.rabbitmq = rabbitmq_client
        agent.llm = None  # Don't need LLM for this test

        # Declare queues
        await agent.rabbitmq.declare_queue(agent.inbox_queue_name, durable=True)

        # Should not raise errors
        assert agent.inbox_queue_name == "report_generator.inbox"

    async def test_registration_message_structure(self):
        """Test that registration message has correct structure"""
        from agents.generator.agent import ReportGenerator

        agent = ReportGenerator()
        capabilities = agent.get_capabilities()

        assert capabilities.description is not None
        assert len(capabilities.tools) >= 2

        # Check tool schemas
        for tool in capabilities.tools:
            assert tool.name in ["generate_summary", "create_visualization"]
            assert tool.description is not None
            assert "properties" in tool.input_schema


class TestReportFormatting:
    """Test report formatting and structure"""

    def test_executive_summary_format(self):
        """Test executive summary has proper format"""
        from agents.generator.agent import ReportGenerator

        agent = ReportGenerator()

        analysis_data = {
            "summary": {
                "total_entries": 100,
                "error_count": 25,
                "error_rate": 0.25
            }
        }

        result = agent.generate_summary(analysis_data)

        # Executive summary should be concise
        assert len(result["summary"]) > 0
        assert isinstance(result["summary"], str)

    def test_recommendations_included(self):
        """Test that recommendations are included based on findings"""
        from agents.generator.agent import ReportGenerator

        agent = ReportGenerator()

        analysis_data = {
            "summary": {
                "total_entries": 100,
                "error_count": 50,  # High error rate
                "error_rate": 0.5
            }
        }

        result = agent.generate_summary(analysis_data)

        # Should include recommendations for high error rate
        assert "key_findings" in result


class TestChartTypes:
    """Test different chart type support"""

    def test_bar_chart_creation(self):
        """Test bar chart for categorical data"""
        from agents.generator.agent import ReportGenerator

        agent = ReportGenerator()

        data = {"A": 10, "B": 20, "C": 15}
        result = agent.create_visualization(data, chart_type="bar")

        assert result["chart_type"] == "bar"
        assert Path(result["file_path"]).exists()

        # Cleanup
        os.remove(result["file_path"])

    def test_pie_chart_creation(self):
        """Test pie chart for proportional data"""
        from agents.generator.agent import ReportGenerator

        agent = ReportGenerator()

        data = {"A": 30, "B": 50, "C": 20}
        result = agent.create_visualization(data, chart_type="pie")

        assert result["chart_type"] == "pie"
        assert Path(result["file_path"]).exists()

        # Cleanup
        os.remove(result["file_path"])

    def test_default_chart_type(self):
        """Test default chart type when not specified"""
        from agents.generator.agent import ReportGenerator

        agent = ReportGenerator()

        data = {"X": 5}
        result = agent.create_visualization(data)

        # Should have a default chart type
        assert "chart_type" in result
        assert Path(result["file_path"]).exists()

        # Cleanup
        os.remove(result["file_path"])
