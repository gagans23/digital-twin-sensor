"""Run with the installed wheel's Python, outside the source checkout."""
from importlib import resources
from pathlib import Path
import digital_twin_sensor
from digital_twin_sensor.connectors.registry import registry

checkout = Path(__file__).resolve().parents[1]
installed = Path(digital_twin_sensor.__file__).resolve()
if checkout in installed.parents:
    raise SystemExit("Smoke check imported the checkout, not the installed package")
expected = {"browser_page", "dev_workspace", "media_player"}
actual = {manifest.id for manifest in registry()}
if actual != expected:
    raise SystemExit(f"Connector inventory mismatch: {sorted(actual)}")
assets = resources.files("digital_twin_sensor.ui_static")
for name in ("index.html", "app.js", "app.css"):
    if not (assets / name).read_bytes():
        raise SystemExit(f"Missing UI asset: {name}")
print("Installed package verified: 3 connectors and 3 UI assets")
