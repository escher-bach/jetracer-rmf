# Vendored Free Fleet packages

Upstream: https://github.com/open-rmf/free_fleet

Base revision: `fb755962d6d9cd6ec42aa2092941b5fabeca2cb5`

License: Apache-2.0; see [LICENSE](LICENSE).

Only `free_fleet`, `free_fleet_adapter` and `free_fleet_examples` are included.
They are ordinary tracked files, so cloning this repository requires no Git
submodules or access to the original developer's workspace.

`free_fleet_adapter/free_fleet_adapter/nav2_robot_adapter.py` carries the
existing local Jetracer fixes. Its changes relative to the base revision are
recorded in [jetracer-nav2.patch](jetracer-nav2.patch). Review or port these fixes
when updating the vendor snapshot; do not overwrite them with upstream files.
The custom onboarding implementation remains in `jetracer_fleet/scripts`.
