"""Windows: run every GUI flow in light + dark at 1440x900 and 1024x640, JOBS at a time (default 3).

The Windows counterpart of run_all.sh (no Xvfb: the flows run on the desktop of the machine or CI runner).
Usage: python tests/gui/run_windows.py OUTDIR [FLOWS...]
"""
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ALL = "F1 F2 F3 F3b F4 F5 F6 F7 F8 F9 F10 F11 F12 F13 F14 F14b F15 F16 F17 F17b F18 F19 F20 F21 F22 F23 F24".split()


def one(job):
    f, theme, size, out = job
    log = os.path.join(out, f"{f}-{theme}-{size}.out")
    env = dict(os.environ, PYTHONUTF8="1", TZ=os.environ.get("TZ", "Europe/Zurich"))
    t0 = time.monotonic()
    with open(log, "w", encoding="utf-8") as fh:
        try:
            rc = subprocess.run([sys.executable, os.path.join(HERE, "flows.py"), f, theme, size, out, "Windows"],
                                stdout=fh, stderr=subprocess.STDOUT, timeout=600, env=env).returncode
        except subprocess.TimeoutExpired:
            rc = "timeout"
    lines = [ln for ln in open(log, encoding="utf-8", errors="replace").read().splitlines() if ln.startswith(f + " ")]
    line = lines[-1] if lines else f"{f} {theme} {size} Windows: CRASH (rc {rc})"
    print(f"{line}  [{time.monotonic() - t0:.0f} s]", flush=True)
    return line


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.environ.get("TEMP", "."), "kluis-flows")
    flows = sys.argv[2:] or ALL
    os.makedirs(out, exist_ok=True)
    jobs = [(f, theme, size, out) for f in flows for theme in ("dark", "light") for size in ("1440x900", "1024x640")]
    with ThreadPoolExecutor(int(os.environ.get("JOBS", "3"))) as ex:
        results = list(ex.map(one, jobs))
    with open(os.path.join(out, "results.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(results) + "\n")
    passed = sum(": PASS" in r for r in results)
    print(f"\npassed: {passed} of {len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
