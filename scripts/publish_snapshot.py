"""Publish a committed CI snapshot without replacing concurrent remote work."""

import subprocess
import time


def git(*args, check=True):
    return subprocess.run(["git", *args], check=check)


def main():
    git("diff", "--quiet")
    git("diff", "--cached", "--quiet")
    for attempt in range(3):
        git("fetch", "--no-tags", "origin", "main")
        # Conflicting generated files require a fresh capture, not an automatic
        # 'ours' resolution that could discard another publisher's snapshot.
        result = git("rebase", "origin/main", check=False)
        if result.returncode:
            git("rebase", "--abort")
            raise SystemExit("Publication conflict: remote data retained; fresh capture required")
        if git("push", "origin", "HEAD:refs/heads/main", check=False).returncode == 0:
            print("SNAPSHOT_PUBLISHED")
            return
        if attempt < 2:
            time.sleep(2)
    raise SystemExit("Publication failed after three non-forced attempts; remote data retained")


if __name__ == "__main__":
    main()
