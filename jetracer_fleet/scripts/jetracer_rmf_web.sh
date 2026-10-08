#!/bin/bash
# Start the rmf-web side of the jetracer stack in one terminal: the native API
# server plus the custom dashboard.
#
#   ros2 run jetracer_fleet jetracer_rmf_web.sh
#
# The ROS side is separate -- start it first with:
#   ros2 launch jetracer_fleet jetracer_bringup.launch.xml \
#     server_uri:=ws://localhost:8000/_internal
#
# Ctrl+C stops both. The API server runs in the background logging to a file
# (it is chatty and its output would drown the dashboard's); the dashboard runs
# in the foreground so you can see its URL and any build errors.
#
# The API server is NOT containerised on purpose -- under this machine's WSL2
# mirrored networking a container both steals the DDS discovery port and fails
# to join the ROS graph. See rmf-web-jetracer-dashboard.md.
set -uo pipefail

VENV=${RMF_WEB_VENV:-$HOME/rmf_web_venv}
API_LOG=${RMF_API_LOG:-$HOME/rmf_api.log}
API_PID=""

cleanup() {
  echo
  echo "Shutting down..."
  if [ -n "$API_PID" ] && kill -0 "$API_PID" 2>/dev/null; then
    kill "$API_PID" 2>/dev/null
    wait "$API_PID" 2>/dev/null
    echo "  api server stopped"
  fi
}
trap cleanup INT TERM EXIT

# --- preflight -------------------------------------------------------------
[ -x "$VENV/bin/rmf_api_server" ] || {
  echo "ERROR: $VENV/bin/rmf_api_server not found."
  echo "Run the one-time install (note the jazzy branch):"
  echo "  git clone -b jazzy https://github.com/open-rmf/rmf-web.git ~/rmf-web"
  echo "  python3 -m venv --system-site-packages $VENV"
  echo "  $VENV/bin/pip install -e ~/rmf-web/packages/api-server"
  exit 1
}

command -v ros2 >/dev/null || {
  echo "ERROR: ros2 not on PATH. Source the workspace first:"
  echo "  source ~/ff_ws/install/setup.bash"
  exit 1
}

SHARE=$(ros2 pkg prefix jetracer_fleet)/share/jetracer_fleet
CONFIG=$SHARE/config/rmf_web/jetracer_api_server_config.py
BUILD_SCRIPT=$SHARE/dashboard/build_jetracer_dashboard.sh

[ -f "$CONFIG" ] || { echo "ERROR: api server config missing: $CONFIG"; exit 1; }
[ -x "$BUILD_SCRIPT" ] || { echo "ERROR: dashboard build script missing or not executable: $BUILD_SCRIPT"; exit 1; }

echo "ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-<unset>}  RMW=${RMW_IMPLEMENTATION:-<default>}"
if [ -z "${ROS_DOMAIN_ID:-}" ]; then
  echo "WARNING: ROS_DOMAIN_ID is unset, so this shell is on domain 0."
  echo "         ~/.bashrc sets 52 for interactive shells; non-interactive ones"
  echo "         do not source it. The api server will start but see no ROS."
fi

# --- api server -------------------------------------------------------------
if ss -ltn 2>/dev/null | grep -q ':8000'; then
  echo "Something is already listening on :8000 -- assuming the api server is up."
  echo "  (if that is a leftover, kill it with: pkill -f rmf_api_server)"
else
  echo "Starting api server (log: $API_LOG)..."
  RMF_API_SERVER_CONFIG="$CONFIG" "$VENV/bin/rmf_api_server" > "$API_LOG" 2>&1 &
  API_PID=$!

  for _ in $(seq 1 20); do
    sleep 1
    ss -ltn 2>/dev/null | grep -q ':8000' && break
    kill -0 "$API_PID" 2>/dev/null || {
      echo "ERROR: api server exited during startup. Last lines of $API_LOG:"
      tail -20 "$API_LOG"
      exit 1
    }
  done

  if ss -ltn 2>/dev/null | grep -q ':8000'; then
    echo "  api server listening on :8000"
  else
    echo "WARNING: :8000 not listening after 20s; continuing anyway. Check $API_LOG"
  fi

  # The building map arrives over DDS. Its absence is the classic silent failure
  # -- everything else works and only the floorplan is missing -- so say so here
  # rather than leaving it to be discovered in the browser.
  if grep -q 'saved new file' "$API_LOG" 2>/dev/null; then
    echo "  building map received from RMF core"
  else
    echo "  NOTE: no building map yet. Expected if RMF core is not running."
    echo "        Start it with: ros2 launch jetracer_fleet jetracer_bringup.launch.xml \\"
    echo "                         server_uri:=ws://localhost:8000/_internal"
    echo "        Verify later with: ros2 topic info /map --verbose"
  fi
fi

# --- dashboard (foreground) -------------------------------------------------
echo
echo "Starting dashboard (Ctrl+C stops both)..."
echo
# Deliberately NOT `exec`: that would replace this shell and discard the trap,
# orphaning the api server on Ctrl+C.
"$BUILD_SCRIPT" dev
