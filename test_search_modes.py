#!/usr/bin/env python3
"""测试 GitHub 搜索的两种模式"""

import requests
import json

BASE_URL = "http://localhost:7860"

def register_or_login():
    """注册或登录并获取 session cookie"""
    # 先尝试注册
    response = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={"username": "testuser", "password": "testpass123"}
    )
    if response.status_code == 200:
        print("✓ 注册成功")
        return response.cookies

    # 如果注册失败（可能已存在），尝试登录
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": "testuser", "password": "testpass123"}
    )
    if response.status_code == 200:
        print("✓ 登录成功")
        return response.cookies
    else:
        print(f"登录失败: {response.status_code}")
        print(f"响应: {response.text}")
        return None

def test_independent_search(cookies):
    """测试独立搜索模式 (use_profile=False)"""
    print("\n=== 测试独立搜索模式 ===")
    response = requests.post(
        f"{BASE_URL}/api/github/search",
        json={
            "user_query": "我想学习 AI Agent 开发",
            "min_stars": 1000,
            "top_n": 3,
            "include_audit": False,
            "include_similar": True,
            "use_profile": False
        },
        cookies=cookies
    )

    if response.status_code == 200:
        result = response.json()
        print(f"状态: {result.get('status')}")
        print(f"返回项目数: {len(result.get('repos', []))}")
        if result.get('repos'):
            print("\n推荐理由示例:")
            for i, repo in enumerate(result['repos'][:2], 1):
                print(f"{i}. {repo.get('name')}")
                print(f"   理由: {repo.get('reason', 'N/A')[:100]}...")
        return result
    else:
        print(f"请求失败: {response.status_code}")
        print(f"响应: {response.text}")
        return None

def test_profile_based_search(cookies):
    """测试基于简历的搜索模式 (use_profile=True)"""
    print("\n=== 测试基于简历的搜索模式 ===")
    response = requests.post(
        f"{BASE_URL}/api/github/search",
        json={
            "user_query": "我想学习 AI Agent 开发",
            "min_stars": 1000,
            "top_n": 3,
            "include_audit": False,
            "include_similar": True,
            "use_profile": True
        },
        cookies=cookies
    )

    if response.status_code == 200:
        result = response.json()
        print(f"状态: {result.get('status')}")
        print(f"返回项目数: {len(result.get('repos', []))}")
        if result.get('repos'):
            print("\n推荐理由示例:")
            for i, repo in enumerate(result['repos'][:2], 1):
                print(f"{i}. {repo.get('name')}")
                print(f"   理由: {repo.get('reason', 'N/A')[:100]}...")
        return result
    else:
        print(f"请求失败: {response.status_code}")
        print(f"响应: {response.text}")
        return None

def main():
    print("开始测试 GitHub 搜索模式...")

    # 注册或登录
    cookies = register_or_login()
    if not cookies:
        print("无法登录，测试终止")
        return

    # 测试两种模式
    result1 = test_independent_search(cookies)
    result2 = test_profile_based_search(cookies)

    # 对比结果
    if result1 and result2:
        print("\n=== 结果对比 ===")
        print(f"独立搜索状态: {result1.get('status')}")
        print(f"简历搜索状态: {result2.get('status')}")

        if result1.get('repos') and result2.get('repos'):
            print("\n两种模式返回的项目是否相同:")
            repos1 = {r.get('name') for r in result1['repos']}
            repos2 = {r.get('name') for r in result2['repos']}
            if repos1 == repos2:
                print("⚠️  项目列表相同（可能是因为查询相同或缓存）")
            else:
                print("✓ 项目列表不同（符合预期）")
                print(f"  独立搜索独有: {repos1 - repos2}")
                print(f"  简历搜索独有: {repos2 - repos1}")

if __name__ == "__main__":
    main()
