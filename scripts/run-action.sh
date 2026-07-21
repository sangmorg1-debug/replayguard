#!/usr/bin/env bash
set -uo pipefail

changed_args=()
changed_file="$RUNNER_TEMP/replayguard-changed-files.txt"
if [[ "$REPLAYGUARD_CHANGED_ONLY" == "true" && -n "${REPLAYGUARD_BASE_SHA:-}" && -n "${REPLAYGUARD_HEAD_SHA:-}" ]]; then
  if git diff --name-only "$REPLAYGUARD_BASE_SHA...$REPLAYGUARD_HEAD_SHA" > "$changed_file" 2>/dev/null; then
    changed_args=(--changed-files "$changed_file")
  fi
fi

candidate_args=()
if [[ -n "${REPLAYGUARD_CANDIDATES:-}" ]]; then
  candidate_args=(--candidate-map "$REPLAYGUARD_CANDIDATES")
fi

set +e
verify ci --suite "$REPLAYGUARD_SUITE" "${candidate_args[@]}" "${changed_args[@]}" \
  --output "$REPLAYGUARD_OUTPUT" --commit-sha "${GITHUB_SHA:-local}" > "$RUNNER_TEMP/replayguard-cli.json"
status=$?
set -e

report_path="$REPLAYGUARD_OUTPUT/report.md"
if [[ -f "$report_path" && -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  cat "$report_path" >> "$GITHUB_STEP_SUMMARY"
fi

evidence_file=$(find "$REPLAYGUARD_OUTPUT" -maxdepth 1 -name 'evidence-*.json' -print -quit)
evidence_sha=""
if [[ -n "$evidence_file" ]]; then
  evidence_sha=$(basename "$evidence_file" | sed -e 's/^evidence-//' -e 's/\.json$//')
fi
passed=false
if [[ $status -eq 0 ]]; then passed=true; fi
{
  echo "passed=$passed"
  echo "evidence_sha256=$evidence_sha"
  echo "report_path=$report_path"
} >> "$GITHUB_OUTPUT"
cat "$RUNNER_TEMP/replayguard-cli.json"
exit "$status"

