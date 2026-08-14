"""修改 openclaw.json，把 agentteams-gateway 的 baseUrl 指向逆向适配层。
用法: python3 patch_openclaw_base.py <openclaw.json路径>
"""
import json
import sys

path = sys.argv[1]
reverse_base = "http://host.docker.internal:9001/v1"

with open(path, "r", encoding="utf-8") as f:
    d = json.load(f)

prov = d.get("models", {}).get("providers", {}).get("agentteams-gateway")
if not prov:
    print("ERROR: 找不到 models.providers.agentteams-gateway")
    sys.exit(1)

old = prov.get("baseUrl")
prov["baseUrl"] = reverse_base
prov["apiKey"] = "sk-reverse-gateway-local"

with open(path, "w", encoding="utf-8") as f:
    json.dump(d, f, indent=2, ensure_ascii=False)

print(f"OK baseUrl: {old} -> {reverse_base}")
print(f"   model.primary: {d.get('agents', {}).get('defaults', {}).get('model', {}).get('primary')}")
