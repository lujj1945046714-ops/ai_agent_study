from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List

try:  # pragma: no cover - py311+ stdlib path
    import tomllib
except Exception:  # pragma: no cover - fallback when unavailable
    tomllib = None  # type: ignore[assignment]


_IGNORE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".next",
    ".turbo",
    "coverage",
}

_LANGUAGE_BY_SUFFIX = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".rb": "Ruby",
    ".php": "PHP",
    ".sh": "Shell",
}

_FRAMEWORK_HINTS = {
    "fastapi": "FastAPI",
    "flask": "Flask",
    "django": "Django",
    "gradio": "Gradio",
    "streamlit": "Streamlit",
    "langchain": "LangChain",
    "llama-index": "LlamaIndex",
    "llama_index": "LlamaIndex",
    "openai": "OpenAI SDK",
    "autogen": "AutoGen",
    "crewai": "CrewAI",
    "react": "React",
    "next": "Next.js",
    "nextjs": "Next.js",
    "express": "Express",
    "nestjs": "NestJS",
    "vue": "Vue",
    "vite": "Vite",
    "electron": "Electron",
}


def _safe_read_text(path: Path, limit: int = 12000) -> str:
    try:
        return path.read_text(encoding="utf-8")[:limit]
    except Exception:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")[:limit]
        except Exception:
            return ""


def _normalize_dependency_name(raw: str) -> str:
    cleaned = raw.strip()
    if not cleaned or cleaned.startswith("#"):
        return ""
    if ";" in cleaned:
        cleaned = cleaned.split(";", 1)[0].strip()
    if "[" in cleaned:
        cleaned = cleaned.split("[", 1)[0].strip()
    for marker in ["==", ">=", "<=", "~=", "!=", ">", "<"]:
        if marker in cleaned:
            cleaned = cleaned.split(marker, 1)[0].strip()
            break
    return cleaned.lower()


def _count_code_files(path: Path) -> int:
    total = 0
    for root, dirs, files in os.walk(path):
        dirs[:] = [directory for directory in dirs if directory not in _IGNORE_DIRS]
        for filename in files:
            if Path(filename).suffix.lower() in _LANGUAGE_BY_SUFFIX:
                total += 1
    return total


def _infer_module_kind(relative_path: str) -> str:
    lower = relative_path.lower()
    if "agent" in lower:
        return "agent"
    if "cli" in lower:
        return "cli"
    if any(token in lower for token in ["api", "server", "backend", "service"]):
        return "service"
    if "web" in lower or "ui" in lower or "frontend" in lower:
        return "ui"
    return "package"


