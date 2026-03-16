# Phase 0: Codex 架构审计结果

**审计时间：** 2026-03-16
**模型：** gpt-5.3-codex (xhigh reasoning)
**审计范围：** GitHub 搜索模块深度优化（6 个 Phase）

---

## 审计摘要

Codex 对架构蓝图进行了深度审计，识别出 **22 个关键风险点**，其中：
- **高严重程度：** 11 个（需立即修复）
- **中严重程度：** 11 个（需纳入实施计划）

**核心发现：**
1. **现有代码存在 3 个高优先级 Bug**（参数传递失效、签名不匹配），必须先修复才能开始新功能开发
2. **向量搜索并发安全问题**（索引损坏风险）需要双缓冲机制
3. **RRF 融合算法需要加权平衡**，避免偏向候选多的通道
4. **过滤器需要下推到 GitHub API**，避免召回截断
5. **向后兼容性**必须通过追加可选参数保证

---

## 高严重程度问题（必须修复）

### 1. 现有 Bug 修复（阻塞新功能开发）

#### 1.1 `min_stars` 参数未生效
**组件：** `github_recommender.py / smart_recommend_projects`
**问题：** API 层传入的 `min_stars` 参数被函数内部固定值（500/100）覆盖，导致用户设置失效
**影响：** RRF 融合和过滤结果失真
**缓解措施：**
```python
# 修改 smart_recommend_projects() 签名
def smart_recommend_projects(
    skill_gaps: List[str],
    profile: Optional[Dict] = None,
    analysis: Optional[Dict] = None,
    top_n: int = 5,
    min_stars: int = 1000,  # 新增：显式参数
    user_choice: Optional[str] = None,
    # ...
):
    # 透传到 _search_github()
    candidates = _search_github(query, min_stars=min_stars)
```

#### 1.2 `use_profile` 参数未传递
**组件：** `webapp/app.py → webapp/service.py`
**问题：** 前端"根据简历推荐"开关（`use_profile`）未传入 service 层，功能失效
**影响：** 用户无法使用个性化推荐
**缓解措施：**
```python
# webapp/app.py
result = service.search_github_projects(
    user_query=payload.user_query,
    min_stars=payload.min_stars,
    top_n=payload.top_n,
    use_profile=payload.use_profile,  # 补传
    # ...
)
```

#### 1.3 Agent Tool 签名不匹配
**组件：** `agent/tools.py / SearchGitHubTool.execute`
**问题：** 仍按旧签名传 `job` 参数调用 `smart_recommend_projects`，存在运行时崩溃风险
**影响：** Agent 调用 GitHub 搜索时报错
**缓解措施：**
```python
# agent/tools.py
result = smart_recommend_projects(
    skill_gaps=[user_query],  # 对齐新签名
    profile=state.profile if state.profile else None,
    analysis=,
    top_n=top_n,
    min_stars=min_stars,
    user_choice=user_choice
)
```

---

### 2. Phase 1: 向量搜索风险

#### 2.1 FAISS 索引并发安全
**组件：** `vector_search.py / FAISS 索引管理`
**问题：** 增量写入与在线查询并发时无读写隔离，索引文件可能损坏或读到半写状态
**影响：** 索引损坏导致搜索失败，需要重建索引
**缓解措施：**
```python
class VectorSearchEngine:
    def _atomic_save_index(self, index, metadata):
        """原子替换索引文件"""
        temp_index = self.index_path.with_suffix(".tmp")
        temp_meta = self.metadata_path.with_suffix(".tmp")

        # 1. 写入临时文件
        faiss.write_index(index, str(temp_index))
        with open(temp_meta, "w") as f:
            json.dump(metadata, f)

        # 2. 校验完整性
        faiss.read_index(str(temp_index))  # 验证可读

        # 3. 原子替换（Windows 需要先删除）
        if self.index_path.exists():
            self.index_path.unlink()
        temp_index.rename(self.index_path)

        if self.metadata_path.exists():
            self.metadata_path.unlink()
        temp_meta.rename(self.metadata_path)
```

