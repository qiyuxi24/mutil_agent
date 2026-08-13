"""FixerLoop 独立调试脚本 —— 不跑完整 Manager Loop，只测 Fixer。

用法：
    cd software-dev-fullflow\src
    ..\demo\.venv\Scripts\python.exe debug_fixer.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from agent_framework import Agent
from agent_framework.openai import OpenAIChatCompletionClient
from openai import AsyncOpenAI

# 加载环境变量
sys.path.insert(0, str(Path(__file__).resolve().parent))
for p in (
    Path(__file__).resolve().parent.parent / "demo" / ".env",
    Path(__file__).resolve().parent / ".env",
):
    if p.exists():
        load_dotenv(p, override=True)
        break

if not os.environ.get("DEEPSEEK_API_KEY"):
    print("缺少 DEEPSEEK_API_KEY，请在 demo/.env 配置后重试。")
    sys.exit(1)

from loop.fixer_loop import FixerLoop  # noqa: E402

# ---- 模拟的 root-cause 分析上下文（逼真的缺陷场景） ----
CONTEXT = """【原始任务】
登录接口 /api/auth/login 在高并发场景下（QPS > 200）偶发返回 HTTP 500。
错误日志显示 NullPointerException，发生在 UserService.authenticate() 方法中。

【根因分析产物 · root-cause.md】
## 根因
UserService.authenticate() 方法中，第 47 行的 `user.getProfile()` 在高并发下可能返回 null。
原因是 loadUserProfile() 是异步方法，但调用处没有 await，导致竞态条件：
- 线程 A 调用 authenticate() → 触发 loadUserProfile() → 返回 Future
- 线程 B 同时调用 authenticate() → 同一个 user 对象的 profile 被覆盖
- 线程 A 的 Future 完成时，profile 已被线程 B 覆盖，getProfile() 返回 null

## 影响面
- 影响文件：src/auth/service.py 第 42-55 行
- 影响模块：auth 模块的 UserService 类
- 风险等级：高（直接导致 500 错误，影响所有登录用户）

## 修复建议
1. 在 authenticate() 中对 loadUserProfile() 加 await 等待
2. 添加 profile 为 null 的防御性检查（返回明确错误而非 NPE）
3. 考虑对 loadUserProfile() 加锁或使用线程安全的缓存
4. 修复后需更新对应的单元测试

【约束条件】
- 不能修改 User 类的公共接口（其他模块依赖）
- 不能引入新的第三方依赖
- 修复必须向后兼容（不影响现有单线程场景）"""

WORKDIR = Path(__file__).resolve().parent / "data"


async def main():
    print("=" * 60)
    print("FixerLoop 独立调试")
    print("=" * 60)
    print(f"模型: {os.environ.get('DEEPSEEK_MODEL', 'deepseek-v4-flash')}")
    print(f"上下文: {len(CONTEXT)} 字符")
    print()

    # 创建客户端
    client = OpenAIChatCompletionClient(
        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        async_client=AsyncOpenAI(
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            http_client=httpx.AsyncClient(trust_env=False),
        ),
    )

    # 创建 FixerLoop
    fixer = FixerLoop(client=client, workdir=WORKDIR, mock=False)

    # 运行
    t0 = time.time()
    print(">>> 启动 FixerLoop ...")
    result = await fixer.run(context=CONTEXT, milestone="FIX_APPLIED")
    elapsed = time.time() - t0

    print()
    print("=" * 60)
    print(f">>> FixerLoop 完成（{elapsed:.1f}s）")
    print(f">>> 总 LLM 调用: {fixer._total_iterations} 次")
    print(f">>> 错误日志: {len(fixer._error_log)} 条")
    if fixer._error_log:
        for e in fixer._error_log:
            print(f"    - {e[:120]}")
    print()
    print(">>> 最终输出:")
    print("-" * 40)
    print(result[:3000])
    if len(result) > 3000:
        print(f"\n... (共 {len(result)} 字符，已截断)")
    print("-" * 40)

    # 判断
    if result.startswith("FIX_APPLIED"):
        print("\n✅ Fixer 成功完成修复（FIX_APPLIED）")
    elif result.startswith("FIX_FAILED"):
        print("\n❌ Fixer 修复失败")
    else:
        print("\n⚠️  输出格式异常（未以 FIX_APPLIED/FIX_FAILED 开头）")


if __name__ == "__main__":
    asyncio.run(main())