"""
Report Generator Agent

Generates executive summaries and visualizations from log analysis data.
- Create executive summaries
- Generate error distribution charts
- Create log level visualizations
- Call Log Analyzer agent when needed
"""

import asyncio
import sys
import json
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from agents.shared.base_agent import BaseAgent
from agents.shared.schemas import (
    AgentCapabilities,
    ToolSchema,
    TaskMessage
)


class ReportGenerator(BaseAgent):
    """
    Report Generator Agent - Creates summaries and visualizations.

    Capabilities:
    - Generate executive summaries from analysis data
    - Create error distribution charts
    - Create log level visualizations
    - Call Log Analyzer agent when analysis data needed
    """

    def __init__(self):
        """Initialize Report Generator agent"""
        super().__init__(
            agent_name="report_generator",
            agent_version="1.0.0"
        )

        # Output directory for generated files
        self.output_dir = Path("output")
        self.output_dir.mkdir(exist_ok=True)

    def get_capabilities(self) -> AgentCapabilities:
        """
        Define agent capabilities.

        Returns:
            AgentCapabilities object
        """
        return AgentCapabilities(
            description="Generates reports with executive summaries and visualizations from log analysis data",
            tools=[
                ToolSchema(
                    name="generate_summary",
                    description="Generate executive summary from log analysis data",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "analysis_data": {
                                "type": "object",
                                "description": "Analysis data from Log Analyzer"
                            }
                        },
                        "required": ["analysis_data"]
                    },
                    output_schema={
                        "type": "object",
                        "properties": {
                            "summary": {
                                "type": "string",
                                "description": "Executive summary text"
                            },
                            "key_findings": {
                                "type": "array",
                                "description": "List of key findings"
                            },
                            "total_logs": {
                                "type": "integer",
                                "description": "Total log entries analyzed"
                            },
                            "error_count": {
                                "type": "integer",
                                "description": "Total errors found"
                            },
                            "error_rate": {
                                "type": "number",
                                "description": "Error rate percentage"
                            },
                            "file_path": {
                                "type": "string",
                                "description": "Path to saved analysis summary JSON file"
                            }
                        }
                    }
                ),
                ToolSchema(
                    name="create_visualization",
                    description="Create visualization chart from data",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "data": {
                                "type": "object",
                                "description": "Data to visualize (key-value pairs)"
                            },
                            "chart_type": {
                                "type": "string",
                                "description": "Type of chart (bar, pie)",
                                "enum": ["bar", "pie"]
                            }
                        },
                        "required": ["data"]
                    },
                    output_schema={
                        "type": "object",
                        "properties": {
                            "file_path": {
                                "type": "string",
                                "description": "Path to generated chart file"
                            },
                            "chart_type": {
                                "type": "string",
                                "description": "Type of chart created"
                            }
                        }
                    }
                )
            ]
        )

    def generate_summary(self, analysis_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate executive summary from analysis data.

        Args:
            analysis_data: Analysis data from Log Analyzer

        Returns:
            Dict containing:
                - summary: Executive summary text
                - key_findings: List of key findings
                - total_logs: Total log entries
                - error_count: Total errors
                - error_rate: Error rate
                - file_path: Path to saved JSON file
        """
        # Handle empty analysis data
        if not analysis_data:
            result = {
                "summary": "No analysis data available.",
                "key_findings": [],
                "total_logs": 0,
                "error_count": 0,
                "error_rate": 0.0,
                "timestamp": datetime.now().isoformat(),
                "raw_analysis_data": {}
            }
        else:
            # Extract summary statistics
            summary_stats = analysis_data.get("summary", {})
            total_logs = summary_stats.get("total_entries", 0)
            error_count = summary_stats.get("error_count", 0)
            error_rate = summary_stats.get("error_rate", 0.0)

            # Generate executive summary
            summary_text = self._create_executive_summary(
                total_logs, error_count, error_rate
            )

            # Extract key findings
            key_findings = self._extract_key_findings(analysis_data)

            result = {
                "summary": summary_text,
                "key_findings": key_findings,
                "total_logs": total_logs,
                "error_count": error_count,
                "error_rate": error_rate,
                "timestamp": datetime.now().isoformat(),
                "raw_analysis_data": analysis_data
            }

        # Save summary to file (always save, even if empty)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"analysis_summary_{timestamp}.json"
        file_path = self.output_dir / filename

        with open(file_path, 'w') as f:
            json.dump(result, f, indent=2)

        print(f"[GENERATOR] Analysis summary saved to: {file_path}")

        # Add file path to result
        result["file_path"] = str(file_path)

        return result

    def _create_executive_summary(
        self,
        total_logs: int,
        error_count: int,
        error_rate: float
    ) -> str:
        """
        Create executive summary text.

        Args:
            total_logs: Total log entries
            error_count: Number of errors
            error_rate: Error rate (0-1)

        Returns:
            Summary text
        """
        # Build summary based on error severity
        if error_rate > 0.5:
            severity = "CRITICAL"
            recommendation = "Immediate investigation required."
        elif error_rate > 0.2:
            severity = "HIGH"
            recommendation = "Review and address errors promptly."
        elif error_rate > 0.05:
            severity = "MODERATE"
            recommendation = "Monitor and investigate as needed."
        else:
            severity = "LOW"
            recommendation = "System operating normally."

        summary = (
            f"Log Analysis Summary: Analyzed {total_logs} log entries. "
            f"Found {error_count} errors ({error_rate*100:.1f}% error rate). "
            f"Severity: {severity}. {recommendation}"
        )

        return summary

    def _extract_key_findings(self, analysis_data: Dict[str, Any]) -> List[str]:
        """
        Extract key findings from analysis data.

        Args:
            analysis_data: Analysis data

        Returns:
            List of key finding strings
        """
        findings = []

        summary = analysis_data.get("summary", {})

        # Finding: Error rate
        error_rate = summary.get("error_rate", 0)
        if error_rate > 0:
            findings.append(f"Error rate: {error_rate*100:.1f}%")

        # Finding: Log level distribution
        by_level = summary.get("by_level", {})
        if by_level:
            top_level = max(by_level, key=by_level.get)
            findings.append(f"Most common log level: {top_level} ({by_level[top_level]} entries)")

        # Future: Add more sophisticated findings using LLM

        return findings

    def create_visualization(
        self,
        data: Dict[str, Any],
        chart_type: str = "bar"
    ) -> Dict[str, Any]:
        """
        Create visualization chart from data.

        Args:
            data: Data to visualize (key-value pairs)
            chart_type: Type of chart ("bar" or "pie")

        Returns:
            Dict containing:
                - file_path: Path to generated chart
                - chart_type: Type of chart created
        """
        if not data:
            # Create empty chart with message
            data = {"No Data": 1}

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"chart_{chart_type}_{timestamp}.png"
        file_path = self.output_dir / filename

        # Create figure
        plt.figure(figsize=(10, 6))

        if chart_type == "pie":
            # Create pie chart
            plt.pie(
                data.values(),
                labels=data.keys(),
                autopct='%1.1f%%',
                startangle=90
            )
            plt.title("Distribution")
        else:
            # Create bar chart (default)
            plt.bar(data.keys(), data.values())
            plt.xlabel("Category")
            plt.ylabel("Count")
            plt.title("Distribution by Category")
            plt.xticks(rotation=45, ha='right')

        plt.tight_layout()
        plt.savefig(file_path)
        plt.close()

        print(f"[GENERATOR] Chart saved to: {file_path}")

        return {
            "file_path": str(file_path),
            "chart_type": chart_type
        }

    async def should_call_analyzer(self) -> Dict[str, Any]:
        """
        Decide if Log Analyzer should be called.

        Returns:
            Dict containing:
                - call_needed: Boolean
                - reasoning: Explanation
        """
        # Future: Use LLM to make sophisticated decision
        # For now, simple logic
        return {
            "call_needed": True,
            "reasoning": "Analysis data required for report generation"
        }

    async def handle_task(self, task: TaskMessage) -> Dict[str, Any]:
        """
        Handle a task assigned to this agent.

        Args:
            task: TaskMessage to process

        Returns:
            Dict containing task results
        """
        print(f"[GENERATOR] Handling task: {task.tool}")

        if task.tool == "generate_summary":
            # Extract analysis data from input
            analysis_data = task.input.get("analysis_data", {})

            print(f"[GENERATOR] Generating summary from analysis data...")

            # Generate summary
            result = self.generate_summary(analysis_data)

            print(f"[GENERATOR] Summary generated: {result['total_logs']} logs, {result['error_count']} errors")

            return {
                **result,
                "llm_calls": 0,  # No LLM calls for basic summary
                "reasoning": f"Generated summary for {result['total_logs']} log entries"
            }

        elif task.tool == "create_visualization":
            # Extract data and chart type from input
            data = task.input.get("data", {})
            chart_type = task.input.get("chart_type", "bar")

            print(f"[GENERATOR] Creating {chart_type} chart...")

            # Create visualization
            result = self.create_visualization(data, chart_type)

            print(f"[GENERATOR] Chart created: {result['file_path']}")

            return {
                **result,
                "llm_calls": 0,
                "reasoning": f"Created {chart_type} chart with {len(data)} categories"
            }

        else:
            raise ValueError(f"Unknown tool: {task.tool}")


async def main():
    """Main entry point for running generator agent"""
    print("[GENERATOR] Starting Report Generator Agent...")

    agent = ReportGenerator()

    try:
        await agent.start()
    except KeyboardInterrupt:
        print("\n[GENERATOR] Shutting down...")
        await agent.stop()
    except Exception as e:
        print(f"[GENERATOR] Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
