---
name: deploy-runtime
description: 把搭建完成的站点部署到可访问地址 + 健康检查 + 回滚预案，确保「站点真的能访问」。触发词：部署、上线、起服务、访问、deploy、健康检查。
assign_when: 部署员（Deployer）在搭建模式下，需要把站点部署到可访问地址并验证可达时分配。
---

# Skill: deploy-runtime

把 frontend/backend 的站点产物启动到一个**可访问地址**，做健康检查（静态页 200 + POST 通），产出带访问 URL 的部署报告 + 回滚预案。解决「搭建类任务交付的最后一公里」。

## 输入

- frontend/backend 的站点产物（`shared/tasks/{id}/site/` + `backend/`）。
- 启动命令（architect 在 design.md 约定，backend 产出）。

## 执行步骤

1. **定位产物**：确认静态页 + 后端启动脚本存在。
2. **起服务**：启动站点到可访问地址（本地端口 / 静态托管），记录访问 URL。
3. **健康检查**：
   - `curl -s -o /dev/null -w "%{http_code}" <url>/` 期望 200。
   - `curl -X POST <url>/api/submit -H "Content-Type: application/json" -d '{"name":"t","message":"m"}'` 期望 200。
4. **回滚预案**：记录停止服务/恢复上一版本的命令。
5. **产出**：部署报告 `shared/tasks/{id}/deploy-report.md`（访问 URL + 部署方式 + 回滚预案）。

## 输出（DEPLOYED）

```json
{
  "task_id": "T-0001",
  "url": "http://localhost:8080",
  "health_check": {"get_200": true, "post_200": true},
  "rollback": "停止服务并恢复上一版本",
  "status": "DEPLOYED"
}
```

## 依赖工具

- L1 基座：`evidence-log`。
- 运行时：`curl`、Python 启动进程。

## 失败处理

- 服务起不来 / 静态页非 200 / POST 不通 → 反馈打回对应开发角色（附具体失败点）。
- 端口占用 → 换端口重试。

## 安全边界

- 部署在 Worker 沙箱容器内，不开放外网。
- 端口限定本地，不暴露到公网。
- 只写 `shared/tasks/{id}/`，不触碰宿主环境。

## 里程碑

- 输出：`DEPLOYED`（含访问 URL，通知 HR 项目可收尾）。
