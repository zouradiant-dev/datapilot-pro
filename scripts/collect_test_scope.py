"""Collect the exact public CI scope instead of maintaining stale test counts."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pytest


class Scope:
    def pytest_collection_finish(self, session):
        items = session.items
        ids = [item.nodeid for item in items]
        if len(set(ids)) != len(ids):
            raise ValueError("CI collection contains duplicate test identities")
        integration = [item for item in items if item.get_closest_marker("integration")]
        live_only = [
            item
            for item in items
            if item.get_closest_marker("live") and not item.get_closest_marker("integration")
        ]
        self.result = {
            "scope": "full-ci",
            "full_ci": True,
            "planned_tests": len(items),
            "planned_pg_tests": len(integration),
            "planned_nonintegration_tests": len(items) - len(integration) - len(live_only),
            "planned_live_only_tests": len(live_only),
            "nodeids_sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest(),
            "ci_result": "NOT_RUN",
        }


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    scope = Scope()
    result = pytest.main(["--collect-only", "-q", "-p", "no:cacheprovider"], plugins=[scope])
    if result:
        raise SystemExit(result)
    args.output.write_text(json.dumps(scope.result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
