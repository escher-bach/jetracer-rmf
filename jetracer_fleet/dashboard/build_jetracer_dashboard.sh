#!/bin/bash
# Build or serve the jetracer rmf-web dashboard.
#
#   ./build_jetracer_dashboard.sh dev     # vite dev server (default), :5173
#   ./build_jetracer_dashboard.sh build   # production build -> dist/
#
# Why this exists: defaultZoom and allowedTasks are compiled into the dashboard
# bundle -- no environment variable can change them -- so a fleet-appropriate
# dashboard requires a build. See ../dashboard/main.tsx for the two changes.
#
# rmf-web is NOT forked. This copies main.tsx/index.html from jetracer_fleet into
# a new `examples/jetracer` directory inside the checkout, which upstream's own
# tooling then treats like any other example.
set -euo pipefail

RMF_WEB=${RMF_WEB:-$HOME/rmf-web}
FRAMEWORK="$RMF_WEB/packages/rmf-dashboard-framework"
EXAMPLE="$FRAMEWORK/examples/jetracer"
SRC=$(cd "$(dirname "$0")" && pwd)
MODE=${1:-dev}

# --- preflight -------------------------------------------------------------
[ -d "$FRAMEWORK" ] || {
  echo "ERROR: $FRAMEWORK not found."
  echo "Clone it first (note the jazzy branch -- main does not build against released Jazzy):"
  echo "  git clone -b jazzy https://github.com/open-rmf/rmf-web.git $RMF_WEB"
  exit 1
}

branch=$(git -C "$RMF_WEB" rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)
[ "$branch" = "jazzy" ] || echo "WARNING: rmf-web is on branch '$branch', expected 'jazzy'."

# rmf-web's root package.json declares engines: node >=20, pnpm >=9.0.0, and
# npm >=99 -- that last one is a deliberate guard so `npm install` always fails
# and you are pushed onto pnpm. Do not try to work around it with npm.
if ! command -v node >/dev/null; then
  cat <<'EOF'
ERROR: node not installed. rmf-web requires Node >= 20.

Ubuntu 24.04's `nodejs` apt package is 18.x, which is too old, so install from
NodeSource:

  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
  sudo apt-get install -y nodejs
  sudo corepack enable

Then re-run this script.
EOF
  exit 1
fi

node_major=$(node --version | sed 's/^v\([0-9]*\).*/\1/')
echo "node $(node --version)"
[ "$node_major" -ge 20 ] || {
  echo "ERROR: node $node_major is too old; rmf-web requires >= 20 (see above for NodeSource install)."
  exit 1
}

if ! command -v pnpm >/dev/null; then
  echo "pnpm not found; enabling via corepack..."
  corepack enable 2>/dev/null || sudo corepack enable || {
    echo "ERROR: could not enable corepack. Install pnpm >= 9 manually."
    exit 1
  }
fi

# Pin pnpm to 9.x. `corepack enable` alone installs the latest pnpm (11.x at time
# of writing), which breaks this workspace in two ways:
#
#   1. pnpm 10+ ignores the `pnpm` field in package.json, so upstream's
#      `pnpm.overrides` dependency pins are silently dropped. rmf-web is mid
#      migration on this -- see their commit "move pnpm overrides (#1092)".
#   2. pnpm 10+ blocks package build scripts by default, giving
#      ERR_PNPM_IGNORED_BUILDS for esbuild and @swc/core. Both are needed here:
#      vite depends on esbuild, and examples/shared/vite.config.ts uses
#      @vitejs/plugin-react-swc. Without their postinstall the binaries are
#      missing and the dev server fails to start.
#
# pnpm 9 satisfies the repo's `engines: pnpm >=9.0.0`, runs build scripts by
# default, and still honours pnpm.overrides.
pnpm_major=$(pnpm --version 2>/dev/null | cut -d. -f1 || echo 0)
if [ "$pnpm_major" != "9" ]; then
  echo "pnpm $pnpm_major detected; pinning to 9.x for this workspace..."
  corepack prepare pnpm@9 --activate || {
    echo "ERROR: could not activate pnpm 9 via corepack."
    exit 1
  }
  if [ -d "$RMF_WEB/node_modules" ]; then
    echo
    echo "NOTE: node_modules exists from an install by a different pnpm major."
    echo "That tree may be missing build scripts. If the dev server misbehaves:"
    echo "  rm -rf $RMF_WEB/node_modules $RMF_WEB/packages/*/node_modules"
    echo "then re-run this script."
    echo
  fi
fi
echo "pnpm $(pnpm --version)"

# --- sync our config into the checkout --------------------------------------
mkdir -p "$EXAMPLE"
cp "$SRC/main.tsx" "$SRC/index.html" "$EXAMPLE/"
echo "synced main.tsx + index.html -> $EXAMPLE"

# --- install workspace deps (idempotent) ------------------------------------
cd "$RMF_WEB"
echo "installing workspace dependencies (first run takes a few minutes)..."
pnpm install

# --- run --------------------------------------------------------------------
cd "$FRAMEWORK"
case "$MODE" in
  dev)
    echo
    echo "Starting vite dev server. Open http://localhost:5173"
    echo "(The API server must already be running on :8000 -- it is a separate process.)"
    pnpm start:example examples/jetracer
    ;;
  build)
    pnpm build:example examples/jetracer
    echo
    echo "Built. Static output is under $FRAMEWORK/dist"
    echo "Serve it with SPA fallback, e.g.:  pnpm exec vite preview -c examples/shared/vite.config.ts"
    ;;
  *)
    echo "Unknown mode '$MODE'. Use 'dev' or 'build'."
    exit 1
    ;;
esac
