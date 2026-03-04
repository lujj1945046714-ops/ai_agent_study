# AI 求职助手 Agent 框架重设计

**日期：** 2026-03-04
**目标：** 参考 OpenClaw 架构，重新设计 AI 求职助手的 Agent 框架
**策略：** 全新重写，采用分层架构 + Hooks + Markdown 记忆
**开发方式：** 严格 TDD，使用 pytest

---

## 一、设计目标

### 核心目标
1. **清晰的分层架构** - 参考 OpenClaw，实现 Gateway → Runtime → Tool → Memory 四层架构
2. **可扩展性** - 支持动态工具注册、Hooks 系统、插件化扩展
3. **可测试性** - 每层独立可测试，采用 TDD 开发
4. **可维护性** - 代码结构清晰，职责分离，易于理解和修改

### 非目标
- 不实现分布式部署（当前阶段）
- 不实现多租户隔离（当前阶段）
- 不实现实时消息推送（当前阶段）

---

## 二、整体架构

### 架构图

```
┌─────────────────────────────────────────────────────┐
│  Interface Layer (接口层)                            │
│  - CLI 入口 (main.py)                               │
│  - Web UI (web_ui.py)                              │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│  Gateway Layer (网关层)                              │
│  - MessageRouter: 消息路由                          │
│  - SessionManager: 会话管理                         │
│  - HooksRegistry: 生命周期钩子                      │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│  Agent Runtime Layer (Agent 运行时层)                │
│  - ReactEngine: ReAct 推理引擎                      │
│  - ToolDispatcher: 工具调度器                       │
│  - ContextManager: 上下文管理                       │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│  Tool Layer (工具层)                                 │
│  - ToolRegistry: 工具注册表                         │
│  - BaseTool: 工具基类                               │
│  - 业务工具: search_jobs, analyze_job, etc.        │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│  Memory Layer (记忆层)                               │
│  - MarkdownMemory: Markdown 格式记忆                │
│  - SessionStore: 会话状态存储                       │
└─────────────────────────────────────────────────────┘
```

### 数据流向

```
用户输入
  → Gateway.MessageRouter (路由 + 会话恢复)
  → Gateway.HooksRegistry (触发 before_message hook)
  → AgentRuntime.ReactEngine (ReAct 推理循环)
  → AgentRuntime.ToolDispatcher (解析工具调用)
  → ToolLayer.ToolRegistry (查找工具)
  → Tool.execute() (执行工具)
  → Gateway.HooksRegistry (触发 after_tool hook)
  → Memory.SessionStore (保存状态)
  → Memory.MarkdownMemory (记录对话)
  → Gateway.HooksRegistry (触发 after_message hook)
  → Gateway.MessageRouter (返回响应)
  → 用户输出
```

---

## 三、核心组件设计

### 3.1 Gateway Layer (网关层)

#### MessageRouter (消息路由器)

**职责：**
- 接收用户消息
- 路由到对应的 Agent 实例
- 管理请求/响应生命周期

**接口：**
```python
class MessageRouter:
    def route(self, message: Message, session_id: Optional[str] = None) -> Response:
        """路由消息到 Agent"""

    def create_agent(self, session_id: str, config: AgentConfig) -> Agent:
        """创建新的 Agent 实例"""
```

#### SessionManager (会话管理器)

**职责：**
- 创建、恢复、保存会话
- 管理会话生命周期
- 会话超时清理

**接口：**
```python
class SessionManager:
    def create_session(self, user_profile: Dict) -> Session:
        """创建新会话"""

    def get_session(self, session_id: str) -> Optional[Session]:
        """获取会话"""

    def save_session(self, session: Session) -> None:
        """保存会话"""

    def restore_session(self, session_id: str) -> Session:
        """恢复会话"""

    def delete_session(self, session_id: str) -> None:
        """删除会话"""
```

#### HooksRegistry (Hooks 注册表)

**职责：**
- 注册和管理生命周期钩子
- 触发钩子函数
- 支持异步钩子

**支持的 Hooks：**
- `on_startup` - 系统启动时
- `on_shutdown` - 系统关闭时
- `before_message` - 处理消息前
- `after_message` - 处理消息后
- `before_tool` - 调用工具前
- `after_tool` - 调用工具后
- `on_error` - 发生错误时

