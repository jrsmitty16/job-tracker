#!/usr/bin/env python3
"""
seed_resumes.py - Load resume .txt files from the /resumes folder into Supabase.

Usage:
  1. Create a folder called 'resumes' in the same directory as this script
  2. Add one .txt file per resume, named after the resume version:
       resumes/Founding Recruiter.txt
       resumes/Senior Technical Recruiter.txt
       resumes/Senior Talent Advisor.txt
  3. Run: python seed_resumes.py

Safe to re-run — updates existing records instead of duplicating.
"""

from pathlib import Path
from db import get_conn

RESUMES_DIR = Path(__file__).parent / "resumes"


def seed():
    if not RESUMES_DIR.exists():
        print(f"Creating resumes folder at: {RESUMES_DIR}")
        RESUMES_DIR.mkdir()
        print("Add your .txt resume files to that folder and re-run.")
        return

    txt_files = list(RESUMES_DIR.glob("*.txt"))
    if not txt_files:
        print(f"No .txt files found in {RESUMES_DIR}")
        print("Add one .txt file per resume version and re-run.")
        return

    conn = get_conn()
    cur  = conn.cursor()

    for path in sorted(txt_files):
        name    = path.stem  # filename without extension
        content = path.read_text(encoding="utf-8").strip()

        cur.execute("SELECT id FROM resumes WHERE name = %s", (name,))
        existing = cur.fetchone()

        if existing:
            cur.execute(
                "UPDATE resumes SET content = %s, uploaded_at = NOW() WHERE name = %s",
                (content, name)
            )
            print(f"  Updated: {name} ({len(content):,} chars)")
        else:
            cur.execute(
                "INSERT INTO resumes (name, content) VALUES (%s, %s)",
                (name, content)
            )
            print(f"  Inserted: {name} ({len(content):,} chars)")

    conn.commit()
    cur.close()
    conn.close()
    print(f"\nDone — {len(txt_files)} resume(s) seeded.")


if __name__ == "__main__":
    seed()
