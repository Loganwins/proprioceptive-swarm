#!/usr/bin/env bash
# scan_ip.sh — zero proprietary-IP gate for proprioceptive-swarm release artifacts.
#
# Unpacks every wheel (.whl = zip) and sdist (.tar.gz) in the given dist dir
# (default: dist/) and FAILS (exit 1) if any member contains:
#   * a numeric array of MORE THAN 32 float literals  (candidate head weights /
#     transport-matrix bytes),
#   * a forbidden server-internals keyword: thr_bits, auroc, ridge, transport,
#     mu_x, sd_x, smu, ssd, coef, tau, youden   (plus droplet/panel_seed/feature_basis
#     path markers),
#   * a binary model payload by extension (.npz .npy .pt .pkl .safetensors .bin
#     .onnx .joblib .h5 .hdf5 .ckpt .gguf),
#   * a long base64-looking blob (> 200 chars of pure b64 — smuggled tensor bytes).
#
# The client is allowed exactly one kind of number: the user's own 16-float state
# vector flowing through at runtime. Nothing in the shipped bytes may look like
# model internals.
#
# Usage: scripts/scan_ip.sh [dist-dir] [version]
#     default dist-dir: dist/ ; default version: the one declared in pyproject.toml
#     (pass "all" to scan every artifact in the dir, e.g. for historical audits).
#     Exit 0 = PASS.
set -euo pipefail
DIST_DIR="${1:-dist}"
cd "$(dirname "$0")/.."
python3 - "$DIST_DIR" "${2:-}" <<'PYEOF'
import base64, os, re, sys, tarfile, zipfile

dist = sys.argv[1]
want = sys.argv[2]
if not want:
    m = re.search(r'^version\s*=\s*"([^"]+)"', open("pyproject.toml").read(), re.M)
    if not m:
        print("SCAN FAIL: cannot resolve version from pyproject.toml"); sys.exit(1)
    want = m.group(1)
arts = sorted(f for f in os.listdir(dist)
              if f.endswith(".whl") or f.endswith(".tar.gz"))
if want != "all":
    arts = [f for f in arts if ("-" + want) in f or (want + ".tar.gz") in f]
if not arts:
    print("SCAN FAIL: no wheel/sdist found in %s" % dist); sys.exit(1)

SUBSTR = ["thr_bits", "auroc", "ridge", "transport", "mu_x", "sd_x", "coef",
          "youden", "droplet", "panel_seed", "feature_basis", "capture_layer"]
BOUNDED = ["tau", "smu", "ssd"]
kw_sub = re.compile("|".join(re.escape(k) for k in SUBSTR), re.IGNORECASE)
kw_word = re.compile(r"(?<![A-Za-z0-9_])(%s)(?![A-Za-z0-9_])" % "|".join(BOUNDED),
                     re.IGNORECASE)
float_run = re.compile(r"[-+]?\d+\.\d+(?:\s*,\s*[-+]?\d+\.\d+){32,}")
b64_blob = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")
BIN_EXT = {".npz", ".npy", ".pt", ".pkl", ".joblib", ".safetensors", ".bin",
           ".onnx", ".h5", ".hdf5", ".ckpt", ".gguf"}
TEXT_EXT = {".py", ".md", ".txt", ".json", ".cfg", ".toml", ".rst", ""}

def members(path):
    if path.endswith(".whl"):
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if not n.endswith("/"):
                    yield n, z.read(n)
    else:
        with tarfile.open(path, "r:gz") as t:
            for m in t.getmembers():
                if m.isfile():
                    yield m.name, t.extractfile(m).read()

bad = 0
for a in arts:
    p = os.path.join(dist, a)
    hits = []
    for name, data in members(p):
        ext = os.path.splitext(name)[1].lower()
        if ext in BIN_EXT:
            hits.append("BINARY PAYLOAD: %s" % name)
            continue
        if ext not in TEXT_EXT:
            # unknown extension: still keyword-scan raw bytes
            pass
        txt = data.decode("utf-8", errors="replace")
        for rx, label in ((kw_sub, "keyword"), (kw_word, "word")):
            for m in set(x.group(0).lower() for x in rx.finditer(txt)):
                hits.append("%s '%s' in %s" % (label, m, name))
        for m in float_run.finditer(txt):
            n = m.group(0).count(",") + 1
            hits.append("float array len %d (>32) in %s" % (n, name))
        for m in b64_blob.finditer(txt):
            try:
                raw = base64.b64decode(m.group(0) + "==", validate=False)
                if len(raw) > 128:
                    hits.append("base64 blob (%d B decoded) in %s" % (len(raw), name))
            except Exception:
                hits.append("base64-like blob in %s" % name)
    if hits:
        bad = 1
        print("SCAN FAIL %s:" % a)
        for h in hits:
            print("   - %s" % h)
    else:
        print("SCAN OK   %s (%d members)" % (a, sum(1 for _ in members(p))))

sys.exit(bad)
PYEOF
