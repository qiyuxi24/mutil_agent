#!/bin/bash
# apply-security-in-container.sh
# 在 copaw worker 容器内执行：把 /tmp/security-config.json 的 security 段合并进 config.json，
# 并追加该 Worker 专属的敏感文件绝对路径（providers.json / config.json / .copaw.secret）。
# 由宿主机 scripts/apply-security-config.ps1 编排（docker cp + docker exec）。
# 容器内 config.json 路径：/root/.copaw-worker/<worker_name>/.copaw/config.json（见 copaw-worker-entrypoint.sh）
set -e

WORKER_NAME="${AGENTTEAMS_WORKER_NAME:-}"
if [ -z "$WORKER_NAME" ]; then
  echo "ERROR: AGENTTEAMS_WORKER_NAME 未设置" >&2
  exit 1
fi

INSTALL_DIR="/root/.copaw-worker"
CONFIG="${INSTALL_DIR}/${WORKER_NAME}/.copaw/config.json"
SEC="/tmp/security-config.json"

if [ ! -f "$CONFIG" ]; then
  echo "SKIP: $CONFIG 不存在，跳过（该 Worker 可能尚未初始化 runtime）"
  exit 0
fi

if [ ! -f "$SEC" ]; then
  echo "ERROR: $SEC 不存在，请先 docker cp security-config.json 到容器" >&2
  exit 1
fi

python3 - "$CONFIG" "$SEC" "$WORKER_NAME" "$INSTALL_DIR" <<'PY'
import json, sys

cfg_path, sec_path, worker_name, install_dir = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
with open(cfg_path) as f:
    cfg = json.load(f)
with open(sec_path) as f:
    sec = json.load(f)["security"]

# 只覆盖 security 段，保留 bridge.py 写入的 channels/agents 等其余字段
cfg["security"] = sec

# 追加 Worker 专属敏感文件绝对路径（file_guard 用精确路径/目录前缀匹配，非 glob）
worker_copaw = f"{install_dir}/{worker_name}/.copaw"
absolute_sensitive = [
    f"{worker_copaw}/providers.json",   # LLM provider 凭据
    f"{worker_copaw}/config.json",      # 运行时配置（含模型/通道配置）
    f"{worker_copaw}.secret/",          # 密钥目录（copaw SECRET_DIR）
]
fg = cfg["security"].setdefault("file_guard", {})
fg.setdefault("enabled", True)
existing = fg.get("sensitive_files", [])
merged = list(existing)
for p in absolute_sensitive:
    if p not in merged:
        merged.append(p)
fg["sensitive_files"] = merged

with open(cfg_path, "w") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)

tg = sec.get("tool_guard", {})
sk = sec.get("skill_scanner", {})
print("OK: security 段已注入 " + cfg_path)
print("  tool_guard.enabled      =", tg.get("enabled"))
print("  tool_guard.custom_rules =", len(tg.get("custom_rules", [])))
print("  file_guard.enabled      =", fg.get("enabled"))
print("  file_guard.sensitive_files =", len(merged))
print("  skill_scanner.mode      =", sk.get("mode"))
PY

# ── 同步回 MinIO（关键：避免 restart 时 mirror_all 用旧版覆盖本地注入） ──
# Worker 重启时 worker.py 会执行 mirror_all()（mc mirror --overwrite），从 MinIO
# 全量覆盖本地 sync root。若不把带 security 段的 config.json 推回 MinIO，
# restart 后 security 段会被旧版冲掉。
# 路径规则（对齐 copaw_worker/sync.py）：alias/bucket/agents/<worker>/.copaw/config.json
MC_ALIAS="${AGENTTEAMS_STORAGE_ALIAS:-}"
if [ -z "$MC_ALIAS" ]; then
  STORAGE_PREFIX="${AGENTTEAMS_STORAGE_PREFIX:-agentteams/agentteams-storage}"
  MC_ALIAS="${STORAGE_PREFIX%%/*}"
  [ -n "$MC_ALIAS" ] || MC_ALIAS="agentteams"
fi
BUCKET="${AGENTTEAMS_FS_BUCKET:-agentteams-storage}"
REMOTE="${MC_ALIAS}/${BUCKET}/agents/${WORKER_NAME}/.copaw/config.json"

if command -v mc >/dev/null 2>&1; then
  if mc cp "$CONFIG" "$REMOTE" 2>/dev/null; then
    echo "OK: config.json 已同步回 MinIO: ${REMOTE}"
  else
    echo "WARN: mc cp 到 MinIO 失败（security 段仅本地生效，restart 后可能丢失）" >&2
  fi
else
  echo "WARN: 容器内无 mc 命令（security 段仅本地生效，restart 后可能丢失）" >&2
fi
