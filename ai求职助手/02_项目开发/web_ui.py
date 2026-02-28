"""
AI 求职助手 Web UI

基于 Gradio 的交互界面，功能：
1. 简历上传/粘贴 → 一键提取画像
2. JD 粘贴 + 一键分析匹配度
3. 多轮对话
4. 学习计划展示
5. 会话历史
"""

import json
import sys
import logging
from pathlib import Path
from typing import List, Tuple, Optional

import gradio as gr

# 确保项目根目录在 sys.path
_BASE = Path(__file__).resolve().parent
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

import config
from onboarding import (
    extract_profile_from_resume,
    format_profile_summary,
    save_profile,
    load_existing_profile,
    PROFILE_PATH,
)

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ── 全局状态 ────────────────────────────────────────────────────────────────

_agent = None
_profile = None
_output_dir = _BASE / "output"
_output_dir.mkdir(exist_ok=True)


def _get_agent(profile: dict):
    """获取或创建 Agent 实例"""
    global _agent
    from agent.react_agent import JobSearchAgent

    if _agent is None:
        _agent = JobSearchAgent(
            user_profile=profile,
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
            model=config.DEEPSEEK_MODEL,
            output_dir=_output_dir,
            name="web_session",
            enable_phase2=True,
        )
    return _agent


# ── 简历读取 ─────────────────────────────────────────────────────────────────

def _read_resume_file(file) -> str:
    """读取上传的简历文件内容"""
    if file is None:
        return ""
    # gr.File 可能传入路径字符串或带 .name 属性的对象
    path = Path(file if isinstance(file, (str, Path)) else file.name)
    suffix = path.suffix.lower()
    if suffix in (".txt", ".md"):
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_text(encoding="gbk", errors="replace")
    elif suffix == ".pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError:
            return "❌ 请安装 pypdf：pip install pypdf"
        except Exception as e:
            return f"❌ PDF 读取失败: {e}"
    else:
        return f"❌ 不支持的文件格式: {suffix}，请上传 .txt / .pdf / .md"


# ── 简历分析 ─────────────────────────────────────────────────────────────────

def analyze_resume(resume_text: str, resume_file) -> Tuple[str, str]:
    """触发简历分析，返回 (profile_status, profile_summary)"""
    global _profile, _agent

    try:
        text = resume_text.strip()
        if not text:
            text = _read_resume_file(resume_file)
        if not text:
            return "⚠️ 请粘贴简历内容或上传简历文件", ""
        if text.startswith("❌"):
            return text, ""

        from openai import OpenAI
        client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)
        profile = extract_profile_from_resume(client, config.DEEPSEEK_MODEL, text)
        _profile = profile
        _agent = None
        save_profile(profile)
        summary = format_profile_summary(profile)
        return "✅ 画像提取成功，已保存", summary
    except Exception as e:
        logger.exception("简历分析失败")
        return f"❌ 分析失败: {e}", ""


# ── JD 确认并分析 ─────────────────────────────────────────────────────────────

def confirm_jd(jd_text: str, chat_history: list) -> Tuple[list, str, str]:
    """JD 确认并直接分析，返回 (chat_history, jd_status, analysis_md)"""
    global _profile
    chat_history = chat_history or []

    if not _profile:
        msg = "⚠️ 请先上传简历并建立画像"
        chat_history = chat_history + [{"role": "assistant", "content": msg}]
        return chat_history, msg, ""

    if not jd_text.strip():
        return chat_history, "⚠️ 请先粘贴职位描述", ""

    try:
        from openai import OpenAI
        client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)
        jobs = _parse_jd_text(client, jd_text)
        agent = _get_agent(_profile)
        agent.preload_jobs(jobs)

        result = agent.run("请分析这个职位与我的匹配度，列出匹配技能和技能缺口")
        jd_preview = " ".join(jd_text.split())
        jd_display = (jd_preview[:80] + "...") if len(jd_preview) > 80 else jd_preview
        chat_history = chat_history + [
            {"role": "user", "content": f"[已读入JD] {jd_display}"},
            {"role": "assistant", "content": result},
        ]
        jd_status = f"✅ 已读入 {len(jobs)} 个职位"
        analysis_md = _build_analysis_panel(agent)
        return chat_history, jd_status, analysis_md
    except Exception as e:
        logger.exception("JD 分析失败")
        err = f"❌ 分析失败: {e}"
        chat_history = chat_history + [{"role": "assistant", "content": err}]
        return chat_history, err, ""


# ── 页面加载时恢复画像 ────────────────────────────────────────────────────────

def _load_profile_on_start() -> Tuple[str, str]:
    """页面加载时检测已有画像"""
    global _profile, _agent
    existing = load_existing_profile()
    if existing:
        _profile = existing
        _agent = None
        summary = format_profile_summary(existing)
        return "✅ 已加载本地画像", summary
    _profile = None
    _agent = None
    return "请上传简历或粘贴简历内容以建立画像", ""


# ── 聊天功能 ─────────────────────────────────────────────────────────────────

