# Third-party notices

This project is distributed under the Apache License, Version 2.0. Original
copyright and license headers in included sources are retained.

## Free Fleet

`vendor/free_fleet` contains the three ROS packages needed by this deployment
from [open-rmf/free_fleet](https://github.com/open-rmf/free_fleet), revision
`fb755962d6d9cd6ec42aa2092941b5fabeca2cb5` (Apache-2.0).
Copyright Open Source Robotics Foundation, Inc. and upstream contributors.
The upstream license is included at `vendor/free_fleet/LICENSE`.

The vendored `nav2_robot_adapter.py` includes this project's local changes:
navigation completion handling, redundant-goal suppression and replan cooldown
handling used by the physical Jetracer fleet. These changes are preserved
instead of depending on an unmodified upstream checkout. See
`vendor/free_fleet/README.md` for provenance and update guidance.

## rmf-web

The dashboard entry point in `jetracer_fleet/dashboard/main.tsx` is derived
from Open-RMF's demo (Apache-2.0, Open Source Robotics Foundation and
contributors), with Jetracer-specific zoom, task selection and URL routing.
The image fetches rmf-web from its Jazzy revision
`dbee3f9e27ba2f9313db68078428754b715bf0ba` for the API and dashboard build.
The image includes its license at `/usr/share/doc/rmf-web/LICENSE`.

ROS, Open-RMF, Zenoh, nginx and Python/JavaScript dependencies retain their
respective upstream licenses. This repository's license does not replace
those licenses.
