"""
DeskPilot — Agent Registry
Manages loading, saving, validating, and querying agent configurations from the agents/ directory.
Strictly enforces the schema defined in PROJECT_BRIEF.md Section 6.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from backend.config.settings import AGENTS_DIR
from backend.utils.logger import get_logger

logger = get_logger("agent.registry")

REQUIRED_FIELDS = {
    "id", "name", "description", "icon", "color",
    "persona", "allowed_tools", "category", "created_by",
    "created_at", "status"
}

ALLOWED_CATEGORIES = {"default", "template", "custom"}


class AgentRegistry:
    """
    Registry for managing all agents (default, template, and custom).
    """

    def __init__(self, agents_dir: Path = AGENTS_DIR):
        self.agents_dir = agents_dir
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        self._runtime_status: Dict[str, str] = {}  # In-memory tracking e.g. "running"

    def set_agent_status(self, agent_id: str, status: str) -> None:
        """Set in-memory runtime status (e.g. 'running', 'active', 'idle')."""
        self._runtime_status[agent_id] = status

    def get_agent_status(self, agent_id: str, default: str = "active") -> str:
        return self._runtime_status.get(agent_id, default)

    def validate_agent_schema(self, data: dict) -> Tuple[bool, str]:
        """
        Validates an agent definition dictionary against Section 6 schema.
        Returns (is_valid, error_message).
        """
        if not isinstance(data, dict):
            return False, "Agent data must be a JSON object"

        missing = REQUIRED_FIELDS - set(data.keys())
        if missing:
            return False, f"Missing required fields: {', '.join(sorted(missing))}"

        if not isinstance(data["id"], str) or not data["id"].strip():
            return False, "Field 'id' must be a non-empty string"

        if not isinstance(data["name"], str) or not data["name"].strip():
            return False, "Field 'name' must be a non-empty string"

        if not isinstance(data["allowed_tools"], list):
            return False, "Field 'allowed_tools' must be a list of strings"

        if data["category"] not in ALLOWED_CATEGORIES:
            return False, f"Category '{data['category']}' invalid. Must be one of {ALLOWED_CATEGORIES}"

        return True, ""

    def load_all_agents(self) -> List[Dict]:
        """
        Loads all agent JSON configurations from the registry directory.
        Injects real-time runtime status.
        """
        agents = []
        for file in sorted(self.agents_dir.glob("*.json")):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                valid, err = self.validate_agent_schema(data)
                if valid:
                    # Update status with runtime status if currently running
                    agent_id = data["id"]
                    data["agent_id"] = agent_id  # Compatibility alias
                    if agent_id in self._runtime_status:
                        data["status"] = self._runtime_status[agent_id]
                    agents.append(data)
                else:
                    logger.warning(f"Invalid agent file {file.name}: {err}")
            except Exception as e:
                logger.error(f"Error loading agent file {file.name}: {e}")
        return agents

    def get_agent(self, agent_id: str) -> Optional[Dict]:
        """Get a single agent by ID."""
        file = self.agents_dir / f"{agent_id}.json"
        if not file.exists():
            return None
        try:
            with open(file, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["agent_id"] = data["id"]  # Compatibility alias
            if agent_id in self._runtime_status:
                data["status"] = self._runtime_status[agent_id]
            return data
        except Exception as e:
            logger.error(f"Failed to read agent '{agent_id}': {e}")
            return None

    def get_active_agents(self) -> List[Dict]:
        """
        Returns agents that appear on the user's dashboard (default + custom).
        Excludes pure unadded gallery templates.
        """
        return [a for a in self.load_all_agents() if a.get("category") in ("default", "custom")]

    def get_template_agents(self) -> List[Dict]:
        """
        Returns template agents available in the gallery.
        """
        return [a for a in self.load_all_agents() if a.get("category") == "template"]

    def get_agents_by_category(self, category: str) -> List[Dict]:
        """
        Returns all agents matching a given category ('default', 'template', 'custom').
        """
        return [a for a in self.load_all_agents() if a.get("category") == category]

    def save_agent(self, agent_data: dict) -> Tuple[bool, str]:
        """
        Validates and writes an agent definition to agents/<agent_id>.json.
        """
        valid, err = self.validate_agent_schema(agent_data)
        if not valid:
            return False, err

        agent_id = agent_data["id"]
        target_file = self.agents_dir / f"{agent_id}.json"

        try:
            with open(target_file, "w", encoding="utf-8") as f:
                json.dump(agent_data, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved agent '{agent_data['name']}' to {target_file.name}")
            return True, ""
        except Exception as e:
            logger.error(f"Failed to write agent file: {e}")
            return False, str(e)

    def delete_agent(self, agent_id: str) -> Tuple[bool, str]:
        """
        Delete a custom agent. Default system agents cannot be deleted.
        """
        agent = self.get_agent(agent_id)
        if not agent:
            return False, f"Agent '{agent_id}' not found"

        if agent.get("category") == "default":
            return False, "Cannot delete built-in default agent"

        target_file = self.agents_dir / f"{agent_id}.json"
        try:
            target_file.unlink()
            logger.info(f"Deleted custom agent '{agent_id}'")
            return True, ""
        except Exception as e:
            return False, f"Error deleting agent: {str(e)}"
