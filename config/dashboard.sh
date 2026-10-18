#!/bin/sh
# Open the dashboard from this repo, then ask for Google sign-in if needed.
set -u

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$ROOT"
export VIVEDASH_ROOT="$ROOT"
export VIVEDASH_PICTURES="$ROOT/Pictures"
mkdir -p "$HOME/.config/vivedash"

if [ -z "${WTFUTIL:-}" ]; then
    case "$(uname -s)" in
        Linux)
            BREW_PREFIX="${HOMEBREW_PREFIX:-/home/linuxbrew/.linuxbrew}"
            ;;
        Darwin)
            BREW_PREFIX="${HOMEBREW_PREFIX:-/opt/homebrew}"
            if [ ! -d "$BREW_PREFIX" ] && [ -d /usr/local/Homebrew ]; then
                BREW_PREFIX=/usr/local
            fi
            ;;
        *)
            echo "Unsupported operating system: $(uname -s)" >&2
            exit 1
            ;;
    esac
    WTFUTIL="$BREW_PREFIX/bin/wtfutil"
fi
if [ ! -x "$WTFUTIL" ]; then
    echo "Install wtfutil first: brew install wtfutil" >&2
    exit 1
fi

RUNTIME=$(mktemp)
sed "s#config/#$ROOT/config/#g" "$ROOT/config/config.yml" > "$RUNTIME"

"$WTFUTIL" --config "$RUNTIME" "$@" &
wtf_pid=$!

if ! python3 "$ROOT/config/login.py" --check; then
    python3 "$ROOT/config/login.py" >>"$HOME/.config/vivedash/login.log" 2>&1 &
fi

"$ROOT/config/palm-photo-service.sh" start "$wtf_pid" || true
wait "$wtf_pid"
rm -f "$RUNTIME"
