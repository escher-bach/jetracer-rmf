# Container sources

Run Compose from the standalone repository root. See [the main README](../../README.md)
for `.env`, build/run commands, GHCR images and operating instructions.

The Compose file in this directory forwards to the root `compose.yaml` for
compatibility. Docker builds require the repository source context, including
`vendor/free_fleet`; an installed ROS package's copy of this directory cannot
build the image by itself.
