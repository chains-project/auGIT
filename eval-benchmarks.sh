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
#   ./eval-benchmarks.sh controls     # collect + report all benign control targets
#   ./eval-benchmarks.sh all           # init + positives + controls
#   ./eval-benchmarks.sh p1-trivy      # single case (see list below)
#
# Override paths:
#   EVAL_DB=./my.db EVAL_OUT=./reports ./eval-benchmarks.sh all
#
# Cases (one primary metric each; event-stream covers three metrics):
#   p1-trivy              Contributor identity
#   p2-tiledesk           Irregular commits
#   p3-xz                 Onboarding of new contributors
#   p4-ctx                Ownership changes
#   p5-event-stream-role  Role changes
#   p6-event-stream-pub   Unverified release publishers
#   p7-mrmustard          Unusual release pattern
#   p8-event-stream-dep   New dependency introduction
#   p9-tj-actions         History integrity
#
# Controls (benign; measured for FP/TN):
#   n1-spoon            INRIA/spoon
#   n2-actions-checkout actions/checkout
#   n3-requests        psf/requests
#
# Timelines are taken from the cited postmortems (as-of = end of incident window).

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

# --- Positives (should surface findings for the primary metric) ---

# p1 — Contributor identity
# Trivy second compromise (2026-03-19): unsigned / imposter commits and
# force-pushed tags on trivy-action (~12h). StepSecurity postmortem:
# https://www.stepsecurity.io/blog/trivy-compromised-a-second-time---malicious-v0-69-4-release
p1_trivy() {
  db collect github aquasecurity/trivy-action --sources all
  db check aquasecurity/trivy-action || true
  db report aquasecurity/trivy-action \
    --out "$EVAL_OUT/p1-trivy-contributor-identity.html" \
    --as-of 2026-03-20T00:00:00Z \
    --tail-days 7
}

# p2 — Irregular commits
# Megalodon / Tiledesk (2026-05-18 11:36–17:48 UTC): direct push to master
# (acac5a9), no PR. SafeDep postmortem:
# https://safedep.io/megalodon-mass-github-repo-backdooring-ci-workflows/
# Commit: https://github.com/Tiledesk/tiledesk-server/commit/acac5a9854650c4ae2883c4740bf87d34120c038
p2_tiledesk() {
  db collect github Tiledesk/tiledesk-server --sources all
  db report Tiledesk/tiledesk-server \
    --out "$EVAL_OUT/p2-tiledesk-irregular-commits.html" \
    --as-of 2026-05-21T00:00:00Z \
    --tail-days 7
}

# p3 — Onboarding of new contributors
# xz backdoor: Jia Tan long-con onboarding; malicious releases 5.6.0 (2024-02-24)
# and 5.6.1 (2024-03-09); public disclosure 2024-03-29.
# Timeline: https://research.swtch.com/xz-timeline
p3_xz() {
  db collect github tukaani-project/xz --sources all
  db report tukaani-project/xz \
    --out "$EVAL_OUT/p3-xz-onboarding.html" \
    --as-of 2024-03-29T00:00:00Z \
    --tail-days 90
}

# p4 — Ownership changes
# ctx PyPI domain takeover: domain re-registered 2022-05-14; malicious uploads
# through 2022-05-24; project removed same day. PSF incident report:
# https://python-security.readthedocs.io/pypi-vuln/index-2022-05-24-ctx-domain-takeover.html
p4_ctx() {
  # Registry-only: package was removed from PyPI (no GitHub link expected).
  db collect auto ctx --no-follow
  db report ctx \
    --provider pypi \
    --out "$EVAL_OUT/p4-ctx-ownership.html" \
    --as-of 2022-05-24T12:00:00Z \
    --tail-days 45
}

# Shared collect for event-stream (used by p5, p6, p8).
# Snyk postmortem: https://snyk.io/blog/a-post-mortem-of-the-malicious-event-stream-backdoor/
#   ~2018-09: right9ctrl gains maintainer / npm publish rights
#   2018-09-09: flatmap-stream added; event-stream 3.3.6 released
#   2018-09-16: flatmap removed from tree; 4.0.0 released
#   2018-11-26: npm notified / packages removed
_event_stream_collect() {
  db collect github dominictarr/event-stream --sources all
}

_event_stream_report() {
  local out="$1"
  db report dominictarr/event-stream \
    --out "$out" \
    --as-of 2018-11-26T00:00:00Z \
    --tail-days 90
}

