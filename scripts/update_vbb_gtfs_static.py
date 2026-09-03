#!/usr/bin/env python3
"""Download, validate, and install the official VBB static GTFS archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import aiohttp

from bvg_radar.static_gtfs import StaticGtfsUpdateError, install_static_gtfs_archive


VBB_GTFS_URL = "https://unternehmen.vbb.de/gtfs"
DEFAULT_OUTPUT_DIR = Path("data/gtfs-static/GTFS")
DEFAULT_MANIFEST = Path("data/gtfs-static/manifest.json")


async def download_archive(
    session: aiohttp.ClientSession,
    url: str,
    destination: Path,
) -> str:
    """Stream the archive to disk and return its SHA-256."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    async with session.get(url) as response:
        if response.status != 200:
            raise StaticGtfsUpdateError(
                f"Download failed with HTTP {response.status}"
            )
        async with destination.open("wb") as output:
            async for chunk in response.content.iter_chunked(1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
    return digest.hexdigest()


async def main(
    argv: list[str] | None = None,
    *,
    stdout: sys._stdout | None = None,
    stderr: sys._stderr | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        description="Download and install the VBB static GTFS archive."
    )
    parser.add_argument(
        "--url",
        default=VBB_GTFS_URL,
        help="Direct ZIP URL (default: %(default)s)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Target directory for extracted GTFS files (default: %(default)s)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Path for the provenance manifest (default: %(default)s)",
    )
    parser.add_argument(
        "--keep-archive",
        action="store_true",
        help="Retain the downloaded ZIP in the output directory",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON to stdout on success",
    )
    args = parser.parse_args(argv)

    output = sys.stdout if stdout is None else stdout
    error_output = sys.stderr if stderr is None else stderr

    archive_path = args.output_dir.parent / "gtfs.zip"
    downloaded_at = datetime.now().isoformat(timespec="seconds") + "Z"

    try:
        timeout = aiohttp.ClientTimeout(total=300)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            await download_archive(session, args.url, archive_path)
    except (aiohttp.ClientError, TimeoutError, StaticGtfsUpdateError) as error:
        if args.json:
            print(
                json.dumps({"error": str(error), "status": "error"}, sort_keys=True),
                file=error_output,
            )
        else:
            print(f"error: {error}", file=error_output)
        return 2

    try:
        manifest = install_static_gtfs_archive(
            archive_path=archive_path,
            output_dir=args.output_dir,
            manifest_path=args.manifest,
            source_url=args.url,
            downloaded_at_utc=downloaded_at,
        )
    except StaticGtfsUpdateError as error:
        if args.json:
            print(
                json.dumps({"error": str(error), "status": "error"}, sort_keys=True),
                file=error_output,
            )
        else:
            print(f"error: {error}", file=error_output)
        return 2

    if not args.keep_archive:
        archive_path.unlink(missing_ok=True)

    if args.json:
        print(json.dumps({**manifest, "status": "installed"}, sort_keys=True), file=output)
    else:
        print(
            f"Installed {len(manifest['files'])} GTFS files from {args.url}",
            file=output,
        )
        print(f"Calendar range: {manifest['calendar_min_date']} → {manifest['calendar_max_date']}", file=output)
        print(f"Archive SHA-256: {manifest['archive_sha256']}", file=output)

    return 0


if __name__ == "__main__":
    import asyncio

    sys.exit(asyncio.run(main()))