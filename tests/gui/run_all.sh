#!/bin/bash
# Run every flow in light + dark at 1440x900 and 1024x640, JOBS at a time (default 4).
# Usage: tests/gui/run_all.sh OUTDIR [DESKTOP] [FLOWS...]
OUT=${1:-/tmp/kluis-flows}; DESKTOP=${2:-X-Cinnamon}; shift 2 2>/dev/null
FLOWS=${*:-"F1 F2 F3 F3b F4 F5 F6 F7 F8 F9 F10 F11 F12 F13 F14 F14b F15 F16 F17 F17b F18 F19 F20"}
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$OUT"; : > "$OUT/results.txt"
one() {  # flow theme size
  local f=$1 theme=$2 size=$3
  timeout 600 xvfb-run -a -s "-screen 0 ${size}x24" dbus-run-session -- \
    python3 "$HERE/flows.py" "$f" "$theme" "$size" "$OUT" "$DESKTOP" > "$OUT/$f-$theme-$size.out" 2>&1
  local rc=$? line
  line=$(grep -E "^$f " "$OUT/$f-$theme-$size.out" | tail -1)
  [ -z "$line" ] && line="$f $theme $size $DESKTOP: CRASH (rc $rc)"
  echo "$line"
}
export -f one; export OUT DESKTOP HERE
for f in $FLOWS; do for theme in dark light; do for size in 1440x900 1024x640; do echo "$f $theme $size"; done; done; done \
  | xargs -P "${JOBS:-4}" -L 1 bash -c 'one $0 $1 $2' | tee "$OUT/results.txt"
total=$(wc -l < "$OUT/results.txt"); pass=$(grep -c ": PASS" "$OUT/results.txt")
echo; echo "passed: $pass of $total"; [ "$pass" -eq "$total" ]
