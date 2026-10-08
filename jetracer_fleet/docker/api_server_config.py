"""Use the site's persistent real-clock API configuration behind nginx."""

import os
import runpy
from pathlib import Path

from ament_index_python.packages import get_package_share_directory

share = Path(get_package_share_directory("jetracer_fleet"))
config = runpy.run_path(str(share / "config/rmf_web/jetracer_api_server_config.py"))["config"]
config.update(
    host="127.0.0.1",
    port=8000,
    public_url=os.environ.get("RMF_PUBLIC_URL", "http://localhost:8080").rstrip("/") + "/api",
)
