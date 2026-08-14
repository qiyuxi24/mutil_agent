"""上下文工程真实 API 测试 —— 对接 WorkBuddy (CodeBuddy) 后端。

用法：
  python test_context_with_api.py

该脚本会：
  1. 从 .env + 本地 auth 文件加载 WorkBuddy 凭据
  2. 用 deepseek-v4-flash 跑 2 组对比测试：
     - 无上下文工程：原始 context 硬拼接
     - 有上下文工程：ContextManager 70/30 预算 + offload + 三层记忆
  3. 输出对比报告
"""

import sys
import time
from pathlib import Path

# 添加 src/loop 到路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from workbuddy_client import WorkBuddyClient
from context import (
    ContextManager,
    TokenEstimator,
)


# ========================================================================== #
# 模拟任务：一个完整的 PDCA 软件修复任务
# ========================================================================== #

TASK_SPEC = """修复一个 Python Web 应用的登录空指针异常：
- 当用户名为空字符串时点击登录按钮，后端抛出 NullPointerException
- 需要在 UserService.login() 方法中添加空值检查
- 如果用户名或密码为空，返回 {"error": "username or password is empty"} 和 HTTP 400
- 不要改动其他业务逻辑"""

STAGES = [
    ("aggregate", "汇总需求，理解问题范围"),
    ("decompose", "分解任务，确定修改点"),
    ("root_cause", "分析根因，定位问题代码"),
    ("fix_apply", "编写修复代码"),
    ("test_verify", "验证修复是否正确"),
    ("retrospect", "回顾总结，记录经验"),
]


# ========================================================================== #
# 测试 1: 无上下文工程（原始硬拼接）
# ========================================================================== #

def run_no_context_engine(client: WorkBuddyClient) -> dict:
    """无上下文工程：原始 context 硬拼接，无预算控制，无 offload。"""
    print("\n" + "=" * 60)
    print("【测试 1】无上下文工程（原始硬拼接）")
    print("=" * 60)

    context = f"【原始任务】\n{TASK_SPEC}\n"
    total_prompt_tokens = 0
    total_completion_tokens = 0
    results = []

    for i, (stage, description) in enumerate(STAGES):
        prompt = (
            f"你是软件研发 Worker，当前阶段: {stage}\n\n"
            f"【任务描述】{description}\n\n"
            f"【上下文】\n{context}\n\n"
            f"请输出 {stage} 阶段的工作产物，标注里程碑: {stage.upper()}_DONE"
        )
        prompt_tokens_est = TokenEstimator.estimate(prompt)
        print(f"\n  [{i+1}] {stage} (prompt ~{prompt_tokens_est}t) ...")

        try:
            response, pt, ct = client.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
            )
            total_prompt_tokens += pt
            total_completion_tokens += ct
            # 原始拼接：直接追加到 context（无截断控制）
            context += f"\n[{stage} 产物]\n{response[:2000]}\n"
            results.append({"stage": stage, "tokens": pt + ct, "output_len": len(response)})
            print(f"    ← {len(response)} 字符 (API: {pt}+{ct}t)")
        except Exception as e:
            print(f"    ✘ 失败: {e}")
            results.append({"stage": stage, "error": str(e)})

    return {
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "total_tokens": total_prompt_tokens + total_completion_tokens,
        "context_final_size": TokenEstimator.estimate(context),
        "results": results,
    }


# ========================================================================== #
# 测试 2: 有上下文工程（ContextManager 70/30 + offload + 三层记忆）
# ========================================================================== #

def run_with_context_engine(client: WorkBuddyClient, workdir: Path) -> dict:
    """有上下文工程：ContextManager 管理预算、offload、三层记忆。"""
    print("\n" + "=" * 60)
    print("【测试 2】有上下文工程（ContextManager 70/30 预算）")
    print("=" * 60)

    import tempfile
    if workdir is None:
        workdir = Path(tempfile.mkdtemp())

    ctx = ContextManager(task_id="ctx-test-001", workdir=workdir, total_budget=32000)
    ctx.set_task_spec(TASK_SPEC)
    ctx.add_context(f"【原始任务】\n{TASK_SPEC}\n", zone="critical")

    total_prompt_tokens = 0
    total_completion_tokens = 0
    results = []

    for i, (stage, description) in enumerate(STAGES):
        if not ctx.start_iteration():
            print(f"  ⚠ 预算不足，跳过 {stage}")
            break

        worker_prompt = ctx.assemble_prompt(
            current_task=f"阶段 {stage}: {description}（标注里程碑: {stage.upper()}_DONE）"
        )
        prompt_tokens_est = TokenEstimator.estimate(worker_prompt)
        print(f"\n  [{i+1}] {stage} (prompt ~{prompt_tokens_est}t, "
              f"budget util: {ctx.budget.utilization:.0%}) ...")

        try:
            response, pt, ct = client.chat(
                model="deepseek-v4-flash",
                messages=[{"role": "user", "content": worker_prompt}],
                max_tokens=300,
            )
            total_prompt_tokens += pt
            total_completion_tokens += ct

            # 信息卸载：大产出 offload 到文件
            ctx.offload_to_file(
                f"# {stage} 产物\n\n{response}",
                prefix=f"stage_{stage}",
            )

            # 记录迭代结果到三层记忆
            ctx.record_iteration_result(
                outcome=f"{stage} 通过",
                decisions=[{"decision": f"完成 {stage}", "justification": "API 返回正常"}],
                improvements=[],
                metrics={"pt": pt, "ct": ct},
            )

            results.append({"stage": stage, "tokens": pt + ct, "output_len": len(response)})
            print(f"    ← {len(response)} 字符 (API: {pt}+{ct}t)")
        except Exception as e:
            print(f"    ✘ 失败: {e}")
            results.append({"stage": stage, "error": str(e)})

        ctx.finish_iteration()

    snapshot = ctx.snapshot()

    return {
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "total_tokens": total_prompt_tokens + total_completion_tokens,
        "context_final_utilization": snapshot["budget"]["utilization"],
        "compact_count": snapshot["budget"]["compact_count"],
        "overflow_count": snapshot["budget"]["overflow_count"],
        "memory_iterations": snapshot["memory"]["medium"]["iteration_count"],
        "memory_retention": snapshot["metrics"]["memory_retention_score"],
        "offloaded_files": len(list(workdir.glob("shared/knowledge/stage_*.md"))),
        "results": results,
    }