#### 2.2 索引去重与增长控制
**组件：** `vector_search.py / 索引增长策略`
**问题：** "每次搜索后增量向量化"若无去重机制会导致重复向量、索引膨胀、召回劣化
**影响：** 索引大小失控，检索性能下降
**缓解措施：**
```python
class VectorSearchEngine:
    def __init__(self):
        self.repo_id_to_vector_id = {}  # repo_name -> vector_id 映射
        self.metadata = []  # 项目元数据

    def add_repos(self, repos: List[Dict]):
        """增量添加项目（去重）"""
        new_repos = []
        for repo in repos:
            repo_id = repo["full_name"]
            if repo_id not in self.repo_id_to_vector_id:
                new_repos.append(repo)

        if not new_repos:
            return

        # 向量化新项目
        embeddings = self._embed_repos(new_repos)

        # 更新索引
        start_id = len(self.metadata)
        for i, repo in enumerate(new_repos):
            self.repo_id_to_vector_id[repo["full_name"]] = start_id + i
            self.metadata.append(repo)

        self.index.add(embeddings)
        self._atomic_save_index(self.index, {
            "repo_id_to_vector_id": self.repo_id_to_vector_id,
            "metadata": self.metadata
        })
```

#### 2.3 依赖管理与降级
**组件：** `pyproject.toml / 依赖策略`
**问题：** 当前缺少 `faiss-cpu` 依赖与平台约束，部署环境易出现安装失败
**影响：** 用户无法安装或运行向量搜索功能
**缓解措施：**
```toml
[project.optional-dependencies]
semantic = [
  "sentence-transformers>=2.0.0",
  "faiss-cpu>=1.7.0; platform_system != 'Windows' or python_version >= '3.10'",
]
```

```python
# vector_search.py
try:
    import faiss
    from sentence_transformers import SentenceTransformer
    VECTOR_SEARCH_AVAILABLE = True
except ImportError:
    VECTOR_SEARCH_AVAILABLE = False
    logger.warning("向量搜索不可用，将仅使用关键词搜索")

class VectorSearchEngine:
    def __init__(self):
        if not VECTOR_SEARCH_AVAILABLE:
            raise RuntimeError("向量搜索依赖未安装，请运行: pip install -e .[semantic]")
```

#### 2.4 RRF 融合算法加权
**组件：** `github_recommender.py / RRF 融合层`
**问题：** 关键词池与语义池候选数量不对齐时，未加权 RRF 会偏向候选多的一侧
**影响：** 融合结果偏向某一通道，失去混合搜索优势
**缓解措施：**
```python
def _rrf_merge(keyword_results: List[Dict], semantic_results: List[Dict],
               k: int = 60, w_keyword: float = 0.5, w_semantic: float = 0.5):
    """加权 RRF 融合"""
    scores = {}

    # 关键词通道
    for rank, repo in enumerate(keyword_results[:20]):  # 固定窗口
        repo_id = repo["full_name"]
        scores[repo_id] = scores.get(repo_id, 0) + w_keyword / (k + rank + 1)

    # 语义通道
    for rank, repo in enumerate(semantic_results[:20]):  # 固定窗口
        repo_id = repo["full_name"]
        scores[repo_id] = scores.get(repo_id, 0) + w_semantic / (k + rank + 1)

    # 按融合分数排序
    merged = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return merged
```

---

### 3. Phase 2: 多维度过滤风险

#### 3.1 过滤器下推到 GitHub API
**组件：** `github_filters.py / 多维过滤`
**问题：** 若过滤全在本地后置执行，会受 GitHub API 结果截断影响，召回与精度都下降
**影响：** 用户设置的过滤条件无法生效（如只返回 Python 项目，但 API 只返回了 30 个结果）
**缓解措施：**
```python
def _build_github_query(user_query: str, filters: Dict) -> str:
    """构建 GitHub 搜索查询（下推过滤条件）"""
    query_parts = [user_query]

    # 下推语言过滤
    if filters.get("languages"):
        lang_query = " OR ".join(f"language:{lang}" for lang in filters["languages"])
        query_parts.append(f"({lang_query})")

    # 下推许可证过滤
    if filters.get("licenses"):
        license_query = " OR ".join(f"license:{lic}" for lic in filters["licenses"])
        query_parts.append(f"({license_query})")

    # 下推 star 数范围
    if filters.get("min_stars"):
        query_parts.append(f"stars:>={filters['min_stars']}")
    if filters.get("max_stars"):
        query_parts.append(f"stars:<={filters['max_stars']}")

    return " ".join(query_parts)
```

