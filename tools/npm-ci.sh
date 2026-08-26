#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
node -e 'if (+process.versions.node.split(".")[0] < 20) process.exit(1)' || {
    echo "Node.js 20 or newer is required" >&2
    exit 1
}
mkdir -p "$ROOT/.build-tools/npm-cache" "$ROOT/.build-tools/puppeteer-cache"
export npm_config_cache="$ROOT/.build-tools/npm-cache"
export PUPPETEER_CACHE_DIR="$ROOT/.build-tools/puppeteer-cache"
exec npm ci --prefix "$ROOT/tools" "$@"
