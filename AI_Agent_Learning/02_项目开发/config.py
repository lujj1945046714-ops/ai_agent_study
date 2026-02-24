import os

# DeepSeek API（兼容 OpenAI 格式）
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"  # DeepSeek-V3

# 本地数据与运行配置
DB_PATH = os.environ.get("JOB_ASSISTANT_DB_PATH", "data/jobs.db")
MAX_FETCH_JOBS = 30

# 渐进式筛选参数
MAX_COARSE_FILTER = 20   # 粗筛后保留的职位数
MAX_DEEP_ANALYSIS = 5    # 深度分析的职位数
GITHUB_TOP_N = 3         # 推荐 GitHub 项目数量
