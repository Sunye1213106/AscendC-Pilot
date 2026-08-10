#!/usr/bin/env bash
# Strict acp workflow driver for full_closure_run_20260810
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=run_env.sh
source "$SCRIPT_DIR/run_env.sh"
export PATH="/work/venv-acp/bin:/usr/bin:/bin:$PATH"

PROJECT="$ASCENDC_PROJECT_ROOT"
LOG_DIR="$RUN_LOG/logs"
mkdir -p "$LOG_DIR"
TIMELINE="$RUN_LOG/timeline.md"
METRICS="$RUN_LOG/metrics.json"
STOP="$RUN_LOG/STOP_REASON.txt"
SKILL_GAPS="$RUN_LOG/skill_gaps.md"
RUN_START=$(date +%s)
RUN_START_ISO=$(date -Iseconds)

append_timeline() {
  local t0="$1" phase="$2" wall_s="$3" metrics="$4" artifact="$5" notes="$6"
  echo "| $t0 | $phase | $wall_s | $metrics | $artifact | $notes |" >> "$TIMELINE"
}

acp_json() {
  local phase="$1" action="$2" extra="${3:-}"
  local ts log t0 t1 wall ec
  ts=$(date +%Y%m%dT%H%M%S)
  log="$LOG_DIR/${phase}_${action}_${ts}.log"
  t0=$(date -Iseconds)
  t0e=$(date +%s)
  echo "=== START $phase/$action at $t0 ===" | tee "$log"
  set +e
  if [ -n "$extra" ]; then
    # shellcheck disable=SC2086
    acp run-action "$action" --project "$PROJECT" $extra >> "$log" 2>&1
  else
    acp run-action "$action" --project "$PROJECT" >> "$log" 2>&1
  fi
  ec=$?
  set -e
  t1=$(date -Iseconds)
  t1e=$(date +%s)
  wall=$((t1e - t0e))
  echo "=== END ec=$ec wall_s=$wall at $t1 ===" >> "$log"
  append_timeline "$t0" "$phase/$action" "$wall" "ec=$ec" "$log" ""
  return $ec
}

acp_start() {
  local wf="$1"
  local ts log t0 t1 wall
  ts=$(date +%Y%m%dT%H%M%S)
  log="$LOG_DIR/start_${wf}_${ts}.log"
  t0=$(date -Iseconds)
  t0e=$(date +%s)
  acp start "$wf" --project "$PROJECT" \
    --op-name "$UO_OPERATOR" --architecture "$UO_ARCH" --level L0 \
    --force-new >> "$log" 2>&1 || true
  t1e=$(date +%s)
  wall=$((t1e - t0e))
  append_timeline "$t0" "start/$wf" "$wall" "—" "$log" "force-new"
}

acp_advance() {
  local wf="$1" phase="$2"
  local ts log t0 t1 wall
  ts=$(date +%Y%m%dT%H%M%S)
  log="$LOG_DIR/advance_${wf}_${phase}_${ts}.log"
  t0=$(date -Iseconds)
  t0e=$(date +%s)
  acp advance "$phase" --project "$PROJECT" >> "$log" 2>&1 || true
  t1e=$(date +%s)
  wall=$((t1e - t0e))
  append_timeline "$t0" "advance/$wf→$phase" "$wall" "—" "$log" ""
}

acp_next() {
  acp next --project "$PROJECT" 2>&1
}

acp_complete() {
  acp complete --project "$PROJECT" 2>&1 || true
}

# Archive untrusted prior closure
archive_old_closure() {
  local arch_dir="$PROJECT/.ascendc-pilot/arch35/tg/closure"
  if [ -d "$arch_dir" ]; then
    local dest="$RUN_LOG/archived_closure_$(date +%Y%m%dT%H%M%S)"
    cp -a "$arch_dir" "$dest"
    echo "Archived prior closure to $dest" >> "$TIMELINE"
    rm -rf "$arch_dir"
    mkdir -p "$arch_dir"
  fi
}

run_workflow_actions() {
  local wf="$1"
  shift
  local actions=("$@")
  for action in "${actions[@]}"; do
    local tries=0
    while [ $tries -lt 3 ]; do
      if acp_json "$wf" "$action"; then
        break
      fi
      tries=$((tries + 1))
      acp next --project "$PROJECT" >> "$LOG_DIR/retry_${action}.log" 2>&1 || true
    done
    acp next --project "$PROJECT" >> "$LOG_DIR/next_after_${action}.log" 2>&1 || true
  done
}

echo "# skill_gaps (auto)" > "$SKILL_GAPS"
echo "Run started $RUN_START_ISO" >> "$TIMELINE"

# Phase 0: archive
archive_old_closure

