"""从快照生成 controller 的 env 文件（用于 docker run --env-file）。
替换 LLM 上游为适配层，其余 env 全部保留（跳过镜像默认 PATH/JAVA_HOME/DEBIAN_FRONTEND）。
"""
import json
import os

snapshot = os.path.join(os.path.dirname(__file__), "controller-env-snapshot-20260814.json")
out = os.path.join(os.path.dirname(__file__), "controller.env")

with open(snapshot, "r", encoding="utf-8") as f:
    env_list = json.load(f)

skip_prefixes = ("PATH=", "JAVA_HOME=", "DEBIAN_FRONTEND=")

lines = []
for entry in env_list:
    if entry.startswith(skip_prefixes):
        continue
    key = entry.split("=", 1)[0]
    if key == "AGENTTEAMS_OPENAI_BASE_URL":
        lines.append("AGENTTEAMS_OPENAI_BASE_URL=http://host.docker.internal:9001/v1")
    elif key == "AGENTTEAMS_LLM_API_KEY":
        lines.append("AGENTTEAMS_LLM_API_KEY=sk-reverse-gateway-local")
    else:
        lines.append(entry)

with open(out, "w", encoding="utf-8", newline="\n") as f:
    f.write("\n".join(lines) + "\n")

print(f"OK 已生成 env 文件: {out}")
print(f"   env 条目数: {len(lines)}")
print(f"   OPENAI_BASE_URL -> http://host.docker.internal:9001/v1")
