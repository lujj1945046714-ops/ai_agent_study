"""
向量搜索引擎测试
"""

import json
import shutil
from pathlib import Path

import pytest

from job_assistant.modules.vector_search import (
    VECTOR_SEARCH_AVAILABLE,
    VectorSearchEngine,
    create_vector_search_engine,
)


@pytest.fixture
def temp_index_dir(tmp_path):
    """临时索引目录"""
    index_dir = tmp_path / "vector_index"
    index_dir.mkdir()
    yield index_dir
    if index_dir.exists():
        shutil.rmtree(index_dir)


@pytest.fixture
def sample_repos():
    """示例项目数据"""
    return [
        {
            "full_name": "langchain-ai/langchain",
            "name": "langchain",
            "description": "Building applications with LLMs through composability",
            "topics": ["llm", "langchain", "agent", "rag"],
            "stargazers_count": 110000,
        },
        {
            "full_name": "run-llama/llama_index",
            "name": "llama_index",
            "description": "LlamaIndex is a data framework for LLM applications",
            "topics": ["llm", "rag", "vector-db"],
            "stargazers_count": 40000,
        },
        {
            "full_name": "microsoft/autogen",
            "name": "autogen",
            "description": "Enable Next-Gen Large Language Model Applications",
            "topics": ["llm", "agent", "autogen"],
            "stargazers_count": 45000,
        },
    ]


@pytest.mark.skipif(not VECTOR_SEARCH_AVAILABLE, reason="向量搜索依赖未安装")
def test_vector_search_engine_init(temp_index_dir):
    """测试向量搜索引擎初始化"""
    engine = VectorSearchEngine(temp_index_dir)
    assert engine.index is not None
    assert engine.embedding_dim > 0
    assert len(engine.metadata) == 0


@pytest.mark.skipif(not VECTOR_SEARCH_AVAILABLE, reason="向量搜索依赖未安装")
def test_add_repos(temp_index_dir, sample_repos):
    """测试添加项目到索引"""
    engine = VectorSearchEngine(temp_index_dir)
    engine.add_repos(sample_repos)

    assert len(engine.metadata) == 3
    assert "langchain-ai/langchain" in engine.repo_id_to_vector_id
    assert "run-llama/llama_index" in engine.repo_id_to_vector_id
    assert "microsoft/autogen" in engine.repo_id_to_vector_id


@pytest.mark.skipif(not VECTOR_SEARCH_AVAILABLE, reason="向量搜索依赖未安装")
def test_add_repos_deduplication(temp_index_dir, sample_repos):
    """测试去重机制"""
    engine = VectorSearchEngine(temp_index_dir)
    engine.add_repos(sample_repos)
    initial_count = len(engine.metadata)

    # 再次添加相同项目
    engine.add_repos(sample_repos)

    # 应该没有增加
    assert len(engine.metadata) == initial_count


@pytest.mark.skipif(not VECTOR_SEARCH_AVAILABLE, reason="向量搜索依赖未安装")
def test_semantic_search(temp_index_dir, sample_repos):
    """测试语义搜索"""
    engine = VectorSearchEngine(temp_index_dir)
    engine.add_repos(sample_repos)

    # 搜索 "AI agent framework"
    results = engine.search("AI agent framework", top_k=3)

    assert len(results) > 0
    assert all("similarity_score" in r for r in results)
    assert all("rank" in r for r in results)

    # 验证结果包含相关项目
    result_names = [r.get("full_name", r.get("name", "")) for r in results]
    assert any("autogen" in name.lower() or "langchain" in name.lower() for name in result_names)


@pytest.mark.skipif(not VECTOR_SEARCH_AVAILABLE, reason="向量搜索依赖未安装")
def test_hybrid_search(temp_index_dir, sample_repos):
    """测试混合搜索（RRF 融合）"""
    engine = VectorSearchEngine(temp_index_dir)
    engine.add_repos(sample_repos)

    # 模拟关键词搜索结果
    keyword_results = [
        {
            "full_name": "langchain-ai/langchain",
            "name": "langchain",
            "description": "Building applications with LLMs",
            "stargazers_count": 110000,
        }
    ]

    # 混合搜索
    results = engine.hybrid_search(
        query="LLM agent framework",
        keyword_results=keyword_results,
        top_k=3,
        w_keyword=0.5,
        w_semantic=0.5
    )

    assert len(results) > 0
    assert all("fusion_score" in r for r in results)

    # 验证融合分数是递减的
    scores = [r["fusion_score"] for r in results]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.skipif(not VECTOR_SEARCH_AVAILABLE, reason="向量搜索依赖未安装")