# p5 — Role changes (event-stream maintainer handover → new merge/release author)
p5_event_stream_role() {
  _event_stream_collect
  _event_stream_report "$EVAL_OUT/p5-event-stream-role-changes.html"
}

# p6 — Unverified release publishers (right9ctrl as new release author)
p6_event_stream_pub() {
  _event_stream_collect
  _event_stream_report "$EVAL_OUT/p6-event-stream-unverified-publishers.html"
}

# p7 — Unusual release pattern
# mrmustard 0.7.4 (2026-07-23/24): PyPI-only version; no matching git tag or
# GitHub release. StepSecurity postmortem:
# https://www.stepsecurity.io/blog/compromised-pypi-mrmustard-0-7-4-credential-stealer
p7_mrmustard() {
  # auto: GitHub + PyPI (name guess / metadata) in one step
  db collect auto XanaduAI/MrMustard --sources all
  db report XanaduAI/MrMustard \
    --out "$EVAL_OUT/p7-mrmustard-unusual-release.html" \
    --as-of 2026-07-24T23:59:00Z \
    --tail-days 14
}

# p8 — New dependency introduction (flatmap-stream added 2018-09-09)
p8_event_stream_dep() {
  _event_stream_collect
  _event_stream_report "$EVAL_OUT/p8-event-stream-new-dependency.html"
}

# p9 — History integrity
# tj-actions/changed-files (CVE-2025-30066): tag retarget ~2025-03-14 16:00 UTC
# through 2025-03-15. StepSecurity postmortem:
# https://www.stepsecurity.io/blog/harden-runner-detection-tj-actions-changed-files-action-is-compromised
p9_tj_actions() {
  db collect github tj-actions/changed-files --sources all
  # Integrity refetch helps history_integrity (tag retarget) signals.
  db check tj-actions/changed-files || true
  db report tj-actions/changed-files \
    --out "$EVAL_OUT/p9-tj-actions-history-integrity.html" \
    --as-of 2025-03-15T12:00:00Z \
    --tail-days 7
}

positives() {
  p1_trivy
  p2_tiledesk
  p3_xz
  p4_ctx
  p5_event_stream_role
  p6_event_stream_pub
  p7_mrmustard
  p8_event_stream_dep
  p9_tj_actions
}

#
# --- Controls (benign; used to observe FP/TN) ---
#
# Fixed calendar window for repeatability.
# Note: this does not guarantee "no findings". It only sets a pre-defined audit window
# for projects that we label benign under the thesis protocol.
CONTROL_AS_OF="2026-07-31T00:00:00Z"
CONTROL_TAIL_DAYS="30"

n1_spoon() {
  db collect github INRIA/spoon --sources all
  db report INRIA/spoon \
    --out "$EVAL_OUT/n1-spoon-tn.html" \
    --as-of "$CONTROL_AS_OF" \
    --tail-days "$CONTROL_TAIL_DAYS"
}

n2_actions_checkout() {
  db collect github actions/checkout --sources all
  db report actions/checkout \
    --out "$EVAL_OUT/n2-actions-checkout-tn.html" \
    --as-of "$CONTROL_AS_OF" \
    --tail-days "$CONTROL_TAIL_DAYS"
}

n3_psf_requests() {
  db collect auto requests --sources all
  db report requests \
    --provider "pypi" \
    --out "$EVAL_OUT/n3-psf-requests-tn.html" \
    --as-of "$CONTROL_AS_OF" \
    --tail-days "$CONTROL_TAIL_DAYS"
}

controls() {
  n1_spoon
  n2_actions_checkout
  n3_psf_requests
}

usage() {
  # Print leading comment block until the first non-comment line.
  awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"
}

cmd="${1:-}"
case "$cmd" in
  init) init ;;
  positives) positives ;;
  controls) controls ;;
  all) init; positives; controls ;;
  p1-trivy) p1_trivy ;;
  p2-tiledesk) p2_tiledesk ;;
  p3-xz) p3_xz ;;
  p4-ctx) p4_ctx ;;
  p5-event-stream-role) p5_event_stream_role ;;
  p6-event-stream-pub) p6_event_stream_pub ;;
  p7-mrmustard) p7_mrmustard ;;
  p8-event-stream-dep) p8_event_stream_dep ;;
  p9-tj-actions) p9_tj_actions ;;
  n1_spoon) n1_spoon ;;
  n2_actions_checkout) n2_actions_checkout ;;
  n3_psf_requests) n3_psf_requests ;;
  help|-h|--help|"") usage ;;
  *)
    echo "unknown command: $cmd" >&2
    usage >&2
    exit 1
    ;;
esac
