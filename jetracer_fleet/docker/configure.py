"""Translate deployment settings to the adapter's standard config formats."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import yaml
import zenoh
from ament_index_python.packages import get_package_share_directory


def configure():
    endpoint = os.environ["ZENOH_ROUTER_ENDPOINT"].strip()
    if not endpoint.startswith(("tcp/", "tls/", "quic/", "udp/")):
        raise ValueError("ZENOH_ROUTER_ENDPOINT must be a Zenoh endpoint, e.g. tcp/192.168.1.10:7447")
    public_url = os.environ.get("RMF_PUBLIC_URL", "http://localhost:8080").rstrip("/")
    url = urlsplit(public_url)
    if url.scheme not in ("http", "https") or not url.netloc or url.path:
        raise ValueError("RMF_PUBLIC_URL must be an HTTP(S) origin, e.g. http://192.168.1.10:8080")
    share = Path(get_package_share_directory("jetracer_fleet"))
    output = Path("/run/jetracer")
    output.mkdir(parents=True, exist_ok=True)

    config = zenoh.Config.from_file(str(share / "config/zenoh/jetracer_fleet_adapter_zenoh_config.json5"))
    config.insert_json5("connect/endpoints", json.dumps([endpoint]))
    config.insert_json5("scouting/multicast/enabled", "false")
    (output / "zenoh.json5").write_text(str(config), encoding="utf-8")

    # Rebase the old operator-home path in a generated copy, retaining calibration.
    fleet = yaml.safe_load((share / "config/fleet/jetracer_fleet_config.yaml").read_text())
    rmf = fleet["rmf_fleet"]
    for robot in [rmf.get("robot_defaults", {}), *rmf.get("robots", {}).values()]:
        for level in robot.get("maps", {}).values():
            if "map_url" in level:
                level["map_url"] = str(share / "maps/jetracer" / Path(level["map_url"]).name)
    (output / "fleet.yaml").write_text(yaml.safe_dump(fleet, sort_keys=False), encoding="utf-8")
    print(f"Robot router: {endpoint}; dashboard: {public_url}; ROS domain: {os.environ.get('ROS_DOMAIN_ID', '52')}")


if __name__ == "__main__":
    configure()
