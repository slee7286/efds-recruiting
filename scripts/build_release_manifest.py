"""Write a non-secret manifest beside a packaged Windows executable."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    digest = hashlib.sha256(args.artifact.read_bytes()).hexdigest()
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
    output = args.output or args.artifact.with_name("release-manifest.json")
    output.write_text(
        json.dumps(
            {
                "artifact": args.artifact.name,
                "sha256": digest,
                "built_at": datetime.now(timezone.utc).isoformat(),
                "commit": commit,
                "supported_shared_api": "v1",
                "local_schema": 5,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
