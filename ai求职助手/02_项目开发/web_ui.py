"""
AI 求职助手 Web UI

基于 Gradio 的交互界面，功能：
1. 聊天界面 - 多轮对话
2. 职位分析面板 - 粘贴 JD 分析
3. 学习计划展示
4. 会话历史
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
    from openai import OpenAI
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


# ── 用户画像加载 ─────────────────────────────────────────────────────────────

def load_profile(profile_json: str) -> Tuple[str, str]:
    """解析用户画像 JSON"""
    global _profile, _agent
    try:
        profile = json.loads(profile_json)
        _profile = profile
        _agent = None  # 重置 agent
        name = profile.get("name", "用户")
        skills = list(profile.get("skills", {}).keys())
        cities = profile.get("target_cities", [])
        summary = (
            f"✅ 已加载用户画像\n"
            f"姓名: {name}\n"
            f"技能: {', '.join(skills[:6])}{'...' if len(skills) > 6 else ''}\n"
            f"目标城市: {', '.join(cities)}"
        )
        return summary, "画像加载成功，可以开始对话"
    except Exception as e:
        return f"❌ 解析失败: {e}", ""


def load_profile_from_file(file) -> Tuple[str, str]:
    """从文件加载用户画像"""
    if file is None:
        return "请选择文件", ""
    try:
        content = Path(file.name).read_text(encoding="utf-8")
        return load_profile(content)
    except Exception as e:
        return f"❌ 读取文件失败: {e}", ""


# ── 聊天功能 ─────────────────────────────────────────────────────────────────

def chat(message: str, history: List[dict], jd_text: str) -> Tuple[List[dict], str, str]:
    """处理聊天消息"""
    global _profile

    if not _profile:
        history = history + [{"role": "assistant", "content": "⚠️ 请先在左侧加载用户画像"}]
        return history, "", ""

    if not message.strip():
        return history, "", ""

    try:
        agent = _get_agent(_profile)

        # 如果有粘贴的 JD，预加载
        if jd_text.strip():
            from openai import OpenAI
            client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)
            jobs = _parse_jd_text(client, jd_text)
            if jobs:
                agent.preload_jobs(jobs)

        # 运行 Agent
        result = agent.run(message)
        history = history + [
            {"role": "user", "content": message},
            {"role": "assistant", "content": result},
        ]

        # 更新分析面板
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
        # 补全 jd_text
        for j in jobs:
            if not j.get("jd_text"):
                j["jd_text"] = jd_text
        return jobs
    except Exception as e:
        logger.warning("JD 解析失败: %s", e)
        # 返回简单格式
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

        # 分数颜色
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


def get_analyzed_jobs() -> List[str]:
    """获取已分析的职位 ID 列表"""
    if _agent is None:
        return []
    return list(_agent._results.keys())


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


# ── 默认用户画像 ─────────────────────────────────────────────────────────────

_DEFAULT_PROFILE = json.dumps({
    "name": "示例用户",
    "target_cities": ["上海", "北京"],
    "target_keywords": ["AI Agent", "LLM", "大模型"],
    "skills": {
        "Python": {"level": 3},
        "FastAPI": {"level": 3},
        "LangChain": {"level": 2},
        "Docker": {"level": 1},
        "Git": {"level": 3},
        "RAG": {"level": 1}
    },
    "experience_years": 3,
    "education": "本科",
    "preferences": {
        "cities": ["上海", "北京"],
        "salary_min": 25000
    }
}, ensure_ascii=False, indent=2)

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
                        profile_input = gr.Textbox(
                            label="用户画像 JSON",
                            value=_DEFAULT_PROFILE,
                            lines=12,
                            max_lines=20,
                        )
                        with gr.Row():
                            load_btn = gr.Button("加载画像", variant="primary")
                            file_btn = gr.UploadButton("从文件加载", file_types=[".json"])
                        profile_status = gr.Textbox(label="状态", interactive=False, lines=4)

                        gr.Markdown("### 粘贴 JD（可选）")
                        jd_input = gr.Textbox(
                            label="职位描述",
                            placeholder="粘贴职位描述，Agent 将自动解析并分析...",
                            lines=6,
                        )

                    with gr.Column(scale=2):
                        chatbot = gr.Chatbot(
                            label="对话",
                            height=500,
                        )
                        with gr.Row():
                            msg_input = gr.Textbox(
                                label="输入消息",
                                placeholder="例如：帮我分析这个职位 / 再推荐几个项目 / 制定学习计划",
                                scale=4,
                            )
                            send_btn = gr.Button("发送", variant="primary", scale=1)
                        clear_btn = gr.Button("清空会话", variant="secondary")

                with gr.Row():
                    analysis_panel = gr.Markdown("暂无分析结果", label="分析结果")

                # 事件绑定
                load_btn.click(
                    load_profile,
                    inputs=[profile_input],
                    outputs=[profile_status, profile_status],
                )
                file_btn.upload(
                    load_profile_from_file,
                    inputs=[file_btn],
                    outputs=[profile_status, profile_status],
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

### 1. 加载用户画像
在左侧编辑或粘贴你的用户画像 JSON，点击「加载画像」。

### 2. 开始对话
在对话框中输入任务，例如：
- `帮我分析当前市场上适合我的 AI Agent 工程师职位`
- `帮我分析这个职位`（配合粘贴 JD）

### 3. 追问
Agent 支持多轮对话，可以直接追问：
- `再推荐几个学习项目`
- `这个职位匹配度怎么样`
- `对比一下这几个职位`
- `制定3个月学习计划`

### 4. 粘贴 JD
在左侧「粘贴 JD」区域粘贴职位描述，Agent 会自动解析并分析。

### 5. 学习计划
在「学习计划」标签页，输入职位 ID 和时间框架，生成详细学习计划。

---

## 用户画像格式

```json
{
  "name": "你的名字",
  "target_cities": ["上海", "北京"],
  "target_keywords": ["AI Agent", "LLM"],
  "skills": {
    "Python": {"level": 3},
    "LangChain": {"level": 2}
  },
  "experience_years": 3
}
```

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
