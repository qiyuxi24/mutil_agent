# vendor/aris — 上交大 ARIS 长时间工作管理模块（原封不动引入）

## 来源

- 仓库：`Auto-claude-code-research-in-sleep`（工作区同级目录）= 上交大 Ruofeng Yang（SJTU）的
  [ARIS-in-AI-Offer](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep)
- 原始路径：`tools/run_state.py` + `tools/provenance.py`
- 引入日期：2026-08-31
- **约定：本目录内文件一字不改（原封不动）**。融合/改造请放到 `src/` 下新模块，
  以本项目现有规范（`src/loop/run_state.py` 等）重写，禁止直接在此目录内修改。

## 组件说明

### run_state.py — 可恢复运行状态机（长任务核心）

- 把一次长运行建模为**有序 phase 列表**，状态两层分离：
  - executor 可写：`pending / running / done / failed / skipped`
  - 验收态（只有 reviewer 可写）：`accepted`（需 verdict_id + reviewer）、`provisional`
- `resume_point()` 前向解析到第一个非终态阶段；`done` 但未 `accepted` = resume 目标（补验收）
- 存储 `<root>/.aris/runs/<run_id>.json`，flock + 原子写，单写者契约
- 原则：**loop 可以 DRIVE 恢复，不能 ACQUIT（自我验收）自己**

### provenance.py — 出处即授权（跨模型验收）

- `stamp()`：跨模型验收（author/reviewer 必须不同 family，或 `deterministic:<verifier>`）
- `stamp_provisional()`：同族评审（可推进但不算正式验收）
- `model_family()`：模型名 → family 映射（fails closed on collision）
- `is_auto_curatable()`：只有带 accepted 且 content_hash 未变的机器产物可被自动改

## 用法（原样调用，不改这两文件）

```bash
# 状态机：创建 run → 推进 → 验收 → 恢复
python vendor/aris/run_state.py start <root> <run_id> --phases a,b,c --executor claude
python vendor/aris/run_state.py set    <root> <run_id> <phase> done --artifact <path>
python vendor/aris/run_state.py accept <root> <run_id> <phase> --verdict-id <vid> --reviewer codex
python vendor/aris/run_state.py resume <root> <run_id>   # 输出第一个未终态 phase

# 出处：跨模型验收
python vendor/aris/provenance.py check --author claude-sonnet --reviewer codex
python vendor/aris/provenance.py stamp --target <artifact> --author claude-sonnet \
    --reviewer codex --verdict-id <trace-id>
```

Python API：`sys.path` 指向本目录后 `from run_state import start_run, set_status, accept, resume_point`。

## 与本项目的接入点（doc-manager Worker）

- `skills/doc-management/SKILL.md` 引用本目录模块管理**文档任务**的多阶段状态
  （大纲→初稿→评审→定稿→归档），`accepted` 由确定性验证（脚本/检查）或跨模型评审写入。