#### 3.2 用户反馈表设计
**组件：** `user_github_feedback 表设计`
**问题：** 仅有行为明细无约束与索引会导致写入重复、查询慢、统计不稳定
**影响：** 反馈数据无法有效利用
**缓解措施：**
```sql
CREATE TABLE user_github_feedback (
    feedback_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    repo_name TEXT NOT NULL,
    search_id TEXT,
    action TEXT NOT NULL CHECK(action IN ('click', 'star', 'dismiss', 'report')),
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    UNIQUE(user_id, repo_name, action, search_id)  -- 去重
);

CREATE INDEX idx_feedback_user_time ON user_github_feedback(user_id, created_at DESC);
CREATE INDEX idx_feedback_user_repo ON user_github_feedback(user_id, repo_name);
CREATE INDEX idx_feedback_search ON user_github_feedback(search_id);
```

---

### 4. 跨组件风险

#### 4.1 统一错误处理
**组件：** `跨组件错误处理（FAISS/GitHub API/LLM）`
**问题：** 当前多数异常被泛化为"失败或降级"，难以定位与恢复
**影响：** 用户看到模糊错误信息，无法自助解决
**缓解措施：**
```python
class SearchError(Exception):
    """搜索错误基类"""
    def __init__(self, code: str, message: str, details: Dict = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)

class GitHubRateLimitError(SearchError):
    """GitHub API 限流"""
    def __init__(self, reset_at: int):
        super().__init__(
            code="GITHUB_RATE_LIMIT",
            message=f"GitHub API 限流，请在 {reset_at} 后重试",
            details={"reset_at": reset_at}
        )

class VectorIndexCorruptError(SearchError):
    """向量索引损坏"""
    def __init__(self):
        super().__init__(
            code="VECTOR_INDEX_CORRUPT",
            message="向量索引损坏，正在重建...",
            details={}
        )
```

#### 4.2 向后兼容性保证
**组件：** `smart_recommend_projects 向后兼容`
**问题：** Phase 1~3 新参数（如 `use_vector_search`/`diversity_mode`）若直接改签名或返回结构，易再次触发调用方断裂
**影响：** 现有调用者（Agent、Web UI、测试）全部失效
**缓解措施：**
```python
def smart_recommend_projects(
    skill_gaps: List[str],
    profile: Optional[Dict] = None,
    analysis: Optional[Dict] = None,
    top_n: int = 5,
    min_stars: int = 1000,
    user_choice: Optional[str] = None,
    # Phase 1: 向量搜索（可选，默认关闭）
    use_vector_search: bool = False,
    # Phase 3: 多样性排序（可选，默认关闭）
    diversity_mode: str = "none",  # "none" / "mmr" / "category"
    # 其他现有参数...
) -> Dict:
    """
    返回结构（固定 schema）：
    {
        "status": "success" | "partial" | "failed",
        "repos": [...],
        "retry_context": {...},
        "fusion_meta": {...},  # 新增：融合元数据（可选）
        # 其他现有字段...
    }
    """
```

---

## 中严重程度问题（纳入实施计划）

### 5. Phase 1: 向量搜索优化

#### 5.1 检索性能优化
**组件：** `vector_search.py / 检索性能`
**问题：** 若默认使用 Flat 索引，数据量上升后查询延迟线性增长
**缓解措施：** 中大规模改用 IVF/HNSW（含训练与参数调优），并记录 P50/P95 延迟

#### 5.2 RRF 容错
**组件：** `github_recommender.py / RRF 容错`
**问题：** 任一通道超时/空结果时缺少明确降级策略，排序稳定性差
**缓解措施：** 定义 fail-open 规则（单通道直出）和超时预算，返回 `fusion_meta` 供调试

---

### 6. Phase 2: 多维度过滤优化

