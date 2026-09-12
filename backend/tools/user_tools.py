"""
DeskPilot — User Memory & Form Interaction Tools
Provides agents with the ability to dynamically prompt users via interactive popup forms,
retrieve stored user context/profiles, and record facts into local memory.
"""

import json
from typing import List, Dict, Any, Union
from strands import tool
from backend.utils.form_engine import request_user_form
from backend.utils.user_memory import UserMemoryManager
from backend.utils.logger import get_logger

logger = get_logger("tools.user")


@tool
def ask_user_form(
    title: str,
    description: str,
    fields: Union[List[Dict[str, Any]], str],
    category: str = "general"
) -> str:
    """
    Presents an interactive popup questionnaire or clarification form to the user in the desktop window at runtime.
    Use this:
    1. On your very first query with a user if you lack critical background context (e.g., in medical/health: age, wellness goals, allergies; in finance: currency, budget targets; in work: job role, deliverable standards; in personal: user name, priorities).
    2. Whenever you encounter confusion, ambiguous instructions, or need specific choices or parameters from the user during any task.

    The user's answers are automatically saved to local JSON storage (config/user_profiles.json) so you will remember them permanently across sessions.

    Args:
        title: Short, friendly title for the popup modal (e.g. 'Personal Health Profile', 'Report Preferences', 'Task Clarification')
        description: 1-2 sentence explanation of why this information is helpful for the user.
        fields: List of field objects (or JSON array string). Each field dictionary should have:
            - 'id': Unique identifier string (e.g. 'user_name', 'age', 'fitness_goal', 'allergies')
            - 'label': Clear question or prompt for the user (e.g. 'What is your current age?')
            - 'type': 'text' | 'number' | 'textarea' | 'select' | 'radio'
            - 'placeholder': (Optional) Example text shown inside the input box
            - 'options': (Optional, for 'select' or 'radio') List of choices
            - 'required': (Optional, boolean) Whether the field is mandatory (default True)
        category: (Optional) Profile category to save under: 'health', 'finance', 'work', or 'general' (default 'general')

    Returns:
        Structured summary of the user's responses, or a note if the user chose to skip.
    """
    # Safe parsing if fields is passed as JSON string by Bedrock
    clean_fields: List[Dict[str, Any]] = []
    if isinstance(fields, str):
        try:
            parsed = json.loads(fields)
            if isinstance(parsed, list):
                clean_fields = parsed
            elif isinstance(parsed, dict):
                clean_fields = [parsed]
        except Exception as e:
            logger.warning(f"Failed to parse fields JSON string: {e}")
            clean_fields = []
    elif isinstance(fields, list):
        clean_fields = fields

    if not clean_fields:
        # Provide fallback field if model called with empty fields
        clean_fields = [
            {
                "id": "clarification_details",
                "label": title or "Please provide additional details:",
                "type": "textarea",
                "placeholder": "Type your details or preferences here...",
                "required": True
            }
        ]

    logger.info(f"Invoking ask_user_form: '{title}' ({len(clean_fields)} fields, category='{category}')")
    return request_user_form(
        title=title,
        description=description,
        fields=clean_fields,
        category=category
    )


@tool
def get_user_profile(section: str = "all") -> str:
    """
    Retrieves the user's stored profile and preferences from local memory (config/user_profiles.json).
    Allows an agent to check what is already known about the user (e.g., name, health background,
    financial goals, or work role) before asking redundant questions.

    Args:
        section: Which profile section to view: 'all', 'global', 'health', 'finance', 'work', or 'custom'. Defaults to 'all'.

    Returns:
        Formatted summary of saved profile information from local storage.
    """
    sec = section.lower().strip()
    if sec == "all":
        profiles = UserMemoryManager.get_all_profiles()
    else:
        profiles = {sec: UserMemoryManager.get_profile(sec)}

    lines = [f"DeskPilot Stored User Memory (Section: {sec}):"]
    found_any = False

    for category, fields in profiles.items():
        if category in ("version", "last_updated", "onboarding_completed"):
            continue
        if isinstance(fields, dict) and fields:
            found_any = True
            lines.append(f"\n[{category.title()} Context]")
            for k, v in fields.items():
                if not k.startswith("_"):
                    lines.append(f"  • {k.replace('_', ' ').title()}: {v}")

    if not found_any:
        return "No user profile details are currently recorded in local storage for this section."

    return "\n".join(lines)


@tool
def update_user_profile(key: str, value: str, category: str = "general") -> str:
    """
    Directly updates or adds a specific fact about the user into local memory (config/user_profiles.json)
    without popping up a full form. Useful when the user mentions an important preference or detail in casual chat.

    Args:
        key: The attribute name (e.g. 'preferred_name', 'target_weight', 'office_location')
        value: The value to store
        category: Profile category ('general', 'health', 'finance', 'work')

    Returns:
        Confirmation that the fact was saved to local storage.
    """
    clean_k = key.strip()
    clean_v = value.strip()
    clean_cat = category.strip().lower()

    UserMemoryManager.update_single_field(clean_k, clean_v, clean_cat)
    return f"SUCCESS: Saved '{clean_k}: {clean_v}' under '{clean_cat}' profile in local memory."
