# 🤖 AI 求职助手 (AI Job Search Agent)

> 基于 ReAct + Multi-Agent 架构的智能求职分析系统
> 输入你的技能画像，自动分析 JD、计算匹配分、推荐学习路径，生成完整求职报告

---

## 📌 项目简介

这是一个端到端的 AI 求职助手，核心能力：

- **JD 解析**：调用 DeepSeek LLM 提取职位必备技能、技术栈、岗位级别，API 失败时自动降级到启发式规则解析
- **技能匹配**：基于语义相似度（SentenceTransformer）+ 同义词归一化，计算用户与职位的 0-100 匹配分
- **学习推荐**：根据技能缺口推荐 GitHub 开源项目，调用 GitHub API（含 24h 本地缓存）
- **报告生成**：输出结构化 Markdown 求职分析报告，包含 Top 职位排名、技能缺口、改进建议
- **记忆系统**：JSON 持久化历史搜索记录，Agent 模式下自动注入上下文

支持三种执行模式，复杂度递增：

| 模式 | 命令 | 特点 |
|------|------|------|
| 线性 Pipeline | `python main.py` | 固定顺序，适合快速跑通 |
| ReAct Agent | `python main.py --agent` | LLM 自主决策工具调用顺序，可动态跳过低分职位 |
| Multi-Agent | `python main.py --multi-agent` | LangGraph Hub-and-Spoke，4 个专职 Agent 协作 |

---

## 🛠 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.10+ |
| LLM | DeepSeek-V3（兼容 OpenAI SDK 格式） |
| Agent 框架 | LangGraph（Multi-Agent）、自实现 ReAct 循环 |
| 语义匹配 | SentenceTransformer `all-MiniLM-L6-v2` |
| 数据持久化 | SQLite（职位数据）、JSON（记忆系统） |
| 外部 API | GitHub REST API（开源项目推荐） |
| 其他 | python-dotenv、openai SDK、pydantic |

---

## ✨ 核心亮点

### 1. 三种执行模式，架构递进

```
Pipeline:   fetch → analyze → match → recommend → report（顺序固定）

ReAct:      LLM 自主决定：
              search_jobs → analyze_job → match_job → recommend_learning → generate_report
              （可动态跳过匹配分 < 25 的职位）

Multi-Agent: Orchestrator 调度 4 个专职 Agent：
              Search → Analysis → Learning → Report
              每个 Agent 执行完回到 Orchestrator，由 Orchestrator 决定下一步
```

### 2. LangGraph Hub-and-Spoke 调度

Orchestrator 通过检查共享 State 字段是否为空来决定调度哪个 Agent，无需 LLM 参与路由：

```python
if not state.get("raw_jobs"):              → 派 SearchAgent
elif not state.get("analyzed_jobs"):       → 派 AnalysisAgent
elif not state.get("learning_resources"):  → 派 LearningAgent
elif not state.get("report_path"):         → 派 ReportAgent
else:                                      → END
```

### 3. 加权技能匹配公式

```python
score = required_match * (0.7 + stack_match * 0.2 + bonus_match * 0.1) * 100
```

必备技能作为乘法门槛：`required_match = 0` 时总分直接为 0，无法被其他项救回。

### 4. LLM 解析三级容错

```
正常调用 DeepSeek API
  → 网络超时：最多重试 3 次，间隔 1 秒
  → JSON 解析失败：重试 1 次
  → 仍失败：降级到启发式规则解析（关键词匹配 + 正则）
  → API Key 无效：立即抛出，不重试
```

### 5. ReAct Agent 流式输出 + 工具分发

Agent 使用 OpenAI streaming API，实时打印 LLM 思考过程；工具调用结果追加到 messages，形成完整的 Think → Act → Observe 循环。

---

## 📁 项目结构

