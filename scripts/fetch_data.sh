#!/usr/bin/env bash
# Fetch and refresh K12-KGraph data files into a local cache dir.
#   bash fetch_data.sh core    # initial fetch: global_KG + subject KG (~13 MB) — enough for queries
#   bash fetch_data.sh all     # initial fetch: + afterclass_exercises + K12-Bench + K12-Train (~25 MB)
#   bash fetch_data.sh update  # 更新缓存: refresh files already cached (conditional GET),
#                              # plus fetch any missing core files. Run after upstream data
#                              # changes — e.g. when a fix for issue #8 lands.
# Env: HF_ENDPOINT (default https://hf-mirror.com, works in CN; use
#      https://huggingface.co elsewhere), K12KGRAPH_DATA (default ~/.cache/k12-kgraph)
set -euo pipefail

MODE="${1:-core}"
OUT="${K12KGRAPH_DATA:-$HOME/.cache/k12-kgraph}"
BASE="${HF_ENDPOINT:-https://hf-mirror.com}/datasets/lhpku20010120/K12-KGraph/resolve/main"

CORE=(
  K12-KGraph/global_KG/nodes.json
  K12-KGraph/global_KG/edges.json
  K12-KGraph/subject_specific_KG/math.json
  K12-KGraph/subject_specific_KG/physics.json
  K12-KGraph/subject_specific_KG/chemistry.json
  K12-KGraph/subject_specific_KG/biology.json
)
EXTRA=(
  K12-KGraph/afterclass_exercises/math_7a_rjb.json
  K12-KGraph/afterclass_exercises/math_7b_rjb.json
  K12-KGraph/afterclass_exercises/math_8a_rjb.json
  K12-KGraph/afterclass_exercises/math_8b_rjb.json
  K12-KGraph/afterclass_exercises/math_9a_rjb.json
  K12-KGraph/afterclass_exercises/math_9b_rjb.json
  K12-KGraph/afterclass_exercises/math_highschool_rjb_bx1.json
  K12-KGraph/afterclass_exercises/math_highschool_rjb_bx2.json
  K12-KGraph/afterclass_exercises/chemistry_9a_rjb.json
  K12-KGraph/afterclass_exercises/chemistry_9b_rjb.json
  K12-KGraph/afterclass_exercises/chemistry_highschool_rjb_bx1.json
  K12-KGraph/afterclass_exercises/chemistry_highschool_rjb_bx2.json
  K12-KGraph/afterclass_exercises/chemistry_highschool_rjb_xzxbx1.json
  K12-KGraph/afterclass_exercises/chemistry_highschool_rjb_xzxbx2.json
  K12-KGraph/afterclass_exercises/chemistry_highschool_rjb_xzxbx3.json
  K12-Bench/ground_subtask1.jsonl
  K12-Bench/ground_subtask2.jsonl
  K12-Bench/prereq_subtask1.jsonl
  K12-Bench/prereq_subtask2.jsonl
  K12-Bench/neighbor.jsonl
  K12-Bench/evidence_subtask1.jsonl
  K12-Bench/evidence_subtask2.jsonl
  K12-Bench/locate_subtask1.jsonl
  K12-Bench/locate_subtask2.jsonl
  K12-Train/train.jsonl
)

UPDATED=0; UNCHANGED=0; SKIPPED=0; FAILED=0

download() {  # $1 = relative path. Conditional GET when a cached copy exists.
  local f="$1" dest="$OUT/$1" tmp="$OUT/$1.tmp" code rc=0
  mkdir -p "$(dirname "$dest")"
  if [ -s "$dest" ]; then
    code=$(curl -sS -L --retry 2 -z "$dest" -o "$tmp" -w '%{http_code}' "$BASE/$f") || rc=$?
  else
    code=$(curl -sS -L --retry 2 -o "$tmp" -w '%{http_code}' "$BASE/$f") || rc=$?
  fi
  if [ "$rc" -ne 0 ]; then
    echo "FAIL: $f (curl rc=$rc)"
    rm -f "$tmp"
    return 1
  fi
  case "$code" in
    2*|000)  # normal body (000 = non-HTTP scheme like file://)
      if [ -s "$tmp" ]; then
        if [ -s "$dest" ] && cmp -s "$tmp" "$dest"; then
          rm -f "$tmp"
          echo "unchanged: $f"
        else
          mv "$tmp" "$dest"
          echo "updated: $f"
        fi
      elif [ -s "$dest" ]; then
        rm -f "$tmp"
        echo "unchanged: $f"    # conditional GET skipped the transfer: cache is up to date
      else
        rm -f "$tmp"
        echo "FAIL: $f (empty response)"
        return 1
      fi
      ;;
    304)     # Not Modified — body intentionally empty
      rm -f "$tmp"
      echo "unchanged: $f"
      ;;
    *)       # 4xx/5xx: error body must never overwrite a good cache entry
      echo "FAIL: $f (http=$code)"
      rm -f "$tmp"
      return 1
      ;;
  esac
}

fetch_list() {  # initial fetch: skip files already present, no network round-trip
  local f out
  for f in "$@"; do
    if [ -s "$OUT/$f" ]; then
      echo "skip (exists): $f"
      SKIPPED=$((SKIPPED+1))
      continue
    fi
    if out=$(download "$f"); then
      echo "$out"
      case "$out" in updated:*) UPDATED=$((UPDATED+1));; *) UNCHANGED=$((UNCHANGED+1));; esac
    else
      echo "$out"
      FAILED=$((FAILED+1))
    fi
  done
}

update_list() {  # refresh: conditional GET for every file that is (or should be) cached
  local f out
  for f in "$@"; do
    if out=$(download "$f"); then
      echo "$out"
      case "$out" in updated:*) UPDATED=$((UPDATED+1));; *) UNCHANGED=$((UNCHANGED+1));; esac
    else
      echo "$out"
      FAILED=$((FAILED+1))
    fi
  done
}

case "$MODE" in
  core) FILES=("${CORE[@]}") ;;
  all)  FILES=("${CORE[@]}" "${EXTRA[@]}") ;;
  update)
    FILES=()
    for f in "${CORE[@]}"; do
      [ -s "$OUT/$f" ] || FILES+=("$f")          # missing core files get fetched
    done
    for f in "${CORE[@]}" "${EXTRA[@]}"; do
      [ -s "$OUT/$f" ] && FILES+=("$f")          # everything cached gets refreshed
    done
    ;;
  *) echo "usage: $0 [core|all|update]" >&2; exit 2 ;;
esac

echo "source: $BASE"
echo "target: $OUT"
echo "mode:   $MODE"

if [ "$MODE" = "update" ]; then
  update_list "${FILES[@]}"
else
  fetch_list "${FILES[@]}"
fi

echo "done: $UPDATED updated, $UNCHANGED unchanged, $SKIPPED skipped, $FAILED failed -> $OUT"
[ "$FAILED" -eq 0 ] || exit 1
