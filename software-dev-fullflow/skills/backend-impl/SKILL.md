---
name: backend-impl
description: 按设计契约实现服务器能力（POST/GET 接口 + 数据存储 + 启动脚本），支撑带服务器的网站场景。触发词：后端、接口、POST、服务器、api、数据存储、backend。
assign_when: 后端开发（Backend）在搭建模式下，需要实现服务器接口与数据落地时分配。
---

# Skill: backend-impl

按 `design.md` 的接口契约 + 数据模型，从零实现**可真实运行**的服务器能力，产出启动脚本，保证下游 tester 能起服务验证。**写真实可运行代码，不写占位。**

## 输入

- `design.md`（接口契约：POST/GET 路径、请求/响应、数据字段）。
- 技术栈约定（由 architect 在 design.md 给出）。

## 执行步骤

1. **实现接口**：按契约实现 POST 接口（请求解析 → 校验 → 处理 → 响应）。
2. **数据落地**：实现数据存储（内存 / JSON 文件 / 轻量 DB），确保数据真实写入可查。
3. **启动脚本**：产出 `server.py`（或 `run.sh`），指定端口，`python server.py --port 8080` 即可起服务。
4. **边界处理**：空输入、非法请求、并发、异常兜底，不 500 崩溃。
5. **真实运行自检**：起服务 → curl POST 打真请求 → 验证返回 + 数据写入。
6. **产出**：代码 + 启动脚本写入 `shared/tasks/{id}/backend/`。

## 输出（BACKEND_READY）

```json
{
  "task_id": "T-0001",
  "endpoints": [{"method": "POST", "path": "/api/submit", "status": 200}],
  "storage": "data.json",
  "start_command": "python server.py --port 8080",
  "self_check": {"start": "ok", "post_ok": "ok", "data_persisted": "ok"},
  "status": "BACKEND_READY"
}
```

## 依赖工具

- L1 基座：`evidence-log`、`umodel-query`。
- 运行时：Python 标准库 http.server（无重依赖）。

## 失败处理

- 起服务失败 / POST 不通 → 修正重试，最多 N 次。
- 仍失败 → 输出 `BACKEND_FAILED` + 原因，交 Manager 决定换技术栈或人工介入。

## 安全边界

- 运行在 Worker 自己沙箱容器内，不触碰宿主机。
- 用户输入做基本校验/转义，防注入。
- 敏感数据不落明文；只写 `shared/tasks/{id}/backend/`。

## 里程碑

- 输出：`BACKEND_READY`（交接 Tester 真实验证）。
- `BACKEND_FAILED` → 通知 Manager。
