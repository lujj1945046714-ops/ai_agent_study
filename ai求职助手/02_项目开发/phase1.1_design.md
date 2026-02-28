# Phase 1.1 设计文档 - 精准技能匹配

## 当前问题分析

### 1. 技能分级不够细化
**现状**:
- 只区分 `required_skills`、`tech_stack`、`nice_to_have`
- 用户技能只有 `core` 和 `tools` 两类
- 没有技能熟练度评估

**问题**:
- "Python" 可能是入门级，也可能是专家级
- "LangChain" 可能只是听说过，也可能有深度实践
- 匹配算法无法区分这些差异

### 2. 语义匹配阈值固定
**现状**:
- 固定阈值 0.75
- 所有技能一视同仁

**问题**:
- "Python" 和 "Python编程" 相似度可能低于 0.75
- "RAG" 和 "检索增强生成" 应该匹配，但可能被过滤
- 核心技能和加分项应该用不同阈值

### 3. 经验级别粗粒度
**现状**:
- 只有 "应届/1-3年/3-5年/5年以上"
- 只在初级岗位给应届生加 8 分

**问题**:
- 1年和3年差距很大，但被归为同一档
- 没有考虑技能深度和项目经验

## 改进方案

### 方案 A: 技能分级系统（推荐）

#### 1. 技能熟练度等级
```python
SKILL_PROFICIENCY = {
    0: "未接触",
    1: "了解概念",      # 看过文档，知道是什么
    2: "基础使用",      # 跑过 demo，写过简单代码
    3: "熟练掌握",      # 独立完成项目，理解原理
    4: "深度实践",      # 解决过复杂问题，有最佳实践
    5: "专家级别"       # 贡献开源，深入源码，能讲课
}
```

#### 2. 岗位技能要求等级
```python
JOB_REQUIREMENT_LEVEL = {
    "required_skills": {
        "min_level": 3,  # 必备技能至少要熟练掌握
        "weight": 0.6
    },
    "tech_stack": {
        "min_level": 2,  # 技术栈至少要基础使用
        "weight": 0.3
    },
    "nice_to_have": {
        "min_level": 1,  # 加分项了解即可
        "weight": 0.1
    }
}
```

#### 3. 新的用户画像格式
```json
{
  "skills": {
    "Python": {"level": 3, "years": 2, "projects": ["项目A", "项目B"]},
    "LangChain": {"level": 2, "years": 0.5, "projects": ["学习项目"]},
    "Git": {"level": 3, "years": 2}
  }
}
```

#### 4. 新的匹配算法
```python
def calculate_skill_match(user_skill, required_skill, category):
    # 1. 语义匹配（是否是同一技能）
    if not semantic_match(user_skill.name, required_skill.name):
        return 0

    # 2. 熟练度匹配
    min_level = JOB_REQUIREMENT_LEVEL[category]["min_level"]
    user_level = user_skill.level

    if user_level < min_level:
        # 未达标，按比例扣分
        return (user_level / min_level) * 0.5
    elif user_level == min_level:
        # 刚好达标
        return 1.0
    else:
        # 超出要求，额外加分
        return 1.0 + (user_level - min_level) * 0.1

    # 3. 经验年限加成
    if user_skill.years >= 2:
        return score * 1.1

    return score
```

### 方案 B: 技能关联图（可选）

#### 1. 技能依赖关系
```python
SKILL_GRAPH = {
    "RAG": {
        "depends_on": ["向量数据库", "Embedding", "LLM API"],
        "related": ["LangChain", "LlamaIndex"]
    },
    "LangChain": {
        "depends_on": ["Python", "LLM API"],
        "related": ["AutoGen", "Agent"]
    }
}
```

#### 2. 技能推断
```python
# 如果用户有 RAG 经验，可以推断出：
# - 一定了解向量数据库（至少 level 1）
# - 一定了解 Embedding（至少 level 1）
# - 可能了解 LangChain（相关技能）
```

### 方案 C: 改用 DeepSeek Embedding API（可选）

#### 优点
- 不需要本地下载模型
- 支持更长的文本
- 可能有更好的中文支持

#### 缺点
- 增加 API 调用成本
- 需要网络连接
- 响应速度可能较慢

#### 建议
- 暂不实现，SentenceTransformer 已经够用
- 如果未来需要更精准的匹配，再考虑

## 实现计划

### 阶段 1: 技能熟练度系统（核心）
1. 定义技能熟练度等级（0-5）
2. 更新用户画像格式（向后兼容）
3. 更新匹配算法（考虑熟练度）
4. 更新 onboarding 流程（询问熟练度）

### 阶段 2: 动态语义阈值（优化）
1. 不同类别技能用不同阈值
2. 核心技能阈值 0.8（严格）
3. 技术栈阈值 0.75（中等）
4. 加分项阈值 0.7（宽松）

### 阶段 3: 技能关联图（增强）
1. 定义常见技能依赖关系
2. 实现技能推断逻辑
3. 在匹配时考虑关联技能

## 兼容性考虑

### 向后兼容
```python
# 旧格式（仍然支持）
{
  "skills": {
    "core": ["Python", "LangChain"],
    "tools": ["Git"]
  }
}

# 新格式
{
  "skills": {
    "Python": {"level": 3, "years": 2},
    "LangChain": {"level": 2, "years": 0.5}
  }
}

# 兼容逻辑
def normalize_skills(profile):
    skills = profile.get("skills", {})

    # 检测旧格式
    if "core" in skills or "tools" in skills:
        # 转换为新格式，默认 level=2
        normalized = {}
        for skill in skills.get("core", []):
            normalized[skill] = {"level": 2, "years": 0}
        for skill in skills.get("tools", []):
            normalized[skill] = {"level": 2, "years": 0}
        return normalized

    # 已经是新格式
    return skills
```

## 测试计划

### 测试用例 1: 熟练度差异
```python
# 用户 A: Python level 2（基础）
# 用户 B: Python level 4（深度实践）
# 职位要求: Python level 3（熟练）
# 预期: A 得分 < B 得分
```

### 测试用例 2: 技能推断
```python
# 用户有 RAG 经验 level 3
# 职位要求: 向量数据库 level 2
# 预期: 自动推断用户了解向量数据库（至少 level 1）
```

### 测试用例 3: 向后兼容
```python
# 旧格式用户画像
# 预期: 正常运行，默认 level=2
```

## 预期效果

### 匹配精准度提升
- 当前: 只要有技能就算匹配（0/1）
- 改进后: 考虑熟练度差异（0-1.5 连续值）

### 用户体验提升
- 当前: "你缺少 Python"（但其实用户会 Python，只是不够熟练）
- 改进后: "你的 Python 是基础级别，岗位要求熟练掌握，建议深入学习"

### 推荐精准度提升
- 当前: 推荐项目不考虑用户水平
- 改进后: 根据熟练度推荐合适难度的项目

## 实现优先级

**高优先级（本周）**:
1. ✅ 定义技能熟练度等级
2. ✅ 更新匹配算法
3. ✅ 向后兼容处理

**中优先级（下周）**:
4. 更新 onboarding 流程
5. 动态语义阈值
6. 测试用例

**低优先级（未来）**:
7. 技能关联图
8. DeepSeek Embedding API

---

**决策**: 先实现阶段 1（技能熟练度系统），这是最核心的改进，能立即提升匹配精准度。
