#!/usr/bin/env bash
# Exercise the built image without touching the physical robot network.
set -euo pipefail
image=${1:-jetracer-rmf:ci}
suffix="${RANDOM}-$$"
network="jetracer-smoke-${suffix}"
router="jetracer-router-${suffix}"
stack="jetracer-stack-${suffix}"

cleanup() {
  result=$?
  if [ "$result" -ne 0 ]; then
    docker logs --tail 150 "$stack" 2>/dev/null || true
    docker inspect --format '{{json .State.Health}}' "$stack" 2>/dev/null || true
  fi
  docker rm -f "$stack" "$router" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create "$network" >/dev/null
docker run -d --name "$router" --network "$network" eclipse/zenoh:1.5.0 >/dev/null
docker run -d --name "$stack" --network "$network" \
  -e "ZENOH_ROUTER_ENDPOINT=tcp/${router}:7447" \
  -e RMF_PUBLIC_URL=http://localhost:8080 \
  -e TZ=Asia/Kolkata "$image" >/dev/null

deadline=$((SECONDS + 180))
while [ "$SECONDS" -lt "$deadline" ]; do
  state=$(docker inspect --format '{{.State.Status}}' "$stack")
  health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$stack")
  [ "$state" = running ] || { echo "Container stopped: $state" >&2; exit 1; }
  if [ "$health" = healthy ]; then
    # Check the production bundle and both browser websocket transports, plus
    # the map delivered over container-local DDS, using installed clients.
    docker exec -i "$stack" /opt/jetracer/entrypoint.sh python3 - <<'PY'
import asyncio
import json
from pathlib import Path
from urllib.request import urlopen
import websockets

with urlopen('http://127.0.0.1:8080/') as response:
    html = response.read().decode()
    assert 'Jetracer RMF Dashboard' in html and '/assets/' in html, html
with urlopen('http://127.0.0.1:8080/api/socket.io/?EIO=4&transport=polling') as response:
    handshake = response.read().decode()
    assert handshake.startswith('0'), handshake
    assert 'sid' in json.loads(handshake[1:]), handshake
assert any(Path('/data/rmf-web/cache').iterdir()), 'Building map never reached the API over DDS'

async def check_websockets():
    async with websockets.connect('ws://127.0.0.1:8080/trajectory', open_timeout=5):
        pass
    async with websockets.connect('ws://127.0.0.1:8080/api/socket.io/?EIO=4&transport=websocket', open_timeout=5) as ws:
        assert (await asyncio.wait_for(ws.recv(), timeout=5)).startswith('0')

asyncio.run(check_websockets())
print('PASS: RMF, adapter, API, production dashboard, DDS map, Socket.IO and trajectory websocket')
PY
    exit 0
  fi
  sleep 3
done
echo 'Stack did not become healthy within 180 seconds' >&2
exit 1
