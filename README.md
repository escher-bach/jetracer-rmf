# Jetracer RMF

Run Open-RMF, the Jetracer fleet adapter, the rmf-web API and the lab dashboard
together in one Docker container. Robot bridges connect through an existing
Zenoh router; its address is configured in `.env`.

The adapter discovers `jetracer_<name>` namespaces from their TF streams and
allocates the five configured parking spaces. This repository includes the
lab's calibrated map and fleet settings. Other sites must supply their own map,
coordinate calibration and robot parameters.

## Quick start

Requires Docker with Linux containers and Compose v2.20 or newer. The supplied
image build targets Linux AMD64; the robot-side Nav2 stack can remain on Humble.

```sh
git clone https://github.com/escher-bach/jetracer-rmf.git
cd jetracer-rmf
cp .env.example .env
```

In `.env`, set the existing robot router's address:

```dotenv
ZENOH_ROUTER_ENDPOINT=tcp/192.168.1.10:7447
```

For a router on the Docker host, the default `tcp/host.docker.internal:7447`
may be used if the router listens on an interface reachable by Docker.
`127.0.0.1` would refer to the container itself. For a router running inside
WSL, use its reachable host/LAN endpoint if the Docker gateway cannot reach it.

```sh
docker compose up -d --build --wait --wait-timeout 180
```

Open **http://localhost:8080**. The first build downloads dependencies and can
take several minutes; subsequent starts reuse the compiled image.

For browsers on another machine, set `RMF_PUBLIC_URL` to this Docker host's
LAN URL, including the configured `WEB_PORT`. API, Socket.IO and trajectory
connections all use the dashboard's origin.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ZENOH_ROUTER_ENDPOINT` | `tcp/host.docker.internal:7447` | Router used by the existing robot bridges |
| `WEB_PORT` | `8080` | Published dashboard/API port |
| `WEB_BIND_ADDRESS` | `0.0.0.0` | Host interface for the published port |
| `RMF_PUBLIC_URL` | `http://localhost:8080` | Browser-facing origin; match the chosen host/port |
| `TZ` | `Asia/Kolkata` | Match the operator browser's timezone |
| `ROS_DOMAIN_ID` | `52` | Container-internal ROS domain |
| `RMF_WEB_REF` | Pinned Jazzy commit | Build revision for both API and dashboard |
| `RMF_IMAGE` | `jetracer-rmf:jazzy` | Local tag or published GHCR image |

After changing runtime settings, run `docker compose up -d --wait` to recreate
the container. No rebuild is needed. Rebuild after changing sources or
`RMF_WEB_REF`.

Robot Nav2/localization, namespaced Zenoh bridges and the site router must
already be running. Robot IP addresses are unnecessary here because the
router carries their namespaced traffic. This build pins the Python Zenoh
client to 1.5.0 to match the project's bridges.

## Operate

```sh
docker compose logs -f --tail 100
docker compose ps
docker compose exec rmf supervisorctl -c /etc/supervisor/supervisord.conf status
docker compose exec rmf /opt/jetracer/entrypoint.sh ros2 node list --no-daemon
docker compose down
```

Task history and cached maps persist in the `rmf-web-data` named volume.
`docker compose down -v` deletes that data.

Healthchecks cover the local services, proxied API, trajectory listener and
essential ROS nodes. A healthy container can have zero online robots.
Supervisor restarts exited service processes. If a ROS child crashes while
its launch process remains alive, inspect the logs, correct the cause and run
`docker compose restart rmf`. Docker does not restart a container solely for
an unhealthy status.

Do not run another fleet adapter against the same robots at the same time.
The dashboard uses rmf-web's development StubAuthenticator; run this deployment
on a trusted robot/operator network. See [SECURITY.md](SECURITY.md).

## GitHub Actions and prebuilt images

[The image workflow](.github/workflows/image.yml) runs onboarding tests,
validates Compose, builds the image and smoke-tests the complete stack against
an isolated Zenoh router. It verifies dashboard HTTP, both websocket
transports and the building map's arrival over DDS.

- Pull requests build and test without publishing.
- Pushes to `main` publish `latest`, `jazzy` and a full commit SHA tag.
- Tags such as `v0.1.0` publish `0.1.0`, `0.1` and the commit SHA tag.
- Manual runs publish a commit SHA tag, plus default-branch tags when run on `main`.

Images are published to **`ghcr.io/<owner>/<repository>`** using GitHub's
automatic `GITHUB_TOKEN`. No personal token or registry secret is required.
Actions are pinned to commit SHAs; Dependabot checks them weekly.

Fork this repository to publish images under another account; the workflow
automatically uses the fork's owner and repository name. Enable Actions if
the repository's settings require it. After the first
successful publish, set the GHCR package's visibility to **Public** if you
want anonymous pulls; a public repository does not automatically make its
container package public.

To run this repository's published image, set `RMF_IMAGE=ghcr.io/escher-bach/jetracer-rmf:jazzy`
in `.env`, then:

```sh
docker compose pull
docker compose up -d --no-build --wait --wait-timeout 180
```

The workflow currently builds `linux/amd64`. ARM64 images need a native ARM64
build and validation before adding a multi-platform manifest.

## Layout and development

- `jetracer_fleet/`: ROS launch files, dynamic adapter, map/configuration and dashboard.
- `jetracer_fleet/docker/`: multi-stage image, nginx, Supervisor and runtime config.
- `vendor/free_fleet/`: required upstream packages with the existing Jetracer fixes.
- `tools/container-smoke-test.sh`: isolated local/CI smoke test.
- `tools/rmf_map_calib.py`: map-coordinate calibration helper.

[Architecture and performance](docs/architecture.md) explains the container
networking and build choices. [CONTRIBUTING.md](CONTRIBUTING.md) lists local
checks. [NOTICE.md](NOTICE.md) records vendored source provenance and licenses.

Apache-2.0; see [LICENSE](LICENSE).
