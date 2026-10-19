"""Report offline local prerequisites; no service, subprocess or DB operation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from collections.abc import Sequence
import sys

ROOT = Path(__file__).resolve().parents[1]
# -I -S ignores site/editable installs; load only this checkout's stdlib checker.
sys.path.insert(0, str(ROOT / 'src'))
from bvg_radar.local_runtime import inspect_local_runtime


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true', help='Print one JSON document')
    args = parser.parse_args(argv)
    report = inspect_local_runtime(ROOT)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Offline preflight: {report['status']}")
        for blocker in report['blockers']:
            print(f'- {blocker}')
        print('Live gate: not_run; this is not a database or Docker-daemon validation.')
        print('No service was started. Inspect existing volumes before any startup; never reset.')
    return 0 if report['status'] == 'offline_checks_passed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
