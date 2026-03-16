from __future__ import annotations

import io
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import requests

from job_assistant.repo_audit.models import RepoSpec


class RepoFetcher:
    def __init__(self, trace_writer: Any | None = None):
        self._trace_writer = trace_writer

    def fetch(self, repo_spec: RepoSpec, workspace_root: Path) -> Path:
        workspace_root.mkdir(parents=True, exist_ok=True)
        repo_dir = workspace_root / "repo"

        if repo_spec.source_type == "local_path":
            self._trace("fetch.copy.start", {"source": str(repo_spec.local_path), "target": str(repo_dir)})
            shutil.copytree(repo_spec.local_path, repo_dir, dirs_exist_ok=True)
            self._trace("fetch.copy.end", {"target": str(repo_dir)})
            return repo_dir

        git_error = self._clone_with_git(repo_spec, repo_dir)
        if repo_dir.exists():
            return repo_dir

        archive_error = self._download_archive(repo_spec, repo_dir, workspace_root)
        if repo_dir.exists():
            return repo_dir

        raise RuntimeError(f"仓库下载失败。git: {git_error}; archive: {archive_error}")

    def _clone_with_git(self, repo_spec: RepoSpec, repo_dir: Path) -> str | None:
        git = shutil.which("git")
        if not git:
            return "git 不可用"

        command = [git, "clone", "--depth", "1"]
        if repo_spec.ref:
            command.extend(["--branch", repo_spec.ref])
        command.extend([repo_spec.clone_url or repo_spec.url, str(repo_dir)])

        self._trace("fetch.git.start", {"command": command})
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=180,
                check=True,
            )
            self._trace(
                "fetch.git.end",
                {
                    "command": command,
                    "stdout_tail": completed.stdout[-500:],
                    "stderr_tail": completed.stderr[-500:],
                },
            )
            return None
        except Exception as exc:
            if repo_dir.exists():
                shutil.rmtree(repo_dir, ignore_errors=True)
            self._trace("fetch.git.error", {"command": command, "error": str(exc)})
            return str(exc)

    def _download_archive(self, repo_spec: RepoSpec, repo_dir: Path, workspace_root: Path) -> str | None:
        last_error = None
        session = requests.Session()
        for archive_url in repo_spec.archive_urls:
            self._trace("fetch.archive.start", {"url": archive_url})
            try:
                response = session.get(archive_url, timeout=60)
                response.raise_for_status()
                with zipfile.ZipFile(io.BytesIO(response.content)) as zip_file:
                    temp_dir = workspace_root / "_archive_extract"
                    if temp_dir.exists():
                        shutil.rmtree(temp_dir)
                    temp_dir.mkdir(parents=True, exist_ok=True)
                    zip_file.extractall(temp_dir)
                    children = [path for path in temp_dir.iterdir() if path.is_dir()]
                    if not children:
                        raise RuntimeError("压缩包中未找到仓库目录")
                    shutil.move(str(children[0]), str(repo_dir))
                    shutil.rmtree(temp_dir, ignore_errors=True)
                self._trace("fetch.archive.end", {"url": archive_url, "target": str(repo_dir)})
                return None
            except Exception as exc:
                last_error = str(exc)
                if repo_dir.exists():
                    shutil.rmtree(repo_dir, ignore_errors=True)
                self._trace("fetch.archive.error", {"url": archive_url, "error": last_error})
        return last_error

    def _trace(self, event: str, payload: dict) -> None:
        if self._trace_writer is not None:
            self._trace_writer.write(event, payload)
