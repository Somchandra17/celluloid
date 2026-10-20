#!/bin/sh
# Linux/macOS entrypoint. All application setup lives in setup_celluloid.py.
set -eu
CELLULOID_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

run_python() {
    for candidate in python3 /usr/bin/python3 /Applications/LibreOffice.app/Contents/Resources/python /opt/homebrew/bin/python3 /usr/local/bin/python3; do
        if command -v "$candidate" >/dev/null 2>&1 &&
           "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
            exec "$candidate" "$CELLULOID_ROOT/setup_celluloid.py" "$@"
        fi
    done
}

run_python "$@"
case " $* " in
    *" --dry-run "*|*" --check "*|*" --no-install "*|*" --help "*)
        echo 'Python 3.10+ is required. No changes made. Install it with your package manager.'
        exit 1 ;;
esac
echo 'Installing Python first; the shared setup script will install/check LibreOffice next.'
case "$(uname -s)" in
    Darwin)
        if command -v brew >/dev/null 2>&1; then
            CELLULOID_BREW=$(command -v brew)
        elif [ -x /opt/homebrew/bin/brew ]; then
            CELLULOID_BREW=/opt/homebrew/bin/brew
        elif [ -x /usr/local/bin/brew ]; then
            CELLULOID_BREW=/usr/local/bin/brew
        else
            echo 'Install Homebrew from https://brew.sh/ and rerun this command.'
            exit 1
        fi
        "$CELLULOID_BREW" install python
        CELLULOID_PY_PREFIX=$("$CELLULOID_BREW" --prefix)
        PATH="$CELLULOID_PY_PREFIX/bin:$PATH"
        export PATH
        ;;
    Linux)
        if [ "$(id -u)" -eq 0 ]; then
            CELLULOID_SUDO=''
        elif command -v sudo >/dev/null 2>&1; then
            CELLULOID_SUDO=sudo
        else
            echo 'Python installation needs sudo or administrator assistance.'
            exit 1
        fi
        if command -v apt-get >/dev/null 2>&1; then
            $CELLULOID_SUDO apt-get update
            $CELLULOID_SUDO apt-get install -y python3
        elif command -v dnf >/dev/null 2>&1; then
            $CELLULOID_SUDO dnf install -y python3
        elif command -v pacman >/dev/null 2>&1; then
            $CELLULOID_SUDO pacman -S --needed python
        else
            echo 'Install Python 3.10+ for your distribution, then rerun setup.'
            exit 1
        fi
        ;;
    *) echo 'Use setup.cmd on Windows, or run setup_celluloid.py with Python 3.10+.'; exit 1 ;;
esac
run_python "$@"
echo 'Python 3.10+ was not found after installation. Check your OS version and reopen Terminal.'
exit 1
