#!/usr/bin/env bash
set -e

MODEL_ID="google/gemma-4-26b-a4b-qat"
API_URL="http://localhost:1234/api/v1/models/load"

echo "Loading model: ${MODEL_ID}..."

curl --silent --request POST "${API_URL}" \
  --header "Content-Type: application/json" \
  --data "{
    \"model\": \"${MODEL_ID}\",
    \"context_length\": 262144,
    \"flash_attention\": true,
    \"offload_kv_cache_to_gpu\": true,
    \"echo_load_config\": true
  }" | jq . || cat