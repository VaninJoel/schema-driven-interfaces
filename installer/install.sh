#!/usr/bin/env bash
# On-target installer (Linux/macOS). This script is bundled INTO the
# self-extracting .sh by build.sh (via makeself) and runs after extraction,
# with the working directory set to the extracted payload (vc_env.tar.gz +
# payload/ alongside it).
#
# It relocates a conda-pack'd environment to a user-chosen prefix, repairs the
# hard-coded prefixes (conda-unpack), drops in the app code + model data, and
# creates `vcornea-gui` / `angio-gui` launchers plus desktop / app-menu
# shortcuts. No conda, no internet, no `conda activate` required afterward.
set -euo pipefail

DEFAULT_PREFIX="$HOME/SchemaDrivenInterfaces"
PREFIX="${SDI_PREFIX:-}"

# Prompt for an install location unless one was provided (or we're non-interactive).
if [ -z "$PREFIX" ]; then
    if [ -t 0 ]; then
        printf "Install location [%s]: " "$DEFAULT_PREFIX"
        read -r reply || true
        PREFIX="${reply:-$DEFAULT_PREFIX}"
    else
        PREFIX="$DEFAULT_PREFIX"
    fi
fi
# Expand a leading ~ and make absolute.
PREFIX="${PREFIX/#\~/$HOME}"
mkdir -p "$PREFIX"
PREFIX="$(cd "$PREFIX" && pwd)"

echo "Installing Schema-Driven Interfaces to: $PREFIX"

echo "  - unpacking environment (this is the large step)..."
tar -xzf vc_env.tar.gz -C "$PREFIX"

echo "  - finalizing environment (conda-unpack)..."
"$PREFIX/bin/python" "$PREFIX/bin/conda-unpack"

echo "  - installing application files..."
SDI="$PREFIX/share/sdi"
mkdir -p "$SDI"
rm -rf "$SDI/payload"
cp -r payload "$SDI/payload"
APPS="$SDI/payload"

# --- Launchers on PATH ---
make_launcher() {
    local name="$1" rel="$2"
    cat > "$PREFIX/bin/$name" <<EOF
#!/usr/bin/env bash
exec "$PREFIX/bin/python" "$APPS/$rel/run_gui.py" "\$@"
EOF
    chmod +x "$PREFIX/bin/$name"
}
make_launcher vcornea-gui vcornea-gui
make_launcher angio-gui   angio-gui

# --- Desktop / application-menu shortcuts ---
OS="$(uname -s)"
if [ "$OS" = "Linux" ]; then
    APPDIR="$HOME/.local/share/applications"; mkdir -p "$APPDIR"
    make_desktop() {
        local file="$1" title="$2" launcher="$3"
        cat > "$APPDIR/$file" <<EOF
[Desktop Entry]
Type=Application
Name=$title
Comment=Schema-Driven Interfaces — agent-based biological model GUI
Exec=$PREFIX/bin/$launcher
Terminal=false
Categories=Science;Education;
EOF
        chmod +x "$APPDIR/$file"
        [ -d "$HOME/Desktop" ] && cp "$APPDIR/$file" "$HOME/Desktop/$file" \
            && chmod +x "$HOME/Desktop/$file" || true
    }
    make_desktop sdi-vcornea.desktop "V-Cornea Simulation" vcornea-gui
    make_desktop sdi-angio.desktop   "Angiogenesis Simulation" angio-gui

elif [ "$OS" = "Darwin" ]; then
    DESK="$HOME/Desktop"; mkdir -p "$DESK"
    make_command() {
        local file="$1" launcher="$2"
        cat > "$DESK/$file" <<EOF
#!/usr/bin/env bash
exec "$PREFIX/bin/$launcher"
EOF
        chmod +x "$DESK/$file"
    }
    make_command "V-Cornea Simulation.command" vcornea-gui
    make_command "Angiogenesis Simulation.command" angio-gui
fi

cat <<EOF

Schema-Driven Interfaces installed successfully.

  Launch from the desktop / application menu, or from a terminal:
      $PREFIX/bin/vcornea-gui
      $PREFIX/bin/angio-gui

EOF
