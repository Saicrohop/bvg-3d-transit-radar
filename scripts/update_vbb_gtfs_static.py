#!/usr/bin/env python3
"""Download, validate, gate, and install the official VBB static GTFS feed."""

from bvg_radar.static_gtfs_cli import cli_main


if __name__ == "__main__":
    raise SystemExit(cli_main())
