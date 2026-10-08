#!/bin/bash
set -eo pipefail
source /opt/ros/jazzy/setup.bash
source /opt/fleet_ws/install/setup.bash
if [ "${1:-}" = /usr/bin/supervisord ]; then
  python3 /opt/jetracer/configure.py
fi
exec "$@"
