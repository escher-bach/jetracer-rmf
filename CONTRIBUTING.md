# Contributing

Use a feature branch and open a pull request. Changes to `main` and version
tags publish a container image after its smoke test passes. Pull requests build
and test without registry credentials.

Run the checks locally:

```sh
python -m unittest discover -s jetracer_fleet/test -v
docker compose --env-file .env.example config --quiet
docker build -f jetracer_fleet/docker/Dockerfile -t jetracer-rmf:ci .
bash tools/container-smoke-test.sh jetracer-rmf:ci
```

The Python tests need PyYAML (`python -m pip install PyYAML`). The container
smoke test needs Bash and Docker; on Windows run it through WSL. It starts an
isolated test router and container and cleans them up on exit. It does not
connect to the configured physical fleet.

Keep changes to vendored dependencies minimal, retain upstream notices, and
update the provenance and patch when changing the snapshot. Use `.env.example`
for documented configuration; keep real `.env` files and credentials local.
