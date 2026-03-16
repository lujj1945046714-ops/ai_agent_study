from datetime import datetime
from pathlib import Path
from typing import Any, Dict


class MarkdownMemory:
    """
    Store conversation history in Markdown format.

    Human-readable format for easy review and version control.
    """

    def __init__(self, memory_dir: Path):
        """
        Initialize Markdown memory.

        Args:
            memory_dir: Base memory directory
        """
        self.memory_dir = Path(memory_dir)
        self.sessions_dir = self.memory_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def create_session_file(self, session_id: str, user_profile: Dict[str, Any]) -> None:
        """
        Create new session markdown file.

        Args:
            session_id: Session identifier
            user_profile: User profile dict
        """
        session_file = self.sessions_dir / f"{session_id}.md"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        content = f"""# Session: {session_id}

**Started:** {timestamp}
**User Profile:** {user_profile.get('name', 'Unknown')}

---

## Conversation History

"""
        session_file.write_text(content, encoding="utf-8")

    def append_conversation(self, session_id: str, user_msg: str, agent_msg: str) -> None:
        """
        Append conversation turn.

        Args:
            session_id: Session identifier
            user_msg: User message
            agent_msg: Agent response
        """
        session_file = self.sessions_dir / f"{session_id}.md"
        if not session_file.exists():
            return

        timestamp = datetime.now().strftime("%H:%M:%S")
        turn = f"""
### Turn ({timestamp})
**User:** {user_msg}
**Agent:** {agent_msg}

"""
        with open(session_file, "a", encoding="utf-8") as f:
            f.write(turn)

    def append_job_analysis(self, session_id: str, job_id: str, analysis: Dict[str, Any]) -> None:
        """
        Append job analysis.

        Args:
            session_id: Session identifier
            job_id: Job identifier
            analysis: Analysis result dict
        """
        session_file = self.sessions_dir / f"{session_id}.md"
        if not session_file.exists():
            return

        content = session_file.read_text(encoding="utf-8")
        if "## Analyzed Jobs" not in content:
            with open(session_file, "a", encoding="utf-8") as f:
                f.write("\n---\n\n## Analyzed Jobs\n\n")

        job_section = f"""
### Job: {job_id}
- **Title:** {analysis.get('title', 'N/A')}
- **Company:** {analysis.get('company', 'N/A')}
- **Match Score:** {analysis.get('match_score', 'N/A')}

"""
        with open(session_file, "a", encoding="utf-8") as f:
            f.write(job_section)

    def read_session(self, session_id: str) -> str:
        """
        Read session content.

        Args:
            session_id: Session identifier

        Returns:
            Session markdown content or empty string
        """
        session_file = self.sessions_dir / f"{session_id}.md"
        if not session_file.exists():
            return ""

        return session_file.read_text(encoding="utf-8")

