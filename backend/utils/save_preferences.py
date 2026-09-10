"""
DeskPilot — Save Location Preferences
Manages user preferences for where deliverable files (Excel, Word, etc.) should be saved.
Supports 'Always save there' persistent preference.
"""

import json
from pathlib import Path
from typing import Dict, Any
from backend.config.settings import DEFAULT_OUTPUT_DIR
from backend.utils.logger import get_logger

logger = get_logger("utils.save_preferences")

_PREFS_FILE = Path(__file__).parent.parent / "config" / "save_preferences.json"


def get_save_preferences() -> Dict[str, Any]:
    """
    Returns current user save preferences.
    Default:
        {
            "save_location": "Desktop",
            "always_save": True,
            "custom_path": ""
        }
    """
    if _PREFS_FILE.exists():
        try:
            with open(_PREFS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {
                    "save_location": data.get("save_location", "Desktop"),
                    "always_save": bool(data.get("always_save", True)),
                    "custom_path": data.get("custom_path", ""),
                }
        except Exception as e:
            logger.warning(f"Failed to read save preferences, using default: {e}")

    # Default to Desktop with always_save=True
    return {
        "save_location": "Desktop",
        "always_save": True,
        "custom_path": "",
    }


def set_save_preferences(save_location: str, always_save: bool = True, custom_path: str = "") -> Dict[str, Any]:
    """
    Saves user preferences for file destinations.
    """
    _PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
    prefs = {
        "save_location": save_location.strip() or "Desktop",
        "always_save": bool(always_save),
        "custom_path": custom_path.strip(),
    }
    try:
        with open(_PREFS_FILE, "w", encoding="utf-8") as f:
            json.dump(prefs, f, indent=2)
        logger.info(f"Updated save preferences: {prefs}")
    except Exception as e:
        logger.error(f"Failed to write save preferences: {e}")

    return prefs


def resolve_effective_save_dir() -> Path:
    """
    Resolves the target directory based on current preferences.
    """
    prefs = get_save_preferences()
    loc = prefs.get("save_location", "Desktop").lower()

    if loc == "desktop":
        target = Path.home() / "Desktop"
    elif loc == "documents":
        target = Path.home() / "Documents"
    elif loc == "downloads":
        target = Path.home() / "Downloads"
    elif loc == "custom" and prefs.get("custom_path"):
        target = Path(prefs["custom_path"])
    else:
        # Default fallback to DeskPilot Output
        target = DEFAULT_OUTPUT_DIR

    try:
        target.mkdir(parents=True, exist_ok=True)
        return target
    except Exception as e:
        logger.warning(f"Could not create preferred dir '{target}': {e}, falling back to Desktop")
        return Path.home() / "Desktop"
