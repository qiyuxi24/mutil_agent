---
name: evidence-check
description: 验收前对「被引用的证据」做确定性预检——源文件必须存在，且被引用的数字/字符串确实出现在源中。用于拦截幻觉证据（例如"支持依据：results/eval.json 显示 73.2"），零模型调用、免费、fail-closed。适用于任何需要引用测试结果/评估数字/产物文件作为证据的验收、评审、复盘环节。
assign_when:
  - 需要在报告或评审中引用具体的测试/评估结果数字
  - 评审前需要机械核对被引用的证据文件是否存在、数值是否真实在源中
  - 复盘时引用里程碑产物（测试报告、评估输出）作为经验依据
scripts:
  - 无（由 src/loop/evidence_check.py 提供 CLI：python -m loop.evidence_check）
---

# Evidence Check — 证据预检

## 用途
在花费跨模型评审之前，先机械校验被引用的证据是否真实存在，拦截「幻觉证据」。

两阶段门：
- **stage 1（本 Skill）**：确定性。路径存在 + 数字/字符串确实在源中。零模型、免费、fail-closed（宁可漏报，绝不产生虚假 verified）。
- **stage 2（评审团）**：跨模型评审，拦截「真实但错误」——数字确实在文件里，但它并不支持该声明。

`verified` 只表示「被引用的证据存在」，并不表示「声明成立」。

## 使用方式
```bash
# 在 src/ 目录下运行（src/ 为 loop 包根，惯例同 run.py）
cd software-dev-fullflow/src
..\demo\.venv\Scripts\python.exe -m loop.evidence_check <root> --value 73.2 --source results/eval.json
# 批处理（JSON：[{value, source, id?}]）
..\demo\.venv\Scripts\python.exe -m loop.evidence_check <root> --batch claims.json
```
- 退出码：全部 verified → 0；存在 path_missing / value_not_found → 1。
- `source` 支持相对 `<root>` 的文件路径或 glob（`results/*.json`）。
- 编程调用：`from loop.evidence_check import check_claim, check_batch`。

## 数字匹配策略（刻意保守）
- 纯数字：与文本中**安全边界内**的数字 token 做精确 Decimal 比较，支持整数/小数/千分位/科学计数/尾随 %，且 % 标志必须一致。
- 复合构造（日期/时间/版本/分数/本地化分组、Unicode 分隔符）→ **fail-closed** 交给评审团，绝不产生 false verified。
- 非数字（如 "SOTA on COCO"）：归一化空白后做子串匹配。

## 判定流转
| status | 含义 | 处理 |
|---|---|---|
| `verified` | 引用的证据确实存在于源中 | 继续流程 |
| `path_missing` | 源文件/glob 不存在 | 打回：修正引用或补齐产物 |
| `value_not_found` | 文件在但值不在其中 | 打回重测；或交评审团 |
| `unparseable` | 声明缺 (value, source) | 交评审团 |

## 验收标准
- `tests/test_evidence_check.py` 全 PASS（8 类契约：path_missing / value_not_found / 数字与字符串命中 / 0 与 unparseable / glob / 复合构造 fail-closed / batch summary / CLI 退出码）。
