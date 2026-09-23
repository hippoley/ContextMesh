#!/usr/bin/env bash
set -euo pipefail

# ContextMesh local serving reference (LMCache MP mode).
# Terminal 1: LMCache server
#   lmcache server --host localhost --port 5555 --l1-size-gb 20 --eviction-policy LRU
#
# Terminal 2: vLLM + LMCache MP connector
MODEL="${MODEL:-Qwen/Qwen3-8B}"
PORT="${PORT:-8000}"
LMCACHE_HOST="${LMCACHE_HOST:-localhost}"
LMCACHE_PORT="${LMCACHE_PORT:-5555}"

vllm serve "$MODEL" \
  --port "$PORT" \
  --kv-transfer-config "{\"kv_connector\":\"LMCacheMPConnector\",\"kv_connector_module_path\":\"lmcache.integration.vllm.lmcache_mp_connector\",\"kv_role\":\"kv_both\",\"kv_connector_extra_config\":{\"lmcache.mp.host\":\"$LMCACHE_HOST\",\"lmcache.mp.port\":$LMCACHE_PORT}}"
