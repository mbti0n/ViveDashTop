#!/bin/sh
# Run one dashboard widget with this repo on the path, no matter where wtfutil was started.
set -u

DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$DIR/.." && pwd)
export VIVEDASH_ROOT="$ROOT"
export VIVEDASH_PICTURES="${VIVEDASH_PICTURES:-$ROOT/Pictures}"
cd "$ROOT"
exec python3 "$DIR/$1"
