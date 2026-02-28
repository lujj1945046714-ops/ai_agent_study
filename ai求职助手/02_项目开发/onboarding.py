"""
对话式用户画像收集模块

CLI 和 Web UI 共用的画像收集逻辑：
- 多轮对话引导用户填写求职画像
- 自动保存 / 复用已有画像
- 提供 LLM 提取和摘要工具函数
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

PROFILE_PATH = Path(__file__).resolve().parent / "profiles" / "user_profile.json"

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

# ── 文件 I/O ──────────────────────────────────────────────────────────────────

def _load_existing_profile() -> dict | None:
    """读取已保存的画像，失败返回 None"""
    return load_existing_profile()


def load_existing_profile() -> dict | None:
    """公开 API：读取已保存的画像，失败返回 None"""
    try:
        if PROFILE_PATH.exists():
            return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("读取画像失败: %s", e)
    return None


def _save_profile(profile: dict) -> None:
    """保存画像到 PROFILE_PATH，自动创建目录"""
    save_profile(profile)


def save_profile(profile: dict) -> None:
    """公开 API：保存画像到 PROFILE_PATH，自动创建目录"""
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("画像已保存到 %s", PROFILE_PATH)


# ── 摘要格式化 ────────────────────────────────────────────────────────────────

def format_profile_summary(profile: dict) -> str:
    """生成单行摘要：姓名 | 技能(Lv) | 城市 | N年 | X-YK"""
    name = profile.get("name", "未知")

    skills = profile.get("skills", {})
    skill_parts = []
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


# ── LLM 提取画像 ──────────────────────────────────────────────────────────────

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


def extract_profile_from_history(llm_client, model: str, history: list) -> dict:
    """
    公开函数：用 LLM 将对话历史整理成标准 profile JSON。
    web_ui.py 也会 import 此函数。
    """
    # 将历史转为文本
    lines = []
    for msg in history:
        role = "助理" if msg.get("role") == "assistant" else "用户"
        content = msg.get("content", "")
        lines.append(f"{role}: {content}")
    conversation_text = "\n".join(lines)

    try:
        resp = llm_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _EXTRACT_PROMPT},
                {"role": "user", "content": f"对话历史：\n{conversation_text}"},
            ],
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # 尝试让 LLM 修复格式
            fix_resp = llm_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "请修复以下 JSON，只返回合法 JSON，不含任何解释或 markdown。"},
                    {"role": "user", "content": raw},
                ],
                temperature=0,
            )
            return json.loads(fix_resp.choices[0].message.content.strip())
    except json.JSONDecodeError as e:
        logger.error("画像 JSON 解析失败（修复后仍无效）: %s", e)
        raise ValueError(f"无法从对话中提取有效画像 JSON: {e}") from e
    except Exception as e:
        logger.error("画像提取 LLM 调用失败: %s", e)
        raise


# ── CLI 对话收集 ──────────────────────────────────────────────────────────────

def _ask_reuse(profile: dict) -> bool:
    """打印画像摘要，询问是否复用"""
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


def _run_conversation(llm_client, model: str) -> dict:
    """多轮对话主循环，检测 [COLLECTION_COMPLETE] 退出"""
    messages = [{"role": "system", "content": ONBOARDING_SYSTEM_PROMPT}]

    print("\n── 开始建立求职画像 ──\n")

    # 获取开场白
    resp = llm_client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.7,
    )
    opening = resp.choices[0].message.content
    messages.append({"role": "assistant", "content": opening})
    print(f"助理: {opening}\n")

    while True:
        user_input = input("你: ").strip()
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})

        resp = llm_client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.7,
        )
        reply = resp.choices[0].message.content
        messages.append({"role": "assistant", "content": reply})

        # 去掉标记后打印
        display = reply.replace("[COLLECTION_COMPLETE]", "").strip()
        print(f"\n助理: {display}\n")

        if "[COLLECTION_COMPLETE]" in reply:
            break

    # 提取结构化画像（去掉 system prompt，只传对话部分）
    history = [m for m in messages if m["role"] != "system"]
    return extract_profile_from_history(llm_client, model, history)


# ── 公开入口 ──────────────────────────────────────────────────────────────────

def get_or_create_profile(llm_client, model: str) -> tuple[str, dict]:
    """
    CLI 入口。检测本地文件 → 询问复用 or 重新收集。
    返回 (name, profile_dict)
    """
    existing = _load_existing_profile()
    if existing:
        if _ask_reuse(existing):
            name = existing.get("name", "用户")
            return name, existing

    # 进入对话收集
    profile = _run_conversation(llm_client, model)

    print("\n── 画像收集完成 ──")
    print(format_profile_summary(profile))

    _save_profile(profile)
    print(f"已保存到 {PROFILE_PATH}\n")

    name = profile.get("name", "用户")
    return name, profile
