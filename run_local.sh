#!/usr/bin/env bash
# Launch the GUIs from this checkout for local, hands-on testing.
#
#   ./run_local.sh                 # both GUIs
#   ./run_local.sh vcornea         # V-Cornea only
#   ./run_local.sh angio           # Angiogenesis only
#   ./run_local.sh check           # verify the interpreter can import cc3d/PyQt5/both wrappers
#   ./run_local.sh tests           # run the headless GUI test suite (tests/gui)
#
# Interpreter: $SDI_PYTHON if set, else the conda env named by $SDI_CONDA_ENV
# (default "vc") under ~/miniconda3 or ~/anaconda3, else whatever `python` is
# on PATH. Output of every launched GUI is mirrored to .logs/run_local/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGDIR="$ROOT/.logs/run_local"
mkdir -p "$LOGDIR"

pick_python() {
    if [ -n "${SDI_PYTHON:-}" ]; then echo "$SDI_PYTHON"; return; fi
    local env="${SDI_CONDA_ENV:-vc}"
    for base in "$HOME/miniconda3" "$HOME/anaconda3" "$HOME/mambaforge" "$HOME/miniforge3" "${CONDA_PREFIX_1:-}" "${CONDA_PREFIX:-}"; do
        [ -n "$base" ] || continue
        if [ -x "$base/envs/$env/bin/python" ]; then echo "$base/envs/$env/bin/python"; return; fi
        if [ -x "$base/bin/python" ] && [ "$(basename "$base")" = "$env" ]; then echo "$base/bin/python"; return; fi
    done
    command -v python
}
PY="$(pick_python)"
export VCORNEA_PROJECT_PATH="${VCORNEA_PROJECT_PATH:-$ROOT/vcornea_paper/Local/Project/paper_version}"

check() {
    echo "python: $PY"
    "$PY" - <<'PYEOF'
import sys
ok = True
for mod in ("cc3d", "PyQt5", "vivarium_vcornea", "vivarium_angio"):
    try:
        m = __import__(mod)
        print(f"  ok   {mod:18s} {getattr(m, '__file__', '')}")
    except Exception as e:
        ok = False
        print(f"  FAIL {mod:18s} {e}")
import os
print("  display:", os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or "(none - GUIs need one)")
sys.exit(0 if ok else 1)
PYEOF
}

launch() {
    local name="$1" dir="$ROOT/$2"
    local log="$LOGDIR/$name-$(date +%Y%m%d-%H%M%S).log"
    echo "launching $name  (log: ${log#$ROOT/})"
    ( cd "$dir" && exec "$PY" -X faulthandler run_gui.py 2>&1 | tee "$log" ) &
}

case "${1:-both}" in
    check)   check ;;
    tests)   shift; cd "$ROOT" && exec "$PY" -m pytest tests/gui -q "$@" ;;
    vcornea) launch vcornea vcornea-gui; wait ;;
    angio)   launch angio angio-gui; wait ;;
    both)    launch vcornea vcornea-gui; launch angio angio-gui; wait ;;
    *) echo "usage: $0 [both|vcornea|angio|check|tests [pytest args]]" >&2; exit 2 ;;
esac
