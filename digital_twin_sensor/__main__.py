from .cli import main


if __name__ == "__main__":
    # Propagate the exit code. Discarding it made `python -m digital_twin_sensor
    # harness` exit 0 on a leak — the console script wrapper hid this, because
    # setuptools wraps the entry point in sys.exit() and CI uses that path.
    raise SystemExit(main())
