from __future__ import annotations

import json
import logging
from pathlib import Path

from job_assistant import config
from job_assistant.llm_runtime import complete_json_flexible, complete_text, create_chat_model

logger = logging.getLogger(__name__)

PROFILE_PATH = config.PROFILES_DIR / "user_profile.json"


ONBOARDING_SYSTEM_PROMPT = """你是一位友好的求职助理，负责通过自然对话收集用户的求职画像。

你需要收集以下信息：
- 姓名或称呼
- 主要技能（每项技能的熟练度 0-5 分，0=未接触，5=专家）
- 工作经验年限
- 目标城市（可多个）
- 期望薪资范围（K/月，如 20-35K）
- 学历（可选）

规则：
1. 每次只问 1-2 个问题，保持对话自然流畅
2. 根据用户回答灵活追问细节（如技能熟练度）
3. 控制在 5-8 轮内完成收集
4. 收集完毕后，先简短总结用户信息，然后在回复末尾单独一行输出：[COLLECTION_COMPLETE]
5. 用中文交流，语气友好亲切
6. 不要一次列出所有问题，循序渐进地引导

开场白示例：你好！我是你的求职助理，让我来帮你建立求职画像。首先，请问怎么称呼你呢？"""

ONBOARDING_KICKOFF_PROMPT = "请开始建立我的求职画像，并先问第一个问题。"


def load_existing_profile() -> dict | None:
    try:
        if PROFILE_PATH.exists():
            return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("读取画像失败: %s", exc)
    return None


def save_profile(profile: dict) -> None:
    config.ensure_dirs()
    PROFILE_PATH.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("画像已保存到 %s", PROFILE_PATH)


def format_profile_summary(profile: dict) -> str:
    name = profile.get("name", "未知")

    skills = profile.get("skills", {})
    skill_parts = []
    if isinstance(skills, dict):
        for skill, info in list(skills.items())[:4]:
            lv = info.get("level", 0) if isinstance(info, dict) else info
            skill_parts.append(f"{skill}(Lv{lv})")
    skills_str = " ".join(skill_parts) if skill_parts else "—"

    cities = profile.get("target_cities") or profile.get("preferences", {}).get("cities", [])
    cities_str = "/".join(cities[:2]) if cities else "—"

    years = profile.get("experience_years", "?")

    prefs = profile.get("preferences", {})
    sal_min = prefs.get("salary_min_k") or prefs.get("salary_min", 0)
    sal_max = prefs.get("salary_max_k") or prefs.get("salary_max", 0)
    if sal_min and sal_max:
        sal_str = f"{sal_min}-{sal_max}K"
    elif sal_min:
        sal_str = f"{sal_min}K+"
    else:
        sal_str = "—"

    return f"{name} | {skills_str} | {cities_str} | {years}年 | {sal_str}"


def _extract_profile_via_llm(messages: list[dict], llm) -> dict:
    try:
        return complete_json_flexible(
            messages,
            llm=llm,
            temperature=0,
        )
    except json.JSONDecodeError as exc:
        preview = (getattr(exc, "doc", "") or "").strip().replace("\n", " ")
        if preview:
            preview = preview[:800]
            raise RuntimeError(f"画像提取失败：LLM 未返回合法 JSON。原始输出片段：{preview}") from exc
        raise RuntimeError("画像提取失败：LLM 未返回合法 JSON，且返回内容为空。") from exc


_EXTRACT_PROMPT = """请根据以下对话历史，提取用户的求职画像，严格返回 JSON，不含 markdown 代码块。

JSON 结构：
{
  "name": "称呼",
  "target_cities": ["城市1", "城市2"],
  "target_keywords": ["AI Agent", "LLM"],
  "skills": {"技能名": {"level": 0-5的整数, "years": 数字或0}},
  "experience_years": 数字,
  "education": "学历或空字符串",
  "experience_level": "初级或中级或高级",
  "preferences": {"cities": ["城市1"], "salary_min_k": 数字, "salary_max_k": 数字}
}

experience_level 推断规则：0-1年=初级，2-4年=中级，5+年=高级。
target_keywords 根据技能和目标岗位推断。
如果某字段用户未提及，使用合理默认值（数字用0，字符串用空，数组用[]）。

只返回 JSON，不要任何解释。"""


