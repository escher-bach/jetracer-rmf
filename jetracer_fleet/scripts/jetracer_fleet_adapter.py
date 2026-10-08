#!/usr/bin/env python3

# Copyright 2024 Open Source Robotics Foundation, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Fleet adapter entry point for the jetracer fleet: upstream free_fleet_adapter's
fleet_adapter.py, with resilient runtime robot onboarding.

Derived from free_fleet_adapter/fleet_adapter.py (Apache-2.0, Open Source
Robotics Foundation). `free_fleet` itself is NOT modified -- Nav2RobotAdapter,
Nav1RobotAdapter, compute_transforms and update_robot are all imported from it
as a library. The only behavioural change is in the robot bring-up loop.

Why this exists
---------------
Upstream builds every robot in a bare loop:

    for robot_name in fleet_config.known_robots:
        robots[robot_name] = Nav2RobotAdapter(...)

and Nav2RobotAdapter.__init__ raises RuntimeError if the robot's tf never
arrives within init_timeout_sec. Nothing isolates that failure to the robot
that caused it, so one robot being off kills the whole process -- taking down
every robot that had already registered with it. That makes a partial fleet
impossible to run: you cannot bring up bot1 alone, and losing bot2 during
startup loses bot1 too.

Here each configured robot is constructed independently. In addition, a
wildcard Zenoh subscription discovers live ``jetracer_*`` namespaces from
their TF topics, assigns each one an unused parking waypoint, and adds it to
the running RMF fleet without restarting the adapter. Pass --require-all-robots
to restore upstream's fail-fast behaviour for any legacy, explicitly listed
robots.
"""

import argparse
import asyncio
from copy import deepcopy
import queue
import sys
import threading
import time

from free_fleet.utils import namespacify
from free_fleet_adapter.fleet_adapter import compute_transforms, update_robot
from free_fleet_adapter.nav1_robot_adapter import Nav1RobotAdapter
from free_fleet_adapter.nav2_robot_adapter import (
    Nav2RobotAdapter,
    Nav2TfHandler,
)
from jetracer_onboarding import (
    DiscoveryGate,
    ParkingAllocator,
    robot_name_from_tf_key,
)
import rclpy
from rclpy.duration import Duration
from rclpy.experimental import EventsExecutor
import rclpy.node
from rclpy.parameter import Parameter
import rclpy.time
import rmf_adapter
from rmf_adapter import Adapter
import rmf_adapter.easy_full_control as rmf_easy
import rmf_adapter.fleet_update_handle as rmf_fleet
from tf2_ros import Buffer
import yaml
import zenoh


# ------------------------------------------------------------------------------
# Robot bring-up
# ------------------------------------------------------------------------------
def wait_for_robot_tf(
    robot_name,
    robot_config_yaml,
    node,
    zenoh_session,
    tf_buffer,
    timeout_sec,
    cancel_event=None
):
    """
    Wait for the robot's map->base_footprint transform to arrive over zenoh.

    Returns True if it arrived within timeout_sec.

    Why this is a separate pre-check rather than just letting
    Nav2RobotAdapter.__init__ time out: __init__ creates a 1-second ROS timer
    and three zenoh subscribers BEFORE its own tf wait, and on timeout it
    raises without destroying the timer (destroy_timer sits after the raise).
    Upstream never had to care -- the raise killed the process. Now that the
    adapter survives an absent robot, every skipped robot would otherwise leave
    behind a timer logging a failed pose lookup once a second, forever, plus
    three live subscriptions.

    Needs no rclpy spinning: Nav2TfHandler is driven entirely by its zenoh
    subscriber callback, which writes straight into tf_buffer from zenoh's own
    thread. can_transform() is used rather than get_transform() because the
    latter logs at INFO on every miss.
    """
    map_frame = robot_config_yaml.get('map_frame', 'map')
    robot_frame = robot_config_yaml.get('robot_frame', 'base_footprint')

    node.get_logger().info(
        f'Waiting up to {timeout_sec}s for tf from robot [{robot_name}]...'
    )
    probe = Nav2TfHandler(
        robot_name,
        zenoh_session,
        tf_buffer,
        node,
        robot_frame=robot_frame,
        map_frame=map_frame
    )
    try:
        target = namespacify(map_frame, robot_name)
        source = namespacify(robot_frame, robot_name)
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                return False
            if tf_buffer.can_transform(target, source, rclpy.time.Time()):
                return True
            time.sleep(0.2)
        return False
    finally:
        # Hand the tf stream over to the real adapter's own handler. The
        # transforms already received stay in the shared tf_buffer (10s cache),
        # so the adapter's init succeeds on its first tick.
        probe.tf_sub.undeclare()


def build_robot_adapter(
    robot_name,
    robot_config,
    robot_config_yaml,
    fleet_config,
    plugin_config,
    node,
    zenoh_session,
    fleet_handle,
    tf_buffer
):
    """
    Construct the RobotAdapter for a single robot.

    Raises whatever the underlying adapter raises -- the caller decides whether
    a failure is fatal.
    """
    if 'navigation_stack' not in robot_config_yaml:
        raise RuntimeError(
            'Navigation stack must be defined to set up RobotAdapter'
        )

    nav_stack = robot_config_yaml['navigation_stack']
    if nav_stack == 2:
        return Nav2RobotAdapter(
            robot_name,
            robot_config,
            robot_config_yaml,
            plugin_config,
            node,
            zenoh_session,
            fleet_handle,
            fleet_config,
            tf_buffer
        )
    elif nav_stack == 1:
        return Nav1RobotAdapter(
            robot_name,
            robot_config,
            robot_config_yaml,
            node,
            zenoh_session,
            fleet_handle,
            tf_buffer
        )

    raise RuntimeError('Navigation stack can only be 1 (experimental) or 2')


# ------------------------------------------------------------------------------
# Fleet adapter
# ------------------------------------------------------------------------------
def start_fleet_adapter(
    config_path: str,
    nav_graph_path: str,
    zenoh_config_path: str | None,
    server_uri: str | None,
    use_sim_time: bool,
    require_all_robots: bool
):
    print('Starting fleet adapter...')

    # Init adapter
    rmf_adapter.init_rclcpp()

    fleet_config = rmf_easy.FleetConfiguration.from_config_files(
        config_path, nav_graph_path
    )
    assert fleet_config, f'Failed to parse config file [{config_path}]'

    # Parse the yaml in Python to get the fleet_manager info
    with open(config_path, 'r') as f:
        config_yaml = yaml.safe_load(f)

    # ROS 2 node for the command handle
    fleet_name = fleet_config.fleet_name
    node = rclpy.node.Node(f'{fleet_name}_command_handle')

    # Accept server_uri as a ROS parameter as well as a CLI argument.
    #
    # Both this package's launch file and free_fleet_adapter's own
    # fleet_adapter.launch.xml pass it as `<param name="server_uri" .../>`, but
    # upstream's fleet_adapter.py only ever reads it from argparse and never
    # declares or reads the parameter -- so launching via either file leaves
    # server_uri as None and the fleet silently never reports to rmf-web.
    #
    # The symptom is confusing because it is partial: task dispatch still works
    # (rmf_task_dispatcher carries its own server_uri) and trajectories and the
    # floorplan still render (DDS and the building map), but no robots ever
    # appear in the dashboard, because fleet state is the one thing only this
    # process publishes to the API server.
    #
    # CLI wins when both are given.
    node.declare_parameter('server_uri', '')
    if not server_uri:
        param_uri = \
            node.get_parameter('server_uri').get_parameter_value().string_value
        if param_uri:
            server_uri = param_uri
            node.get_logger().info(
                f'Using server_uri from ROS parameter: {server_uri}'
            )

    if server_uri:
        node.get_logger().info(f'Reporting fleet state to [{server_uri}]')
    else:
        node.get_logger().warn(
            'No server_uri set: this fleet will NOT appear in rmf-web. Pass '
            'server_uri:=ws://localhost:8000/_internal to the launch file.'
        )

    adapter = Adapter.make(f'{fleet_name}_fleet_adapter')
    assert adapter, (
        'Unable to initialize fleet adapter. '
        'Please ensure RMF Schedule Node is running'
    )

    # Enable sim time for testing offline
    if use_sim_time:
        param = Parameter('use_sim_time', Parameter.Type.BOOL, True)
        node.set_parameters([param])
        adapter.node.use_sim_time()

    adapter.start()
    time.sleep(1.0)

    fleet_config.server_uri = server_uri

    # Configure the transforms between robot and RMF frames
    for level, coords in config_yaml['reference_coordinates'].items():
        tf = compute_transforms(level, coords, node)
        fleet_config.add_robot_coordinates_transformation(level, tf)

    fleet_handle = adapter.add_easy_fleet(fleet_config)
    assert fleet_handle is not None, \
        'Failed to create EasyFullControl fleet, \
        please verify that the fleet config is valid.'

    # Initialize zenoh
    zenoh_config = zenoh.Config.from_file(zenoh_config_path) \
        if zenoh_config_path is not None else zenoh.Config()
    zenoh_session = zenoh.open(zenoh_config)

    # Set up tf2 buffer
    tf_buffer = Buffer()

    # Set up custom action plugins
    plugin_config = config_yaml.get('plugins')

    def _accept_action(description: dict):
        confirm = rmf_fleet.Confirmation()
        confirm.accept()
        return confirm

    if plugin_config is not None:
        for plugin_name, plugin_data in plugin_config.items():
            plugin_actions = plugin_data.get('actions')
            if not plugin_actions:
                node.get_logger().warn(
                    f'No action provided for plugin [{plugin_name}]! Fleet '
                    f'[{fleet_handle.fleet_name}] will not bid on tasks submitted '
                    f'with actions associated with this plugin unless the action '
                    f'is registered as a performable action for this fleet by '
                    f'the user.'
                )
                continue
            for action in plugin_actions:
                fleet_handle.more().add_performable_action(action, _accept_action)

    # --- Resilient robot onboarding -------------------------------------------
    # Explicitly listed robots are still supported for backwards compatibility.
    # The normal jetracer configuration has no per-robot entries: robots are
    # discovered from their namespaced TF key and admitted by the worker below.
    rmf_fleet_yaml = config_yaml['rmf_fleet']
    known_robots = list(fleet_config.known_robots)
    robots = {}
    robots_lock = threading.RLock()
    admitted = []
    unavailable = {}
    for robot_name in known_robots:
        robot_config_yaml = rmf_fleet_yaml['robots'][robot_name]
        robot_config = fleet_config.get_known_robot_configuration(robot_name)
        timeout_sec = robot_config_yaml.get('init_timeout_sec', 10)

        # Check the robot is actually there BEFORE constructing its adapter --
        # see wait_for_robot_tf's docstring for why this matters now that a
        # failed init no longer takes the process down with it.
        if not wait_for_robot_tf(
            robot_name,
            robot_config_yaml,
            node,
            zenoh_session,
            tf_buffer,
            timeout_sec
        ):
            reason = (
                f'no tf received over zenoh within {timeout_sec}s '
                f'(robot powered off, its zenoh bridge down, the zenoh router '
                f'unreachable, or localization not running)'
            )
            unavailable[robot_name] = reason
            if require_all_robots:
                node.get_logger().error(
                    f'Robot [{robot_name}] is unavailable and '
                    '--require-all-robots was set: aborting.'
                )
                raise RuntimeError(f'Robot [{robot_name}] unavailable: {reason}')
            node.get_logger().warn(
                f'Robot [{robot_name}] is unavailable and has been SKIPPED: '
                f'{reason}'
            )
            continue

        try:
            robots[robot_name] = build_robot_adapter(
                robot_name,
                robot_config,
                robot_config_yaml,
                fleet_config,
                plugin_config,
                node,
                zenoh_session,
                fleet_handle,
                tf_buffer
            )
            admitted.append(robot_name)
        except Exception as e:
            unavailable[robot_name] = f'{type(e).__name__}: {e}'
            if require_all_robots:
                node.get_logger().error(
                    f'Robot [{robot_name}] failed to initialize and '
                    '--require-all-robots was set: aborting.'
                )
                raise
            node.get_logger().warn(
                f'Robot [{robot_name}] is unavailable and has been SKIPPED: '
                f'{type(e).__name__}: {e}'
            )

    # A partial fleet is otherwise indistinguishable from a full one in the
    # logs -- every "Successfully added robot" line still looks normal. Say it
    # explicitly, once, at a level that survives a busy console.
    summary = (
        f'Fleet [{fleet_name}] started with {len(admitted)}/{len(known_robots)} '
        f'configured robots -- admitted: {admitted}'
    )
    if unavailable:
        node.get_logger().warn(
            f'{summary}, unavailable: {list(unavailable.keys())}'
        )
        for robot_name, reason in unavailable.items():
            node.get_logger().warn(f'  [{robot_name}] skipped because: {reason}')
    else:
        node.get_logger().info(summary)

    discovery_yaml = rmf_fleet_yaml.get('robot_discovery', {})
    discovery_enabled = discovery_yaml.get('enabled', True)
    discovery_sub = None
    onboarding_thread = None
    onboarding_queue = queue.Queue()
    stop_event = threading.Event()

    if discovery_enabled:
        robot_defaults = rmf_fleet_yaml.get('robot_defaults')
        if not isinstance(robot_defaults, dict):
            raise RuntimeError(
                'rmf_fleet.robot_defaults must be a map when robot discovery '
                'is enabled'
            )

        namespace_prefix = discovery_yaml.get(
            'namespace_prefix', 'jetracer_'
        )
        tf_keyexpr = discovery_yaml.get('tf_keyexpr', '*/tf')
        retry_interval_sec = float(
            discovery_yaml.get('retry_interval_sec', 10.0)
        )
        parking_spots = rmf_fleet_yaml.get('parking_spots', [])
        configured_assignments = {
            name: rmf_fleet_yaml['robots'][name]['charger']
            for name in admitted
            if rmf_fleet_yaml['robots'][name].get('charger')
        }
        parking = ParkingAllocator(parking_spots, configured_assignments)
        discovery_gate = DiscoveryGate(retry_interval_sec)
        for robot_name in admitted:
            discovery_gate.admitted(robot_name)

        def onboard_discovered_robot(robot_name):
            parking_spot = parking.reserve(robot_name)
            if parking_spot is None:
                node.get_logger().error(
                    f'Cannot onboard robot [{robot_name}]: all '
                    f'{parking.capacity} parking spots are assigned. Add a '
                    'parking_spot to the fleet config before increasing fleet '
                    'capacity.'
                )
                # Capacity cannot change without reloading the config, so stop
                # accepting repeated TF events for this name during this run.
                discovery_gate.admitted(robot_name)
                return

            robot_config_yaml = deepcopy(robot_defaults)
            robot_config_yaml['charger'] = parking_spot
            timeout_sec = robot_config_yaml.get('init_timeout_sec', 10)

            try:
                if not wait_for_robot_tf(
                    robot_name,
                    robot_config_yaml,
                    node,
                    zenoh_session,
                    tf_buffer,
                    timeout_sec,
                    stop_event
                ):
                    raise RuntimeError(
                        f'no tf received over zenoh within {timeout_sec}s'
                    )

                # Use RMF's supported runtime-registration API. Per-robot
                # responsive wait and merge settings intentionally come from
                # the fleet defaults; only the compatible parking/charger
                # waypoint varies between otherwise identical jetracers.
                robot_config = rmf_easy.RobotConfiguration([parking_spot])
                fleet_config.add_known_robot_configuration(
                    robot_name, robot_config
                )
                robot = build_robot_adapter(
                    robot_name,
                    robot_config,
                    robot_config_yaml,
                    fleet_config,
                    plugin_config,
                    node,
                    zenoh_session,
                    fleet_handle,
                    tf_buffer
                )
                with robots_lock:
                    robots[robot_name] = robot
                    active_names = sorted(robots)
                discovery_gate.admitted(robot_name)
                node.get_logger().info(
                    f'Onboarded robot [{robot_name}] while running; assigned '
                    f'parking spot [{parking_spot}]. Active robots: '
                    f'{active_names}'
                )
            except Exception as e:
                parking.release(robot_name)
                discovery_gate.failed(robot_name)
                node.get_logger().warn(
                    f'Runtime onboarding failed for robot [{robot_name}]: '
                    f'{type(e).__name__}: {e}. It may retry after '
                    f'{retry_interval_sec}s when TF is seen again.'
                )

        def onboarding_loop():
            while not stop_event.is_set():
                try:
                    robot_name = onboarding_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                try:
                    if robot_name is None:
                        return
                    onboard_discovered_robot(robot_name)
                finally:
                    onboarding_queue.task_done()

        def discover_from_tf(sample):
            robot_name = robot_name_from_tf_key(
                sample.key_expr, namespace_prefix
            )
            if robot_name is None or not discovery_gate.offer(robot_name):
                return
            node.get_logger().info(
                f'Discovered robot namespace [{robot_name}] from TF; '
                'scheduling runtime onboarding.'
            )
            onboarding_queue.put(robot_name)

        # Declare discovery before starting the worker. If Zenoh rejects the
        # key expression, startup fails cleanly without leaving a worker alive;
        # callbacks that arrive in this brief window are safely queued.
        discovery_sub = zenoh_session.declare_subscriber(
            tf_keyexpr, discover_from_tf
        )
        onboarding_thread = threading.Thread(
            target=onboarding_loop,
            name='jetracer_onboarding',
            daemon=True
        )
        onboarding_thread.start()
        node.get_logger().info(
            f'Runtime robot discovery active on Zenoh [{tf_keyexpr}] for '
            f'namespaces beginning [{namespace_prefix}] with '
            f'{parking.capacity} parking spots.'
        )

    if not robots:
        node.get_logger().warn(
            f'Fleet [{fleet_name}] currently has no active robots. The adapter '
            'will stay up and onboard a matching namespace as soon as its TF '
            'appears.' if discovery_enabled else
            f'Fleet [{fleet_name}] has no active robots and discovery is '
            'disabled.'
        )
    # --------------------------------------------------------------------------

    update_period = 1.0/config_yaml['rmf_fleet'].get(
        'robot_state_update_frequency', 10.0
    )

    def update_loop():
        asyncio.set_event_loop(asyncio.new_event_loop())
        while rclpy.ok() and not stop_event.is_set():
            now = node.get_clock().now()

            # Update all the robots in parallel using a thread pool
            with robots_lock:
                robot_snapshot = list(robots.values())
            update_jobs = [update_robot(robot) for robot in robot_snapshot]

            # asyncio.wait() raises on an empty set, which upstream never hits
            # because an empty fleet was impossible there. It is reachable here.
            if update_jobs:
                asyncio.get_event_loop().run_until_complete(
                    asyncio.wait(update_jobs)
                )

            next_wakeup = now + Duration(nanoseconds=update_period*1e9)
            while (
                node.get_clock().now() < next_wakeup
                and not stop_event.is_set()
            ):
                time.sleep(0.001)

    update_thread = threading.Thread(
        target=update_loop, name='jetracer_state_updates', daemon=True
    )
    update_thread.start()

    # Create executor for the command handle node
    rclpy_executor = EventsExecutor()
    rclpy_executor.add_node(node)

    # Start the fleet adapter
    try:
        rclpy_executor.spin()
    finally:
        stop_event.set()
        if discovery_sub is not None:
            discovery_sub.undeclare()
        if onboarding_thread is not None:
            onboarding_queue.put(None)
            onboarding_thread.join(timeout=2.0)
        update_thread.join(timeout=2.0)
        node.destroy_node()
        rclpy_executor.shutdown()
        zenoh_session.close()


# ------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------
def main(argv=sys.argv):
    # Init rclpy
    rclpy.init(args=argv)
    args_without_ros = rclpy.utilities.remove_ros_args(argv)

    parser = argparse.ArgumentParser(
        prog='jetracer_fleet_adapter',
        description='Configure and spin up the jetracer fleet adapter')
    parser.add_argument('-c', '--config_file', type=str, required=True,
                        help='Path to the config.yaml file')
    parser.add_argument('-n', '--nav_graph', type=str, required=True,
                        help='Path to the nav_graph for this fleet adapter')
    parser.add_argument('-s', '--server_uri', type=str, required=False,
                        default='',
                        help='URI of the api server to transmit state and '
                             'task information.')
    parser.add_argument('-sim', '--use_sim_time', action='store_true',
                        help='Use sim time, default: false')
    parser.add_argument(
        '--zenoh-config',
        type=str,
        help='Path to custom zenoh configuration file to be used, if not '
        'provided the default config will be used'
    )
    # Accepts both a bare flag (--require-all-robots) for hand-run invocations
    # and an explicit value (--require-all-robots true) so the launch file can
    # interpolate $(var require_all_robots) without conditional plumbing.
    parser.add_argument(
        '--require-all-robots',
        nargs='?',
        const='true',
        default='false',
        help='Abort startup if any configured robot fails to initialize '
             '(upstream free_fleet_adapter behaviour). Default is to skip '
             'unavailable robots and run with whoever is present.'
    )
    args = parser.parse_args(args_without_ros[1:])

    require_all_robots = \
        str(args.require_all_robots).strip().lower() in ('1', 'true', 'yes')

    start_fleet_adapter(
        config_path=args.config_file,
        nav_graph_path=args.nav_graph,
        zenoh_config_path=args.zenoh_config
        if args.zenoh_config != '' else None,
        server_uri=args.server_uri if args.server_uri != '' else None,
        use_sim_time=args.use_sim_time,
        require_all_robots=require_all_robots
    )

    rclpy.shutdown()


if __name__ == '__main__':
    main(sys.argv)
