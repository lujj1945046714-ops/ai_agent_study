from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from job_assistant.repo_audit.models import RepoAuditResult


class AuditReporter:
    def __init__(self, trace_writer: Any | None = None):
        self._trace_writer = trace_writer

    def write(self, result: RepoAuditResult) -> None:
        audit_json = Path(result.artifacts["audit_json"])
        audit_md = Path(result.artifacts["audit_md"])
        audit_json.parent.mkdir(parents=True, exist_ok=True)
        audit_md.parent.mkdir(parents=True, exist_ok=True)

        audit_json.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        audit_md.write_text(self._render_markdown(result), encoding="utf-8")
        self._trace(
            "reporting.completed",
            {
                "audit_json": str(audit_json),
                "audit_md": str(audit_md),
            },
        )

    def _render_markdown(self, result: RepoAuditResult) -> str:
        capabilities = result.expected_capabilities or []
        modules = result.usable_modules or []
        highlights = result.highlights or []
        risks = result.risks or []
        run_summary = result.run_summary or {}
        static_analysis = result.static_analysis or {}

        lines = [
            f"# 仓库审计报告：{result.repo.get('display_name') or result.repo.get('url')}",
            "",
            "## 结论",
            f"- Verdict: `{result.verdict}`",
            f"- Summary: {result.summary}",
            "",
            "## 亮点",
            *self._bullet_list(highlights, fallback="- 暂无"),
            "",
            "## 可复用模块",
            *self._module_lines(modules),
            "",
            "## 期望能力匹配",
            *self._capability_lines(capabilities),
            "",
            "## 静态分析",
            f"- 主要语言: {', '.join(static_analysis.get('primary_languages', [])) or '未识别'}",
            f"- 框架: {', '.join(static_analysis.get('frameworks', [])) or '未识别'}",
            f"- 入口: {', '.join(item.get('path', '') for item in static_analysis.get('entrypoints', [])) or '未识别'}",
            f"- 测试: {'有' if static_analysis.get('has_tests') else '无'}",
            f"- CI: {', '.join(static_analysis.get('ci_workflows', [])) or '无'}",
            "",
            "## 运行验证",
            f"- 状态: `{run_summary.get('status', 'unknown')}`",
            f"- 运行时: {run_summary.get('runtime', 'n/a')}",
            f"- 命令: `{run_summary.get('command', '')}`" if run_summary.get("command") else "- 命令: 未执行",
            f"- 出口码: {run_summary.get('exit_code', 'n/a')}",
            "",
            "## 风险",
            *self._bullet_list(risks, fallback="- 暂无明显风险"),
            "",
            "## 生命周期",
            f"- 工作目录: `{result.workspace.get('workspace_root', '')}`",
            f"- 清理状态: {'已清理' if result.cleanup.get('performed') else '保留工作区'}",
            f"- 保留产物: {', '.join(result.cleanup.get('preserved', [])) or '无'}",
        ]
        return "\n".join(lines).strip() + "\n"

    def _capability_lines(self, capabilities: Iterable[dict]) -> list[str]:
        lines = []
        for item in capabilities:
            status = "matched" if item.get("matched") else "not_matched"
            evidence = ", ".join(item.get("evidence", [])) or "无"
            lines.append(f"- {item.get('capability')}: `{status}`（evidence: {evidence}）")
        return lines or ["- 未提供期望能力"]

    def _module_lines(self, modules: Iterable[dict]) -> list[str]:
        lines = []
        for item in modules:
            lines.append(f"- `{item.get('path', '')}` · {item.get('kind', 'module')} · {item.get('reason', '')}")
        return lines or ["- 未识别出明确的可复用模块"]

    def _bullet_list(self, items: Iterable[str], fallback: str) -> list[str]:
        values = [f"- {item}" for item in items if item]
        return values or [fallback]

    def _trace(self, event: str, payload: dict) -> None:
        if self._trace_writer is not None:
            self._trace_writer.write(event, payload)
