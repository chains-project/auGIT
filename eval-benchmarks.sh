#!/usr/bin/env bash
# Benchmark evaluation commands for augit.
#
# Prerequisites:
#   uv sync --all-groups
#   export GITHUB_TOKEN=ghp_...    # required for GitHub collect and check
#
# Usage:
#   ./eval-benchmarks.sh init          # create DB and output directory
#   ./eval-benchmarks.sh positives     # collect + report all positive cases
#   ./eval-benchmarks.sh negatives     # collect + report all negative controls
#   ./eval-benchmarks.sh all           # init + positives + negatives
#   ./eval-benchmarks.sh p1-event-stream   # single case (see list below)
#
# Override paths:
#   EVAL_DB=./my.db EVAL_OUT=./reports ./eval-benchmarks.sh all
#
# Cases:
#   Positives: p1-event-stream, p2-ua-parser-js, p3-ultralytics, p4-ctx,
#              p5-litellm, p6-tj-actions, p7-solana-web3js, p8-ledger-connect-kit
#   Negatives: n1-lodash, n2-requests, n3-guava, n4-arrapi

set -euo pipefail

EVAL_DB="${EVAL_DB:-./eval-benchmarks.db}"
EVAL_OUT="${EVAL_OUT:-./eval-reports}"
CLI="${SSC_AUDIT_CLI:-uv run augit}"

db() {
  $CLI --db "$EVAL_DB" "$@"
}

init() {
  $CLI db init --path "$EVAL_DB"
  mkdir -p "$EVAL_OUT"
  echo "DB: $EVAL_DB"
  echo "Reports: $EVAL_OUT"
}

# --- Positives (should surface findings) ---

p1_event_stream() {
  db collect github dominictarr/event-stream --sources all
  db report dominictarr/event-stream \
    --out "$EVAL_OUT/p1-event-stream.html" \
    --as-of 2018-11-26T00:00:00Z \
    --tail-days 90
}

p2_ua_parser_js() {
  db collect github faisalman/ua-parser-js --sources all
  db report faisalman/ua-parser-js \
    --out "$EVAL_OUT/p2-ua-parser-js.html" \
    --as-of 2021-10-22T00:00:00Z \
    --tail-days 14
}

p3_ultralytics() {
  db collect github ultralytics/ultralytics --sources all
  db collect pypi ultralytics
  db link pypi ultralytics
  db report ultralytics/ultralytics \
    --out "$EVAL_OUT/p3-ultralytics.html" \
    --as-of 2024-12-07T12:00:00Z \
    --tail-days 21
}

p4_ctx() {
  db collect pypi ctx
  db report ctx \
    --provider pypi \
    --out "$EVAL_OUT/p4-ctx.html" \
    --as-of 2022-05-24T00:00:00Z \
    --tail-days 45
}

p5_litellm() {
  db collect github BerriAI/litellm --sources all
  db collect pypi litellm
  db link pypi litellm
  db report BerriAI/litellm \
    --out "$EVAL_OUT/p5-litellm.html" \
    --as-of 2026-03-24T18:00:00Z \
    --tail-days 7
}

p6_tj_actions() {
  db collect github tj-actions/changed-files --sources all
  # Integrity refetch helps history_integrity (tag retarget) signals.
  db check tj-actions/changed-files || true
  db report tj-actions/changed-files \
    --out "$EVAL_OUT/p6-tj-actions.html" \
    --as-of 2025-03-15T12:00:00Z \
    --tail-days 7
}

p7_solana_web3js() {
  db collect github solana-foundation/solana-web3.js --sources all
  db report solana-foundation/solana-web3.js \
    --out "$EVAL_OUT/p7-solana-web3js.html" \
    --as-of 2024-12-04T00:00:00Z \
    --tail-days 3
}

p8_ledger_connect_kit() {
  db collect github LedgerHQ/ledger-live --sources all
  db report LedgerHQ/ledger-live \
    --out "$EVAL_OUT/p8-ledger-connect-kit.html" \
    --as-of 2023-12-14T18:00:00Z \
    --tail-days 7
}

positives() {
  p1_event_stream
  p2_ua_parser_js
  p3_ultralytics
  p4_ctx
  p5_litellm
  p6_tj_actions
  p7_solana_web3js
  p8_ledger_connect_kit
}

# --- Negatives (should stay quiet or info-only) ---

n1_lodash() {
  db collect github lodash/lodash --sources all
  db report lodash/lodash \
    --out "$EVAL_OUT/n1-lodash.html" \
    --as-of 2024-06-01T00:00:00Z \
    --tail-days 90
}

n2_requests() {
  db collect github psf/requests --sources all
  db collect pypi requests
  db link pypi requests
  db report psf/requests \
    --out "$EVAL_OUT/n2-requests.html" \
    --as-of 2024-06-01T00:00:00Z \
    --tail-days 90
}

n3_guava() {
  db collect maven com.google.guava:guava
  db report com.google.guava:guava \
    --provider maven \
    --out "$EVAL_OUT/n3-guava.html" \
    --as-of 2024-06-01T00:00:00Z \
    --tail-days 90
}

n4_arrapi() {
  # Dec 2023 PyPI ownership transfer without package changes — expect no findings today.
  db collect pypi arrapi
  db report arrapi \
    --provider pypi \
    --out "$EVAL_OUT/n4-arrapi.html" \
    --as-of 2023-12-10T00:00:00Z \
    --tail-days 30
}

negatives() {
  n1_lodash
  n2_requests
  n3_guava
  n4_arrapi
}

usage() {
  sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
}

cmd="${1:-}"
case "$cmd" in
  init) init ;;
  positives) positives ;;
  negatives) negatives ;;
  all) init; positives; negatives ;;
  p1-event-stream) p1_event_stream ;;
  p2-ua-parser-js) p2_ua_parser_js ;;
  p3-ultralytics) p3_ultralytics ;;
  p4-ctx) p4_ctx ;;
  p5-litellm) p5_litellm ;;
  p6-tj-actions) p6_tj_actions ;;
  p7-solana-web3js) p7_solana_web3js ;;
  p8-ledger-connect-kit) p8_ledger_connect_kit ;;
  n1-lodash) n1_lodash ;;
  n2-requests) n2_requests ;;
  n3-guava) n3_guava ;;
  n4-arrapi) n4_arrapi ;;
  help|-h|--help|"") usage ;;
  *)
    echo "unknown command: $cmd" >&2
    usage >&2
    exit 1
    ;;
esac
