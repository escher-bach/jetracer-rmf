# rmf-web api-server configuration for the jetracer fleet.
#
# Point the server at this file:
#   RMF_API_SERVER_CONFIG=/abs/path/to/jetracer_api_server_config.py rmf_api_server
#
# The path is loaded with importlib (see api_server/app_config.py), and the
# resulting module must define a `config` dict containing EVERY AppConfig field
# -- hence importing default_config and updating it rather than writing a dict
# from scratch. A missing key is a TypeError at startup, not a default.
#
# Do NOT use upstream's sqlite_local_config.py: it sets
# ros_args = ["-p", "use_sim_time:=true"], which is correct for their simulation
# demos and wrong here. With use_sim_time on and no /clock publisher, the
# server's ROS node blocks on a clock that never ticks.

import os
from pathlib import Path

from api_server.default_config import config

# Kept outside the colcon install tree on purpose: this holds the task-history
# database, and `colcon build` would otherwise wipe it. Override with
# RMF_WEB_RUN_DIR.
run_dir = Path(os.environ.get("RMF_WEB_RUN_DIR", Path.home() / ".rmf_web" / "run"))
cache_dir = run_dir / "cache"
# The building-map handler writes floorplan images here and serves URLs pointing
# at them; if the directory is missing the map fails to cache. Upstream's dev
# script handles this with a `mkdir -p run/cache` before launching -- doing it
# here means there is no setup step to forget.
cache_dir.mkdir(parents=True, exist_ok=True)


def _system_timezone() -> str:
    """
    Resolve the system timezone.

    default_config.py notes that this must match the system timezone and the
    browser's, since cross-timezone scheduling is unsupported. Reading it beats
    hardcoding a value that silently disagrees with the machine.
    """
    tz = os.environ.get("TZ")
    if tz:
        return tz
    try:
        return Path("/etc/timezone").read_text(encoding="utf-8").strip() or "UTC"
    except OSError:
        return "UTC"


config.update(
    {
        # Persistent, unlike the default sqlite://:memory:, so task history
        # survives a restart.
        "db_url": f"sqlite://{run_dir}/db.sqlite3",
        "cache_directory": str(cache_dir),
        # Empty on purpose -- real robots, real clock. See the note above.
        "ros_args": [],
        "log_level": "INFO",
        "timezone": _system_timezone(),
        # host/port/public_url inherit the defaults (127.0.0.1:8000). If the
        # dashboard in Docker cannot reach the server, set "host": "0.0.0.0"
        # rather than changing the dashboard's RMF_SERVER_URL.
    }
)
