import io
import json
from pathlib import Path

import pytest

from bvg_radar import static_gtfs_cli
from bvg_radar.gtfs_compatibility import GtfsCompatibilityReport
from bvg_radar.static_gtfs import (
    StaticGtfsCompatibilityError,
    StaticGtfsUpdateError,
    StaticGtfsUpdateResult,
)
from bvg_radar.static_gtfs_cli import cli_main


def _report(match_ratio: float) -> GtfsCompatibilityReport:
    return GtfsCompatibilityReport(
        feed_timestamp=1_788_430_000,
        schedule_hash="schedule-123",
        total_trip_updates=1,
        scheduled_trip_updates=1,
        unique_scheduled_trip_ids=1,
        matched_scheduled_trip_ids=1 if match_ratio == 1.0 else 0,
        unmatched_scheduled_trip_ids=0 if match_ratio == 1.0 else 1,
        scheduled_match_ratio=match_ratio,
        canceled_trip_updates=0,
        matched_canceled_trip_ids=0,
        unmatched_canceled_trip_ids=0,
        exempt_non_scheduled_trip_ids=0,
        matched_route_ids=1 if match_ratio == 1.0 else 0,
        mismatched_route_ids=0,
        missing_route_ids=0,
        unmatched_scheduled_trip_id_sample=(),
        route_id_mismatch_sample=(),
    )


