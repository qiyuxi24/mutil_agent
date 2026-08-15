---
name: umodel-rca
description: 在 UModel 研发对象图上做模型引导的自主根因分析：沿任务→缺陷→根因→补丁的关系链收集证据、排除干扰项、推理到根因。触发词：根因、root cause、RCA、为什么慢、为什么挂、缺陷定位、告警定位、SLO 击穿。
assign_when: 根因定位员（RootCause）需要在 UModel 统一对象图上做模型引导的根因分析（替代纯文本/纯搜索定位）时分配。
---

# Skill: umodel-rca

在 UModel 对象图上做**模型引导的自主根因分析**。用方法而非脚本：让证据决定下一步查询，保持竞争假设存活，并用对象图/指标/日志来源引用每个结论。

> 官方技能全文：`references/refs/unified-model/skills/umodel-rca/SKILL.md`（本项目为官方技能的研发域定制）。

## 前置

先加载 `umodel-query`（提供 `.entity` / `.topo` / `.umodel` 读取面），并完成其 Setup。

## 输入

- 目标缺陷 / 症状实体 id（`dev.defect` 或 `dev.task`）。
- UModel workspace 名。

## RCA Loop（对齐官方 6 步）

1. **Orient（定位）**：`.entity with(domain='dev', name='dev.defect', query='<id or symptom>')`，读缺陷字段（severity/status/description）。
2. **Characterize（表征）**：沿 `dev.task ──produces──> dev.defect` 确认任务上下文，读 `dev.defect ──analyzed_by──> dev.root_cause` 已有分析。
3. **Hypothesize（假设）**：基于缺陷类型生成 2-3 个根因候选（空指针/并发/资源泄漏/配置/逻辑）。
4. **Gather Evidence（跨域取证）**：沿关系链遍历——`.topo with(domain='dev', src='dev.defect', link='analyzed_by')`、查历史同类 `dev.retrospective`（`enriches` 反哺）、关联 `dev.worker` 分工。
5. **Correlate（关联排除）**：用时间线/证据排除干扰项（最近但无关的改动不是因果）。
6. **Conclude（结论）**：产出诊断（Symptom / Timeline / Root cause / Causal chain / Ruled out / Confidence）。

## 输出（ROOT_CAUSE_FOUND）

```markdown
## Diagnosis
Symptom: <缺陷量化影响>
Timeline: | Time | Evidence | Source |
Root cause: <一句话触发点 + 机制>
Causal chain: 1.触发 2.放大 3.饱和 4.用户可见影响
Ruled out: <候选>: <为何排除 + 来源>
Confidence: high|medium|low because <证据强度与缺口>
```

## 依赖工具

- L1：`umctl`（读实体/拓扑/模型）。
- MCP：`umodel`（复赛环境）。
- 关联：`umodel-query`（读取面）、`root-cause-analysis`（产出 RCA Report 文件）。

## 失败处理

- 证据不足 → `ROOT_CAUSE_FOUND` 换成 `INCONCLUSIVE`（疑似根因 + 置信度 + 需补充证据），交 Manager 决策。
- 误判 → Tester 验证闸门反向打回（闭环回滚），重新定位。

## 安全边界

- **只读**，推荐修复但不执行回滚/重启/改配置。
- 涉及安全漏洞的根因，脱敏后入知识库。

## 里程碑

- 输出：`ROOT_CAUSE_FOUND`（交接 Fixer）。
- `INCONCLUSIVE` → 通知 Manager。

## 关联 Skill

- `umodel-query`（读取基础）。