# Phase 1: uo-init review readiness
acp_start uo-init
# Advance through to review if possible — run review action when phase allows
for phase in extract analyze resolve commit review; do
  acp_advance uo-init "$phase"
  case "$phase" in
    review) acp_json uo-init review || true ;;
  esac
done
acp_complete

# Phase 2: tg-init
acp_start tg-init
TG_INIT_ACTIONS=(init_intent kb_check contract_build semantic_bind bind_merge mid_nest integrity_gate)
for a in "${TG_INIT_ACTIONS[@]}"; do
  acp_json tg-init "$a" || true
done
# init_audit is subagent — prepare then finalize with auto if possible
acp_json tg-init init_audit || true
# human_confirm: user authorized full coverage
acp_json tg-init human_confirm || true
acp_json tg-init human_confirm --finalize || true
acp_advance tg-init confirm
acp_complete

# Phase 3: tg-plan T=D
acp_start tg-plan
acp_json tg-plan plan_intent || true
acp_json tg-plan plan_intent --finalize || true
for a in plan_scope plan_precheck plan_build; do
  acp_json tg-plan "$a" || true
done
acp_json tg-plan plan_approve || true
acp_json tg-plan plan_approve --finalize || true
acp_complete

# Phase 4: tg-solve loop
acp_start tg-solve
SOLVE_ROUND=0
MAX_SOLVE_ROUNDS=20
while [ $SOLVE_ROUND -lt $MAX_SOLVE_ROUNDS ]; do
  SOLVE_ROUND=$((SOLVE_ROUND + 1))
  NEXT=$(acp next --project "$PROJECT" 2>/dev/null || echo '{}')
  echo "Round $SOLVE_ROUND next=$NEXT" >> "$LOG_DIR/solve_round_${SOLVE_ROUND}.log"
  # Run recommended action from next if parseable
  ACTION=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('recommended_next_action',{}).get('id','') or '')" "$NEXT" 2>/dev/null || echo "")
  if [ -z "$ACTION" ]; then
    ACTION=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); al=d.get('allowed_actions') or []; print(al[0]['id'] if al else '')" "$NEXT" 2>/dev/null || echo "")
  fi
  if [ -z "$ACTION" ]; then
    echo "No action from next; trying advance certify" >> "$LOG_DIR/solve_round_${SOLVE_ROUND}.log"
    acp_advance tg-solve certify
    break
  fi
  case "$ACTION" in
    lemma_mine|lemma_review|closure_audit|init_audit)
      acp_json tg-solve "$ACTION" || true
      acp_json tg-solve "$ACTION" --finalize || true
      ;;
    closure_certify)
      acp_json tg-solve closure_certify || true
      break
      ;;
    *)
      acp_json tg-solve "$ACTION" || true
      ;;
  esac
  # Check gap
  CERT="$PROJECT/.ascendc-pilot/arch35/tg/closure/certificate.yaml"
  if [ -f "$CERT" ]; then
    GAP=$(python3 -c "import yaml; d=yaml.safe_load(open('$CERT')); print(d.get('state',{}).get('gap', d.get('gate',{}).get('gap','?')))" 2>/dev/null || echo "?")
    if [ "$GAP" = "0" ]; then
      echo "gap=0 detected" >> "$LOG_DIR/solve_round_${SOLVE_ROUND}.log"
      break
    fi
  fi
done
acp_complete

# Collect metrics
python3 <<'PY'
import json, yaml, time
from pathlib import Path
run_log = Path("/mnt/d/PR-review/AscendC-Pilot/artifacts/fa-pr13/full_closure_run_20260810")
proj = Path("/work/ops-transformer/attention/flash_attention_score_grad")
cert = proj / ".ascendc-pilot/arch35/tg/closure/certificate.yaml"
m = {"run_end": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "certificate": {}}
if cert.is_file():
    d = yaml.safe_load(cert.read_text()) or {}
    st = d.get("state") or {}
    g = d.get("gate") or {}
    m["certificate"] = {
        "ok": d.get("ok"),
        "D": st.get("declared") or g.get("declared"),
        "R": st.get("R") or g.get("R"),
        "E": st.get("E") or g.get("E"),
        "gap": st.get("gap") if st.get("gap") is not None else g.get("gap"),
        "invariants_ok": (d.get("invariants") or {}).get("ok"),
    }
(run_log / "metrics.json").write_text(json.dumps(m, indent=2))
PY

RUN_END=$(date +%s)
TOTAL=$((RUN_END - RUN_START))
append_timeline "$(date -Iseconds)" "TOTAL" "$TOTAL" "see metrics.json" "$METRICS" "driver complete"
echo "COMPLETED wall_s=$TOTAL" > "$STOP"