**接口：**
```python
class HooksRegistry:
    def register(self, hook_name: str, callback: Callable) -> None:
        """注册钩子"""

    def trigger(self, hook_name: str, context: Dict) -> None:
        """触发钩子"""

    def unregister(self, hook_name: str, callback: Callable) -> None:
        """注销钩子"""
```

---

### 3.2 Agent Runtime Layer (运行时层)

#### ReactEngine (ReAct 推理引擎)

**职责：**
- 实现 Think → Act → Observe 循环
- 调用 LLM 进行推理
- 管理推理步骤和最大步数限制

**接口：**
```python
class ReactEngine:
    def __init__(self, llm_client, tool_dispatcher: ToolDispatcher, max_steps: int = 30):
        """初始化引擎"""

    def run(self, task: str, context: Context) -> str:
        """运行 ReAct 循环"""

    def _think(self, messages: List[Dict]) -> Tuple[str, List[ToolCall]]:
        """Think 阶段：LLM 推理"""

    def _act(self, tool_calls: List[ToolCall]) -> List[ToolResult]:
        """Act 阶段：执行工具"""

    def _observe(self, tool_results: List[ToolResult]) -> None:
        """Observe 阶段：观察结果"""
```

#### ToolDispatcher (工具调度器)

**职责：**
- 解析 LLM 的工具调用请求
- 分发到具体工具执行
- 处理工具执行错误

**接口：**
```python
class ToolDispatcher:
    def __init__(self, tool_registry: ToolRegistry, hooks: HooksRegistry):
        """初始化调度器"""

    def dispatch(self, tool_call: ToolCall) -> ToolResult:
        """调度工具执行"""

    def dispatch_batch(self, tool_calls: List[ToolCall]) -> List[ToolResult]:
        """批量调度工具"""
```

#### ContextManager (上下文管理器)

**职责：**
- 管理对话上下文
- 构建 system prompt
- 管理消息历史

**接口：**
```python
class ContextManager:
    def build_system_prompt(self, user_profile: Dict, memory_context: str) -> str:
        """构建系统提示词"""

    def add_message(self, role: str, content: str) -> None:
        """添加消息"""

    def get_messages(self) -> List[Dict]:
        """获取消息列表"""

    def clear(self) -> None:
        """清空上下文"""
```

---

### 3.3 Tool Layer (工具层)

#### BaseTool (工具基类)

**职责：**
- 定义工具接口契约
- 提供工具元数据（名称、描述、schema）
- 执行工具逻辑

**接口：**
```python
class BaseTool(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称"""

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述"""

    @property
    @abstractmethod
    def schema(self) -> Dict:
        """工具参数 schema (OpenAI function calling 格式)"""

    @abstractmethod
    def execute(self, **kwargs) -> Dict:
        """执行工具，返回结果"""

    def validate_params(self, params: Dict) -> bool:
        """验证参数（可选重写）"""
```

#### ToolRegistry (工具注册表)

**职责：**
- 动态注册和管理工具
- 查询工具
- 生成工具 schema 列表（供 LLM 使用）

**接口：**
```python
class ToolRegistry:
    def register(self, tool: BaseTool) -> None:
        """注册工具"""

    def unregister(self, tool_name: str) -> None:
        """注销工具"""

    def get_tool(self, tool_name: str) -> Optional[BaseTool]:
        """获取工具"""

    def list_tools(self) -> List[str]:
        """列出所有工具名称"""

    def get_schemas(self) -> List[Dict]:
        """获取所有工具的 schema（供 LLM 使用）"""
```

---

### 3.4 Memory Layer (记忆层)

#### MarkdownMemory (Markdown 记忆系统)

**职责：**
- 以 Markdown 格式存储对话历史
- 便于人类阅读和版本控制
- 支持追加写入

**存储格式：**
```markdown
# Session: {session_id}

**Started:** 2026-03-04 10:30:00
**User Profile:** AI Agent 工程师求职者

---

## Conversation History

### Turn 1 (10:30:15)
**User:** 帮我分析这个职位
**Agent:** 好的，我来分析这个职位...

### Turn 2 (10:31:20)
**User:** 匹配度如何？
**Agent:** 根据分析，匹配度为 75 分...

---

## Analyzed Jobs

### Job: job_001
- **Title:** AI Agent 工程师
- **Company:** 某科技公司
- **Match Score:** 75
- **Analyzed At:** 2026-03-04 10:31:00

---

## Recommended Projects

### For Job: job_001
1. [langchain](https://github.com/langchain-ai/langchain) - ⭐ 50000
2. [autogen](https://github.com/microsoft/autogen) - ⭐ 30000
```