```
02_项目开发/
├── main.py                    # 入口，三种模式统一调度
├── config.py                  # API Key、路径、参数配置
├── database.py                # SQLite 数据持久化
├── memory.py                  # JSON 记忆系统
├── report_generator.py        # Markdown 报告生成
├── user_profile.json          # 用户技能画像（需自行填写）
├── .env                       # 环境变量（不提交 Git）
│
├── modules/
│   ├── scraper.py             # 职位获取（Mock 数据 / 手动输入）
│   ├── analyzer.py            # JD 解析（LLM + 启发式降级）
│   ├── matcher.py             # 技能匹配评分
│   ├── github_recommender.py  # GitHub 项目推荐
│   └── suggestion.py          # 改进建议生成
│
├── agent/
│   ├── tools.py               # 工具 Schema + 实现函数
│   ├── react_agent.py         # ReAct 循环实现
│   └── multi_agent/
│       ├── state.py           # 共享状态定义
│       ├── graph.py           # LangGraph 图构建
│       ├── orchestrator.py    # 调度中心
│       ├── search_agent.py    # 搜索 Agent
│       ├── analysis_agent.py  # 分析 Agent
│       ├── learning_agent.py  # 学习推荐 Agent
│       └── report_agent.py    # 报告生成 Agent
│
├── data/
│   └── jobs.db                # SQLite 数据库（自动创建）
└── output/
    └── report_*.md            # 生成的分析报告
```

---

## 🚀 本地运行

### 1. 克隆项目 & 安装依赖

```bash
git clone <your-repo-url>
cd 02_项目开发

pip install openai langgraph sentence-transformers python-dotenv pydantic requests
```

> 如果不需要语义匹配（只用关键词匹配），可以跳过 `sentence-transformers`，系统会自动降级。

### 2. 配置环境变量

在项目根目录创建 `.env` 文件：

```env
# 必填：DeepSeek API Key（https://platform.deepseek.com）
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx

# 可选：GitHub Token，不填则只用本地项目目录
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxx
```

### 3. 填写用户画像

编辑 `user_profile.json`，填入你的真实技能：

```json
{
  "skills": {
    "programming": ["Python"],
    "llm": ["LLM API调用", "Prompt Engineering", "RAG项目深度分析"],
    "tools": ["Git", "Docker"]
  },
  "experience_level": "应届生",
  "target_roles": ["AI Agent工程师", "LLM应用开发"],
  "preferences": {
    "cities": ["上海", "北京", "深圳"],
    "salary_min_k": 15,
    "salary_max_k": 35
  }
}
```

### 4. 运行

**模式一：线性 Pipeline（使用内置 Mock 数据）**
```bash
python main.py
```

**模式二：手动输入真实 JD**
```bash
python main.py --boss
# 终端会提示你逐个输入职位名、公司、薪资、JD 文本
# 输入 --- 结束 JD 文本，输入 n 结束添加
```

**模式三：ReAct Agent**
```bash
python main.py --agent
```

**模式四：Multi-Agent（LangGraph）**
```bash
python main.py --multi-agent
```

### 5. 查看报告

所有报告生成在 `output/` 目录：

```
output/
├── report_20260225_164424.md        # Pipeline 模式
├── report_agent_20260225_155201.md  # ReAct Agent 模式
└── report_multi_agent_xxx.md        # Multi-Agent 模式
```

---

## ⚙️ 参数配置

在 `config.py` 中可调整：

```python
MAX_FETCH_JOBS = 30      # 最多获取职位数
MAX_COARSE_FILTER = 20   # 粗筛保留数
MAX_DEEP_ANALYSIS = 5    # 深度分析数（影响 API 调用次数）
GITHUB_TOP_N = 3         # 推荐 GitHub 项目数
```

---

## 📊 输出示例

```markdown
### 1. 初级 AI 工程师（Agent方向） | 起跑线科技 | 上海 | 15-22k

- 匹配分：60
- 必备技能：Agent / Python / Prompt Engineering
- 技能缺口：Agent / Git
- 匹配理由：已覆盖关键技能：Python, Prompt Engineering

推荐项目：
- langchain-ai/langchain (110000 stars) | 难度: 中 | 预计时间: 4-6天
  - 推荐理由：可补齐技能缺口：agent
```

---

## 📝 License

MIT