#### 6.1 链式过滤性能
**组件：** `github_filters.py / 链式实现`
**问题：** 多过滤器逐步复制列表会放大 CPU/内存开销
**缓解措施：** 改为谓词合并后单次遍历，或惰性迭代管线

---

### 7. Phase 3: 多样性排序优化

#### 7.1 MMR 接入点
**组件：** `diversity_ranker.py / MMR 接入点`
**问题：** 若在 LLM 重排后直接做 MMR，但缺少可比较的数值相关性分数，会破坏主相关性
**缓解措施：** 保留基础相关性分数（关键词/语义/LLM）并仅在候选窗口内重排

#### 7.2 λ 参数调优
**组件：** `diversity_ranker.py / λ 参数`
**问题：** 默认 λ 未定义会导致"过度多样化"或"同质化"
**缓解措施：** 默认 λ 建议 0.6~0.7，按 `top_n` 与查询类型动态调节，并做 A/B 评估

---

### 8. Phase 4: 多轮对话优化

#### 8.1 摘要触发策略
**组件：** `conversation_memory.py / summarize_history`
**问题：** 若每轮都做摘要会显著增加 LLM 成本，且可能丢失硬约束信息
**缓解措施：** 按 token/轮次阈值触发摘要，保留结构化"不可丢字段"（目标岗位、硬技能、排除条件）

#### 8.2 意图识别优化
**组件：** `conversation_memory.py / extract_user_intent`
**问题：** 纯 LLM 意图识别成本高且抖动大
**缓解措施：** 先规则分类（搜索/细化/反馈/切换），低置信度再调用 LLM

---

### 9. Phase 5: 实时数据源优化

#### 9.1 Trending 抓取策略
**组件：** `trending_scraper.py / 抓取策略`
**问题：** 实时请求路径抓取 Trending 易触发反爬/页面结构变更导致失败
**缓解措施：** 改为后台定时抓取+1小时缓存+stale-while-revalidate，失败时回退上次缓存

#### 9.2 Trending 融合权重
**组件：** `trending 融合权重`
**问题：** Trending 加权若无上限会压过个性化相关性
**缓解措施：** 设置最大加分上限与时间衰减，仅对基础相关性达标候选生效

---

### 10. Phase 6: 用户反馈优化

#### 10.1 反馈驱动优化策略
**组件：** `反馈驱动优化策略`
**问题：** 直接在线调权容易形成反馈回路（越推越窄）
**缓解措施：** 使用有界更新（学习率/上下限）、最小样本阈值与周期性离线重估

---

## 实施建议

### 阶段 0：修复现有 Bug（阻塞）
**优先级：** 🔴 最高
**预计工作量：** 1-2 天
**任务：**
1. 修复 `min_stars` 参数传递
2. 修复 `use_profile` 参数传递
3. 修复 Agent Tool 签名不匹配
4. 补充回归测试

### 阶段 1：Phase 1 核心功能（高优先级）
**优先级：** 🔴 高
**预计工作量：** 3-5 天
**任务：**
1. 实现 `VectorSearchEngine`（含并发安全）
2. 实现 RRF 融合算法（加权版本）
3. 集成到 `smart_recommend_projects`
4. 添加依赖管理与降级逻辑
5. 补充单元测试与集成测试

### 阶段 2：Phase 2 核心功能（高优先级）
**优先级：** 🔴 高
**预计工作量：** 2-3 天
**任务：**
1. 实现 `GitHubFilter`（含下推逻辑）
2. 修改 API Payload 和前端 UI
3. 补充端到端测试

### 阶段 3：Phase 3-6 优化功能（中优先级）
**优先级：** 🟡 中
**预计工作量：** 5-7 天
**任务：**
1. 实现多样性排序
2. 增强对话记忆
3. 集成 Trending 数据源
4. 实现用户反馈循环

---

## 总结

Codex 审计揭示了架构蓝图中的关键风险，特别是：
1. **现有代码质量问题**必须先修复
2. **并发安全**是向量搜索的核心挑战
3. **向后兼容性**必须通过严格的接口设计保证
4. **过滤器下推**是提升召回率的关键

建议按照"修复 Bug → Phase 1 → Phase 2 → Phase 3-6"的顺序实施，确保每个阶段都有完整的测试覆盖。