**接口：**
```python
class MarkdownMemory:
    def __init__(self, memory_dir: Path):
        """初始化记忆系统"""

    def create_session_file(self, session_id: str, user_profile: Dict) -> None:
        """创建会话文件"""

    def append_conversation(self, session_id: str, user_msg: str, agent_msg: str) -> None:
        """追加对话"""

    def append_job_analysis(self, session_id: str, job_id: str, analysis: Dict) -> None:
        """追加职位分析"""

    def read_session(self, session_id: str) -> str:
        """读取会话内容"""
```

#### SessionStore (会话状态存储)

**职责：**
- 存储会话状态（JSON 格式）
- 保存工具调用历史、中间结果
- 支持会话恢复

**存储格式：**
```json
{
  "session_id": "sess_20260304_103000",
  "created_at": "2026-03-04T10:30:00",
  "updated_at": "2026-03-04T10:35:00",
  "user_profile": {...},
  "analyzed_jobs": {
    "job_001": {
      "analysis": {...},
      "match": {...},
      "repos": [...]
    }
  },
  "tool_call_history": [
    {"tool": "search_jobs", "args": {...}, "result": {...}, "timestamp": "..."}
  ],
  "context": {
    "last_analyzed_job_id": "job_001",
    "last_action": "match_job"
  }
}
```

**接口：**
```python
class SessionStore:
    def __init__(self, memory_dir: Path):
        """初始化存储"""

    def save(self, session_id: str, state: Dict) -> None:
        """保存会话状态"""

    def load(self, session_id: str) -> Optional[Dict]:
        """加载会话状态"""

    def delete(self, session_id: str) -> None:
        """删除会话"""

    def list_sessions(self) -> List[str]:
        """列出所有会话"""
```

---

## 四、目录结构

```
ai_agent_framework/
├── core/                          # 核心框架
│   ├── __init__.py
│   ├── gateway/                   # 网关层
│   │   ├── __init__.py
│   │   ├── message_router.py
│   │   ├── session_manager.py
│   │   └── hooks.py
│   ├── runtime/                   # 运行时层
│   │   ├── __init__.py
│   │   ├── react_engine.py
│   │   ├── tool_dispatcher.py
│   │   └── context.py
│   ├── tools/                     # 工具层
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── registry.py
│   └── memory/                    # 记忆层
│       ├── __init__.py
│       ├── markdown_memory.py
│       └── session_store.py
├── tools/                         # 业务工具实现
│   ├── __init__.py
│   ├── search_jobs.py
│   ├── analyze_job.py
│   ├── match_job.py
│   ├── recommend_learning.py
│   └── generate_report.py
├── tests/                         # 测试目录
│   ├── __init__.py
│   ├── conftest.py               # pytest fixtures
│   ├── core/
│   │   ├── gateway/
│   │   │   ├── test_message_router.py
│   │   │   ├── test_session_manager.py
│   │   │   └── test_hooks.py
│   │   ├── runtime/
│   │   │   ├── test_react_engine.py
│   │   │   ├── test_tool_dispatcher.py
│   │   │   └── test_context.py
│   │   ├── tools/
│   │   │   ├── test_base_tool.py
│   │   │   └── test_registry.py
│   │   └── memory/
│   │       ├── test_markdown_memory.py
│   │       └── test_session_store.py
│   ├── tools/
│   │   └── test_business_tools.py
│   └── integration/
│       └── test_end_to_end.py
├── memory/                        # 记忆存储目录
│   └── sessions/
├── main.py                        # CLI 入口
├── web_ui.py                      # Web UI
├── config.py                      # 配置
├── requirements.txt
└── pytest.ini                     # pytest 配置
```

---

## 五、TDD 开发计划

### 开发顺序（自底向上）

