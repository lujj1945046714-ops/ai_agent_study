from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from job_assistant.repo_audit.models import RepoSpec

_GITHUB_HOSTS = {"github.com", "www.github.com"}
_SHORTHAND_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class RepoResolver:
    def resolve(self, source: str) -> RepoSpec:
        raw = (source or "").strip()
        if not raw:
            raise ValueError("仓库地址不能为空")

        local_path = self._resolve_local_path(raw)
        if local_path is not None:
            return RepoSpec(
                original=raw,
                source_type="local_path",
                url=local_path.resolve().as_posix(),
                display_name=local_path.name,
                name=local_path.name,
                local_path=local_path.resolve(),
            )

        github_spec = self._resolve_github(raw)
        if github_spec is not None:
            return github_spec

        raise ValueError(f"无法识别仓库地址: {source}")

    def _resolve_local_path(self, source: str) -> Path | None:
        if source.startswith("file://"):
            parsed = urlparse(source)
            candidate = Path(parsed.path)
        else:
            candidate = Path(source).expanduser()
        if candidate.exists():
            if not candidate.is_dir():
                raise ValueError(f"本地路径不是目录: {candidate}")
            return candidate
        return None

    def _resolve_github(self, source: str) -> RepoSpec | None:
        candidate = source
        if _SHORTHAND_PATTERN.match(source):
            candidate = f"https://github.com/{source}"

        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in _GITHUB_HOSTS:
            return None

        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) < 2:
            raise ValueError(f"GitHub 地址缺少 owner/repo: {source}")

        owner = parts[0]
        name = parts[1][:-4] if parts[1].endswith(".git") else parts[1]
        ref = ""
        if len(parts) >= 4 and parts[2] == "tree":
            ref = "/".join(parts[3:])

        base_url = f"https://github.com/{owner}/{name}"
        archive_urls = []
        if ref:
            archive_urls.append(f"https://codeload.github.com/{owner}/{name}/zip/refs/heads/{ref}")
        archive_urls.extend(
            [
                f"https://codeload.github.com/{owner}/{name}/zip/refs/heads/main",
                f"https://codeload.github.com/{owner}/{name}/zip/refs/heads/master",
            ]
        )

        return RepoSpec(
            original=source,
            source_type="github",
            url=base_url,
            display_name=f"{owner}/{name}",
            owner=owner,
            name=name,
            ref=ref,
            clone_url=f"{base_url}.git",
            archive_urls=archive_urls,
        )
