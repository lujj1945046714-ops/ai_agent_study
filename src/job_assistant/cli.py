from __future__ import annotations

import argparse
import logging
import json
import sys

from job_assistant import config
from job_assistant.agent.job_agent import JobAssistantAgent
from job_assistant.llm_runtime import create_chat_model
from job_assistant.modules.scraper import parse_jd_input
from job_assistant.onboarding import get_or_create_profile
from job_assistant.repo_audit import audit_repository


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI 求职助手（CLI）")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="运行求职分析 Agent")
    run_parser.add_argument(
        "--task",
        default="帮我分析当前最适合我的 AI Agent 工程师职位，并给出学习建议",
        help="Agent 的总任务描述",
    )
    run_parser.add_argument("--max-steps", type=int, default=30, help="ReAct 最大步数")
    run_parser.add_argument("--no-phase2", action="store_true", help="禁用会话记忆/主动建议等增强功能")

    audit_parser = subparsers.add_parser("audit-repo", help="下载并审计某个 GitHub 仓库")
    audit_parser.add_argument("repo_url", help="GitHub 仓库 URL，或本地仓库路径")
    audit_parser.add_argument(
        "--capability",
        action="append",
        dest="expected_capabilities",
        default=[],
        help="期望能力标签，可重复传入，例如 --capability agent --capability cli",
    )
    audit_parser.add_argument("--no-light-run", action="store_true", help="只做静态分析，不做轻量运行验证")
    audit_parser.add_argument("--keep-workspace", action="store_true", help="保留下载仓库及其本地依赖")
    return parser


def _normalize_argv(argv: list[str] | None) -> list[str]:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        return ["run"]
    if args[0] in {"run", "audit-repo", "-h", "--help"}:
        return args
    return ["run", *args]


def _run_agent(args: argparse.Namespace) -> int:
    llm = create_chat_model()
    name, profile = get_or_create_profile(llm=llm)
    jobs = parse_jd_input(llm=llm)

    agent = JobAssistantAgent(
        user_profile=profile,
        session_id=name or "default",
        max_steps=args.max_steps,
        enable_phase2=not args.no_phase2,
    )
    if jobs:
        agent.preload_jobs(jobs)

    result = agent.run(args.task, stream=True, on_token=lambda t: print(t, end="", flush=True))
    print("\n\n── Agent 总结 ──")
    print(result)
    return 0


def _run_repo_audit(args: argparse.Namespace) -> int:
    result = audit_repository(
        args.repo_url,
        expected_capabilities=args.expected_capabilities,
        allow_light_run=not args.no_light_run,
        keep_workspace=args.keep_workspace,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    args = _build_parser().parse_args(_normalize_argv(argv))

    config.ensure_dirs()
    if args.command == "audit-repo":
        return _run_repo_audit(args)
    return _run_agent(args)


if __name__ == "__main__":
    raise SystemExit(main())
