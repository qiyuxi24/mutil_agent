# ARIS 高价值资产迁移计划（多窗口并行版）

> 制定日期：2026-08-31　**✅ 全部 7 批次已完成（2026-08-31）**
> 上游仓库：`Auto-claude-code-research-in-sleep`（上交大 Ruofeng Yang / ARIS，82 skills）
> 目标：把 ARIS 中对我们「多 Agent 软件研发团队系统」有补位价值的确定性工具与协议，分批迁移进 `software-dev-fullflow`。
> 方式：**批次 1–6 可在 6 个窗口并行执行，批次 7（集成）必须等前 6 批完成**。
> 最终验证：全量 `pytest tests/ -q` → **387 passed + 12 skipped**（基线 207 零回归）；`verify-skill-refs.py` → 29 skill 全 PASS；mock 闭环 6/6 里程碑完整。

---

## 0. 结论回顾（为什么迁这些）

| # | ARIS 资产 | 对我们的价值 | 补位的短板 |
|---|-----------|--------------|------------|
| 1 | `tools/evidence_check.py` | 确定性证据预检，零模型调用，防「幻觉证据」 | Tester 自报"73.2% 通过"可能是编的，evidence-log 只记事件不校验引用 |
| 2 | `tools/threat_scan.py` | 上下文注入/外泄扫描（regex 层） | copaw guard 只防执行侧，不防喂给 LLM 的上下文被污染 |
| 3 | `tools/iteration_log.py` | 无人值守停滞检测 → 强制结构性转向 | loop 缺"跑不动怎么办"，只会重试 |
| 4 | `tools/review_gate.py` | 跨模型评审路由的**可执行**状态转移表 | 我们有"跨模型评审"概念，但没有可测试的 stop/continue/escalate 裁决表 |
| 5 | `shared-references/experiment-integrity.md` 等协议 | 防假数据/伪造归一化/幽灵结果 | 测试验收数据可信度准则 |
| 6 | `done ≠ accepted` 语义（resumable-runs） | 验收与执行硬分离 | SOUL.md 写了准则，代码层没有强制 |

---

## 1. 总览表

| 批次 | 内容 | 新建文件（独占） | 依赖 | 建议窗口 |
|------|------|------------------|------|----------|
| 1 | 证据预检 Evidence Check | `src/loop/evidence_check.py` + `tests/test_evidence_check.py` + `skills/evidence-check/` | 无 | 窗口 A |
| 2 | 注入扫描 Threat Scan | `src/loop/threat_scan.py` + `tests/test_threat_scan.py` + `skills/injection-scan/` | 无 | 窗口 B |
| 3 | 停滞检测 Iteration Log | `src/loop/iteration_log.py` + `tests/test_iteration_log.py` + `skills/stall-detection/` | 无 | 窗口 C |
| 4 | 评审路由 Review Gate | `src/loop/review_gate.py` + `tests/test_review_gate.py` + `skills/review-gate/` | 无 | 窗口 D |
| 5 | 完整性协议沉淀 | `skills/evidence-integrity/SKILL.md`（+ 可选 references 摘要） | 无 | 窗口 E |
| 6 | 验收门 Acceptance Gate | `src/loop/acceptance_gate.py` + `tests/test_acceptance_gate.py` | **零依赖**（内嵌 family 推导，不 import 批次 4） | 窗口 F |
| 7 | 集成（单窗口） | 改 6 类**共享文件**（见 §7） | 1–6 全部完成 | 窗口 G（最后） |

> ⚠️ **并行安全规则**：批次 1–6 只允许创建自己名下的新文件，**绝不修改任何已有文件**（尤其 `workers.yaml` / `agentteams_loop.py` / `state.py` / `evaluation.py` / `__init__.py` / SKILL-LIST 等共享文件）。共享文件的改动全部集中在批次 7，避免多窗口写同一文件。

---

## 2. 批次 1 · 证据预检（窗口 A）

