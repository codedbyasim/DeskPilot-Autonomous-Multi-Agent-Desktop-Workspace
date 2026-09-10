"""
DeskPilot — Chat Session Manager
Handles JSON-backed persistence for multi-turn conversational chat sessions.
Supports creating, loading, appending messages, auto-titling, and deleting sessions.
"""

import os
import json
import uuid
import threading
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

from backend.config.settings import CHATS_DIR
from backend.utils.logger import get_logger

logger = get_logger("chat.session_manager")


class ChatSessionManager:
    """
    Thread-safe manager for conversational chat sessions stored as JSON files.
    """

    def __init__(self, storage_dir: Optional[Path] = None):
        self.storage_dir = storage_dir or CHATS_DIR
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def create_session(self, agent_id: str, title: Optional[str] = None) -> Dict[str, Any]:
        """
        Creates and persists a new chat session.
        """
        session_id = f"chat_{uuid.uuid4().hex[:10]}"
        now = datetime.now().isoformat()
        
        session = {
            "id": session_id,
            "agent_id": agent_id,
            "title": title or "New Conversation",
            "created_at": now,
            "updated_at": now,
            "messages": [],
        }

        with self._lock:
            self._save_session(session)

        logger.info(f"Created chat session '{session_id}' for agent '{agent_id}'")
        return session

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves a single chat session by ID.
        """
        path = self._get_path(session_id)
        if not path.exists():
            return None

        with self._lock:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to read session file {path}: {e}")
                return None

    def list_sessions(self) -> List[Dict[str, Any]]:
        """
        Lists all chat sessions sorted by updated_at descending.
        Omits large message bodies for fast sidebar listing.
        """
        sessions = []
        with self._lock:
            for p in self.storage_dir.glob("chat_*.json"):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        messages = data.get("messages", [])
                        last_msg = messages[-1]["content"] if messages else ""
                        sessions.append({
                            "id": data.get("id"),
                            "agent_id": data.get("agent_id"),
                            "title": data.get("title", "Conversation"),
                            "created_at": data.get("created_at"),
                            "updated_at": data.get("updated_at"),
                            "message_count": len(messages),
                            "last_message": last_msg[:80] if last_msg else "",
                        })
                except Exception as e:
                    logger.warning(f"Error loading session from {p}: {e}")

        # Sort newest first
        sessions.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
        return sessions

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: Optional[List[str]] = None,
        deliverables: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Appends a message to the session, updates timestamp, and auto-titles if needed.
        """
        session = self.get_session(session_id)
        if not session:
            logger.warning(f"Cannot add message to non-existent session '{session_id}'")
            return None

        now = datetime.now().isoformat()
        msg_id = f"msg_{uuid.uuid4().hex[:8]}"
        msg = {
            "id": msg_id,
            "role": role,
            "content": content,
            "tool_calls": tool_calls or [],
            "deliverables": deliverables or [],
            "timestamp": now,
        }

        session["messages"].append(msg)
        session["updated_at"] = now

        # Auto-title on first user message if current title is default
        if role == "user" and session.get("title") in ("New Conversation", "New Chat", ""):
            clean_text = content.strip().replace("\n", " ")
            if clean_text:
                title = clean_text[:42] + ("..." if len(clean_text) > 42 else "")
                session["title"] = title

        with self._lock:
            self._save_session(session)

        return msg

    def update_title(self, session_id: str, new_title: str) -> bool:
        """
        Renames a conversation session.
        """
        session = self.get_session(session_id)
        if not session:
            return False

        session["title"] = new_title.strip() or "Conversation"
        session["updated_at"] = datetime.now().isoformat()
        with self._lock:
            self._save_session(session)
        return True

    def delete_session(self, session_id: str) -> bool:
        """
        Deletes a chat session file.
        """
        path = self._get_path(session_id)
        with self._lock:
            if path.exists():
                try:
                    path.unlink()
                    logger.info(f"Deleted chat session '{session_id}'")
                    return True
                except Exception as e:
                    logger.error(f"Failed to delete session '{session_id}': {e}")
                    return False
        return False

    def _get_path(self, session_id: str) -> Path:
        clean_id = "".join(c for c in session_id if c.isalnum() or c in ("_", "-"))
        return self.storage_dir / f"{clean_id}.json"

    def _save_session(self, session: Dict[str, Any]) -> None:
        path = self._get_path(session["id"])
        temp_path = path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(session, f, indent=2, ensure_ascii=False)
        temp_path.replace(path)
