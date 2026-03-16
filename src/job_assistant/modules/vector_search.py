"""
向量搜索引擎

功能：
1. 使用 sentence-transformers 向量化项目描述
2. 使用 FAISS 构建向量索引
3. 支持语义相似度搜索
4. 支持混合搜索（关键词 + 语义）
5. 原子替换机制保证并发安全
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)

# 检查依赖是否可用
try:
    import faiss
    import numpy as np
    from sentence_transformers import SentenceTransformer
    VECTOR_SEARCH_AVAILABLE = True
except ImportError:
    VECTOR_SEARCH_AVAILABLE = False
    logger.info("向量搜索依赖未安装，将仅使用关键词搜索。安装方法: pip install -e .[semantic]")


class VectorSearchEngine:
    """向量搜索引擎"""

    def __init__(self, index_dir: Path, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        """
        初始化向量搜索引擎

        参数：
        - index_dir: 索引存储目录
        - model_name: sentence-transformers 模型名称
        """
        if not VECTOR_SEARCH_AVAILABLE:
            raise RuntimeError(
                "向量搜索依赖未安装。请运行: pip install -e .[semantic]"
            )

        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)

        self.index_path = self.index_dir / "vector_index.faiss"
        self.metadata_path = self.index_dir / "vector_metadata.json"

        # 加载模型
        logger.info("加载向量模型: %s", model_name)
        self.model = SentenceTransformer(model_name)
        self.embedding_dim = self.model.get_sentence_embedding_dimension()

        # 加载或初始化索引
        self.index = None
        self.repo_id_to_vector_id = {}
        self.metadata = []
        self._load_index()

    def _load_index(self):
        """加载已有索引"""
        if self.index_path.exists() and self.metadata_path.exists():
            try:
                logger.info("加载已有索引: %s", self.index_path)
                self.index = faiss.read_index(str(self.index_path))

                with open(self.metadata_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.repo_id_to_vector_id = data.get("repo_id_to_vector_id", {})
                    self.metadata = data.get("metadata", [])

                logger.info("索引加载成功，包含 %d 个项目", len(self.metadata))
            except Exception as e:
                logger.warning("索引加载失败，将创建新索引: %s", e)
                self._init_empty_index()
        else:
            logger.info("索引文件不存在，创建新索引")
            self._init_empty_index()

    def _init_empty_index(self):
        """初始化空索引"""
        self.index = faiss.IndexFlatL2(self.embedding_dim)
        self.repo_id_to_vector_id = {}
        self.metadata = []

    def _atomic_save_index(self):
        """原子替换索引文件（避免并发读写损坏）"""
        temp_index = self.index_path.with_suffix(".tmp")
        temp_meta = self.metadata_path.with_suffix(".tmp")

        try:
            # 1. 写入临时文件
            faiss.write_index(self.index, str(temp_index))
            with open(temp_meta, "w", encoding="utf-8") as f:
                json.dump({
                    "repo_id_to_vector_id": self.repo_id_to_vector_id,
                    "metadata": self.metadata
                }, f, ensure_ascii=False, indent=2)

            # 2. 校验完整性
            faiss.read_index(str(temp_index))

            # 3. 原子替换（Windows 需要先删除）
            if self.index_path.exists():
                self.index_path.unlink()
            temp_index.rename(self.index_path)

            if self.metadata_path.exists():
                self.metadata_path.unlink()
            temp_meta.rename(self.metadata_path)

            logger.info("索引保存成功: %s", self.index_path)
        except Exception as e:
            logger.error("索引保存失败: %s", e)
            # 清理临时文件
            if temp_index.exists():
                temp_index.unlink()
            if temp_meta.exists():
                temp_meta.unlink()
            raise

    def _embed_repos(self, repos: List[Dict]):
        """向量化项目描述"""
        texts = []
        for repo in repos:
            # 组合项目名称、描述和主题
            name = repo.get("name", repo.get("full_name", ""))
            description = repo.get("description", "")
            topics = " ".join(repo.get("topics", []))
            text = f"{name} {description} {topics}".strip()
            texts.append(text if text else "unknown project")

        embeddings = self.model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        return embeddings

    def add_repos(self, repos: List[Dict]):
        """
        增量添加项目（去重）

        参数：
        - repos: 项目列表，每个项目需包含 full_name 字段
        """
        if not repos:
            return

        # 去重：只添加新项目
        new_repos = []
        for repo in repos:
            repo_id = repo.get("full_name", repo.get("name", ""))
            if not repo_id:
                continue
            if repo_id not in self.repo_id_to_vector_id:
                new_repos.append(repo)

        if not new_repos:
            logger.info("所有项目已存在，跳过添加")
            return

        logger.info("添加 %d 个新项目到索引", len(new_repos))

        # 向量化新项目
        embeddings = self._embed_repos(new_repos)

        # 更新索引
        start_id = len(self.metadata)
        for i, repo in enumerate(new_repos):
            repo_id = repo.get("full_name", repo.get("name", ""))
            self.repo_id_to_vector_id[repo_id] = start_id + i
            self.metadata.append(repo)

        self.index.add(embeddings)
        self._atomic_save_index()

    def search(self, query: str, top_k: int = 10) -> List[Dict]:
        """
        语义搜索

        参数：
        - query: 搜索查询
        - top_k: 返回结果数量

        返回：
        - 项目列表（包含相似度分数）
        """
        if not self.metadata:
            logger.warning("索引为空，无法搜索")
            return []

        # 向量化查询
        query_embedding = self.model.encode([query], convert_to_numpy=True, show_progress_bar=False)

        # FAISS 相似度搜索
        distances, indices = self.index.search(query_embedding, min(top_k, len(self.metadata)))

        # 构建结果
        results = []
        for i, (dist, idx) in enumerate(zip(distances[0], indices[0])):
            if idx < 0 or idx >= len(self.metadata):
                continue
            repo = dict(self.metadata[idx])
            repo["similarity_score"] = float(1.0 / (1.0 + dist))  # 转换为相似度分数
            repo["rank"] = i + 1
            results.append(repo)

        return results

    def hybrid_search(
        self,
        query: str,
        keyword_results: List[Dict],
        top_k: int = 10,
        w_keyword: float = 0.5,
        w_semantic: float = 0.5
    ) -> List[Dict]:
        """
        混合搜索：关键词 + 语义（RRF 融合）

        参数：
        - query: 搜索查询
        - keyword_results: 关键词搜索结果
        - top_k: 返回结果数量
        - w_keyword: 关键词权重
        - w_semantic: 语义权重

        返回：
        - 融合后的项目列表
        """
        # 语义搜索
        semantic_results = self.search(query, top_k=20)  # 固定窗口

        # RRF 融合
        return self._rrf_merge(
            keyword_results[:20],  # 固定窗口
            semantic_results,
            k=60,
            w_keyword=w_keyword,
            w_semantic=w_semantic,
            top_k=top_k
        )

    def _rrf_merge(
        self,
        keyword_results: List[Dict],
        semantic_results: List[Dict],
        k: int = 60,
        w_keyword: float = 0.5,
        w_semantic: float = 0.5,
        top_k: int = 10
    ) -> List[Dict]:
        """
        加权 RRF (Reciprocal Rank Fusion) 融合算法

        参数：
        - keyword_results: 关键词搜索结果
        - semantic_results: 语义搜索结果
        - k: RRF 参数（默认 60）
        - w_keyword: 关键词权重
        - w_semantic: 语义权重
        - top_k: 返回结果数量

        返回：
        - 融合后的项目列表
        """
        scores = {}
        repo_map = {}

        # 关键词通道
        for rank, repo in enumerate(keyword_results):
            repo_id = repo.get("full_name", repo.get("name", ""))
            if not repo_id:
                continue
            scores[repo_id] = scores.get(repo_id, 0) + w_keyword / (k + rank + 1)
            if repo_id not in repo_map:
                repo_map[repo_id] = repo

        # 语义通道
        for rank, repo in enumerate(semantic_results):
            repo_id = repo.get("full_name", repo.get("name", ""))
            if not repo_id:
                continue
            scores[repo_id] = scores.get(repo_id, 0) + w_semantic / (k + rank + 1)
            if repo_id not in repo_map:
                repo_map[repo_id] = repo

        # 按融合分数排序
        sorted_repos = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        # 构建结果
        results = []
        for repo_id, score in sorted_repos[:top_k]:
            repo = dict(repo_map[repo_id])
            repo["fusion_score"] = float(score)
            results.append(repo)

        return results


def create_vector_search_engine(index_dir: Path) -> Optional[VectorSearchEngine]:
    """
    创建向量搜索引擎（带降级处理）

    参数：
    - index_dir: 索引存储目录

    返回：
    - VectorSearchEngine 实例，如果依赖缺失则返回 None
    """
    if not VECTOR_SEARCH_AVAILABLE:
        logger.warning("向量搜索依赖未安装，将仅使用关键词搜索")
        return None

    try:
        return VectorSearchEngine(index_dir)
    except Exception as e:
        logger.error("向量搜索引擎初始化失败: %s", e)
        return None
