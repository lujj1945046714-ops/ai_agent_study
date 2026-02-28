# 🤖 AI 求职助手

> 粘贴你的简历 + 目标 JD，AI 自动分析匹配度、找出技能缺口、推荐学习项目

---

## 它能做什么？

1. **读懂你的简历** — 上传或粘贴简历，自动提取技能画像
2. **分析职位 JD** — 粘贴 JD 文本，AI 解析必备技能和技术栈
3. **计算匹配分** — 0-100 分，告诉你和这个职位差多远
4. **找出技能缺口** — 明确列出你还缺哪些技能
5. **推荐学习项目** — 根据缺口从 GitHub 推荐最合适的开源项目
6. **制定学习计划** — 生成 3/6/12 个月的个性化学习路径

---

## 快速开始

### 1. 安装依赖

```bash
pip install openai langgraph sentence-transformers gradio python-dotenv pydantic requests pypdf
```

### 2. 配置 API Key

在项目根目录创建 `.env`：

```env
# 必填：DeepSeek API Key（https://platform.deepseek.com）
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx

# 可选：GitHub Token（不填则使用内置项目目录）
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxx
```

### 3. 启动 Web 界面

```bash
python web_ui.py
```

浏览器打开 `http://localhost:7860`，按以下步骤操作：

```
① 粘贴简历 → 点击「分析简历并建立画像」
② 粘贴 JD  → 点击「确认JD并分析匹配度」
③ 查看匹配分、技能缺口、推荐项目
④ 继续对话追问，例如「制定3个月学习计划」
```

> 支持多个 JD 同时分析：用单独一行 `---` 分隔多段 JD 粘贴即可

---

## 也可以用命令行

```bash
# 线性流程（最简单）
python main.py

# ReAct Agent 模式（LLM 自主决策）
python main.py --agent

# Multi-Agent 模式（4 个专职 Agent 协作）
python main.py --multi-agent
```

---

## 技术架构

```
用户输入（简历 / JD）
       ↓
  画像提取（LLM）
       ↓
  JD 解析（LLM + 启发式降级）
       ↓
  技能匹配（SentenceTransformer 语义相似度）
       ↓
  GitHub 项目推荐（LLM 规划搜索 → 质量检测 → LLM 重排序）
       ↓
  学习计划生成 + 报告输出
```

**三种执行模式：**

| 模式 | 特点 |
|------|------|
| Pipeline | 固定顺序执行，适合快速跑通 |
| ReAct Agent | LLM 自主决定工具调用顺序，可动态跳过低分职位 |
| Multi-Agent | LangGraph 调度 4 个专职 Agent 协作完成任务 |

---

## 核心设计

**匹配评分公式**
```
score = 必备技能匹配率 × (0.7 + 技术栈匹配率 × 0.2 + 加分项 × 0.1) × 100
```
必备技能匹配率为 0 时，总分直接为 0 —— 核心技能不能靠其他项补救。

**LLM 解析容错**
```
调用 DeepSeek API
  → 超时：重试 3 次
  → JSON 解析失败：重试 1 次
  → 仍失败：降级到关键词 + 正则启发式解析
  → API Key 无效：立即报错
```

**GitHub 推荐流程**
```
LLM 分析技能缺口 → 生成搜索策略
  → 搜索 GitHub API（24h 缓存）
  → 质量检测（star 数 / 描述覆盖率）
  → 不合格：重新规划搜索策略（最多 2 次）
  → LLM 按用户背景重排序 → 输出推荐
```

---

## 项目结构

```
02_项目开发/
├── web_ui.py              # Web 界面（推荐入口）
├── main.py                # 命令行入口
├── config.py              # 配置（API Key、参数）
├── onboarding.py          # 对话式画像收集
├── memory.py              # 跨会话记忆
├── database.py            # SQLite 数据持久化
├── report_generator.py    # Markdown 报告生成
│
├── modules/
│   ├── analyzer.py        # JD 解析
│   ├── matcher_enhanced.py# 技能匹配评分
│   ├── github_recommender.py # GitHub 项目推荐
│   └── scraper.py         # JD 输入处理
│
└── agent/
    ├── react_agent.py     # ReAct Agent 核心
    ├── tools.py           # 工具定义
    └── multi_agent/       # LangGraph Multi-Agent
```

---

## 配置参数

`config.py` 中可调整：

```python
MAX_DEEP_ANALYSIS = 5    # 深度分析的职位数（影响 API 调用次数）
GITHUB_TOP_N = 3         # 推荐 GitHub 项目数
```

---

## License

MIT
