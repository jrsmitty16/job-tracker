#!/usr/bin/env python3
"""
Application Status Tracker
Run this to update the status of jobs (Applied, Interviewing, etc.)
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "jobs.db"

STATUSES = {
    "n": "New",
    "a": "Applied",
    "i": "Interviewing",
    "o": "Offer",
    "r": "Rejected/Passed",
}

STATUS_COLORS = {
    "New":             "\033[94m",   # blue
    "Applied":         "\033[93m",   # yellow
    "Interviewing":    "\033[92m",   # green
    "Offer":           "\033[95m",   # magenta
    "Rejected/Passed": "\033[90m",   # grey
}
RESET = "\033[0m"
BOLD  = "\033[1m"


def color(text, status):
    c = STATUS_COLORS.get(status, "")
    return f"{c}{text}{RESET}"


def show_menu(prompt, options: dict):
    for key, label in options.items():
        print(f"  [{key}] {label}")
    return input(f"\n{prompt}: ").strip().lower()


def main():
    conn = sqlite3.connect(DB_PATH)

    while True:
        print(f"\n{BOLD}=== Job Application Tracker ==={RESET}")
        print("\nWhat would you like to do?")
        choice = show_menu("Choice", {
            "1": "View & update job statuses",
            "2": "View pipeline summary",
            "q": "Quit",
        })

        if choice == "q":
            break

        elif choice == "2":
            rows = conn.execute(
                "SELECT COALESCE(status,'New'), COUNT(*) FROM seen_jobs GROUP BY COALESCE(status,'New')"
            ).fetchall()
            print(f"\n{BOLD}Pipeline Summary{RESET}")
            print("-" * 30)
            total = 0
            for status, count in sorted(rows):
                print(f"  {color(f'{status:<20}', status)} {count}")
                total += count
            print(f"  {'Total':<20} {total}")

        elif choice == "1":
            print(f"\n{BOLD}Filter by status:{RESET}")
            filter_choice = show_menu("Show", {
                "1": "New (unreviewed)",
                "2": "Applied",
                "3": "Interviewing",
                "4": "All active (excludes Rejected/Passed)",
                "5": "All",
            })

            status_map = {
                "1": ("New",),
                "2": ("Applied",),
                "3": ("Interviewing",),
                "4": ("New", "Applied", "Interviewing", "Offer"),
                "5": None,
            }
            statuses = status_map.get(filter_choice)

            if statuses:
                placeholders = ",".join("?" * len(statuses))
                rows = conn.execute(
                    f"SELECT id, campaign, title, company, location, url, "
                    f"COALESCE(status,'New') as status, found_at "
                    f"FROM seen_jobs WHERE COALESCE(status,'New') IN ({placeholders}) "
                    f"ORDER BY found_at DESC LIMIT 50",
                    statuses,
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, campaign, title, company, location, url, "
                    "COALESCE(status,'New') as status, found_at "
                    "FROM seen_jobs ORDER BY found_at DESC LIMIT 50"
                ).fetchall()

            if not rows:
                print("\n  No jobs found with that filter.")
                input("\nPress Enter to continue...")
                continue

            print(f"\n{'#':<4} {'Status':<16} {'Title':<42} {'Company':<22} Campaign")
            print("─" * 105)
            for i, row in enumerate(rows, 1):
                jid, campaign, title, company, location, url, status, found_at = row
                status_str = color(f"{status:<16}", status)
                print(f"{i:<4} {status_str} {title[:41]:<42} {company[:21]:<22} {campaign[:30]}")

            print(f"\nEnter a job number to update its status (or press Enter to go back): ", end="")
            sel = input().strip()

            if not sel:
                continue
            if not sel.isdigit() or not (1 <= int(sel) <= len(rows)):
                print("  Invalid selection.")
                input("Press Enter to continue...")
                continue

            job = rows[int(sel) - 1]
            jid, _, title, company, *_ = job
            print(f"\n  Selected: {BOLD}{title}{RESET} at {company}")
            print(f"\n  New status:")
            new_status_key = show_menu("  Choice", STATUSES)
            new_status = STATUSES.get(new_status_key)

            if not new_status:
                print("  Invalid choice — no change made.")
            else:
                conn.execute(
                    "UPDATE seen_jobs SET status=?, status_updated_at=? WHERE id=?",
                    (new_status, datetime.now(timezone.utc).isoformat(), jid),
                )
                conn.commit()
                print(f"\n  {BOLD}Updated:{RESET} '{title}' → {color(new_status, new_status)}")

        input("\nPress Enter to continue...")

    conn.close()
    print("\nGoodbye!")


if __name__ == "__main__":
    main()
