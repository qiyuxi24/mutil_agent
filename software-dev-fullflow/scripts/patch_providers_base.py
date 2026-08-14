"""修改 CoPaw providers.json，把 agentteams-gateway 的 base_url 指向逆向适配层。
用法: python3 patch_providers_base.py <providers.json路径>
"""
import json
import sys

path = sys.argv[1]
reverse_base = "http://host.docker.internal:9001/v1"

with open(path, "r", encoding="utf-8") as f:
    d = json.load(f)

gw = d.get("custom_providers", {}).get("agentteams-gateway")
if not gw:
    print("ERROR: 找不到 custom_providers.agentteams-gateway")
    sys.exit(1)

old = gw.get("default_base_url")
gw["default_base_url"] = reverse_base
gw["api_key"] = "sk-reverse-gateway-local"

with open(path, "w", encoding="utf-8") as f:
    json.dump(d, f, indent=2)

print(f"OK base_url: {old} -> {reverse_base}")
print(f"   active_llm: {d.get('active_llm')}")
print(f"   models 数量: {len(gw.get('models', []))}")