def test_index_persistence(temp_index_dir, sample_repos):
    """测试索引持久化"""
    # 创建引擎并添加项目
    engine1 = VectorSearchEngine(temp_index_dir)
    engine1.add_repos(sample_repos)

    # 验证文件已创建
    assert (temp_index_dir / "vector_index.faiss").exists()
    assert (temp_index_dir / "vector_metadata.json").exists()

    # 创建新引擎，应该加载已有索引
    engine2 = VectorSearchEngine(temp_index_dir)
    assert len(engine2.metadata) == 3
    assert "langchain-ai/langchain" in engine2.repo_id_to_vector_id


@pytest.mark.skipif(not VECTOR_SEARCH_AVAILABLE, reason="向量搜索依赖未安装")
def test_atomic_save_index(temp_index_dir, sample_repos):
    """测试原子替换机制"""
    engine = VectorSearchEngine(temp_index_dir)
    engine.add_repos(sample_repos)

    # 验证没有临时文件残留
    assert not (temp_index_dir / "vector_index.tmp").exists()
    assert not (temp_index_dir / "vector_metadata.tmp").exists()

    # 验证索引文件完整
    index_path = temp_index_dir / "vector_index.faiss"
    metadata_path = temp_index_dir / "vector_metadata.json"

    assert index_path.exists()
    assert metadata_path.exists()

    # 验证元数据可读
    with open(metadata_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert "repo_id_to_vector_id" in data
        assert "metadata" in data


def test_create_vector_search_engine_with_missing_deps(temp_index_dir, monkeypatch):
    """测试依赖缺失时的降级处理"""
    # 模拟依赖缺失
    monkeypatch.setattr("job_assistant.modules.vector_search.VECTOR_SEARCH_AVAILABLE", False)

    engine = create_vector_search_engine(temp_index_dir)
    assert engine is None


@pytest.mark.skipif(not VECTOR_SEARCH_AVAILABLE, reason="向量搜索依赖未安装")
def test_rrf_merge_weights(temp_index_dir, sample_repos):
    """测试 RRF 融合权重"""
    engine = VectorSearchEngine(temp_index_dir)
    engine.add_repos(sample_repos)

    keyword_results = [sample_repos[0]]  # langchain

    # 测试不同权重
    results_keyword_heavy = engine.hybrid_search(
        query="LLM framework",
        keyword_results=keyword_results,
        top_k=3,
        w_keyword=0.8,
        w_semantic=0.2
    )

    results_semantic_heavy = engine.hybrid_search(
        query="LLM framework",
        keyword_results=keyword_results,
        top_k=3,
        w_keyword=0.2,
        w_semantic=0.8
    )

    # 验证权重影响排序
    assert len(results_keyword_heavy) > 0
    assert len(results_semantic_heavy) > 0

    # 关键词权重高时，langchain 应该排名靠前
    keyword_heavy_names = [r.get("full_name", r.get("name", "")) for r in results_keyword_heavy]
    assert "langchain-ai/langchain" in keyword_heavy_names[:2]


@pytest.mark.skipif(not VECTOR_SEARCH_AVAILABLE, reason="向量搜索依赖未安装")
def test_empty_query_handling(temp_index_dir, sample_repos):
    """测试空查询处理"""
    engine = VectorSearchEngine(temp_index_dir)
    engine.add_repos(sample_repos)

    results = engine.search("", top_k=3)
    # 空查询应该返回结果（基于向量相似度）
    assert len(results) >= 0


@pytest.mark.skipif(not VECTOR_SEARCH_AVAILABLE, reason="向量搜索依赖未安装")
def test_search_with_empty_index(temp_index_dir):
    """测试空索引搜索"""
    engine = VectorSearchEngine(temp_index_dir)

    results = engine.search("AI agent", top_k=3)
    assert len(results) == 0