def chat(message: str, history: List[dict], jd_text: str) -> Tuple[List[dict], str, str]:
    """处理聊天消息"""
    global _profile

    if not _profile:
        history = history + [{"role": "assistant", "content": "⚠️ 请先在左侧上传简历建立画像"}]
        return history, "", ""

    if not message.strip():
        return history, "", ""

    try:
        agent = _get_agent(_profile)

        if jd_text.strip():
            from openai import OpenAI
            client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)
            jobs = _parse_jd_text(client, jd_text)
            if jobs:
                agent.preload_jobs(jobs)

        result = agent.run(message)
        history = history + [
            {"role": "user", "content": message},
            {"role": "assistant", "content": result},
        ]
        analysis_md = _build_analysis_panel(agent)
        return history, "", analysis_md

    except Exception as e:
        logger.exception("聊天处理失败")
        history = history + [
            {"role": "user", "content": message},
            {"role": "assistant", "content": f"❌ 处理失败: {e}"},
        ]
        return history, "", ""


def _parse_jd_text(client, jd_text: str) -> list:
    """用 LLM 解析粘贴的 JD 文本"""
    try:
        prompt = f"""请从以下职位描述中提取结构化信息，返回 JSON 数组：
[{{
  "job_id": "jd-001",
  "title": "职位名称",
  "company": "公司名称",
  "city": "城市",
  "salary": "薪资范围",
  "jd_text": "完整JD文本"
}}]

职位描述：
{jd_text[:3000]}

只返回 JSON，不要其他内容。"""

        resp = client.chat.completions.create(
            model=config.DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        if "```" in raw:
            raw = raw.split("```")[1].lstrip("json").strip()
        jobs = json.loads(raw)
        for j in jobs:
            if not j.get("jd_text"):
                j["jd_text"] = jd_text
        return jobs
    except Exception as e:
        logger.warning("JD 解析失败: %s", e)
        return [{
            "job_id": "jd-001",
            "title": "待分析职位",
            "company": "未知公司",
            "city": "未知城市",
            "salary": "面议",
            "jd_text": jd_text,
        }]


def _build_analysis_panel(agent) -> str:
    """构建分析结果面板的 Markdown"""
    if not agent._results:
        return "暂无分析结果"

    lines = ["## 📊 职位分析结果\n"]

    for job_id, data in agent._results.items():
        job = agent._job_store.get(job_id, {})
        match = data.get("match", {})
        score = match.get("score", 0)

        if score >= 85:
            badge = "🟢"
        elif score >= 70:
            badge = "🟡"
        elif score >= 50:
            badge = "🟠"
        else:
            badge = "🔴"

        lines.append(f"### {badge} {job.get('title', job_id)}")
        lines.append(f"**公司**: {job.get('company', '—')} | **城市**: {job.get('city', '—')} | **薪资**: {job.get('salary', '—')}")
        lines.append(f"**匹配度**: {score}/100\n")

        matched = match.get("matched_skills", [])
        if matched:
            lines.append(f"✅ **已匹配**: {', '.join(matched[:5])}")

        gaps = match.get("skill_gaps", [])
        if gaps:
            lines.append(f"❌ **技能缺口**: {', '.join(gaps[:5])}")

        repos = data.get("repos", [])
        if repos:
            lines.append(f"\n📚 **推荐学习**:")
            for r in repos[:3]:
                repo = r.get("repo", "")
                stars = r.get("stars", 0)
                lines.append(f"  - [{repo}](https://github.com/{repo}) ⭐{stars:,}")

        lines.append("")

    return "\n".join(lines)


# ── 学习计划 ─────────────────────────────────────────────────────────────────

def generate_plan(job_id: str, timeframe: str) -> str:
    """生成学习计划"""
    global _profile
    if not _profile or _agent is None:
        return "⚠️ 请先加载用户画像并分析职位"

    result = _agent._dispatch("create_learning_plan", {
        "job_id": job_id,
        "timeframe": timeframe,
    })

    if "error" in result:
        return f"❌ {result['error']}"

    return result.get("formatted_plan", "计划生成失败")


# ── 会话管理 ─────────────────────────────────────────────────────────────────

def clear_session() -> Tuple[List[dict], str, str]:
    """清空会话"""
    global _agent
    _agent = None
    return [], "", "会话已清空"


def get_session_stats() -> str:
    """获取会话统计"""
    if _agent is None or not _agent.enable_phase2:
        return "暂无会话数据"

    stats = _agent.conversation_memory.get_statistics()
    lines = ["## 📈 会话统计\n"]
    label_map = {
        "analyzed_jobs": "已分析职位",
        "match_results": "匹配结果",
        "recommended_projects": "推荐项目组",
        "conversation_turns": "对话轮数",
        "session_duration_minutes": "会话时长(分钟)",
    }
    for k, v in stats.items():
        label = label_map.get(k, k)
        lines.append(f"- **{label}**: {v}")
    return "\n".join(lines)


# ── UI 构建 ──────────────────────────────────────────────────────────────────

def build_ui():
    with gr.Blocks(title="AI 求职助手") as demo:

        gr.Markdown("# 🤖 AI 求职助手\n> 智能分析职位匹配度，制定个性化学习计划")

        with gr.Tabs():

            # ── Tab 1: 对话 ──────────────────────────────────────────────
            with gr.Tab("💬 智能对话"):
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("### 用户画像")
                        resume_input = gr.Textbox(
                            label="粘贴简历内容",
                            placeholder="将简历文字粘贴到此处...",
                            lines=8,
                        )
                        resume_file = gr.File(
                            label="或上传简历文件（.txt / .pdf / .md）",
                            file_types=[".txt", ".pdf", ".md"],
                        )
                        analyze_resume_btn = gr.Button("分析简历并建立画像", variant="primary")
                        profile_status = gr.Textbox(label="状态", interactive=False, lines=1)
                        profile_summary = gr.Textbox(label="画像摘要", interactive=False, lines=2)

                        gr.Markdown("### 粘贴 JD")
                        jd_input = gr.Textbox(
                            label="职位描述",
                            placeholder="粘贴职位描述...",
                            lines=6,
                        )
                        confirm_jd_btn = gr.Button("确认JD并分析匹配度", variant="primary")
                        jd_status = gr.Textbox(label="JD状态", interactive=False, lines=1)

                    with gr.Column(scale=2):
                        chatbot = gr.Chatbot(
                            label="对话",
                            height=500,
                        )
                        with gr.Row():
                            msg_input = gr.Textbox(
                                label="输入消息",
                                placeholder="例如：再推荐几个项目 / 制定学习计划",
                                scale=4,
                            )
                            send_btn = gr.Button("发送", variant="primary", scale=1)
                        clear_btn = gr.Button("清空会话", variant="secondary")

                with gr.Row():
                    analysis_panel = gr.Markdown("暂无分析结果", label="分析结果")

                # 事件绑定
                demo.load(
                    _load_profile_on_start,
                    outputs=[profile_status, profile_summary],
                )
                analyze_resume_btn.click(
                    analyze_resume,
                    inputs=[resume_input, resume_file],
                    outputs=[profile_status, profile_summary],
                )
                confirm_jd_btn.click(
                    confirm_jd,
                    inputs=[jd_input, chatbot],
                    outputs=[chatbot, jd_status, analysis_panel],
                )
                send_btn.click(
                    chat,
                    inputs=[msg_input, chatbot, jd_input],
                    outputs=[chatbot, msg_input, analysis_panel],
                )
                msg_input.submit(
                    chat,
                    inputs=[msg_input, chatbot, jd_input],
                    outputs=[chatbot, msg_input, analysis_panel],
                )
                clear_btn.click(
                    clear_session,
                    outputs=[chatbot, analysis_panel, profile_status],
                )

            # ── Tab 2: 学习计划 ──────────────────────────────────────────
            with gr.Tab("📅 学习计划"):
                gr.Markdown("### 为已分析的职位制定学习计划")
                with gr.Row():
                    job_id_input = gr.Textbox(
                        label="职位 ID",
                        placeholder="例如：job-001",
                    )
                    timeframe_input = gr.Dropdown(
                        label="时间框架",
                        choices=["3months", "6months", "12months"],
                        value="3months",
                    )
                    plan_btn = gr.Button("生成计划", variant="primary")

                plan_output = gr.Markdown("请先在对话页面分析职位，然后输入职位 ID 生成学习计划")

                plan_btn.click(
                    generate_plan,
                    inputs=[job_id_input, timeframe_input],
                    outputs=[plan_output],
                )

            # ── Tab 3: 会话统计 ──────────────────────────────────────────
            with gr.Tab("📊 会话统计"):
                refresh_btn = gr.Button("刷新统计", variant="secondary")
                stats_output = gr.Markdown("点击刷新查看会话统计")

                refresh_btn.click(
                    get_session_stats,
                    outputs=[stats_output],
                )

            # ── Tab 4: 使用说明 ──────────────────────────────────────────
            with gr.Tab("📖 使用说明"):
                gr.Markdown("""
## 使用步骤

### 1. 建立用户画像
在左侧粘贴简历内容或上传简历文件（.txt / .pdf / .md），点击「分析简历并建立画像」。

### 2. 分析 JD
在左侧「粘贴 JD」区域粘贴职位描述，点击「确认JD并分析匹配度」，右侧将直接输出匹配分析结果。

### 3. 继续对话
在对话框中追问，例如：
- `再推荐几个学习项目`
- `对比一下这几个职位`
- `制定3个月学习计划`

### 4. 学习计划
在「学习计划」标签页，输入职位 ID 和时间框架，生成详细学习计划。

---

## 技能等级说明

| 等级 | 含义 |
|------|------|
| 0 | 未接触 |
| 1 | 了解概念 |
| 2 | 基础使用 |
| 3 | 熟练掌握 |
| 4 | 深度实践 |
| 5 | 专家级别 |
""")

    return demo


if __name__ == "__main__":
    demo = build_ui()
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        inbrowser=True,
    )
