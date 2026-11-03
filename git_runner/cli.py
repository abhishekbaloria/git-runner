"""Command line entry point. Secrets are accepted only through environment variables."""

import argparse
from datetime import date
import json
import os
from pathlib import Path
import sys

from .activity import Snapshot, collect, demo_snapshot
from .render import render


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Turn GitHub activity into an animated pixel runner.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--demo", choices=("run", "walk", "rest"), help="Use clearly labelled sample data.")
    source.add_argument("--username", help="Read live GitHub activity; set GH_TOKEN in the environment.")
    source.add_argument("--snapshot", type=Path, help="Render a previously saved JSON snapshot offline.")
    parser.add_argument("--name", default="Abhishek", help="Display name, separate from GitHub username.")
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--mp4", action="store_true", help="Also encode an MP4 with FFmpeg.")
    parser.add_argument("--through", type=date.fromisoformat, help="Last complete day, YYYY-MM-DD (UTC).")
    parser.add_argument("--exclude-repository", help="Exclude this repository from outfit-language calculation.")
    args = parser.parse_args(argv)
    try:
        if not args.name.strip() or len(args.name) > 30:
            raise ValueError("Choose a display name between 1 and 30 characters.")
        if args.demo:
            snapshot = demo_snapshot(args.demo, args.through)
        elif args.snapshot:
            snapshot = Snapshot.from_dict(json.loads(args.snapshot.read_text(encoding="utf-8")))
        else:
            snapshot = collect(args.username, os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", ""),
                               args.through, args.exclude_repository)
        state = render(snapshot, args.output, args.name.strip(), mp4=args.mp4)
        # Only persist fresh activity after rendering succeeds.
        temporary = args.output / "activity.json.tmp"
        temporary.write_text(json.dumps(snapshot.to_dict(), indent=2) + "\n", encoding="utf-8")
        temporary.replace(args.output / "activity.json")
        print(f"Saved {args.output / 'runner.gif'} ({state.mode}; {'sample' if snapshot.demo else 'GitHub'} data).")
        return 0
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as error:
        print(f"git-runner: {error}", file=sys.stderr)
        return 1
