"""Create a disposable Git repository for Req2Code's live smoke test."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def run(cwd: Path, *args: str) -> None:
    result = subprocess.run(
        list(args), cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or result.stdout.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=".demo", help="New directory to create (default: .demo)")
    args = parser.parse_args()
    root = Path(args.output).expanduser().resolve()
    if root.exists():
        raise SystemExit(f"Refusing to overwrite existing path: {root}")

    remote = root / "remote.git"
    work = root / "work"
    remote.mkdir(parents=True)
    work.mkdir()
    run(remote, "git", "init", "--bare")
    run(work, "git", "init", "-b", "main")

    (work / "calculator.py").write_text(
        '"""Small calculator used by the Req2Code demo."""\n\n'
        "def add(a, b):\n    return a + b\n\n"
        "def divide(a, b):\n    return a / b\n",
        encoding="utf-8",
    )
    (work / "test_calculator.py").write_text(
        "from calculator import add, divide\n\n"
        "def test_add():\n    assert add(2, 3) == 5\n\n"
        "def test_divide():\n    assert divide(8, 2) == 4\n",
        encoding="utf-8",
    )
    (work / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n.coverage\n", encoding="utf-8")
    run(work, "git", "add", ".")
    run(work, "git", "-c", "user.name=Req2Code Demo", "-c", "user.email=demo@localhost", "commit", "-m", "Initial demo")
    run(work, "git", "remote", "add", "origin", str(remote))
    run(work, "git", "push", "-u", "origin", "main")

    print(f"Demo working repository: {work}")
    print(f"Demo bare remote:        {remote}")
    print("Next: follow the live smoke-test commands in docs/TESTING.md or docs/TESTING.zh-CN.md")


if __name__ == "__main__":
    main()