**源**：`Auto-claude-code-research-in-sleep/tools/evidence_check.py`（213 行，纯标准库）
**目标**：`src/loop/evidence_check.py`（新建）

移植要点：
- 完整保留核心：`_NUM_CORE` / `_NUM_TOKEN_RE` / `_WS_GROUP_TAIL` / `_WS_GROUP_LEAD` / `_GROUP_TAIL_TOK` / `_PURE_NUMBER_RE` / `_dec` / `_pure_number` / `_value_in_text` / `_resolve_sources` / `check_claim` / `check_batch` / `main()`。
- 数字匹配策略必须原样保留（ALLOW-LIST fail-closed，绝不产生 false verified）。这是本模块的灵魂，不要"优化"。
- 修改点：文件头 docstring 改为适配"AI 研发团队"语境（证据=任务产物文件），其余逻辑不动。
- `__all__ = ["check_claim", "check_batch"]`。

**测试**：`tests/test_evidence_check.py`（新建），至少覆盖：
1. `path_missing`：引用的源文件不存在
2. `value_not_found`：文件存在但值不在其中
3. `verified`：数字（整数/小数/千分位/科学计数/尾随%）与普通字符串命中
4. 数字 0 能正常检查（`value is None` 才 unparseable，0 不跳过）
5. glob 源（`results/*.json`）命中
6. 复合构造 fail-closed：日期 `2024-05-30` / 版本 `1.2.3` / 时间戳，不误判 verified
7. `check_batch` 的 summary 统计
8. `main()` CLI：`--value/--source` 与 `--batch` 退出码

**Skill**：`skills/evidence-check/SKILL.md`（新建，frontmatter 对齐现有规范：name/description/assign_when）。描述：验收前对"被引用的证据"做确定性预检，路径存在 + 数字/字符串确实在源里，失败则打回重测。

**验证**：`cd software-dev-fullflow && demo\.venv\Scripts\python.exe -m pytest tests/test_evidence_check.py -q` 全 PASS。

---

## 3. 批次 2 · 注入扫描（窗口 B）

**源**：`Auto-claude-code-research-in-sleep/tools/threat_scan.py`（223 行，纯标准库）
**目标**：`src/loop/threat_scan.py`（新建）

移植要点：
- 完整保留 `_PATTERNS`（all/context/strict 三层）、`INVISIBLE_CHARS`、`_compile`、`scan_for_threats`、`first_threat_message`、`quarantine`、`main()`。
- 调整：模式中 ARIS 专属路径（`.aris/installed-skills.txt` / `skill-source.txt`）改为我们的路径（`skills/` 安装清单），其余（CLAUDE.md / AGENTS.md / MEMORY.md / .cursorrules 等）保留。
- `__all__ = ["INVISIBLE_CHARS", "scan_for_threats", "first_threat_message", "quarantine"]`。

**测试**：`tests/test_threat_scan.py`（新建），至少覆盖：
1. `prompt_injection` / `sys_prompt_override` / `hidden_div` / `deception_hide`（all 层）
2. `role_hijack` / `remove_filters` / `fake_update`（context 层）
3. `c2_node_registration` / `c2_explicit`（context 层）
4. `read_secrets` / `ssh_backdoor` / `hardcoded_secret`（strict 层）
5. 隐形 Unicode 命中 `invisible_unicode_U+XXXX`
6. clean 内容返回空
7. `quarantine` 返回占位符 + findings，原始文本不被注入
8. scope 三层叠加正确（all ⊂ context ⊂ strict）

**Skill**：`skills/injection-scan/SKILL.md`（新建）。描述：对要注入 agent 上下文的第三方内容（web 抓取/社区技能/MEMORY 写入）做 regex 威胁扫描，命中则隔离。

**验证**：`demo\.venv\Scripts\python.exe -m pytest tests/test_threat_scan.py -q` 全 PASS。

---

## 4. 批次 3 · 停滞检测（窗口 C）

