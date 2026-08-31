"""Install only the optional macOS exporter; never reinstall the sensor runtime."""
import argparse
import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit


LABEL = "com.local.digital-twin-opik"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, help="Python 3.10+ exporter venv with .[observability] installed")
    parser.add_argument("--db", type=Path, default=Path.home() / ".digital-twin-sensor/events.sqlite")
    parser.add_argument("--api-key-file", type=Path)
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("This service installer is for macOS; use export --watch under your OS supervisor")
    domain = f"gui/{os.getuid()}"
    path = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
    if args.uninstall:
        subprocess.run(["launchctl", "bootout", domain + "/" + LABEL], capture_output=True)
        path.unlink(missing_ok=True)
        print("Opik exporter service removed. Local logs and Opik copies were not deleted.")
        return
    if args.python is None:
        parser.error("--python must name a separate exporter environment")
    executable = str(args.python.expanduser().absolute())
    check = subprocess.run([executable, "-c", "import sys, importlib.util; assert sys.version_info >= (3,10); assert importlib.util.find_spec('opik')"], capture_output=True)
    if check.returncode:
        parser.error("Exporter Python needs Python 3.10+ and the observability extra")
    db = str(args.db.expanduser().absolute())
    state = subprocess.run([executable, "-m", "digital_twin_sensor", "--db", db, "observability", "status"], capture_output=True, text=True)
    if state.returncode or json.loads(state.stdout).get("mode") != "opik":
        parser.error("Configure an explicit Opik destination before installing its exporter service")
    command = [executable, "-m", "digital_twin_sensor", "--db", db, "observability", "export", "--watch"]
    if args.api_key_file:
        key_path = args.api_key_file.expanduser().absolute()
        if key_path.is_symlink() or key_path.stat().st_mode & 0o077:
            parser.error("API key file must be private (chmod 600), not a symlink")
        command.extend(["--api-key-file", str(key_path)])
    elif urlsplit(json.loads(state.stdout)["destination"]).hostname not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("Provide --api-key-file for a remote authenticated service; shell variables are not inherited")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"Label": LABEL, "ProgramArguments": command, "RunAtLoad": True, "KeepAlive": True,
               "ThrottleInterval": 30, "ProcessType": "Background",
               # Detailed status is bounded in SQLite, not an unbounded launchd text log.
               "StandardOutPath": os.devnull, "StandardErrorPath": os.devnull}
    if path.exists():
        subprocess.run(["launchctl", "bootout", domain + "/" + LABEL], capture_output=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as stream:
        plistlib.dump(payload, stream)
    os.chmod(path, 0o600)
    subprocess.run(["launchctl", "enable", domain + "/" + LABEL], check=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True)
    print("Installed the separate Opik exporter. Check Observability for actual API acceptance.")


if __name__ == "__main__":
    main()