#### Phase 1: 工具层（1-2 天）
1. **test_base_tool.py** - 测试工具基类接口契约
   - 测试抽象方法必须实现
   - 测试 schema 格式验证
   - 测试参数验证逻辑

2. **test_registry.py** - 测试工具注册表
   - 测试注册/注销工具
   - 测试查询工具
   - 测试获取 schemas
   - 测试重复注册处理

#### Phase 2: 记忆层（1-2 天）
3. **test_markdown_memory.py** - 测试 Markdown 记忆
   - 测试创建会话文件
   - 测试追加对话
   - 测试追加职位分析
   - 测试读取会话
   - 测试 Markdown 格式正确性

4. **test_session_store.py** - 测试会话存储
   - 测试保存/加载会话
   - 测试删除会话
   - 测试列出会话
   - 测试 JSON 序列化/反序列化

#### Phase 3: 运行时层（2-3 天）
5. **test_context.py** - 测试上下文管理器
   - 测试构建 system prompt
   - 测试添加/获取消息
   - 测试清空上下文

6. **test_tool_dispatcher.py** - 测试工具调度器
   - 测试单个工具调度
   - 测试批量工具调度
   - 测试工具不存在处理
   - 测试工具执行错误处理
   - 测试 hooks 触发

7. **test_react_engine.py** - 测试 ReAct 引擎
   - 测试 Think 阶段（mock LLM）
   - 测试 Act 阶段（工具调用）
   - 测试 Observe 阶段（结果处理）
   - 测试完整循环
   - 测试最大步数限制
   - 测试无工具调用退出

#### Phase 4: 网关层（2-3 天）
8. **test_hooks.py** - 测试 Hooks 系统
   - 测试注册/注销钩子
   - 测试触发钩子
   - 测试多个钩子按顺序执行
   - 测试钩子异常处理

9. **test_session_manager.py** - 测试会话管理器
   - 测试创建会话
   - 测试获取会话
   - 测试保存会话
   - 测试恢复会话
   - 测试删除会话
   - 测试会话不存在处理

10. **test_message_router.py** - 测试消息路由器
    - 测试路由消息到 Agent
    - 测试创建 Agent 实例
    - 测试会话关联
    - 测试错误处理

#### Phase 5: 业务工具迁移（3-4 天）
11. **test_search_jobs.py** - 测试搜索职位工具
12. **test_analyze_job.py** - 测试分析职位工具
13. **test_match_job.py** - 测试匹配职位工具
14. **test_recommend_learning.py** - 测试推荐学习工具
15. **test_generate_report.py** - 测试生成报告工具

#### Phase 6: 集成测试（1-2 天）
16. **test_end_to_end.py** - 端到端测试
    - 测试完整的用户交互流程
    - 测试会话恢复
    - 测试多轮对话
    - 测试错误恢复

**总计：10-16 天**

---

## 六、关键设计决策

### 6.1 为什么选择分层架构？

**优点：**
- 职责清晰，每层只关注一个方面
- 易于测试，每层可以独立 mock
- 易于扩展，新增功能只需修改对应层
- 易于维护，降低耦合度

**权衡：**
- 增加了抽象层次，代码量增加
- 需要定义清晰的层间接口

### 6.2 为什么使用 Markdown 记忆？

**优点：**
- 人类可读，便于调试和审查
- 支持版本控制（Git）
- 无需数据库，部署简单
- 便于导出和分享

**权衡：**
- 不支持复杂查询（如全文搜索）
- 大量会话时性能可能下降
- 需要额外的 JSON 存储来保存结构化数据

**解决方案：**
- Markdown 用于人类可读的对话历史
- JSON (SessionStore) 用于结构化数据和快速查询
- 两者互补，各司其职

### 6.3 为什么采用 Hooks 系统？

**优点：**
- 支持插件化扩展（日志、监控、审计）
- 不修改核心代码即可添加功能
- 便于调试和追踪

**权衡：**
- 增加了系统复杂度
- 需要文档说明 Hooks 的使用方式

### 6.4 为什么工具层使用注册表模式？

**优点：**
- 支持动态注册工具，无需修改核心代码
- 便于测试，可以注册 mock 工具
- 支持工具热加载（未来扩展）

**权衡：**
- 需要显式注册工具，增加初始化代码

---

## 七、与现有代码的对比