def extract_profile_from_history(history: list, llm=None) -> dict:
    lines = []
    for m in history:
        role = m.get("role", "")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            lines.append(f"用户: {content}")
        elif role == "assistant":
            lines.append(f"助理: {content}")

    text = "\n".join(lines).strip()
    return _extract_profile_via_llm(
        [
            {"role": "system", "content": _EXTRACT_PROMPT},
            {"role": "user", "content": text},
        ],
        llm=llm,
    )


_RESUME_EXTRACT_PROMPT = """你是一个简历解析专家。请从简历文本中提取用户的求职画像，严格返回 JSON，不含 markdown 代码块。

JSON 结构：
{
  "name": "称呼（若简历没有姓名可为空）",
  "target_cities": [],
  "target_keywords": [],
  "skills": {"技能名": {"level": 0-5的整数, "years": 数字或0}},
  "experience_years": 数字,
  "education": "学历或空字符串",
  "experience_level": "初级或中级或高级",
  "preferences": {"cities": [], "salary_min_k": 0, "salary_max_k": 0}
}

规则：
- 技能只写明确出现的技术名词，尽量使用通用名称（如 Python, PyTorch, RAG, LangChain）
- level 为主观估计（0-5），years 如果无法判断填 0
- experience_years 优先从工作经历推断；不确定就估计
- experience_level 推断规则：0-1年=初级，2-4年=中级，5+年=高级

只返回 JSON，不要任何解释。"""


def extract_profile_from_resume(resume_text: str, llm=None) -> dict:
    llm_model = llm or create_chat_model()
    return _extract_profile_via_llm(
        [
            {"role": "system", "content": _RESUME_EXTRACT_PROMPT},
            {"role": "user", "content": f"简历文本：\n{resume_text}"},
        ],
        llm=llm_model,
    )


def _ask_reuse(profile: dict) -> bool:
    print("\n── 已找到本地画像 ──")
    print(format_profile_summary(profile))
    print()
    while True:
        ans = input("是否使用此画像？(y/n): ").strip().lower()
        if ans in ("y", "yes", "是", ""):
            return True
        if ans in ("n", "no", "否"):
            return False
        print("请输入 y 或 n")


def _run_conversation(llm=None) -> dict:
    llm_model = llm or create_chat_model()
    messages = [{"role": "system", "content": ONBOARDING_SYSTEM_PROMPT}]

    print("\n── 开始建立求职画像 ──\n")
    opening = complete_text(
        [*messages, {"role": "user", "content": ONBOARDING_KICKOFF_PROMPT}],
        llm=llm_model,
        temperature=0.7,
    )
    messages.append({"role": "assistant", "content": opening})
    print(f"助理: {opening}\n")

    while True:
        user_input = input("你: ").strip()
        if not user_input:
            continue
        messages.append({"role": "user", "content": user_input})

        reply = complete_text(messages, llm=llm_model, temperature=0.7)
        messages.append({"role": "assistant", "content": reply})

        display = reply.replace("[COLLECTION_COMPLETE]", "").strip()
        print(f"\n助理: {display}\n")
        if "[COLLECTION_COMPLETE]" in reply:
            break

    history = [m for m in messages if m["role"] != "system"]
    return extract_profile_from_history(history, llm=llm_model)


def get_or_create_profile(llm=None) -> tuple[str, dict]:
    existing = load_existing_profile()
    if existing and _ask_reuse(existing):
        name = existing.get("name", "用户")
        return name, existing

    profile = _run_conversation(llm=llm)

    print("\n── 画像收集完成 ──")
    print(format_profile_summary(profile))

    save_profile(profile)
    print(f"已保存到 {PROFILE_PATH}\n")

    name = profile.get("name", "用户")
    return name, profile