**源**：`Auto-claude-code-research-in-sleep/tools/iteration_log.py`（144 行，纯标准库）
**目标**：`src/loop/iteration_log.py`（新建）

移植要点：
- 保留 `PIVOT_STRUCTURAL_AT=2` / `ESCALATE_HUMAN_AT=4` / `pivot_for` / `note` / `show` / `_log_path` 的 run_id 防逃逸校验（`[A-Za-z0-9-_.]`）。
- `_lock` 保留 try/except `fcntl`（Windows 无 fcntl 时静默退化，项目在 Windows 上跑，加注释说明）。
- 调整：侧车文件路径从 `.aris/runs/<run_id>.iterations.jsonl` 改为 `src/data/shared/runs/<run_id>.iterations.jsonl`（与现有 `src/data/shared/` 产物目录一致）。

**测试**：`tests/test_iteration_log.py`（新建），至少覆盖：
1. `note` 有 findings（>0）时 stale_count 归零
2. 连续 0 findings：2 次 → `structural`，4 次 → `human`
3. 中间插入一次 >0 后 stale 重置
4. `new_findings < 0` 抛 ValueError
5. `show` 回读全部记录
6. run_id 非法（`../`、含 `/`、空）抛 ValueError
7. `pivot_for` 边界（0/1→none，2/3→structural，≥4→human）
8. append-only：不覆盖历史行

**Skill**：`skills/stall-detection/SKILL.md`（新建）。描述：Leader 每轮迭代记录新发现数，连续 0 新发现触发结构性转向（≥2）或上报人类（≥4）。

**验证**：`demo\.venv\Scripts\python.exe -m pytest tests/test_iteration_log.py -q` 全 PASS。

---

## 5. 批次 4 · 评审路由（窗口 D）

**源**：`Auto-claude-code-research-in-sleep/tools/review_gate.py`（503 行，标准库 + 一个外部可选依赖）
**目标**：`src/loop/review_gate.py`（新建）

移植要点：
- **保留**：`KNOWN_FAMILIES`（13 家族）/ `POSITIVE_VERDICTS` / `VALID_BACKENDS` / `VALID_VERDICTS` / `derive_model_family`（正则推导，含 qwen/deepseek/glm/kimi 等中文厂商）/ `Transition` dataclass / `evaluate_transition`（codex / manual / llm-chat / oracle-pro / agy 路径 + 同族拒绝 + score 1..10 校验 + `requires_external_acquittal` 终审器语义）。
- **剥离**：`copilot-native` / `copilot` 两条路径及 `load_native_evidence`、`NativeEvidence`、对 `copilot_native_evidence.py` 的 ImportError——我们没有 Copilot 集成，保留会制造死代码。`VALID_BACKENDS` 去掉 `copilot-native`，保留 `copilot` 与否自行判断（建议也去掉，避免误导）。
- 调整：docstring 改为"跨模型评审路由裁决表"，去掉 ARIS/Copilot 语境。
- 核心语义保留：**同族评审不能终结**（executor family == reviewer family → `review_unavailable`/`failed`）；`score >= 6 && verdict ∈ {ready, almost}` 才算 positive。

**测试**：`tests/test_review_gate.py`（新建），至少覆盖：
1. `derive_model_family`：`deepseek-v4-flash`→deepseek、`qwen2.5-72b`→qwen、`gpt-4o`→openai、`claude-sonnet-4`→anthropic、未知→unknown
2. llm-chat 跨族 positive → `stop`
3. llm-chat 同族 → `review_unavailable`（failed）
4. 分数 <6 或 verdict=not ready → `continue`（同后端）
5. 非法 backend / 非法 verdict / score 越界 → `review_unavailable`
6. codex / agy / oracle-pro 无 acquittal 义务且 positive → `stop`
7. 终审器语义：requires_external_acquittal 下同族 → failed；跨族 positive → stop
8. manual 缺 identity → review_unavailable；有 identity 且跨族 → stop

