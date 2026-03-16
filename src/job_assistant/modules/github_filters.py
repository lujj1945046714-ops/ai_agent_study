"""
GitHub 项目多维度过滤器

功能：
1. 按编程语言过滤
2. 按许可证过滤
3. 按活跃度过滤
4. 按主题标签过滤
5. 按仓库大小过滤
6. 按 star 数范围过滤
"""

from datetime import datetime, timedelta
from typing import Dict, List


class GitHubFilter:
    """GitHub 项目多维度过滤器"""

    @staticmethod
    def by_language(repos: List[Dict], languages: List[str]) -> List[Dict]:
        """
        按编程语言过滤

        参数：
        - repos: 项目列表
        - languages: 语言列表（如 ["Python", "TypeScript"]）

        返回：
        - 过滤后的项目列表
        """
        if not languages:
            return repos

        # 标准化语言名称（不区分大小写）
        languages_lower = [lang.lower() for lang in languages]

        return [
            repo for repo in repos
            if repo.get("language", "").lower() in languages_lower
        ]

    @staticmethod
    def by_license(repos: List[Dict], licenses: List[str]) -> List[Dict]:
        """
        按许可证过滤

        参数：
        - repos: 项目列表
        - licenses: 许可证列表（如 ["MIT", "Apache-2.0"]）

        返回：
        - 过滤后的项目列表
        """
        if not licenses:
            return repos

        # 标准化许可证名称（不区分大小写）
        licenses_lower = [lic.lower() for lic in licenses]

        filtered = []
        for repo in repos:
            license_info = repo.get("license")
            if license_info:
                # license 可能是字典 {"key": "mit", "name": "MIT License"}
                if isinstance(license_info, dict):
                    license_key = license_info.get("key", "").lower()
                else:
                    license_key = str(license_info).lower()

                if license_key in licenses_lower:
                    filtered.append(repo)

        return filtered

    @staticmethod
    def by_activity(repos: List[Dict], days: int) -> List[Dict]:
        """
        按活跃度过滤（最近 N 天有更新）

        参数：
        - repos: 项目列表
        - days: 天数（如 180 表示最近 180 天活跃）

        返回：
        - 过滤后的项目列表
        """
        if days <= 0:
            return repos

        cutoff = datetime.now() - timedelta(days=days)

        filtered = []
        for repo in repos:
            updated_at = repo.get("updated_at")
            if not updated_at:
                continue

            try:
                # 解析 ISO 8601 格式（GitHub API 返回格式）
                # 例如：2024-03-15T10:30:00Z
                if isinstance(updated_at, str):
                    # 移除时区信息（Z 或 +00:00）
                    updated_at = updated_at.replace("Z", "").split("+")[0].split(".")[0]
                    updated_date = datetime.fromisoformat(updated_at)
                else:
                    updated_date = updated_at

                if updated_date > cutoff:
                    filtered.append(repo)
            except (ValueError, AttributeError):
                # 日期解析失败，跳过该项目
                continue

        return filtered

    @staticmethod
    def by_topics(repos: List[Dict], topics: List[str], match_all: bool = False) -> List[Dict]:
        """
        按主题标签过滤

        参数：
        - repos: 项目列表
        - topics: 主题列表（如 ["llm", "agent", "rag"]）
        - match_all: 是否匹配所有主题（True=AND, False=OR）

        返回：
        - 过滤后的项目列表
        """
        if not topics:
            return repos

        # 标准化主题名称（不区分大小写）
        topics_lower = set(topic.lower() for topic in topics)

        filtered = []
        for repo in repos:
            repo_topics = repo.get("topics", [])
            if not repo_topics:
                continue

            # 标准化仓库主题
            repo_topics_lower = set(topic.lower() for topic in repo_topics)

            if match_all:
                # 匹配所有主题（AND）
                if topics_lower.issubset(repo_topics_lower):
                    filtered.append(repo)
            else:
                # 匹配任一主题（OR）
                if topics_lower.intersection(repo_topics_lower):
                    filtered.append(repo)

        return filtered

    @staticmethod
    def by_size(repos: List[Dict], min_kb: int = 0, max_kb: int = None) -> List[Dict]:
        """
        按仓库大小过滤（单位：KB）

        参数：
        - repos: 项目列表
        - min_kb: 最小大小（KB）
        - max_kb: 最大大小（KB），None 表示不限

        返回：
        - 过滤后的项目列表
        """
        filtered = []
        for repo in repos:
            size = repo.get("size", 0)  # GitHub API 返回的 size 单位是 KB

            if size < min_kb:
                continue

            if max_kb is not None and size > max_kb:
                continue

            filtered.append(repo)

        return filtered

    @staticmethod
    def by_stars_range(repos: List[Dict], min_stars: int = 0, max_stars: int = None) -> List[Dict]:
        """
        按 star 数范围过滤

        参数：
        - repos: 项目列表
        - min_stars: 最小 star 数
        - max_stars: 最大 star 数，None 表示不限

        返回：
        - 过滤后的项目列表
        """
        filtered = []
        for repo in repos:
            stars = repo.get("stargazers_count", 0)

            # 兼容字符串格式
            if isinstance(stars, str):
                try:
                    stars = int(stars)
                except ValueError:
                    stars = 0

            if stars < min_stars:
                continue

            if max_stars is not None and stars > max_stars:
                continue

            filtered.append(repo)

        return filtered

    @classmethod
    def apply_filters(
        cls,
        repos: List[Dict],
        languages: List[str] = None,
        licenses: List[str] = None,
        topics: List[str] = None,
        topics_match_all: bool = False,
        activity_days: int = None,
        min_size_kb: int = 0,
        max_size_kb: int = None,
        min_stars: int = 0,
        max_stars: int = None,
    ) -> List[Dict]:
        """
        应用多个过滤器（链式调用）

        参数：
        - repos: 项目列表
        - languages: 语言列表
        - licenses: 许可证列表
        - topics: 主题列表
        - topics_match_all: 是否匹配所有主题
        - activity_days: 活跃度（天数）
        - min_size_kb: 最小大小（KB）
        - max_size_kb: 最大大小（KB）
        - min_stars: 最小 star 数
        - max_stars: 最大 star 数

        返回：
        - 过滤后的项目列表
        """
        result = repos

        if languages:
            result = cls.by_language(result, languages)

        if licenses:
            result = cls.by_license(result, licenses)

        if topics:
            result = cls.by_topics(result, topics, match_all=topics_match_all)

        if activity_days:
            result = cls.by_activity(result, activity_days)

        if min_size_kb > 0 or max_size_kb is not None:
            result = cls.by_size(result, min_kb=min_size_kb, max_kb=max_size_kb)

        if min_stars > 0 or max_stars is not None:
            result = cls.by_stars_range(result, min_stars=min_stars, max_stars=max_stars)

        return result


def build_github_query(
    base_query: str,
    languages: List[str] = None,
    licenses: List[str] = None,
    min_stars: int = None,
    max_stars: int = None,
) -> str:
    """
    构建 GitHub 搜索查询（下推过滤条件）

    参数：
    - base_query: 基础查询字符串
    - languages: 语言列表
    - licenses: 许可证列表
    - min_stars: 最小 star 数
    - max_stars: 最大 star 数

    返回：
    - 完整的 GitHub 搜索查询字符串
    """
    query_parts = [base_query]

    # 下推语言过滤
    if languages:
        lang_query = " OR ".join(f"language:{lang}" for lang in languages)
        query_parts.append(f"({lang_query})")

    # 下推许可证过滤
    if licenses:
        license_query = " OR ".join(f"license:{lic}" for lic in licenses)
        query_parts.append(f"({license_query})")

    # 下推 star 数范围
    if min_stars is not None and max_stars is not None:
        query_parts.append(f"stars:{min_stars}..{max_stars}")
    elif min_stars is not None:
        query_parts.append(f"stars:>={min_stars}")
    elif max_stars is not None:
        query_parts.append(f"stars:<={max_stars}")

    return " ".join(query_parts)
