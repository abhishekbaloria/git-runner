"""Run Git Runner from the project folder."""
import sys
from git_runner.cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["--demo", "run"]))
