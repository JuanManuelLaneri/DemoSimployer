"""
Agent Registry - In-memory agent registration and discovery

Manages agent registration, capabilities, and service discovery.
Thread-safe for concurrent access.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, UTC
from threading import Lock
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agents.shared.schemas import RegistrationMessage


class AgentRegistry:
    """
    In-memory registry for agent registration and service discovery.

    Stores agent metadata including:
    - Agent name (unique identifier)
    - Capabilities (list of tools/functions)
    - Queue names (for task routing)
    - Status (active, inactive)
    - Last seen timestamp
    """

    def __init__(self):
        """Initialize empty registry with thread-safe lock"""
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._lock = Lock()

    def register(self, registration: RegistrationMessage) -> None:
        """
        Register or update an agent in the registry.

        Args:
            registration: RegistrationMessage with agent details

        Updates last_seen timestamp on every registration.
        Extracts tool names from AgentCapabilities for easier searching.
        """
        with self._lock:
            # Extract tool names from capabilities for easier searching
            tool_names = [tool.name for tool in registration.capabilities.tools]

            agent_info = {
                "agent_name": registration.agent_name,
                "capabilities": tool_names,  # Store as list of tool names
                "capabilities_full": registration.capabilities,  # Store full object too
                "queue_name": registration.queue_name,
                "reply_queue_name": registration.reply_queue_name,
                "status": "active",
                "last_seen": datetime.now(UTC),
                "registered_at": self._agents.get(
                    registration.agent_name, {}
                ).get("registered_at", datetime.now(UTC))
            }

            self._agents[registration.agent_name] = agent_info

    def get_agent(self, agent_name: str) -> Optional[Dict[str, Any]]:
        """
        Get agent information by name.

        Args:
            agent_name: Name of the agent to retrieve

        Returns:
            Agent info dict or None if not found
        """
        with self._lock:
            return self._agents.get(agent_name)

    def list_all(self) -> List[str]:
        """
        List all registered agent names.

        Returns:
            List of agent names
        """
        with self._lock:
            return list(self._agents.keys())

    def find_by_capability(self, capability: str) -> List[Dict[str, Any]]:
        """
        Find all agents that have a specific capability.

        Args:
            capability: Capability to search for

        Returns:
            List of agent info dicts that have the capability
        """
        with self._lock:
            matching_agents = []
            for agent_info in self._agents.values():
                if capability in agent_info["capabilities"]:
                    matching_agents.append(agent_info.copy())
            return matching_agents

    def unregister(self, agent_name: str) -> bool:
        """
        Remove an agent from the registry.

        Args:
            agent_name: Name of agent to remove

        Returns:
            True if agent was removed, False if not found
        """
        with self._lock:
            if agent_name in self._agents:
                del self._agents[agent_name]
                return True
            return False

    def mark_inactive(self, agent_name: str) -> bool:
        """
        Mark an agent as inactive (without removing it).

        Args:
            agent_name: Name of agent to mark inactive

        Returns:
            True if agent was marked inactive, False if not found
        """
        with self._lock:
            if agent_name in self._agents:
                self._agents[agent_name]["status"] = "inactive"
                return True
            return False

    def get_all_capabilities(self) -> List[str]:
        """
        Get a unique list of all capabilities across all agents.

        Returns:
            Sorted list of unique capabilities
        """
        with self._lock:
            all_caps = set()
            for agent_info in self._agents.values():
                all_caps.update(agent_info["capabilities"])
            return sorted(list(all_caps))

    def get_active_agents(self) -> List[Dict[str, Any]]:
        """
        Get all agents with status='active'.

        Returns:
            List of active agent info dicts
        """
        with self._lock:
            return [
                agent_info.copy()
                for agent_info in self._agents.values()
                if agent_info["status"] == "active"
            ]

    def health_check(self, timeout_seconds: int = 300) -> Dict[str, Any]:
        """
        Check health of registered agents based on last_seen timestamp.

        Args:
            timeout_seconds: Number of seconds before marking agent as stale

        Returns:
            Dict with health summary
        """
        with self._lock:
            now = datetime.now(UTC)
            active = 0
            stale = 0
            inactive = 0

            for agent_info in self._agents.values():
                if agent_info["status"] == "inactive":
                    inactive += 1
                    continue

                time_since_seen = (now - agent_info["last_seen"]).total_seconds()
                if time_since_seen > timeout_seconds:
                    stale += 1
                else:
                    active += 1

            return {
                "total_agents": len(self._agents),
                "active": active,
                "stale": stale,
                "inactive": inactive,
                "timestamp": now
            }
