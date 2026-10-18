#!/bin/sh
set -u

WTFUTIL="${WTFUTIL:-/home/linuxbrew/.linuxbrew/bin/wtfutil}"
PHOTO_SERVICE="$HOME/.config/wtf/palm-photo-service.sh"

"$WTFUTIL" "$@" &
wtf_pid=$!
"$PHOTO_SERVICE" start "$wtf_pid"
wait "$wtf_pid"
