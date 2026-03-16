from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import List

from agent_framework.harness.trace import JsonlTraceWriter

from job_assistant import config
from job_assistant.repo_audit.analysis import ExpectationMatcher, ModuleExtractor, StaticAnalyzer
from job_assistant.repo_audit.fetcher import RepoFetcher
from job_assistant.repo_audit.models import RepoAuditResult
from job_assistant.repo_audit.reporting import AuditReporter
from job_assistant.repo_audit.resolver import RepoResolver
from job_assistant.repo_audit.runner import SandboxRunner


def audit_repository(
    repo_url: str,
    expected_capabilities: List[str] | None = None,
    allow_light_run: bool = True,
    keep_workspace: bool = False,
) -> dict:
    config.ensure_dirs()
    resolver = RepoResolver()
    repo_spec = resolver.resolve(repo_url)

    task_id = _build_task_id(repo_spec.display_name)
    audit_dir = config.OUTPUT_DIR / "repo_audits" / task_id
    workspace_root = audit_dir / "workspace"
    repo_dir = workspace_root / "repo"
    trace_path = audit_dir / "trace.jsonl"
    trace_writer = JsonlTraceWriter(trace_path)
    reporter = AuditReporter(trace_writer)

    result = RepoAuditResult(
        task_id=task_id,
        repo=repo_spec.to_dict(),
        verdict="failed",
        summary="审计尚未执行",
        usable_modules=[],
        highlights=[],
        run_summary={},
        risks=[],
        artifacts={
            "root": str(audit_dir),
            "audit_md": str(audit_dir / "audit.md"),
            "audit_json": str(audit_dir / "audit.json"),
            "trace_jsonl": str(trace_path),
        },
        workspace={
            "audit_dir": str(audit_dir),
            "workspace_root": str(workspace_root),
            "repo_dir": str(repo_dir),
            "kept": keep_workspace,
            "exists_after_cleanup": False,
        },
        cleanup={},
        static_analysis={},
        expected_capabilities=[],
    )

    trace_writer.write(
        "audit.start",
        {
            "task_id": task_id,
            "repo": result.repo,
            "expected_capabilities": expected_capabilities or [],
            "allow_light_run": allow_light_run,
            "keep_workspace": keep_workspace,
        },
    )

    try:
        fetched_repo = RepoFetcher(trace_writer).fetch(repo_spec, workspace_root)
        static_analysis = StaticAnalyzer(trace_writer).analyze(fetched_repo)
        usable_modules = ModuleExtractor(trace_writer).extract(fetched_repo, static_analysis)
        expectation_result = ExpectationMatcher(trace_writer).match(expected_capabilities, static_analysis, usable_modules)
        run_summary = SandboxRunner(trace_writer).run(fetched_repo, static_analysis, allow_light_run=allow_light_run)

        result.verdict = _build_verdict(expectation_result, run_summary, static_analysis, usable_modules)
        result.summary = _build_summary(repo_spec.display_name, static_analysis, expectation_result, run_summary, usable_modules)
        result.usable_modules = usable_modules
        result.highlights = _build_highlights(static_analysis, usable_modules, expectation_result, run_summary)
        result.run_summary = run_summary
        result.risks = _build_risks(static_analysis, expectation_result, run_summary)
        result.static_analysis = static_analysis
        result.expected_capabilities = expectation_result.get("capabilities", [])
    except Exception as exc:
        result.verdict = "failed"
        result.summary = f"审计失败：{exc}"
        result.risks = [str(exc)]
        trace_writer.write("audit.error", {"error": str(exc)})
    finally:
        result.cleanup = _cleanup_workspace(workspace_root, result.artifacts, keep_workspace)
        result.workspace["exists_after_cleanup"] = repo_dir.exists()
        reporter.write(result)
        trace_writer.write(
            "audit.end",
            {
                "task_id": task_id,
                "verdict": result.verdict,
                "cleanup": result.cleanup,
                "artifacts": result.artifacts,
            },
        )

    return result.to_dict()


def _build_task_id(display_name: str) -> str:
    slug = "".join(ch if ch.isalnum() else "_" for ch in display_name).strip("_").lower() or "repo"
    return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{slug[:48]}"


