from typing import Any, Dict, List


class ContextManager:
    """
    Manage conversation context and system prompts.
    """

    def __init__(self):
        self._messages: List[Dict[str, str]] = []

    def build_system_prompt(self, user_profile: Dict[str, Any], memory_context: str) -> str:
        """
        Build system prompt from user profile and memory.

        Args:
            user_profile: User profile dict
            memory_context: Memory context string

        Returns:
            System prompt string
        """
        skills = ", ".join(user_profile.get("skills", []))
        roles = ", ".join(user_profile.get("target_roles", []))

        prompt = f"""你是一个专业的 AI 求职助手 Agent。

## 用户画像
- 姓名: {user_profile.get('name', '未知')}
- 技能: {skills}
- 经验: {user_profile.get('experience_years', 0)} 年
- 目标职位: {roles}

## 历史记忆
{memory_context}

## 工作原则
1. 分析职位要求，计算匹配度
2. 找出技能缺口
3. 推荐学习项目
4. 生成求职报告
"""
        return prompt

    def add_message(self, role: str, content: str) -> None:
        """
        Add message to context.

        Args:
            role: Message role (user/assistant/system)
            content: Message content
        """
        self._messages.append({"role": role, "content": content})

    def get_messages(self) -> List[Dict[str, str]]:
        """
        Get all messages.

        Returns:
            List of message dicts
        """
        return self._messages.copy()

    def clear(self) -> None:
        """Clear all messages"""
        self._messages.clear()

