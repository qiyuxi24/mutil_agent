#!/usr/bin/env bash
# doc-gen 依赖一键安装（Linux 容器 / AgentTeams Worker 镜像）
# 用法：bash skills/doc-gen/scripts/setup-docgen.sh
set -euo pipefail

echo "[doc-gen] 安装系统库（Pango/Cairo/CJK 字体）..."
apt-get update
apt-get install -y \
  libpango-1.0-0 \
  libpangocairo-1.0-0 \
  libcairo2 \
  libgdk-pixbuf-2.0-0 \
  fonts-noto-cjk

echo "[doc-gen] 安装 Python 依赖..."
pip install python-docx markdown weasyprint

echo "[doc-gen] 完成：md2docx / md2pdf 全部可用（python-docx=Word，weasyprint=PDF）"
