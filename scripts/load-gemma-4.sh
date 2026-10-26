#!/usr/bin/env bash
set -e

API_URL="http://localhost:1234/api/v1/models/load"

MODEL_ID="google/gemma-4-26b-a4b-qat"
# Context window is set so that Gemma 4 has plenty of room
# for all the plaintext Wikipedia articles. But also low
# enough that thinking loops will be cut.
CONTEXT_LENGTH=32768

echo "Loading model: ${MODEL_ID}..."

curl --silent --request POST "${API_URL}" \
  --header "Content-Type: application/json" \
  --data "{
    \"model\": \"${MODEL_ID}\",
    \"context_length\": ${CONTEXT_LENGTH},
    \"flash_attention\": true,
    \"offload_kv_cache_to_gpu\": true,
    \"echo_load_config\": true
  }" | jq . || cat