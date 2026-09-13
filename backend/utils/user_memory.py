"""
DeskPilot — User Memory & Profile Manager
Maintains persistent, local JSON-backed profiles and domain context for users across agents.
Enables agents to remember user identity, health profiles, financial preferences, and work context
without asking repeatedly, while supporting runtime clarification updates.
"""

import json
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from backend.config.settings import PROJECT_ROOT
from backend.utils.logger import get_logger

logger = get_logger("utils.user_memory")

# Path to the persistent user profiles JSON file
CONFIG_DIR = PROJECT_ROOT / "config"
USER_PROFILES_FILE = CONFIG_DIR / "user_profiles.json"

_memory_lock = threading.Lock()


class UserMemoryManager:
    """
    Manages reading, writing, and merging user profile details in config/user_profiles.json.
    Organizes profile data into:
    - global: General user identity (name, role, preferences)
    - health: Medical history, allergies, fitness goals, age
    - finance: Currency, budgeting goals, risk tolerance
    - work: Department, job title, deliverable standards
    - custom: Freeform domain facts learned during conversations
    """

    @classmethod
    def _ensure_file_exists(cls) -> Dict[str, Any]:
        """Ensure config directory and user_profiles.json exist with baseline schema."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if not USER_PROFILES_FILE.exists():
            default_data = {
                "version": "1.0",
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "global": {},
                "health": {},
                "finance": {},
                "work": {},
                "custom": {},
                "onboarding_completed": {}
            }
            try:
                with open(USER_PROFILES_FILE, "w", encoding="utf-8") as f:
                    json.dump(default_data, f, indent=2, ensure_ascii=False)
            except Exception as e:
                logger.error(f"Failed to initialize user_profiles.json: {e}")
                return default_data
            return default_data

        try:
            with open(USER_PROFILES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    data = {}
                return data
        except Exception as e:
            logger.error(f"Failed to read user_profiles.json: {e}")
            return {
                "version": "1.0",
                "last_updated": datetime.utcnow().isoformat() + "Z",
                "global": {},
                "health": {},
                "finance": {},
                "work": {},
                "custom": {},
                "onboarding_completed": {}
            }

    @classmethod
    def get_all_profiles(cls) -> Dict[str, Any]:
        """Return the complete user profiles dictionary."""
        with _memory_lock:
            return cls._ensure_file_exists()

    @classmethod
    def get_profile(cls, category: str = "global") -> Dict[str, Any]:
        """
        Get profile data for a specific category:
        'global', 'health', 'finance', 'work', 'custom', or agent_id.
        """
        cat_key = cls._normalize_category(category)
        with _memory_lock:
            data = cls._ensure_file_exists()
            return data.get(cat_key, {})

    @classmethod
    def _normalize_category(cls, category_or_agent_id: str) -> str:
        """Map agent_id or category string to canonical profile key."""
        raw = category_or_agent_id.lower().strip()
        if "health" in raw or "medical" in raw or "doctor" in raw:
            return "health"
        if "finance" in raw or "budget" in raw or "money" in raw:
            return "finance"
        if "work" in raw or "job" in raw or "office" in raw:
            return "work"
        if "personal" in raw or "general" in raw or "global" in raw:
            return "global"
        return raw

    @classmethod
    def has_profile_data(cls, category_or_agent_id: str) -> bool:
        """Checks if meaningful profile data has already been recorded for this category."""
        profile = cls.get_profile(category_or_agent_id)
        if not profile or not isinstance(profile, dict):
            return False
        # Filter out metadata keys
        useful_keys = [k for k in profile.keys() if not k.startswith("_")]
        return len(useful_keys) > 0

    @classmethod
    def save_profile_data(cls, category_or_agent_id: str, new_fields: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merges new fields into the specified profile section and writes to user_profiles.json.
        Intelligently routes domain keys (sleep, diet, budget, work) even if category was generic.
        """
        cat_key = cls._normalize_category(category_or_agent_id)
        if cat_key == "global" and new_fields:
            field_keys = [str(k).lower() for k in new_fields.keys()]
            if any(k in field_keys for k in ["bedtime", "wakeup_time", "sleep_quality", "sleep_environment", "pre_sleep_routine", "allergies", "fitness_goal", "daily_steps_target", "daily_activity"]):
                cat_key = "health"
            elif any(k in field_keys for k in ["income", "income_sources", "fixed_expenses", "variable_expenses", "savings_goals", "monthly_savings_goal", "currency"]):
                cat_key = "finance"
            elif any(k in field_keys for k in ["user_role", "team_size", "favorite_editor", "job_title", "company"]):
                cat_key = "work"

        with _memory_lock:
            data = cls._ensure_file_exists()
            if cat_key not in data or not isinstance(data[cat_key], dict):
                data[cat_key] = {}

            # Sanitize and merge keys
            for k, v in new_fields.items():
                if v is not None and str(v).strip() != "":
                    clean_k = str(k).strip()
                    data[cat_key][clean_k] = v

            # Mark onboarding as completed for this category
            if "onboarding_completed" not in data or not isinstance(data["onboarding_completed"], dict):
                data["onboarding_completed"] = {}
            data["onboarding_completed"][cat_key] = True

            data["last_updated"] = datetime.now(timezone.utc).isoformat()

            try:
                with open(USER_PROFILES_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                logger.info(f"Updated user profile for category '{cat_key}': {list(new_fields.keys())}")
            except Exception as e:
                logger.error(f"Failed to write to user_profiles.json: {e}")

            return data.get(cat_key, {})

    @classmethod
    def update_single_field(cls, key: str, value: Any, category: str = "global") -> None:
        """Update or insert a single key-value fact into local memory."""
        cls.save_profile_data(category, {key: value})

    @classmethod
    def get_formatted_memory_context(cls, agent_id: Optional[str] = None) -> str:
        """
        Constructs a concise, highly informative prompt injection summarizing known user details.
        Automatically includes global user details plus category-specific details.
        """
        with _memory_lock:
            data = cls._ensure_file_exists()

        lines = ["=== USER PROFILE & LOCAL MEMORY CONTEXT ==="]
        has_any = False

        # 1. Global User Details
        global_prof = data.get("global", {})
        if global_prof:
            has_any = True
            lines.append("• General Profile:")
            for k, v in global_prof.items():
                if not k.startswith("_"):
                    lines.append(f"  - {k.replace('_', ' ').title()}: {v}")

        # 2. Agent / Category Specific Details
        cat_key = cls._normalize_category(agent_id) if agent_id else None
        if cat_key and cat_key != "global":
            cat_prof = data.get(cat_key, {})
            if cat_prof:
                has_any = True
                lines.append(f"• {cat_key.title()} Profile:")
                for k, v in cat_prof.items():
                    if not k.startswith("_"):
                        lines.append(f"  - {k.replace('_', ' ').title()}: {v}")

        # Also show other relevant categories if present
        for other_cat in ["health", "finance", "work"]:
            if other_cat != cat_key and data.get(other_cat):
                has_any = True
                lines.append(f"• {other_cat.title()} Context:")
                for k, v in data[other_cat].items():
                    if not k.startswith("_"):
                        lines.append(f"  - {k.replace('_', ' ').title()}: {v}")

        if not has_any:
            lines.append("No prior user background has been recorded yet.")
            lines.append("(If your domain requires critical user background or onboarding details, or if you face any ambiguity, invoke the 'ask_user_form' tool to prompt the user with a custom popup form).")
        else:
            lines.append("CRITICAL OPERATING RULES WITH USER CONTEXT:")
            lines.append("• Use the details above to personalize all answers, advice, calculations, and documents.")
            lines.append("• PREFERRED CURRENCY: If the user specified a currency (e.g. PKR, EUR, GBP, INR), ALWAYS use that exact currency and symbol. NEVER replace it with US dollars ($).")
            lines.append("• NUMERIC AMOUNTS: If the user's responses contain qualitative descriptions where numbers are needed (e.g., income source is 'pocket money', expense is 'lunch'), DO NOT assume 0. Ask the user in chat for the numerical amounts.")
            lines.append("• CHAT FIRST: Give all plans, advice, tables, and answers in the chat window. Only generate physical files (.xlsx, .docx) when the user explicitly says to create or export a file.")
            lines.append("(If you ever need clarification, missing details, or updated preferences, invoke 'ask_user_form').")

        lines.append("===========================================")
        return "\n".join(lines)


# Singleton convenience accessors
def get_user_memory_context(agent_id: Optional[str] = None) -> str:
    return UserMemoryManager.get_formatted_memory_context(agent_id)

def get_user_profile(category: str = "global") -> Dict[str, Any]:
    return UserMemoryManager.get_profile(category)

def save_user_profile(category: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return UserMemoryManager.save_profile_data(category, data)
