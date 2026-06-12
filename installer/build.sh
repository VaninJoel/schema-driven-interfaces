#!/usr/bin/env bash
# Build the Schema-Driven Interfaces desktop installer for the CURRENT OS
# (Linux/macOS) using conda-pack + makeself.
#
# Unlike a constructor build, this does NOT re-solve the environment — it packs
# the EXACT environment created from environment.yml, which is the only reliable
# way to ship CompuCell3D 4.7.0 (whose conda packages don't resolve against
# conda-forge alone; see README.md).
#
#   1. create/refresh the conda env from ../environment.yml   (uses defaults)
#   2. reinstall the two wrapper packages non-editable (relocatable)
#   3. conda-pack the env to a relocatable tarball
#   4. stage the app code + model data (sibling layout preserved)
#   5. makeself everything + install.sh into a single self-extracting installer
#
# Requires: conda on PATH, and conda-pack + makeself available
#   (conda install -n base -c conda-forge conda-pack makeself).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
ENV_NAME="${SDI_ENV_NAME:-sdi-dist}"
STAGE="$HERE/stage"
DIST="$HERE/dist"
VERSION="$(grep -m1 '^version' "$REPO/vivarium-vcornea/pyproject.toml" | tr -d ' "' | cut -d= -f2 || echo 0.1.0)"

case "$(uname -s)" in
    Linux)  OSTAG="Linux-$(uname -m)";;
    Darwin) OSTAG="macOS-$(uname -m)";;
    *)      OSTAG="$(uname -s)-$(uname -m)";;
esac
INSTALLER="$DIST/SchemaDrivenInterfaces-${VERSION}-${OSTAG}.sh"

# shellcheck disable=SC1091
source "$(conda info --base)/etc/profile.d/conda.sh"

echo ">> [1/5] Creating conda env '$ENV_NAME' from environment.yml"
if conda env list | grep -qE "^$ENV_NAME\s"; then
    conda env update -n "$ENV_NAME" -f "$REPO/environment.yml" --prune
else
    # environment.yml's name: is 'vc'; -n overrides it for the dist build.
    conda env create -n "$ENV_NAME" -f "$REPO/environment.yml"
fi

echo ">> [2/5] Reinstalling wrapper packages non-editable (relocatable)"
TMPWHL="$(mktemp -d)"
conda run -n "$ENV_NAME" python -m pip wheel "$REPO/vivarium-vcornea" "$REPO/vivarium-angio" \
    -w "$TMPWHL" --no-deps
conda run -n "$ENV_NAME" python -m pip install --no-deps --force-reinstall "$TMPWHL"/*.whl

echo ">> [3/5] Packing environment (conda-pack)"
rm -rf "$STAGE" "$DIST"; mkdir -p "$STAGE/payload" "$DIST"
# Use the conda-pack executable (installed in base), not a `conda pack`
# subcommand — the latter isn't registered as a conda plugin in all versions.
conda run -n base conda-pack -n "$ENV_NAME" -o "$STAGE/vc_env.tar.gz" --force

echo ">> [4/5] Staging app code + model data"
for item in vcornea-gui angio-gui vivarium-vcornea vivarium-angio vcornea_paper \
            README.md INSTALL.md; do
    cp -r "$REPO/$item" "$STAGE/payload/"
done
find "$STAGE/payload" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE/payload" -type d -name experiments -prune -exec rm -rf {} + 2>/dev/null || true
cp "$HERE/install.sh" "$STAGE/install.sh"
chmod +x "$STAGE/install.sh"

echo ">> [5/5] Building self-extracting installer with makeself"
# makeself lives in base (not on PATH here), same as conda-pack above.
conda run -n base makeself --gzip "$STAGE" "$INSTALLER" \
    "Schema-Driven Interfaces installer" ./install.sh

echo ">> Done: $INSTALLER"
ls -lh "$INSTALLER"
