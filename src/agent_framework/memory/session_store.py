import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class SessionStore:
    """
    Store session state in JSON format.

    Storage structure:
    memory_dir/
      sessions/
        session_001.json
        session_002.json
    """

    def __init__(self, memory_dir: Path):
        """
        Initialize session store.

        Args:
            memory_dir: Base memory directory
        """
        self.memory_dir = Path(memory_dir)
        self.sessions_dir = self.memory_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def save(self, session_id: str, state: Dict[str, Any]) -> None:
        """
        Save session state.

        Args:
            session_id: Session identifier
            state: Session state dict
        """
        session_file = self.sessions_dir / f"{session_id}.json"
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)

    def load(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Load session state.

        Args:
            session_id: Session identifier

        Returns:
            Session state dict or None if not found
        """
        session_file = self.sessions_dir / f"{session_id}.json"
        if not session_file.exists():
            return None

        with open(session_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def delete(self, session_id: str) -> None:
        """
        Delete session.

        Args:
            session_id: Session identifier
        """
        session_file = self.sessions_dir / f"{session_id}.json"
        if session_file.exists():
            session_file.unlink()

    def list_sessions(self) -> List[str]:
        """
        List all session IDs.

        Returns:
            List of session IDs
        """
        return [f.stem for f in self.sessions_dir.glob("*.json")]

