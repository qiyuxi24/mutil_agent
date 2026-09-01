#!/bin/bash
grep -nE 'mcp|mcporter' /root/.copaw-worker/leader/openclaw.json | head -20
echo '---mcp-related-keys---'
python3 - <<'PYEOF'
import json
d = json.load(open('/root/.copaw-worker/leader/openclaw.json'))
for k, v in d.items():
    if 'mcp' in k.lower():
        print(json.dumps({k: v}, indent=1, ensure_ascii=False))
PYEOF
