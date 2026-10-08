"""Check supervision, HTTP, trajectory socket, and essential ROS participants."""

import socket
import subprocess
import time
from urllib.request import urlopen

import rclpy
import yaml
from rclpy.node import Node


def main():
    status = subprocess.check_output(
        ["/usr/bin/supervisorctl", "-c", "/etc/supervisor/supervisord.conf", "status"],
        text=True, timeout=2,
    )
    if len(status.splitlines()) != 4 or any("RUNNING" not in line for line in status.splitlines()):
        raise RuntimeError(status)
    for url in ("http://127.0.0.1:8080/healthz", "http://127.0.0.1:8080/api/openapi.json"):
        with urlopen(url, timeout=2) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP check failed: {url}")
    with socket.create_connection(("127.0.0.1", 8006), timeout=2):
        pass
    with open("/run/jetracer/fleet.yaml", encoding="utf-8") as stream:
        fleet_name = yaml.safe_load(stream)["rmf_fleet"]["name"]
    required = {"rmf_traffic_schedule_primary", "rmf_task_dispatcher", f"{fleet_name}_command_handle"}
    rclpy.init()
    node = Node("jetracer_container_healthcheck", enable_rosout=False)
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if required.issubset(set(node.get_node_names())):
                return
            rclpy.spin_once(node, timeout_sec=0.1)
        raise RuntimeError(f"Missing ROS nodes: {required - set(node.get_node_names())}")
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