def _module_name_from_path(repo_dir: Path, entrypoint: Path) -> str:
    relative = entrypoint.relative_to(repo_dir)
    parts = list(relative.parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    if not parts:
        return ""
    if parts[-1].endswith(".py"):
        parts[-1] = Path(parts[-1]).stem
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


class StaticAnalyzer:
    def __init__(self, trace_writer: Any | None = None):
        self._trace_writer = trace_writer

    def analyze(self, repo_dir: Path) -> Dict[str, Any]:
        suffix_counter: Counter[str] = Counter()
        code_files = 0
        files_scanned = 0
        file_paths: List[str] = []
        docs: List[str] = []
        readme_path = self._find_readme(repo_dir)

        for root, dirs, files in os.walk(repo_dir):
            dirs[:] = [directory for directory in dirs if directory not in _IGNORE_DIRS]
            for filename in files:
                path = Path(root) / filename
                relative = str(path.relative_to(repo_dir)).replace("\\", "/")
                files_scanned += 1
                file_paths.append(relative)
                suffix = path.suffix.lower()
                if suffix in _LANGUAGE_BY_SUFFIX:
                    suffix_counter[_LANGUAGE_BY_SUFFIX[suffix]] += 1
                    code_files += 1
                if relative.lower().startswith("docs/") or suffix in {".md", ".rst"}:
                    docs.append(relative)

        manifests = self._find_manifests(repo_dir)
        python_info = self._analyze_python(repo_dir)
        node_info = self._analyze_node(repo_dir)
        frameworks = self._detect_frameworks(python_info, node_info, readme_path)
        entrypoints = self._detect_entrypoints(repo_dir, manifests, python_info, node_info)
        tests = self._find_tests(repo_dir)
        ci_workflows = self._find_ci(repo_dir)
        languages = [{"name": name, "files": count} for name, count in suffix_counter.most_common()]
        primary_languages = [item["name"] for item in languages[:3]]

        analysis = {
            "repo_root": str(repo_dir),
            "files_scanned": files_scanned,
            "code_files": code_files,
            "languages": languages,
            "primary_languages": primary_languages,
            "manifests": manifests,
            "frameworks": frameworks,
            "entrypoints": entrypoints,
            "python": python_info,
            "node": node_info,
            "readme_path": str(readme_path.relative_to(repo_dir)).replace("\\", "/") if readme_path else "",
            "readme_excerpt": _safe_read_text(readme_path, limit=6000) if readme_path else "",
            "docs": docs[:20],
            "has_tests": bool(tests),
            "test_paths": tests[:20],
            "ci_workflows": ci_workflows,
            "sample_paths": file_paths[:80],
        }
        self._trace("static_analysis.completed", analysis)
        return analysis

    def _find_readme(self, repo_dir: Path) -> Path | None:
        for name in ["README.md", "README.rst", "README.txt", "readme.md"]:
            candidate = repo_dir / name
            if candidate.exists():
                return candidate
        return None

    def _find_manifests(self, repo_dir: Path) -> Dict[str, str]:
        manifests = {}
        for name in [
            "pyproject.toml",
            "requirements.txt",
            "package.json",
            "Dockerfile",
            "docker-compose.yml",
            "docker-compose.yaml",
            "Makefile",
            "pytest.ini",
        ]:
            candidate = repo_dir / name
            if candidate.exists():
                manifests[name] = name
        return manifests

    def _analyze_python(self, repo_dir: Path) -> Dict[str, Any]:
        dependencies: List[str] = []
        scripts: Dict[str, str] = {}

        requirements_path = repo_dir / "requirements.txt"
        if requirements_path.exists():
            for line in _safe_read_text(requirements_path, limit=12000).splitlines():
                dependency = _normalize_dependency_name(line)
                if dependency:
                    dependencies.append(dependency)

        pyproject_path = repo_dir / "pyproject.toml"
        if pyproject_path.exists() and tomllib is not None:
            try:
                parsed = tomllib.loads(_safe_read_text(pyproject_path, limit=20000))
                project = parsed.get("project", {})
                for dependency in project.get("dependencies", []) or []:
                    normalized = _normalize_dependency_name(str(dependency))
                    if normalized:
                        dependencies.append(normalized)
                for extras in (project.get("optional-dependencies", {}) or {}).values():
                    for dependency in extras:
                        normalized = _normalize_dependency_name(str(dependency))
                        if normalized:
                            dependencies.append(normalized)
                scripts = {str(key): str(value) for key, value in (project.get("scripts", {}) or {}).items()}
            except Exception:
                scripts = {}

        unique_dependencies = sorted(set(filter(None, dependencies)))
        return {
            "detected": any(path.suffix.lower() == ".py" for path in repo_dir.rglob("*.py")),
            "dependencies": unique_dependencies,
            "scripts": scripts,
        }

    def _analyze_node(self, repo_dir: Path) -> Dict[str, Any]:
        package_path = repo_dir / "package.json"
        if not package_path.exists():
            return {
                "detected": any(path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx"} for path in repo_dir.rglob("*")),
                "dependencies": [],
                "scripts": {},
                "main": "",
            }

        try:
            package_data = json.loads(_safe_read_text(package_path, limit=20000) or "{}")
        except Exception:
            package_data = {}

        dependencies = sorted(
            set(
                list((package_data.get("dependencies") or {}).keys())
                + list((package_data.get("devDependencies") or {}).keys())
            )
        )
        return {
            "detected": True,
            "dependencies": [dependency.lower() for dependency in dependencies],
            "scripts": {str(key): str(value) for key, value in (package_data.get("scripts") or {}).items()},
            "main": str(package_data.get("main") or ""),
        }

    def _detect_frameworks(self, python_info: Dict[str, Any], node_info: Dict[str, Any], readme_path: Path | None) -> List[str]:
        framework_hits = set()
        haystacks = [" ".join(python_info.get("dependencies", [])), " ".join(node_info.get("dependencies", []))]
        if readme_path is not None:
            haystacks.append(_safe_read_text(readme_path, limit=3000).lower())
        combined = "\n".join(haystacks).lower()
        for hint, label in _FRAMEWORK_HINTS.items():
            if hint in combined:
                framework_hits.add(label)
        return sorted(framework_hits)

    def _detect_entrypoints(
        self,
        repo_dir: Path,
        manifests: Dict[str, str],
        python_info: Dict[str, Any],
        node_info: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        entrypoints: List[Dict[str, Any]] = []

        for script_name, target in python_info.get("scripts", {}).items():
            module_name = target.split(":", 1)[0]
            entrypoints.append(
                {
                    "path": "pyproject.toml",
                    "runtime": "python",
                    "kind": "python_script",
                    "name": script_name,
                    "target": target,
                    "module": module_name,
                    "command_hint": f"python -m {module_name}",
                }
            )

        for filename in ["main.py", "app.py", "server.py", "cli.py", "run.py"]:
            candidate = repo_dir / filename
            if candidate.exists():
                entrypoints.append(
                    {
                        "path": filename,
                        "runtime": "python",
                        "kind": "file",
                        "command_hint": f"python {filename}",
                    }
                )

        for path in repo_dir.glob("src/*/cli.py"):
            entrypoints.append(
                {
                    "path": str(path.relative_to(repo_dir)).replace("\\", "/"),
                    "runtime": "python",
                    "kind": "python_module",
                    "module": _module_name_from_path(repo_dir, path),
                    "command_hint": f"python -m {_module_name_from_path(repo_dir, path)}",
                }
            )

        if "package.json" in manifests:
            main_file = node_info.get("main") or ""
            if main_file:
                entrypoints.append(
                    {
                        "path": main_file.replace("\\", "/"),
                        "runtime": "node",
                        "kind": "node_main",
                        "command_hint": f"node {main_file}",
                    }
                )
            for filename in ["index.js", "server.js", "app.js", "main.js", "index.ts", "main.ts"]:
                candidate = repo_dir / filename
                if candidate.exists():
                    entrypoints.append(
                        {
                            "path": filename,
                            "runtime": "node",
                            "kind": "file",
                            "command_hint": f"node {filename}",
                        }
                    )

        deduped = []
        seen = set()
        for entrypoint in entrypoints:
            key = (entrypoint.get("runtime"), entrypoint.get("path"), entrypoint.get("kind"), entrypoint.get("module", ""))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(entrypoint)
        return deduped

    def _find_tests(self, repo_dir: Path) -> List[str]:
        tests = []
        for candidate in [repo_dir / "tests", repo_dir / "test", repo_dir / "__tests__"]:
            if candidate.exists():
                tests.append(str(candidate.relative_to(repo_dir)).replace("\\", "/"))
        for path in repo_dir.glob("test_*.py"):
            tests.append(str(path.relative_to(repo_dir)).replace("\\", "/"))
        return tests

    def _find_ci(self, repo_dir: Path) -> List[str]:
        workflows = []
        workflow_dir = repo_dir / ".github" / "workflows"
        if workflow_dir.exists():
            for file in workflow_dir.iterdir():
                if file.suffix.lower() in {".yml", ".yaml"}:
                    workflows.append(str(file.relative_to(repo_dir)).replace("\\", "/"))
        return sorted(workflows)

    def _trace(self, event: str, payload: dict) -> None:
        if self._trace_writer is not None:
            self._trace_writer.write(event, payload)


class ModuleExtractor:
    def __init__(self, trace_writer: Any | None = None):
        self._trace_writer = trace_writer

    def extract(self, repo_dir: Path, static_analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
        modules: List[Dict[str, Any]] = []
        seen_paths = set()

        for init_file in repo_dir.rglob("__init__.py"):
            if any(part in _IGNORE_DIRS for part in init_file.parts):
                continue
            parent = init_file.parent
            relative = str(parent.relative_to(repo_dir)).replace("\\", "/")
            if not relative or "tests" in relative.lower():
                continue
            code_count = _count_code_files(parent)
            if code_count == 0 or relative in seen_paths:
                continue
            seen_paths.add(relative)
            modules.append(
                {
                    "name": parent.name,
                    "path": relative,
                    "kind": _infer_module_kind(relative),
                    "language": "Python",
                    "files": code_count,
                    "reason": f"Python 包，包含 {code_count} 个代码文件",
                }
            )

        for root_name in ["src", "lib", "app", "apps", "packages", "services"]:
            root = repo_dir / root_name
            if not root.exists():
                continue
            for child in root.iterdir():
                if not child.is_dir() or child.name in _IGNORE_DIRS:
                    continue
                relative = str(child.relative_to(repo_dir)).replace("\\", "/")
                if relative in seen_paths or "tests" in relative.lower():
                    continue
                code_count = _count_code_files(child)
                if code_count < 2:
                    continue
                language = self._infer_language(child)
                modules.append(
                    {
                        "name": child.name,
                        "path": relative,
                        "kind": _infer_module_kind(relative),
                        "language": language,
                        "files": code_count,
                        "reason": f"目录包含 {code_count} 个 {language} 代码文件",
                    }
                )
                seen_paths.add(relative)

        for entrypoint in static_analysis.get("entrypoints", []):
            path = entrypoint.get("path", "")
            if not path or path in seen_paths:
                continue
            modules.append(
                {
                    "name": Path(path).stem or path,
                    "path": path,
                    "kind": "entrypoint",
                    "language": "Python" if entrypoint.get("runtime") == "python" else "Node",
                    "files": 1,
                    "reason": "检测到可直接执行的入口",
                }
            )
            seen_paths.add(path)

        modules.sort(key=lambda item: (item.get("files", 0), item.get("kind", "")), reverse=True)
        selected = modules[:8]
        self._trace("module_extractor.completed", {"usable_modules": selected})
        return selected

    def _infer_language(self, path: Path) -> str:
        counter = Counter(
            _LANGUAGE_BY_SUFFIX[file.suffix.lower()]
            for file in path.rglob("*")
            if file.is_file() and file.suffix.lower() in _LANGUAGE_BY_SUFFIX
        )
        if not counter:
            return "Unknown"
        return counter.most_common(1)[0][0]

    def _trace(self, event: str, payload: dict) -> None:
        if self._trace_writer is not None:
            self._trace_writer.write(event, payload)


class ExpectationMatcher:
    def __init__(self, trace_writer: Any | None = None):
        self._trace_writer = trace_writer

    def match(
        self,
        expected_capabilities: Iterable[str] | None,
        static_analysis: Dict[str, Any],
        usable_modules: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        capabilities = [item.strip() for item in (expected_capabilities or []) if item and item.strip()]
        if not capabilities:
            result = {"capabilities": [], "matched_count": 0, "total": 0, "match_ratio": 0.0}
            self._trace("expectation_matcher.completed", result)
            return result

        evidence_sources = {
            "README": static_analysis.get("readme_excerpt", "").lower(),
            "frameworks": " ".join(static_analysis.get("frameworks", [])).lower(),
            "entrypoints": " ".join(item.get("path", "") for item in static_analysis.get("entrypoints", [])).lower(),
            "modules": " ".join(f"{item.get('name', '')} {item.get('path', '')}" for item in usable_modules).lower(),
            "paths": " ".join(static_analysis.get("sample_paths", [])).lower(),
        }

        matches = []
        matched_count = 0
        for capability in capabilities:
            search_terms = self._expand_terms(capability)
            matched_sources = []
            for source_name, haystack in evidence_sources.items():
                if any(term in haystack for term in search_terms if term):
                    matched_sources.append(source_name)
            matched = bool(matched_sources)
            if not matched:
                tokens = [token for token in re.split(r"[^a-z0-9]+", capability.lower()) if token]
                matched = bool(tokens) and all(any(token in haystack for haystack in evidence_sources.values()) for token in tokens)
                if matched:
                    matched_sources.append("tokens")
            if matched:
                matched_count += 1
            matches.append(
                {
                    "capability": capability,
                    "matched": matched,
                    "evidence": matched_sources[:3],
                }
            )

        result = {
            "capabilities": matches,
            "matched_count": matched_count,
            "total": len(capabilities),
            "match_ratio": matched_count / len(capabilities) if capabilities else 0.0,
        }
        self._trace("expectation_matcher.completed", result)
        return result

    def _expand_terms(self, capability: str) -> List[str]:
        base = capability.lower().strip()
        terms = {base}
        aliases = {
            "agent": {"agent", "assistant", "workflow", "react"},
            "cli": {"cli", "command", "argparse", "click", "typer"},
            "api": {"api", "server", "fastapi", "flask", "express"},
            "web": {"web", "gradio", "streamlit", "react", "frontend", "ui"},
            "rag": {"rag", "retrieval", "embedding", "vector"},
            "github": {"github", "repo", "repository"},
            "sandbox": {"sandbox", "runner", "subprocess"},
            "resume": {"resume", "cv", "job"},
            "match": {"match", "matcher", "matching"},
            "search": {"search", "recommend", "recommender"},
        }
        for key, values in aliases.items():
            if key in base:
                terms.update(values)
        terms.update(token for token in re.split(r"[^a-z0-9]+", base) if len(token) >= 2)
        return sorted(terms)

    def _trace(self, event: str, payload: dict) -> None:
        if self._trace_writer is not None:
            self._trace_writer.write(event, payload)
