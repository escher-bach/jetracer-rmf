# syntax=docker/dockerfile:1.7

# One Jazzy revision for both the API and browser client.
FROM node:22-bookworm-slim AS web-source
ARG RMF_WEB_REF=dbee3f9e27ba2f9313db68078428754b715bf0ba
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src/rmf-web
RUN git init && git remote add origin https://github.com/open-rmf/rmf-web.git \
    && git fetch --depth 1 origin "${RMF_WEB_REF}" && git checkout --detach FETCH_HEAD

FROM web-source AS dashboard-build
ENV HUSKY=0 NODE_OPTIONS=--max-old-space-size=4096
RUN corepack enable && corepack prepare pnpm@9.15.9 --activate \
    && pnpm config set store-dir /pnpm/store --global
# Skip upstream Python/dev-tool hooks; only these native JS packages are needed.
RUN --mount=type=cache,id=rmf-pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile --ignore-scripts \
    && pnpm -r rebuild esbuild @swc/core
COPY jetracer_fleet/dashboard/main.tsx jetracer_fleet/dashboard/index.html \
    packages/rmf-dashboard-framework/examples/jetracer/
ENV VITE_RMF_SAME_ORIGIN=true
WORKDIR /src/rmf-web/packages/rmf-dashboard-framework
RUN pnpm build:example examples/jetracer

FROM ros:jazzy-ros-base AS ros-runtime
ENV DEBIAN_FRONTEND=noninteractive
RUN rm -f /etc/apt/apt.conf.d/docker-clean
# Released RMF binaries: no source build of RMF, simulator, or Nav2.
RUN --mount=type=cache,id=rmf-apt-cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=rmf-apt-lists,target=/var/lib/apt/lists,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
      nginx-light supervisor tini tzdata python3-venv \
      ros-jazzy-rmw-cyclonedds-cpp ros-jazzy-launch-xml \
      ros-jazzy-rmf-traffic-ros2 ros-jazzy-rmf-task-ros2 \
      ros-jazzy-rmf-fleet-adapter-python ros-jazzy-rmf-building-map-tools \
      ros-jazzy-rmf-visualization ros-jazzy-tf-transformations \
      ros-jazzy-rmf-api-msgs ros-jazzy-rmf-scheduler-msgs ros-jazzy-rmf-site-map-msgs \
    && apt-get clean

FROM ros-runtime AS ros-build
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN --mount=type=cache,id=rmf-apt-cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=rmf-apt-lists,target=/var/lib/apt/lists,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
      build-essential python3-colcon-common-extensions \
    && apt-get clean
RUN python3 -m venv --system-site-packages /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
COPY jetracer_fleet/docker/requirements.txt /tmp/requirements.txt
COPY --from=web-source /src/rmf-web/packages/api-server /tmp/api-server
RUN --mount=type=cache,id=rmf-pip,target=/root/.cache/pip \
    pip install -r /tmp/requirements.txt /tmp/api-server \
    && cp -a /tmp/api-server/api_server/static /opt/venv/lib/python3.12/site-packages/api_server/
WORKDIR /opt/fleet_ws
COPY vendor/free_fleet/free_fleet src/free_fleet
COPY vendor/free_fleet/free_fleet_adapter src/free_fleet_adapter
COPY vendor/free_fleet/free_fleet_examples src/free_fleet_examples
COPY jetracer_fleet src/jetracer_fleet
# Installed ROS scripts need Unix shebangs even with Windows checkouts.
RUN find src -type f \( -name '*.py' -o -name '*.sh' \) -exec sed -i 's/\r$//' {} + \
    && source /opt/ros/jazzy/setup.bash \
    && colcon build --merge-install --packages-select \
         free_fleet free_fleet_adapter free_fleet_examples jetracer_fleet \
         --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF

FROM ros-runtime AS runtime
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    RMW_IMPLEMENTATION=rmw_cyclonedds_cpp ROS_DOMAIN_ID=52 \
    CYCLONEDDS_URI=file:///etc/jetracer/cyclonedds.xml \
    RMF_API_SERVER_CONFIG=/etc/jetracer/api_server_config.py \
    RMF_WEB_RUN_DIR=/data/rmf-web ROS_LOG_DIR=/tmp/ros-log \
    ZENOH_ROUTER_ENDPOINT=tcp/host.docker.internal:7447 \
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
COPY --from=ros-build /opt/venv /opt/venv
COPY --from=ros-build /opt/fleet_ws/install /opt/fleet_ws/install
COPY LICENSE NOTICE.md /usr/share/doc/jetracer-rmf/
COPY --from=web-source /src/rmf-web/LICENSE.md /usr/share/doc/rmf-web/LICENSE
COPY --from=dashboard-build /src/rmf-web/packages/rmf-dashboard-framework/examples/jetracer/dist/ /usr/share/nginx/html/
COPY jetracer_fleet/docker/nginx.conf /etc/nginx/nginx.conf
COPY jetracer_fleet/docker/supervisord.conf /etc/supervisor/supervisord.conf
COPY jetracer_fleet/docker/cyclonedds.xml jetracer_fleet/docker/api_server_config.py /etc/jetracer/
COPY jetracer_fleet/docker/entrypoint.sh jetracer_fleet/docker/configure.py \
    jetracer_fleet/docker/healthcheck.py /opt/jetracer/
RUN sed -i 's/\r$//' /opt/jetracer/entrypoint.sh \
    && chmod +x /opt/jetracer/entrypoint.sh \
    && mkdir -p /data/rmf-web /run/jetracer
WORKDIR /opt/fleet_ws
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD ["/opt/jetracer/entrypoint.sh", "python3", "/opt/jetracer/healthcheck.py"]
ENTRYPOINT ["/usr/bin/tini", "--", "/opt/jetracer/entrypoint.sh"]
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf"]
