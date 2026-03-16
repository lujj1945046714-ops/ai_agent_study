# GitHub 搜索功能错误修复

## 问题描述
用户在使用 GitHub 搜索功能时遇到错误：
```
TypeError: smart_recommend_projects() got an unexpected keyword argument 'job'
```

## 根本原因
在 `service.py` 的 `search_github_projects()` 方法中，调用 `smart_recommend_projects()` 时使用了错误的参数。

**错误的调用：**
```python
result = smart_recommend_projects(
    profile=profile,
    job=temp_job,  # ❌ 错误：函数不接受 'job' 参数
    top_n=top_n,
    min_stars=min_stars,
    user_choice=user_choice
)
```

**正确的函数签名：**
```python
def smart_recommend_projects(
    skill_gaps: List[str],  # ✅ 第一个参数是 skill_gaps
    profile: Dict = None,
    analysis: Dict = None,
    top_n: int = 3,
    user_choice: str = None,
    retry_context: Dict = None,
    audit_top_repo: bool = False,
    audit_expected_capabilities: List[str] | None = None,
    audit_allow_light_run: bool = True,
    audit_keep_workspace: bool = False,
) -> Dict:
```

## 解决方案

修改 `src/job_assistant/webapp/service.py` 中的调用：

```python
def search_github_projects(
    self,
    user_id: int,
    *,
    user_query: str,
    min_stars: int = 1000,
    top_n: int = 5,
    include_audit: bool = False,
    include_similar: bool = True,
    user_choice: str | None = None,
    retry_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """执行 GitHub 项目搜索"""
    profile = self.get_profile(user_id) or {}

    # ✅ 从用户查询中提取技能关键词作为 skill_gaps
    skill_gaps = [user_query]

    # ✅ 使用正确的参数调用
    result = smart_recommend_projects(
        skill_gaps=skill_gaps,
        profile=profile,
        analysis={},
        top_n=top_n,
        user_choice=user_choice,
        retry_context=retry_context,
        audit_top_repo=include_audit,
        audit_expected_capabilities=[],
        audit_allow_light_run=True,
        audit_keep_workspace=False,
    )

    # 保存搜索记录
    search_record = self.store.save_github_search(
        user_id,
        user_query=user_query,
        min_stars=min_stars,
        top_n=top_n,
        include_audit=include_audit,
        include_similar=include_similar,
        status=result.get("status", "success"),
        repos=result.get("repos", []),
        replan_options=result.get("replan_options", []),
        retry_context=result.get("retry_context", {}),
    )

    return search_record
```

## 修改内容

1. **移除错误的参数**：删除了 `job` 和 `min_stars` 参数
2. **添加正确的参数**：
   - `skill_gaps=[user_query]` - 使用用户查询作为技能缺口
   - `analysis={}` - 提供空的分析字典
   - `retry_context` - 支持重规划
   - `audit_top_repo` - 支持自动审计
   - 其他审计相关参数

## 测试步骤

1. 重启服务器（已完成）
2. 访问 http://localhost:7860
3. 登录账号
4. 点击 "🐙 项目搜索"
5. 输入搜索需求，例如："我想学习 AI Agent 开发"
6. 点击"搜索项目"
7. 应该能正常返回结果（不再显示错误）

## 状态

- ✅ 代码已修复
- ✅ 服务器已重启
- ✅ Git 提交已完成
- ⏳ 等待用户测试验证

## Git 提交

```
commit 4c8a51d
fix: 修复 GitHub 搜索 API 参数错误

- 修正 smart_recommend_projects() 调用参数
- 第一个参数应为 skill_gaps 而不是 job
- 使用用户查询作为 skill_gaps
```

## 注意事项

⚠️ **需要配置 LLM API**

GitHub 搜索功能依赖 LLM API 来：
1. 理解用户需求
2. 生成搜索关键词
3. 分析和排序项目

如果未配置 LLM API，搜索可能会：
- 返回本地预设目录
- 或显示 LLM 配置错误

**配置方法：**
在项目根目录创建 `.env` 文件：
```env
DEEPSEEK_API_KEY=your_api_key_here
# 或其他 LLM 配置
```

---

**修复完成时间：** 2026-03-16
**修复人员：** Claude Opus 4.6
