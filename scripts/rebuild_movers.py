#!/usr/bin/env python3
"""Rebuild price movers from saved local and git snapshot data without fetching CK."""

from update_site_data import load_git_payload, load_previous_payload, write_movers


def main() -> int:
    current = load_previous_payload()
    daily_previous = load_git_payload("HEAD~1")
    weekly_previous = load_git_payload("HEAD~7")
    if not daily_previous or not weekly_previous:
        raise RuntimeError("Saved daily or weekly Git snapshot is unavailable")
    write_movers(current, daily_previous, weekly_previous)
    print("Rebuilt movers.json from HEAD~1 and HEAD~7 snapshots")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