### 现有架构
```
main.py → JobSearchAgent (单体类)
  ├── _dispatch() - 工具分发
  ├── _handle_*() - 工具处理
  ├── ConversationMemory - 记忆
  └── ProactiveSuggestionEngine - 建议
```

**问题：**
- 单体类过大（600+ 行）
- 职责不清晰，难以测试
- 工具硬编码，难以扩展
- 记忆系统与 Agent 耦合

### 新架构
```
Gateway → Agent Runtime → Tool Layer → Memory Layer
```

**改进：**
- 清晰的分层，每层职责单一
- 工具动态注册，易于扩展
- 记忆系统独立，支持多种存储方式
- 每层独立可测试

---

## 八、迁移策略

### 业务逻辑迁移

**现有工具 → 新工具类：**
1. `search_jobs` → `SearchJobsTool(BaseTool)`
2. `analyze_job` → `AnalyzeJobTool(BaseTool)`
3. `match_job` → `MatchJobTool(BaseTool)`
4. `recommend_learning` → `RecommendLearningTool(BaseTool)`
5. `generate_report` → `GenerateReportTool(BaseTool)`

**复用现有模块：**
- `modules/scraper.py` - 职位抓取逻辑
- `modules/analyzer.py` - JD 分析逻辑
- `modules/matcher_enhanced.py` - 匹配算法
- `modules/github_recommender.py` - GitHub 推荐逻辑

**不迁移的部分：**
- `agent/react_agent.py` - 完全重写
- `agent/conversation_memory.py` - 用新的 Memory Layer 替代
- `agent/suggestion_engine.py` - 可选迁移为 Hook

---

## 九、测试策略

### 测试覆盖率目标
- 核心框架：≥ 90%
- 业务工具：≥ 80%
- 集成测试：覆盖主要用户流程

### Mock 策略
- LLM 调用：使用 mock 返回预定义响应
- 文件 I/O：使用 pytest 的 tmp_path fixture
- 外部 API：使用 mock 或 VCR.py 录制响应

### Fixtures 设计
```python
# conftest.py
@pytest.fixture
def tool_registry():
    """提供空的工具注册表"""
    return ToolRegistry()

@pytest.fixture
def mock_llm_client():
    """提供 mock 的 LLM 客户端"""
    return Mock(spec=OpenAI)

@pytest.fixture
def temp_memory_dir(tmp_path):
    """提供临时记忆目录"""
    return tmp_path / "memory"

@pytest.fixture
def sample_user_profile():
    """提供示例用户画像"""
    return {...}
```

---

## 十、风险与缓解

### 风险 1：重写成本高
**缓解：**
- 采用 TDD，确保每个组件正确
- 复用现有业务逻辑模块
- 分阶段实施，先完成核心框架

### 风险 2：性能下降
**缓解：**
- 分层架构增加的开销很小
- 关键路径进行性能测试
- 必要时使用缓存优化

### 风险 3：学习曲线
**缓解：**
- 编写详细的文档和示例
- 代码注释清晰
- 提供迁移指南

---

## 十一、后续扩展方向

### 短期（1-3 个月）
- 完善 Hooks 系统，支持更多生命周期事件
- 添加更多业务工具（如简历优化、面试准备）
- 优化 Markdown 记忆格式，支持更丰富的展示

### 中期（3-6 个月）
- 支持多种 LLM 后端（OpenAI、Anthropic、本地模型）
- 实现工具热加载和版本管理
- 添加 Web API 接口，支持远程调用

### 长期（6-12 个月）
- 支持分布式部署
- 实现多租户隔离
- 添加实时消息推送（WebSocket）
- 支持多模态输入（图片、PDF）

---

## 十二、总结

本设计方案参考 OpenClaw 的分层架构理念，重新设计了 AI 求职助手的 Agent 框架。核心改进包括：

1. **清晰的分层架构** - Gateway → Runtime → Tool → Memory
2. **可扩展的工具系统** - 动态注册、热加载
3. **灵活的 Hooks 机制** - 支持插件化扩展
4. **人类友好的记忆系统** - Markdown + JSON
5. **严格的 TDD 开发** - 确保代码质量

通过这次重构，项目将具备更好的可维护性、可扩展性和可测试性，为后续功能迭代打下坚实基础。