**Skill**：`skills/review-gate/SKILL.md`（新建）。描述：评审裁决表——只有跨模型家族的正向判定才能终结验收；同族自评只能 continue，卡住时 escalate。

**验证**：`demo\.venv\Scripts\python.exe -m pytest tests/test_review_gate.py -q` 全 PASS。

---

## 6. 批次 5 · 完整性协议沉淀（窗口 E）

**源**（`Auto-claude-code-research-in-sleep/skills/shared-references/`）：
- `experiment-integrity.md`（核心）
- `acceptance-gate.md`（done≠accepted）
- `injection-hygiene.md`（与批次 2 呼应）
- `evidence-precheck.md`（与批次 1 呼应）
- `reviewer-independence.md`（与批次 4 呼应）
- `reviewer-routing.md`（补充）

**目标**：`skills/evidence-integrity/SKILL.md`（新建）——把上述协议浓缩为适合本项目的**验收数据可信度准则**，包括：
1. 禁止伪造 ground truth；禁止用归一化到自身 max 的分数冒充绝对值（0.99 陷阱）
2. 禁止幽灵结果（引用不存在的文件）；验收前必须过批次 1 证据预检
3. done ≠ accepted：执行者不能给自己验收，验收必须有跨族评审（批次 4）
4. 注入 hygiene：第三方内容进上下文前必须过批次 2 扫描
5. 挂载建议：Tester（验收前）、Releaser（发布门禁）、Leader（编排时）阅读

可另建 `references/theory/ARIS-INTEGRITY-PROTOCOLS.md` 存原文摘要对照（可选，不建也不影响）。

**验证**：无代码，人工 review frontmatter 与内容；跑一次 `scripts/verify-skill-refs.py` 确认格式无碍（本批次不动 workers.yaml，所以该脚本结果不变）。

---

## 7. 批次 6 · 验收门（窗口 F）

**目标**：`src/loop/acceptance_gate.py`（新建）+ `tests/test_acceptance_gate.py`（新建）

设计（**零依赖，不 import 批次 4 的 review_gate**）：
- 内嵌一份极简 `derive_family(model)`（覆盖 deepseek/qwen/openai/anthropic/unknown 即可，注释说明与 review_gate.derive_model_family 对齐、后续可统一）。
- 提供 `accept(claim, executor, reviewer, verdict_id)`：
  - 校验：`verdict_id` 非空且以 `review-` 开头（对应现有 audit 习惯）；
  - 校验：`reviewer != executor` 且 `derive_family(reviewer) != derive_family(executor)`（同族拒绝）；
  - 校验：`reviewer != "self"` / `executor` 不能验收自己；
  - 通过返回 `{"accepted": True, "verdict_id": ...}`，失败返回 `{"accepted": False, "reason": ...}`（fail-closed）。
- 与现有 `ApprovalManager`（人工审批）互补：`acceptance_gate` 管"跨模型评审验收"，`ApprovalManager` 管"人工审批"，两者接口不同、互不修改。
- 纯函数 + dataclass，无 IO，方便单测。

**测试**：`tests/test_acceptance_gate.py`（新建）：
1. 跨族 reviewer 正向 → accepted
2. 同族（deepseek vs deepseek）→ rejected
3. 执行者自评 → rejected
4. verdict_id 缺失/格式错 → rejected
5. 空 reviewer / executor → rejected
6. fail-closed：任何异常参数不抛错、返回 rejected

**验证**：`demo\.venv\Scripts\python.exe -m pytest tests/test_acceptance_gate.py -q` 全 PASS。

---

## 8. 批次 7 · 集成（窗口 G，单窗口，须最后做）

前 6 批完成后，由**一个窗口**统一改以下共享文件（逐一、增量、向后兼容）：