def _build_verdict(expectation_result: dict, run_summary: dict, static_analysis: dict, usable_modules: list[dict]) -> str:
    ratio = expectation_result.get("match_ratio", 0.0)
    run_status = run_summary.get("status")
    has_tests = static_analysis.get("has_tests", False)

    if ratio >= 0.75 and run_status in {"passed", "started"}:
        return "strong_match"
    if ratio >= 0.4 or run_status in {"passed", "started"} or (usable_modules and has_tests):
        return "partial_match"
    if usable_modules:
        return "limited_match"
    return "needs_work"


def _build_summary(
    display_name: str,
    static_analysis: dict,
    expectation_result: dict,
    run_summary: dict,
    usable_modules: list[dict],
) -> str:
    languages = ", ".join(static_analysis.get("primary_languages", [])[:2]) or "未识别语言"
    frameworks = ", ".join(static_analysis.get("frameworks", [])[:2]) or "未识别框架"
    matched = expectation_result.get("matched_count", 0)
    total = expectation_result.get("total", 0)
    run_status = run_summary.get("status", "skipped")
    return (
        f"{display_name} 主要使用 {languages}，检测到 {frameworks}，"
        f"识别出 {len(usable_modules)} 个可复用模块，"
        f"期望能力匹配 {matched}/{total}，轻量运行结果为 {run_status}。"
    )


def _build_highlights(static_analysis: dict, usable_modules: list[dict], expectation_result: dict, run_summary: dict) -> list[str]:
    highlights = []
    primary_languages = static_analysis.get("primary_languages", [])
    if primary_languages:
        highlights.append(f"代码主体语言为 {', '.join(primary_languages[:2])}")
    frameworks = static_analysis.get("frameworks", [])
    if frameworks:
        highlights.append(f"检测到框架/SDK：{', '.join(frameworks[:3])}")
    if usable_modules:
        top_modules = ", ".join(module.get("name", "") for module in usable_modules[:3] if module.get("name"))
        highlights.append(f"可复用模块集中在：{top_modules}")
    if static_analysis.get("has_tests"):
        highlights.append("仓库包含测试目录，可继续做更深验证")
    if run_summary.get("status") in {"passed", "started"}:
        highlights.append(f"轻量运行验证成功，状态为 {run_summary.get('status')}")
    if expectation_result.get("total"):
        highlights.append(f"期望能力命中 {expectation_result.get('matched_count', 0)}/{expectation_result.get('total', 0)}")
    return highlights


def _build_risks(static_analysis: dict, expectation_result: dict, run_summary: dict) -> list[str]:
    risks = []
    if not static_analysis.get("readme_excerpt"):
        risks.append("README 信息不足，功能判断主要依赖代码结构")
    if not static_analysis.get("has_tests"):
        risks.append("缺少自动化测试，运行可靠性需要人工补充验证")
    if not static_analysis.get("ci_workflows"):
        risks.append("未发现 CI 工作流，工程化闭环偏弱")
    if not static_analysis.get("entrypoints"):
        risks.append("未识别出明确入口，可能无法快速启动")
    if run_summary.get("status") == "failed":
        risks.append("轻量运行失败，需要进一步排查依赖或启动方式")
    if run_summary.get("status") == "skipped":
        risks.append(f"轻量运行被跳过：{run_summary.get('reason', '未知原因')}")
    unmatched = [item["capability"] for item in expectation_result.get("capabilities", []) if not item.get("matched")]
    if unmatched:
        risks.append(f"以下期望能力证据不足：{', '.join(unmatched[:4])}")
    return risks


def _cleanup_workspace(workspace_root: Path, artifacts: dict, keep_workspace: bool) -> dict:
    preserved = [artifacts["audit_md"], artifacts["audit_json"], artifacts["trace_jsonl"]]
    if keep_workspace:
        return {
            "performed": False,
            "removed": [],
            "preserved": preserved + [str(workspace_root)],
            "reason": "keep_workspace=true",
        }

    removed = []
    if workspace_root.exists():
        shutil.rmtree(workspace_root, ignore_errors=True)
        removed.append(str(workspace_root))

    return {
        "performed": True,
        "removed": removed + [".venv", "node_modules"],
        "preserved": preserved,
        "reason": "default_cleanup",
    }
