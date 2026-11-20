#!/usr/bin/env bash
# 一键更新所有源: 收集 -> TV直连复测 -> 构建最终订阅
# 用法: bash scripts/update_all.sh
set -e
cd "$(dirname "$0")/.."

echo "========== [1/3] 收集上游源 =========="
# 收集阶段需要能访问 jsdelivr 列表; 若本机直连不通, 可设置 TVBOX_PROXY
python scripts/manager.py collect

echo "========== [2/3] 电视网络直连复测 + jsdelivr 改写 =========="
python scripts/tv_rewriter.py

echo "========== [3/3] 构建最终订阅文件 =========="
python scripts/build_final.py

echo "========== 完成 =========="
echo "主订阅: subscriptions/tvbox.json"
echo "详细报告: reports/tv_report.md"