1. **`src/agentteams/workers.yaml`**：按角色挂载新 skill
   - `tester`：+ `evidence-check`（验收前证据预检）、+ `review-gate`（裁决表）
   - `releaser`：+ `review-gate`、+ `evidence-integrity`
   - `leader`：+ `stall-detection`（停滞转向）、+ `evidence-integrity`
   - `aggregator`：+ `injection-scan`（外部需求/抓取内容入库前扫描）
   - 具体哪些 worker 挂哪些 skill 以 `skills/ASSIGNMENT-MATRIX.md` 现有约定为准，逐行确认。
2. **`skills/SKILL-LIST.md`**：追加 5 个新 skill 条目（evidence-check / injection-scan / stall-detection / review-gate / evidence-integrity）。
3. **`skills/REGISTRY.md`**：登记新 skill。
4. **`skills/ASSIGNMENT-MATRIX.md`**：更新挂载矩阵。
5. **`src/loop/__init__.py`**：导出新模块 `EvidencePrecheck`（或 `check_claim/check_batch`）、`scan_for_threats/quarantine`、`note/pivot_for`、`evaluate_transition`、`acceptance_gate` 相关符号。**保持向后兼容**：只新增 import，不删旧导出。
6. **`src/loop/agentteams_loop.py`**：三处增量接入（每处都做成可选、默认不改变现有行为）：
   - Tester 阶段（`TESTING`/milestone 产出后）：如存在 `evidence-check` 引用，先跑 `check_batch` 预检，未过打回 `TEST_FAILED`；
   - 循环顶部：每轮调 `iteration_log.note(...)`，`pivot == "structural"` 时打印转向提示，`pivot == "human"` 时打印上报人类（**只提示不硬改流程**，避免破坏 207 passed 基线）；
   - 验收/评审环节：如启用了跨模型评审，用 `evaluate_transition` 替换硬编码的"通过/不通过"判断（保持默认路径不变）。
   - ⚠️ 修改前必须 `read_file` 重新确认当前内容（该文件历史上被多会话改写过）。
7. **`src/loop/evaluation.py`（可选）**：仅当确认不影响现有 score 契约时，把 `review-gate` 的裁决接入跨模型评审路径。

**回归验收**：
- 全量：`demo\.venv\Scripts\python.exe -m pytest tests/ -q` → **基线 207 passed + 12 skipped 无回归**（新增测试并入后总数增加）。
- 引用核对：`python scripts/verify-skill-refs.py` → PASS。
- 单文件 sanity：`python -c "from loop import AgentTeamsLoop, ...新符号"` 可导入。

---

## 9. 执行顺序与窗口建议

```
窗口 A ─ 批次 1 ┐
窗口 B ─ 批次 2 │
窗口 C ─ 批次 3 ├─ 并行（互不依赖、文件不重叠）─→ 批次 7（窗口 G 单窗口集成）
窗口 D ─ 批次 4 │
窗口 E ─ 批次 5 │
窗口 F ─ 批次 6 ┘
```

- 批次 1–6 可同开 6 个窗口；每个窗口只动自己名下的新文件。
- 批次 7 必须等 1–6 完成后单独开窗口做，避免 `workers.yaml`/`agentteams_loop.py`/`__init__.py` 等共享文件被多窗口同时写。
- 每批完成后在 TODO.md 对应条目打勾 + 记录验证命令输出（沿用项目惯例）。
- 若某窗口发现上游源文件与本计划描述不符，以源文件为准并在批次内适配，同时记录差异。

---

## 10. 工作量估算（每批独立窗口）

| 批次 | 预计 | 风险 |
|------|------|------|
| 1 | 2–4 h | 低（逻辑照搬，测试面大） |
| 2 | 1.5–3 h | 低（纯正则） |
| 3 | 1–2 h | 低（逻辑简单） |
| 4 | 2–4 h | 中（剥离 copilot 分支需仔细） |
| 5 | 1–2 h | 低（纯文档） |
| 6 | 1–2 h | 低 |
| 7 | 3–5 h | **高**（共享文件，需全量回归 207+） |
