#!/usr/bin/env bash
set -euo pipefail
umask 077
ta_project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ta_project_root"
ta_runtime_dir="$ta_project_root/.runtime"
mkdir -p "$ta_runtime_dir"
chmod 700 "$ta_runtime_dir"
export TZ=Asia/Shanghai
export TRADINGAGENTS_CHATGPT_AUTH_FILE="${TRADINGAGENTS_CHATGPT_AUTH_FILE:-$ta_runtime_dir/auth/chatgpt-auth.json}"
export TRADINGAGENTS_MCP_AUTH_DIR="${TRADINGAGENTS_MCP_AUTH_DIR:-$ta_runtime_dir/auth}"
export TRADINGAGENTS_RESULTS_DIR="${TRADINGAGENTS_RESULTS_DIR:-$ta_runtime_dir/logs}"
export TRADINGAGENTS_CACHE_DIR="${TRADINGAGENTS_CACHE_DIR:-$ta_runtime_dir/cache}"
export TRADINGAGENTS_MEMORY_LOG_PATH="${TRADINGAGENTS_MEMORY_LOG_PATH:-$ta_runtime_dir/memory/trading_memory.md}"
exec "$ta_project_root/.venv/bin/python" -m tradingagents.watchlist.cli "$@"
