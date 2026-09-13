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
    1. On your very first query with a user if you lack critical background context (e.g., in medical/health: age, wellness goals, allergies; in finance: currency, numeric monthly income, numeric fixed/variable expenses, savings targets; in work: job role, deliverable standards; in personal: user name, priorities).
    2. Whenever you encounter confusion, ambiguous instructions, or need specific choices or parameters from the user during any task.

    IMPORTANT GUIDELINES FOR FINANCIAL & BUDGETING QUESTIONS:
    - ALWAYS ask for NUMERIC AMOUNTS (type: 'number' or clear monetary number prompts like 'Monthly Income (Amount in Numbers)', 'Fixed Monthly Expenses (Amount in Numbers)', 'Monthly Savings Goal (Amount in Numbers)') and preferred currency ('PKR', 'USD', 'EUR', 'INR', etc.).
    - NEVER ask vague questions like 'income sources' or 'fixed expenses' that lead users to reply with text strings like 'pocket money' or 'lunch' when you need numerical figures for calculations.
    - Set the 'category' argument appropriately: 'health' for wellness/sleep/health, 'finance' for budgeting/money/expenses, 'work' for career/projects, 'general' for general.

    The user's answers are automatically saved to local JSON storage (config/user_profiles.json) so you will remember them permanently across sessions.

    Args:
        title: Short, friendly title for the popup modal (e.g. 'Personal Health Profile', 'Budget Details', 'Task Clarification')
        description: 1-2 sentence explanation of why this information is helpful for the user.
        fields: List of field objects (or JSON array string). Each field dictionary should have:
            - 'id': Unique identifier string (e.g. 'user_name', 'age', 'monthly_income', 'currency')
            - 'label': Clear question or prompt for the user (e.g. 'What is your monthly income amount?')
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

    # Auto-detect category if default 'general' was provided
    if category.strip().lower() in ("general", "global"):
        ctx_str = (title + " " + description + " " + " ".join(str(f.get("id", "")) + " " + str(f.get("label", "")) for f in clean_fields)).lower()
        if any(k in ctx_str for k in ["sleep", "bedtime", "wakeup", "allergy", "health", "workout", "exercise", "weight", "diet", "doctor", "medical"]):
            category = "health"
        elif any(k in ctx_str for k in ["budget", "income", "expense", "salary", "savings", "currency", "spending", "finance", "money", "invoice"]):
            category = "finance"
        elif any(k in ctx_str for k in ["company", "role", "team", "colleague", "deliverable", "client", "work", "job"]):
            category = "work"

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
