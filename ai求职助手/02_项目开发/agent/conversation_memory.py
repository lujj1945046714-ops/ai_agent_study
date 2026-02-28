"""
对话记忆系统

功能：
1. 记录职位分析历史
2. 记录匹配结果
3. 记录推荐项目
4. 提供上下文查询接口
5. 持久化到文件
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional


class ConversationMemory:
    """对话记忆系统"""

    def __init__(self, max_history: int = 20):
        """
        初始化记忆系统

        Args:
            max_history: 最大保留的对话轮数
        """
        self.max_history = max_history

        # 核心数据
        self.analyzed_jobs: Dict[str, Dict[str, Any]] = {}  # {job_id: analysis_result}
        self.match_results: Dict[str, Dict[str, Any]] = {}  # {job_id: match_result}
        self.recommended_projects: Dict[str, List[Dict[str, Any]]] = {}  # {job_id: [projects]}
        self.user_preferences: Dict[str, Any] = {}  # 用户偏好
        self.conversation_history: List[Dict[str, Any]] = []  # 对话历史

        # 辅助数据
        self.last_analyzed_job_id: Optional[str] = None  # 最近分析的职位
        self.last_action: Optional[str] = None  # 最近的操作
        self.session_start_time = datetime.now()

    # ==================== 添加数据 ====================

    def add_job_analysis(self, job_id: str, job_info: Dict[str, Any], analysis: Dict[str, Any]):
        """
        记录职位分析

        Args:
            job_id: 职位ID
            job_info: 职位基本信息（title, company, city, salary）
            analysis: 分析结果
        """
        self.analyzed_jobs[job_id] = {
            "job_info": job_info,
            "analysis": analysis,
            "analyzed_at": datetime.now().isoformat()
        }
        self.last_analyzed_job_id = job_id
        self.last_action = "analyze_job"

    def add_match_result(self, job_id: str, match_result: Dict[str, Any]):
        """
        记录匹配结果

        Args:
            job_id: 职位ID
            match_result: 匹配结果
        """
        self.match_results[job_id] = {
            "result": match_result,
            "matched_at": datetime.now().isoformat()
        }
        self.last_action = "match_job"

    def add_recommended_projects(self, job_id: str, projects: List[Dict[str, Any]]):
        """
        记录推荐项目

        Args:
            job_id: 职位ID
            projects: 推荐的项目列表
        """
        if job_id not in self.recommended_projects:
            self.recommended_projects[job_id] = []

        # 添加新项目，避免重复
        existing_repos = {p.get("repo") for p in self.recommended_projects[job_id]}
        new_projects = [p for p in projects if p.get("repo") not in existing_repos]

        self.recommended_projects[job_id].extend(new_projects)
        self.last_action = "recommend_projects"

    def add_conversation_turn(self, user_input: str, agent_output: str, metadata: Optional[Dict] = None):
        """
        记录一轮对话

        Args:
            user_input: 用户输入
            agent_output: Agent 输出
            metadata: 额外的元数据
        """
        turn = {
            "user": user_input,
            "agent": agent_output,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {}
        }

        self.conversation_history.append(turn)

        # 保持窗口大小
        if len(self.conversation_history) > self.max_history:
            self.conversation_history.pop(0)

    def update_user_preference(self, key: str, value: Any):
        """
        更新用户偏好

        Args:
            key: 偏好键
            value: 偏好值
        """
        self.user_preferences[key] = value

    # ==================== 查询数据 ====================

    def get_last_analyzed_job(self) -> Optional[Dict[str, Any]]:
        """获取最近分析的职位"""
        if self.last_analyzed_job_id:
            return {
                "job_id": self.last_analyzed_job_id,
                **self.analyzed_jobs[self.last_analyzed_job_id]
            }
        return None

    def get_job_analysis(self, job_id: str) -> Optional[Dict[str, Any]]:
        """获取指定职位的分析结果"""
        return self.analyzed_jobs.get(job_id)

    def get_match_result(self, job_id: str) -> Optional[Dict[str, Any]]:
        """获取指定职位的匹配结果"""
        return self.match_results.get(job_id)

    def get_recommended_projects(self, job_id: str) -> List[Dict[str, Any]]:
        """获取指定职位的推荐项目"""
        return self.recommended_projects.get(job_id, [])

    def get_all_analyzed_jobs(self) -> List[Dict[str, Any]]:
        """获取所有已分析的职位"""
        return [
            {"job_id": job_id, **data}
            for job_id, data in self.analyzed_jobs.items()
        ]

    def has_analyzed_job(self, job_id: str) -> bool:
        """检查是否已分析过该职位"""
        return job_id in self.analyzed_jobs

    def get_conversation_history(self, last_n: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        获取对话历史

        Args:
            last_n: 获取最近 N 轮对话，None 表示全部

        Returns:
            对话历史列表
        """
        if last_n:
            return self.conversation_history[-last_n:]
        return self.conversation_history

    # ==================== 上下文摘要 ====================

    def get_context_summary(self) -> str:
        """
        获取上下文摘要（用于 Agent 的 system prompt）

        Returns:
            上下文摘要字符串
        """
        summary_parts = []

        # 会话信息
        summary_parts.append(f"会话开始时间: {self.session_start_time.strftime('%Y-%m-%d %H:%M')}")

        # 已分析的职位
        if self.analyzed_jobs:
            summary_parts.append(f"\n已分析职位数: {len(self.analyzed_jobs)}")
            for job_id, data in list(self.analyzed_jobs.items())[-3:]:  # 最近3个
                job_info = data["job_info"]
                summary_parts.append(
                    f"  - {job_id}: {job_info.get('title')} @ {job_info.get('company')}"
                )

        # 最近的操作
        if self.last_analyzed_job_id:
            summary_parts.append(f"\n最近分析的职位: {self.last_analyzed_job_id}")

        # 推荐项目统计
        total_projects = sum(len(projects) for projects in self.recommended_projects.values())
        if total_projects > 0:
            summary_parts.append(f"已推荐项目总数: {total_projects}")

        # 用户偏好
        if self.user_preferences:
            summary_parts.append(f"\n用户偏好: {self.user_preferences}")

        return "\n".join(summary_parts)

    def get_short_context(self) -> str:
        """
        获取简短上下文（用于工具调用时的上下文）

        Returns:
            简短上下文字符串
        """
        if not self.last_analyzed_job_id:
            return "无上下文"

        last_job = self.analyzed_jobs[self.last_analyzed_job_id]
        job_info = last_job["job_info"]

        context = f"当前职位: {job_info.get('title')} @ {job_info.get('company')}"

        # 添加匹配结果
        if self.last_analyzed_job_id in self.match_results:
            match = self.match_results[self.last_analyzed_job_id]["result"]
            score = match.get("score", 0)
            context += f" (匹配度: {score}分)"

        return context

    # ==================== 统计信息 ====================

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "analyzed_jobs_count": len(self.analyzed_jobs),
            "total_recommended_projects": sum(
                len(projects) for projects in self.recommended_projects.values()
            ),
            "conversation_turns": len(self.conversation_history),
            "session_duration_minutes": (
                datetime.now() - self.session_start_time
            ).total_seconds() / 60,
            "last_action": self.last_action,
        }

    # ==================== 持久化 ====================

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于序列化）"""
        return {
            "analyzed_jobs": self.analyzed_jobs,
            "match_results": self.match_results,
            "recommended_projects": self.recommended_projects,
            "user_preferences": self.user_preferences,
            "conversation_history": self.conversation_history,
            "last_analyzed_job_id": self.last_analyzed_job_id,
            "last_action": self.last_action,
            "session_start_time": self.session_start_time.isoformat(),
            "max_history": self.max_history,
        }

    def from_dict(self, data: Dict[str, Any]):
        """从字典恢复（用于反序列化）"""
        self.analyzed_jobs = data.get("analyzed_jobs", )
        self.match_results = data.get("match_results", {})
        self.recommended_projects = data.get("recommended_projects", {})
        self.user_preferences = data.get("user_preferences", {})
        self.conversation_history = data.get("conversation_history", [])
        self.last_analyzed_job_id = data.get("last_analyzed_job_id")
        self.last_action = data.get("last_action")
        self.max_history = data.get("max_history", 20)

        # 恢复时间
        session_start = data.get("session_start_time")
        if session_start:
            self.session_start_time = datetime.fromisoformat(session_start)

    def save(self, filepath: str):
        """
        保存到文件

        Args:
            filepath: 文件路径
        """
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    def load(self, filepath: str):
        """
        从文件加载

        Args:
            filepath: 文件路径
        """
        filepath = Path(filepath)
        if not filepath.exists():
            return

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.from_dict(data)

    # ==================== 清理 ====================

    def clear(self):
        """清空所有记忆"""
        self.analyzed_jobs.clear()
        self.match_results.clear()
        self.recommended_projects.clear()
        self.user_preferences.clear()
        self.conversation_history.clear()
        self.last_analyzed_job_id = None
        self.last_action = None
        self.session_start_time = datetime.now()

    def clear_old_data(self, keep_last_n: int = 5):
        """
        清理旧数据，只保留最近 N 个职位

        Args:
            keep_last_n: 保留最近 N 个职位
        """
        if len(self.analyzed_jobs) <= keep_last_n:
            return

        # 按时间排序
        sorted_jobs = sorted(
            self.analyzed_jobs.items(),
            key=lambda x: x[1]["analyzed_at"],
            reverse=True
        )

        # 保留最近的
        keep_job_ids = {job_id for job_id, _ in sorted_jobs[:keep_last_n]}

        # 删除旧的
        self.analyzed_jobs = {
            job_id: data
            for job_id, data in self.analyzed_jobs.items()
            if job_id in keep_job_ids
        }

        self.match_results = {
            job_id: data
            for job_id, data in self.match_results.items()
            if job_id in keep_job_ids
        }

        self.recommended_projects = {
            job_id: projects
            for job_id, projects in self.recommended_projects.items()
            if job_id in keep_job_ids
        }