# ========================================================================== #
# 主流程
# ========================================================================== #

def main():
    import tempfile

    print("=== 上下文工程 API 对比测试 ===")
    print(f"后端: WorkBuddy (CodeBuddy) v2")
    print(f"模型: {WorkBuddyClient.DEFAULT_MODEL}")

    # 初始化客户端
    print("\n--- 初始化 WorkBuddy API 客户端 ---")
    try:
        client = WorkBuddyClient()
        print(f"✓ 凭据加载成功 ({client.info['uid']})")
    except Exception as e:
        print(f"✘ 凭据加载失败: {e}")
        print("  请确保已安装 CodeBuddy/WorkBuddy 桌面版并已登录")
        return

    # 快速连通性测试
    print("\n--- 连通性测试 ---")
    ok, msg = client.check_connectivity()
    if ok:
        print(f"✓ API 连通: {msg}")
    else:
        print(f"✘ API 不通: {msg}")
        return

    # 运行对比测试
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)

        # 测试 1: 无上下文工程
        t0 = time.time()
        result_no_ctx = run_no_context_engine(client)
        time_no_ctx = time.time() - t0

        # 测试 2: 有上下文工程
        t0 = time.time()
        result_with_ctx = run_with_context_engine(client, workdir)
        time_with_ctx = time.time() - t0

        # ---- 对比报告 ----
        print("\n" + "=" * 60)
        print("【对比报告】")
        print("=" * 60)

        print(f"\n{'指标':<25} {'无上下文工程':>15} {'有上下文工程':>15} {'变化':>10}")
        print("-" * 65)

        no_total = result_no_ctx["total_tokens"]
        with_total = result_with_ctx["total_tokens"]
        change = (with_total - no_total) / no_total * 100 if no_total > 0 else 0

        print(f"{'API Prompt Tokens':<25} {result_no_ctx['total_prompt_tokens']:>15,} "
              f"{result_with_ctx['total_prompt_tokens']:>15,} {change:>+9.1f}%")
        print(f"{'API Completion Tokens':<25} {result_no_ctx['total_completion_tokens']:>15,} "
              f"{result_with_ctx['total_completion_tokens']:>15,}")
        print(f"{'API Total Tokens':<25} {no_total:>15,} {with_total:>15,} {change:>+9.1f}%")
        print(f"{'耗时':<25} {time_no_ctx:>14.1f}s {time_with_ctx:>14.1f}s")

        # 上下文工程特有指标
        print(f"\n{'上下文工程指标':<25} {'值':>15}")
        print("-" * 40)
        print(f"{'Context 利用率':<25} {result_with_ctx.get('context_final_utilization', 0):>14.1%}")
        print(f"{'压缩次数':<25} {result_with_ctx.get('compact_count', 0):>15}")
        print(f"{'溢出次数':<25} {result_with_ctx.get('overflow_count', 0):>15}")
        print(f"{'记忆迭代数':<25} {result_with_ctx.get('memory_iterations', 0):>15}")
        print(f"{'记忆留存率':<25} {result_with_ctx.get('memory_retention', 0):>14.1%}")
        print(f"{'Offload 文件数':<25} {result_with_ctx.get('offloaded_files', 0):>15}")

        # 阶段对比
        print(f"\n{'阶段':<15} {'无ctx tokens':>13} {'有ctx tokens':>13} {'差异':>8}")
        print("-" * 50)
        for i, (nr, wr) in enumerate(zip(result_no_ctx["results"], result_with_ctx["results"])):
            nt = nr.get("tokens", 0)
            wt = wr.get("tokens", 0)
            diff = wt - nt
            stage = nr.get("stage", f"stage_{i}")
            print(f"{stage:<15} {nt:>13,} {wt:>13,} {diff:>+8,}")

        # 结论
        print(f"\n{'='*60}")
        if change < 0:
            print(f"✅ 上下文工程减少了 {abs(change):.1f}% 的 API token 消耗")
        elif change < 10:
            print(f"📊 上下文工程 token 消耗持平 ({change:+.1f}%)，但提供了记忆持久化和预算控制")
        else:
            print(f"⚠ 上下文工程增加了 {change:.1f}% 的 token 消耗（首次运行需要建立记忆）")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()