import os
from dotenv import load_dotenv

load_dotenv()

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

# GitHub API（可选，不填则只用本地目录）
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# 本地代理（VPN），用于访问 GitHub API / HuggingFace
HTTP_PROXY = os.environ.get("HTTP_PROXY", "http://127.0.0.1:7897")
