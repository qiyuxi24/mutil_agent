#!/bin/bash
for ip in 192.168.65.254 192.168.65.1 172.18.0.1 172.17.0.1 10.0.75.1; do
  printf "%-16s -> " "$ip"
  curl -s -m 2 http://${ip}:9400/health || printf "FAIL"
  echo
done
echo "--- IPv6 host.docker.internal ---"
curl -s -m 3 "http://[fdc4:f303:9324::254]:9400/health" || echo "FAIL-v6"
echo
echo "--- docker gateway (host-gateway flag check) ---"
ip addr show eth0 | head -4
