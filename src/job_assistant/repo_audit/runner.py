from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

_SAFE_PYTHON_DEPENDENCIES = {
    "click",
    "fastapi",
    "flask",
    "openai",
    "pydantic",
    "python-dotenv",
    "pyyaml",
    "requests",
    "rich",
    "typer",
}
_SAFE_NODE_DEPENDENCIES = {
    "axios",
    "chalk",
    "commander",
    "dotenv",
    "express",
}


class SandboxRunner:
    def __init__(self, trace_writer: Any | None = None, timeout_seconds: int = 10):
        self._trace_writer = trace_writer
        self._timeout_seconds = timeout_seconds

    def run(self, repo_dir: Path, static_analysis: Dict[str, Any], allow_light_run: bool = True) -> Dict[str, Any]:
        if not allow_light_run:
            result = {"status": "skipped", "reason": "light_run_disabled", "attempts": []}
            self._trace("sandbox_runner.completed", result)
            return result

        candidates = self._build_candidates(static_analysis)
        if not candidates:
            result = {"status": "skipped", "reason": "no_entrypoint", "attempts": []}
            self._trace("sandbox_runner.completed", result)
            return result

        attempts = []
        for candidate in candidates:
            attempt = self._run_candidate(repo_dir, candidate)
            attempts.append(attempt)
            if attempt.get("status") in {"passed", "started"}:
                result = {**attempt, "attempts": [dict(item) for item in attempts]}
                self._trace("sandbox_runner.completed", result)
                return result

        fallback = {**attempts[-1], "attempts": [dict(item) for item in attempts]}
        self._trace("sandbox_runner.completed", fallback)
        return fallback

    def _build_candidates(self, static_analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        python_dependencies = static_analysis.get("python", {}).get("dependencies", [])
        node_dependencies = static_analysis.get("node", {}).get("dependencies", [])

        for entrypoint in static_analysis.get("entrypoints", []):
            runtime = entrypoint.get("runtime")
            path = entrypoint.get("path", "")
            if runtime == "python":
                module = entrypoint.get("module")
                command = [sys.executable, "-m", module] if module else [sys.executable, path]
                candidates.append(
                    {
                        "runtime": "python",
                        "path": path,
                        "command": command,
                        "dependencies": python_dependencies,
                    }
                )
            elif runtime == "node":
                node = shutil.which("node")
                if node:
                    candidates.append(
                        {
                            "runtime": "node",
                            "path": path,
                            "command": [node, path],
                            "dependencies": node_dependencies,
                        }
                    )
                else:
                    candidates.append(
                        {
                            "runtime": "node",
                            "path": path,
                            "command": [],
                            "dependencies": node_dependencies,
                            "status": "skipped",
                            "reason": "node_missing",
                        }
                    )
        return candidates

    def _run_candidate(self, repo_dir: Path, candidate: Dict[str, Any]) -> Dict[str, Any]:
        if candidate.get("status") == "skipped":
            return {
                "status": "skipped",
                "runtime": candidate.get("runtime", ""),
                "command": "",
                "reason": candidate.get("reason", "candidate_skipped"),
            }

        dependency_policy = self._evaluate_dependency_policy(candidate.get("runtime", ""), candidate.get("dependencies", []))
        if candidate.get("dependencies") and not dependency_policy.get("install_allowed"):
            return {
                "status": "skipped",
                "runtime": candidate.get("runtime", ""),
                "command": " ".join(candidate.get("command", [])),
                "reason": dependency_policy.get("reason", "dependency_policy_blocked"),
                "dependency_policy": dependency_policy,
            }

        env = os.environ.copy()
        env["PYTHONPATH"] = self._build_pythonpath(repo_dir, env.get("PYTHONPATH", ""))
        runtime_command = list(candidate.get("command", []))
        installed_dependencies = []

        if candidate.get("runtime") == "python" and dependency_policy.get("install_allowed") and candidate.get("dependencies"):
            installed_dependencies = candidate.get("dependencies", [])
            runtime_command[0] = self._prepare_python_env(repo_dir, installed_dependencies)
        elif candidate.get("runtime") == "node" and dependency_policy.get("install_allowed") and candidate.get("dependencies"):
            installed_dependencies = self._prepare_node_env(repo_dir)

        if not runtime_command:
            return {
                "status": "skipped",
                "runtime": candidate.get("runtime", ""),
                "command": "",
                "reason": "empty_command",
                "dependency_policy": dependency_policy,
            }

        self._trace("sandbox_runner.start", {"runtime": candidate.get("runtime"), "command": runtime_command})
        start = time.perf_counter()
        process = subprocess.Popen(
            runtime_command,
            cwd=repo_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=self._timeout_seconds)
            duration = round(time.perf_counter() - start, 2)
            status = "passed" if process.returncode == 0 else "failed"
            return {
                "status": status,
                "runtime": candidate.get("runtime", ""),
                "command": " ".join(runtime_command),
                "entrypoint": candidate.get("path", ""),
                "exit_code": process.returncode,
                "stdout_tail": (stdout or "")[-1000:],
                "stderr_tail": (stderr or "")[-1000:],
                "duration_seconds": duration,
                "dependency_policy": dependency_policy,
                "installed_dependencies": installed_dependencies,
            }
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            duration = round(time.perf_counter() - start, 2)
            status = "started" if not stderr.strip() else "failed"
            return {
                "status": status,
                "runtime": candidate.get("runtime", ""),
                "command": " ".join(runtime_command),
                "entrypoint": candidate.get("path", ""),
                "exit_code": None,
                "stdout_tail": (stdout or "")[-1000:],
                "stderr_tail": (stderr or "")[-1000:],
                "duration_seconds": duration,
                "dependency_policy": dependency_policy,
                "installed_dependencies": installed_dependencies,
                "reason": "timeout_reached" if status == "started" else "timeout_with_errors",
            }
        except Exception as exc:
            return {
                "status": "failed",
                "runtime": candidate.get("runtime", ""),
                "command": " ".join(runtime_command),
                "entrypoint": candidate.get("path", ""),
                "reason": str(exc),
                "dependency_policy": dependency_policy,
            }

    def _build_pythonpath(self, repo_dir: Path, existing: str) -> str:
        paths = [str(repo_dir)]
        src_dir = repo_dir / "src"
        if src_dir.exists():
            paths.insert(0, str(src_dir))
        if existing:
            paths.append(existing)
        return os.pathsep.join(paths)

    def _evaluate_dependency_policy(self, runtime: str, dependencies: List[str]) -> Dict[str, Any]:
        if not dependencies:
            return {
                "install_allowed": False,
                "reason": "no_dependencies",
                "dependencies": [],
            }

        if runtime == "python":
            allowed = all(dependency in _SAFE_PYTHON_DEPENDENCIES for dependency in dependencies)
        elif runtime == "node":
            allowed = all(dependency in _SAFE_NODE_DEPENDENCIES for dependency in dependencies)
        else:
            allowed = False

        if len(dependencies) > 5:
            allowed = False
            reason = "too_many_dependencies"
        elif allowed:
            reason = "whitelisted"
        else:
            reason = "non_whitelisted_dependencies"

        return {
            "install_allowed": allowed,
            "reason": reason,
            "dependencies": dependencies,
        }

    def _prepare_python_env(self, repo_dir: Path, dependencies: List[str]) -> str:
        venv_dir = repo_dir / ".venv"
        python_executable = venv_dir / "Scripts" / "python.exe" if os.name == "nt" else venv_dir / "bin" / "python"
        if not python_executable.exists():
            subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], cwd=repo_dir, check=True, capture_output=True, text=True)
        pip_executable = venv_dir / "Scripts" / "pip.exe" if os.name == "nt" else venv_dir / "bin" / "pip"
        subprocess.run(
            [str(pip_executable), "install", *dependencies],
            cwd=repo_dir,
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        )
        return str(python_executable)

    def _prepare_node_env(self, repo_dir: Path) -> List[str]:
        npm = shutil.which("npm")
        if not npm:
            raise RuntimeError("npm 不可用")
        subprocess.run(
            [npm, "install", "--ignore-scripts", "--no-audit", "--no-fund"],
            cwd=repo_dir,
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        )
        return ["node_modules"]

    def _trace(self, event: str, payload: dict) -> None:
        if self._trace_writer is not None:
            self._trace_writer.write(event, payload)
