from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run(
        "job_assistant.webapp.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=7860,
        reload=False,
    )


if __name__ == "__main__":
    main()
