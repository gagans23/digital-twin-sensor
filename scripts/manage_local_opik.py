"""Run the tested Opik stack on loopback without exposing its data services."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen


TESTED_COMMIT = "c0e842537db5d57ef8ed890af38c6180445d667f"
DEFAULT_SOURCE = Path.home() / ".digital-twin-sensor" / "services" / "opik"
DEFAULT_RUNTIME = Path.home() / ".digital-twin-sensor" / "services" / "opik-local"
REPOSITORY = "https://github.com/comet-ml/opik.git"


def run(command, **kwargs):
    return subprocess.run([str(item) for item in command], check=True, **kwargs)


def ensure_source(source):
    compose = source / "deployment" / "docker-compose" / "docker-compose.yaml"
    if compose.exists():
        return compose
    if source.exists() and any(source.iterdir()):
        raise SystemExit(f"Opik source directory is not usable: {source}")
    source.mkdir(parents=True, exist_ok=True)
    run(["git", "init", "--quiet", source])
    run(["git", "-C", source, "remote", "add", "origin", REPOSITORY])
    run(["git", "-C", source, "fetch", "--depth", "1", "origin", TESTED_COMMIT])
    run(["git", "-C", source, "checkout", "--quiet", "--detach", "FETCH_HEAD"])
    if not compose.exists():
        raise SystemExit("The tested Opik deployment file is missing")
    return compose


def compose_command(source, runtime):
    return [
        "docker", "compose", "-p", "dts-opik",
        "-f", source / "deployment" / "docker-compose" / "docker-compose.yaml",
        "-f", runtime / "compose.local.yaml",
        "--profile", "opik",
    ]


def runtime_files(runtime):
    root = Path(__file__).resolve().parents[1]
    runtime.mkdir(parents=True, exist_ok=True)
    for name in ("compose.local.yaml", "nginx.local.conf"):
        target = runtime / name
        shutil.copyfile(root / "deployment" / "opik" / name, target)
        target.chmod(0o600)


def health(timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen("http://127.0.0.1:5173/health", timeout=2) as response:
                if response.status == 200:
                    return True
        except OSError:
            time.sleep(2)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "status"))
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--pull", choices=("always", "missing", "never"), default="missing")
    args = parser.parse_args()
    source, runtime = args.source.expanduser().absolute(), args.runtime.expanduser().absolute()
    compose = source / "deployment" / "docker-compose" / "docker-compose.yaml"
    if args.action == "start":
        run(["docker", "info"], stdout=subprocess.DEVNULL)
        compose = ensure_source(source)
        runtime_files(runtime)
    elif not compose.exists() or not (runtime / "compose.local.yaml").exists():
        raise SystemExit("Local Opik has not been installed")
    env = {**os.environ, "DTS_OPIK_NGINX_CONFIG": str(runtime / "nginx.local.conf")}
    command = compose_command(source, runtime)
    if args.action == "start":
        run([*command, "up", "-d", "--no-build", "--pull", args.pull, "frontend", "mc"], env=env)
        if not health():
            raise SystemExit("Opik did not become healthy within 180 seconds")
        commit = subprocess.check_output(["git", "-C", source, "rev-parse", "HEAD"], text=True).strip()
        print(f"Opik is healthy at http://127.0.0.1:5173 (source {commit[:12]}).")
    elif args.action == "stop":
        run([*command, "down"], env=env)
        print("Opik stopped. Named volumes were retained.")
    else:
        run([*command, "ps"], env=env)
        print("Health: healthy" if health(timeout=2) else "Health: unavailable")


if __name__ == "__main__":
    main()
