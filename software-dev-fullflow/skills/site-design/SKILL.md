---
name: site-design
description: 基于「从零搭建」任务，产出可执行的系统设计文档（页面架构 + API 路由 + 数据模型 + 技术栈），作为下游开发输入契约。触发词：搭建、建站、设计网站、architect、从零实现、design。
assign_when: 架构设计师（Architect）在搭建模式下，需要把任务转化为系统设计契约时分配。
---

# Skill: site-design

基于搭建任务描述 + 验收标准，产出 **design.md**（结构化设计契约），供前端/后端开发作为输入实现。参考 MetaGPT「结构化产物即契约」思想，防需求漂移。

## 输入

- 搭建任务描述（Manager 下发）+ 验收标准。
- 若涉及服务器能力（POST/数据库），需识别并纳入接口契约。

## 执行步骤

1. **需求拆解**：把任务拆成页面/模块清单 + 功能点。
2. **页面架构**：定义静态页面清单（首页/关于/产品等）+ 导航结构。
3. **接口契约**：定义 POST/GET 接口（路径、方法、请求体、响应体、错误码）。**服务器能力必须在这里显式标注**。
4. **数据模型**：定义表单提交/存储的数据字段 + 存储方式（内存/文件/轻量 DB）。
5. **技术栈**：选轻量可落地方案（Python http.server / FastAPI / Node Express），避免重依赖。
6. **启动方式**：约定如何把站点跑起来（入口文件/命令/端口）。
7. **产出**：`design.md` 写入 `shared/tasks/{id}/design.md`。

## 输出（DESIGN_READY）

```json
{
  "task_id": "T-0001",
  "pages": ["index.html", "about.html", "contact.html"],
  "apis": [{"method": "POST", "path": "/api/submit", "request": {...}, "response": {...}}],
  "data_model": {"fields": ["name", "message"], "storage": "file"},
  "stack": "python http.server + 静态页",
  "run_command": "python server.py --port 8080",
  "status": "DESIGN_READY"
}
```

## 依赖工具

- L1 基座：`evidence-log`、`umodel-query`（读共享数据模型）。

## 失败处理

- 任务描述含糊 → 先向 Manager 确认验收标准，再设计。
- 接口契约无法确定 → 明确标注待定项，不臆造。

## 安全边界

- 只写设计文档，**不写实现代码**。
- 接口契约遵循最小原则，不引入不必要的后端能力。
- 敏感数据（用户密码等）在设计时即标注需加密/不落明文。

## 里程碑

- 输出：`DESIGN_READY`（交接前端/后端开发）。