def test_cli_installs_compatible_candidate_and_emits_json(tmp_path: Path) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    output_dir = tmp_path / "GTFS"
    manifest_path = tmp_path / "manifest.json"

    async def updater(**arguments: object) -> StaticGtfsUpdateResult:
        assert arguments["static_url"] == "https://example.test/static.zip"
        assert arguments["realtime_url"] == "https://example.test/realtime"
        assert arguments["output_dir"] == output_dir
        assert arguments["manifest_path"] == manifest_path
        assert arguments["minimum_scheduled_match"] == 0.99
        assert arguments["sample_limit"] == 5
        archive_path = arguments["archive_path"]
        assert isinstance(archive_path, Path)
        archive_path.write_bytes(b"zip")
        return StaticGtfsUpdateResult(
            manifest={
                "source_url": "https://example.test/static.zip",
                "archive_sha256": "abc123",
                "files": {},
                "calendar_min_date": "2026-09-01",
                "calendar_max_date": "2026-12-31",
                "downloaded_at_utc": arguments["downloaded_at_utc"],
            },
            compatibility_report=_report(1.0),
        )

    exit_code = cli_main(
        [
            "--url",
            "https://example.test/static.zip",
            "--feed-url",
            "https://example.test/realtime",
            "--output",
            str(output_dir),
            "--manifest",
            str(manifest_path),
            "--json",
        ],
        updater=updater,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    payload = json.loads(stdout.getvalue())
    assert payload["status"] == "installed"
    assert payload["compatibility_report"]["scheduled_match_ratio"] == 1.0
    assert payload["manifest"]["archive_sha256"] == "abc123"
    assert not list(tmp_path.glob(".vbb-gtfs-*.zip"))


def test_cli_forwards_and_reports_freshness_population_policy(
    tmp_path: Path,
) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    observed: dict[str, object] = {}

    async def updater(**arguments: object) -> StaticGtfsUpdateResult:
        observed.update(arguments)
        archive_path = arguments["archive_path"]
        assert isinstance(archive_path, Path)
        archive_path.write_bytes(b"zip")
        return StaticGtfsUpdateResult(
            manifest={"archive_sha256": "abc123"},
            compatibility_report=_report(1.0),
        )

    exit_code = cli_main(
        [
            "--output",
            str(tmp_path / "GTFS"),
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--minimum-scheduled-match",
            "0.995",
            "--minimum-unique-scheduled-trips",
            "321",
            "--max-feed-age-seconds",
            "600",
            "--max-future-skew-seconds",
            "45",
            "--json",
        ],
        updater=updater,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert observed["minimum_scheduled_match"] == 0.995
    assert observed["minimum_unique_scheduled_trip_ids"] == 321
    assert observed["max_feed_age_seconds"] == 600
    assert observed["max_future_skew_seconds"] == 45
    assert json.loads(stdout.getvalue())["compatibility_policy"] == {
        "agency_timezone": "Europe/Berlin",
        "max_feed_age_seconds": 600,
        "max_future_skew_seconds": 45,
        "minimum_scheduled_match": 0.995,
        "minimum_unique_scheduled_trip_ids": 321,
    }


def test_cli_keep_archive_downloads_directly_to_retained_path(tmp_path: Path) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    output_dir = tmp_path / "GTFS"
    manifest_path = tmp_path / "manifest.json"
    retained_archive = tmp_path / "gtfs.zip"

    async def updater(**arguments: object) -> StaticGtfsUpdateResult:
        assert arguments["archive_path"] == retained_archive
        retained_archive.write_bytes(b"retained zip")
        return StaticGtfsUpdateResult(
            manifest={
                "source_url": "https://example.test/static.zip",
                "archive_sha256": "abc123",
                "files": {},
                "calendar_min_date": "2026-09-01",
                "calendar_max_date": "2026-12-31",
                "downloaded_at_utc": arguments["downloaded_at_utc"],
            },
            compatibility_report=_report(1.0),
        )

    exit_code = cli_main(
        [
            "--output",
            str(output_dir),
            "--manifest",
            str(manifest_path),
            "--keep-archive",
            "--json",
        ],
        updater=updater,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert retained_archive.read_bytes() == b"retained zip"
    assert json.loads(stdout.getvalue())["status"] == "installed"


def test_cli_rejects_retained_archive_manifest_collision_before_update(
    tmp_path: Path,
) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    called = False

    async def updater(**_arguments: object) -> StaticGtfsUpdateResult:
        nonlocal called
        called = True
        raise AssertionError("updater must not run for colliding paths")

    exit_code = cli_main(
        [
            "--output",
            str(tmp_path / "GTFS"),
            "--manifest",
            str(tmp_path / "gtfs.zip"),
            "--keep-archive",
            "--json",
        ],
        updater=updater,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 2
    assert called is False
    assert stdout.getvalue() == ""
    payload = json.loads(stderr.getvalue())
    assert payload["status"] == "error"
    assert "paths overlap" in payload["error"]


def test_cli_returns_two_for_output_parent_creation_error(tmp_path: Path) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("file", encoding="utf-8")
    called = False

    async def updater(**_arguments: object) -> StaticGtfsUpdateResult:
        nonlocal called
        called = True
        raise AssertionError("updater must not run")

    exit_code = cli_main(
        [
            "--output",
            str(blocked_parent / "GTFS"),
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--json",
        ],
        updater=updater,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 2
    assert called is False
    assert stdout.getvalue() == ""
    payload = json.loads(stderr.getvalue())
    assert payload["status"] == "error"
    assert payload["error"]


def test_cli_returns_two_for_tempfile_creation_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    called = False

    async def updater(**_arguments: object) -> StaticGtfsUpdateResult:
        nonlocal called
        called = True
        raise AssertionError("updater must not run")

    def fail_mkstemp(**_arguments: object):
        raise PermissionError("temporary file denied")

    monkeypatch.setattr(static_gtfs_cli.tempfile, "mkstemp", fail_mkstemp)

    exit_code = cli_main(
        [
            "--output",
            str(tmp_path / "GTFS"),
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--json",
        ],
        updater=updater,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 2
    assert called is False
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue()) == {
        "error": "temporary file denied",
        "status": "error",
    }


def test_cli_returns_one_for_incompatible_candidate(tmp_path: Path) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    async def updater(**arguments: object) -> StaticGtfsUpdateResult:
        archive_path = arguments["archive_path"]
        assert isinstance(archive_path, Path)
        archive_path.write_bytes(b"zip")
        raise StaticGtfsCompatibilityError(_report(0.0), 0.99)

    exit_code = cli_main(
        [
            "--url",
            "https://example.test/static.zip",
            "--feed-url",
            "https://example.test/realtime",
            "--output",
            str(tmp_path / "GTFS"),
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--json",
        ],
        updater=updater,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 1
    assert stderr.getvalue() == ""
    payload = json.loads(stdout.getvalue())
    assert payload["status"] == "incompatible"
    assert payload["compatibility_report"]["scheduled_match_ratio"] == 0.0
    assert not list(tmp_path.glob(".vbb-gtfs-*.zip"))


def test_cli_returns_two_when_temporary_archive_cleanup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    async def updater(**arguments: object) -> StaticGtfsUpdateResult:
        archive_path = arguments["archive_path"]
        assert isinstance(archive_path, Path)
        archive_path.write_bytes(b"zip")
        return StaticGtfsUpdateResult(
            manifest={
                "source_url": "https://example.test/static.zip",
                "archive_sha256": "abc123",
                "files": {},
                "calendar_min_date": "2026-09-01",
                "calendar_max_date": "2026-12-31",
                "downloaded_at_utc": arguments["downloaded_at_utc"],
            },
            compatibility_report=_report(1.0),
        )

    original_unlink = Path.unlink

    def fail_temp_unlink(self: Path, *arguments: object, **keywords: object) -> None:
        if self.name.startswith(".vbb-gtfs-"):
            raise PermissionError("temporary archive locked")
        original_unlink(self, *arguments, **keywords)

    monkeypatch.setattr(Path, "unlink", fail_temp_unlink)

    exit_code = cli_main(
        [
            "--output",
            str(tmp_path / "GTFS"),
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--json",
        ],
        updater=updater,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 2
    assert stdout.getvalue() == ""
    payload = json.loads(stderr.getvalue())
    assert payload["status"] == "error"
    assert "could not clean temporary archive" in payload["error"]
    assert "temporary archive locked" in payload["error"]


def test_cli_returns_two_for_operational_error(tmp_path: Path) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    async def updater(**arguments: object) -> StaticGtfsUpdateResult:
        raise StaticGtfsUpdateError("invalid archive")

    exit_code = cli_main(
        [
            "--url",
            "https://example.test/static.zip",
            "--feed-url",
            "https://example.test/realtime",
            "--output",
            str(tmp_path / "GTFS"),
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--json",
        ],
        updater=updater,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue()) == {
        "error": "invalid archive",
        "status": "error",
    }
