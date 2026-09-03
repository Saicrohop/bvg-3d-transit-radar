"""Command-line entry point for the GTFS compatibility preflight."""

from bvg_radar.gtfs_compatibility import cli_main


if __name__ == "__main__":
    raise SystemExit(cli_main())
