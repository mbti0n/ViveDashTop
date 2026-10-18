#!/bin/sh
set -u

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
PHOTO_SERVICE="$HOME/.config/wtf/palm-photo-service.sh"

"$WTFUTIL" "$@" &
wtf_pid=$!
"$PHOTO_SERVICE" start "$wtf_pid"
wait "$wtf_pid"
