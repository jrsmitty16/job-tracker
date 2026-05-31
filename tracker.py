#!/usr/bin/env python3
"""
Job Board Tracker
Monitors multiple job boards for new postings and sends notifications.
"""

import psycopg2
import feedparser
import requests
import smtplib
import yaml
import hashlib
import logging
import time
import json
import calendar
from datetime import datetime, timezone, timedelta
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.parse import quote_plus
import email.utils as _email_utils
import re


def strip_html(html: str) -> str:
    """Strip HTML tags and return plain text."""
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.yaml"
LOG_PATH = BASE_DIR / "tracker.log"
REPORT_PATH = BASE_DIR / "latest_jobs.html"
STATE_PATH = BASE_DIR / "state.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State (tracks last email timestamp across runs)
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(state: dict):
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

def parse_date(value) -> datetime | None:
    """Parse a date from any common format into a timezone-aware datetime."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    # feedparser returns published_parsed as time.struct_time
    if hasattr(value, "tm_year"):
        return datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)
    s = str(value).strip()
    # ISO 8601 variants
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s[: len(fmt)], fmt)
            return dt.replace(tzinfo=timezone.utc) if not dt.tzinfo else dt
        except ValueError:
            continue
    # RFC 2822 (used by RSS feeds)
    try:
        return _email_utils.parsedate_to_datetime(s)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def init_db():
    from db import get_conn
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS seen_jobs (
            id                TEXT PRIMARY KEY,
            campaign          TEXT,
            title             TEXT,
            company           TEXT,
            location          TEXT,
            url               TEXT,
            source            TEXT,
            found_at          TEXT,
            posted_at         TEXT,
            status            TEXT DEFAULT 'New',
            status_updated_at TEXT,
            score             INTEGER DEFAULT 0,
            rationale         TEXT,
            best_resume       TEXT,
            resume_score      INTEGER,
            resume_rationale  TEXT,
            nudge             TEXT
        )
    """)
    # Safe migration: add nudge column if this table was created before this version
    cur.execute("""
        ALTER TABLE seen_jobs ADD COLUMN IF NOT EXISTS nudge TEXT
    """)
    conn.commit()
    cur.close()
    return conn


def job_fingerprint(title: str, company: str, url: str) -> str:
    key = f"{title.lower()}|{company.lower()}|{url.lower()}"
    return hashlib.md5(key.encode()).hexdigest()


def is_new(conn, jid: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM seen_jobs WHERE id=%s", (jid,))
    result = cur.fetchone()
    cur.close()
    return result is None


# ---------------------------------------------------------------------------
# Relevance Scoring — LLM-based via Anthropic
# ---------------------------------------------------------------------------

def score_job_with_llm(title: str, company: str, description: str = "") -> tuple[int, str]:
    """Score a job 1-5 using Claude Haiku based on Corey's recruiter background."""
    try:
        import anthropic
        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from environment

        desc_snippet = description[:1500] if description else "Not available"
        prompt = (
            "You are evaluating job fit for a senior technical recruiter.\n"
            "Background: 10+ years recruiting experience, founding recruiter at multiple startups, "
            "strong focus on AI/ML and technical hiring, full-cycle recruiting, "
            "talent acquisition leadership, experience at high-growth Series A-C companies.\n\n"
            f"Job details:\n"
            f"- Title: {title}\n"
            f"- Company: {company}\n"
            f"- Description: {desc_snippet}\n\n"
            "Rate this job's fit on a scale of 1-5:\n"
            "1 = Poor fit (wrong field or wildly mismatched)\n"
            "2 = Weak fit (some overlap but significant gaps)\n"
            "3 = Moderate fit (relevant but not ideal)\n"
            "4 = Good fit (strong match for background)\n"
            "5 = Excellent fit (perfect match)\n\n"
            'Respond ONLY with a JSON object, no other text:\n'
            '{"score": <integer 1-5>, "rationale": "<one sentence, max 20 words>"}'
        )

        message = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )
        content = message.content[0].text.strip()
        # Strip markdown code fences if present
        if content.startswith("```"):
            content = re.sub(r"^```[a-z]*\n?", "", content)
            content = re.sub(r"\n?```$", "", content).strip()
        result    = json.loads(content)
        score     = max(1, min(5, int(result["score"])))
        rationale = str(result.get("rationale", ""))[:300]
        return score, rationale

    except Exception as exc:
        log.debug(f"LLM scoring failed for '{title}': {exc}")
        return 3, "LLM unavailable"


# ---------------------------------------------------------------------------
# Resume Matching — picks best resume for each job via Anthropic
# ---------------------------------------------------------------------------

def match_resume_to_job(conn, title: str, company: str, description: str = "") -> tuple[str | None, int, str]:
    """Compare all resumes against a job and return (best_resume_name, score, rationale)."""
    try:
        cur = conn.cursor()
        cur.execute("SELECT name, content FROM resumes ORDER BY id")
        resumes = cur.fetchall()
        cur.close()

        if not resumes:
            return None, 0, ""

        import anthropic
        client = anthropic.Anthropic()

        desc_snippet = description[:1000] if description else "Not available"
        best_name, best_score, best_rationale = None, 0, ""

        for resume_name, resume_content in resumes:
            prompt = (
                f"You are evaluating how well a resume matches a job posting.\n\n"
                f"RESUME — {resume_name}:\n{resume_content[:3000]}\n\n"
                f"JOB DETAILS:\n"
                f"- Title: {title}\n"
                f"- Company: {company}\n"
                f"- Description: {desc_snippet}\n\n"
                "Rate how well this resume matches this job on a scale of 1-5:\n"
                "1 = Poor match\n2 = Weak match\n3 = Moderate match\n"
                "4 = Good match\n5 = Excellent match\n\n"
                'Respond ONLY with a JSON object, no other text:\n'
                '{"score": <integer 1-5>, "rationale": "<one sentence, max 20 words>"}'
            )
            message = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=100,
                messages=[{"role": "user", "content": prompt}],
            )
            content = message.content[0].text.strip()
            if content.startswith("```"):
                content = re.sub(r"^```[a-z]*\n?", "", content)
                content = re.sub(r"\n?```$", "", content).strip()
            result    = json.loads(content)
            r_score   = max(1, min(5, int(result["score"])))
            r_rationale = str(result.get("rationale", ""))[:300]

            if r_score > best_score:
                best_score     = r_score
                best_name      = resume_name
                best_rationale = r_rationale

        return best_name, best_score, best_rationale

    except Exception as exc:
        log.debug(f"Resume matching failed for '{title}': {exc}")
        return None, 0, ""


def save_job(conn, jid, campaign, title, company, location, url, source,
             posted_at=None, score=3, rationale="",
             best_resume=None, resume_score=None, resume_rationale=None):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO seen_jobs
           (id, campaign, title, company, location, url, source,
            found_at, posted_at, status, status_updated_at, score, rationale,
            best_resume, resume_score, resume_rationale)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (id) DO NOTHING""",
        (jid, campaign, title, company, location, url, source,
         datetime.now(timezone.utc).isoformat(),
         posted_at.isoformat() if posted_at else None,
         "New", None, score, rationale,
         best_resume, resume_score, resume_rationale),
    )
    conn.commit()
    cur.close()


def load_all_jobs(conn):
    cur = conn.cursor()
    cur.execute(
        "SELECT campaign, title, company, location, url, source, found_at, posted_at, "
        "COALESCE(status,'New') as status, COALESCE(score,0) as score "
        "FROM seen_jobs ORDER BY score DESC, found_at DESC LIMIT 500"
    )
    rows = cur.fetchall()
    cur.close()
    return rows


def get_pipeline_summary(conn) -> dict:
    cur = conn.cursor()
    cur.execute(
        "SELECT COALESCE(status,'New'), COUNT(*) FROM seen_jobs "
        "WHERE COALESCE(status,'New') != 'Not a Fit' "
        "GROUP BY COALESCE(status,'New')"
    )
    rows = cur.fetchall()
    cur.close()
    return dict(rows)


def get_weekly_stats(conn, since: datetime) -> dict:
    since_str = since.isoformat()
    cur = conn.cursor()
    cur.execute(
        "SELECT campaign, COUNT(*) FROM seen_jobs WHERE found_at >= %s GROUP BY campaign",
        (since_str,)
    )
    new_this_week = cur.fetchall()
    cur.execute(
        "SELECT title, company, url, status_updated_at FROM seen_jobs "
        "WHERE status='Applied' AND status_updated_at >= %s ORDER BY status_updated_at DESC",
        (since_str,)
    )
    applied = cur.fetchall()
    cur.execute("SELECT title, company, url FROM seen_jobs WHERE status='Interviewing'")
    interviewing = cur.fetchall()
    cur.close()
    return {
        "new_by_campaign": dict(new_this_week),
        "applied":         list(applied),
        "interviewing":    list(interviewing),
    }


# ---------------------------------------------------------------------------
# Job Board Sources
# ---------------------------------------------------------------------------

HEADERS = {"User-Agent": "JobTracker/1.0 (personal job search tool)"}


def fetch_indeed(query: str, max_age_days: int = 3) -> list[dict]:
    url = (
        f"https://www.indeed.com/rss?q={quote_plus(query)}"
        f"&sort=date&fromage={max_age_days}"
    )
    try:
        feed = feedparser.parse(url)
        jobs = []
        for e in feed.entries:
            company = ""
            if hasattr(e, "source") and isinstance(e.source, dict):
                company = e.source.get("title", "")
            location = getattr(e, "indeed_city", "") or ""
            if getattr(e, "indeed_country", ""):
                location = f"{location}, {e.indeed_country}".strip(", ")
            jobs.append({
                "title":     e.get("title", "").split(" - ")[0].strip(),
                "company":   company,
                "location":  location,
                "url":       e.get("link", ""),
                "source":    "Indeed",
                "posted_at": parse_date(e.get("published_parsed")),
            })
        log.info(f"  Indeed     '{query}': {len(jobs)} results")
        return jobs
    except Exception as exc:
        log.warning(f"  Indeed fetch failed for '{query}': {exc}")
        return []


def fetch_remoteok(query: str) -> list[dict]:
    tag = query.lower().replace(" ", "-")
    url = f"https://remoteok.com/api?tag={quote_plus(tag)}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        data = resp.json()
        jobs = []
        for item in data[1:]:
            if isinstance(item, dict) and item.get("position"):
                tags = item.get("tags", [])
                tag_text = " ".join(tags) if isinstance(tags, list) else ""
                jobs.append({
                    "title":       item.get("position", ""),
                    "company":     item.get("company", ""),
                    "location":    item.get("location", "Remote"),
                    "url":         item.get("url") or f"https://remoteok.com/jobs/{item.get('id','')}",
                    "source":      "RemoteOK",
                    "posted_at":   parse_date(item.get("date")),
                    "description": strip_html(item.get("description", "")) + " " + tag_text,
                })
        log.info(f"  RemoteOK   '{query}': {len(jobs)} results")
        return jobs
    except Exception as exc:
        log.warning(f"  RemoteOK fetch failed for '{query}': {exc}")
        return []


def fetch_arbeitnow(query: str) -> list[dict]:
    url = f"https://www.arbeitnow.com/api/job-board-api?search={quote_plus(query)}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        data = resp.json()
        jobs = []
        for item in data.get("data", []):
            jobs.append({
                "title":       item.get("title", ""),
                "company":     item.get("company_name", ""),
                "location":    item.get("location", ""),
                "url":         item.get("url", ""),
                "source":      "Arbeitnow",
                "posted_at":   parse_date(item.get("created_at")),
                "description": strip_html(item.get("description", "")),
            })
        log.info(f"  Arbeitnow  '{query}': {len(jobs)} results")
        return jobs
    except Exception as exc:
        log.warning(f"  Arbeitnow fetch failed for '{query}': {exc}")
        return []


def fetch_weworkremotely(query: str) -> list[dict]:
    url = "https://weworkremotely.com/remote-jobs.rss"
    try:
        feed = feedparser.parse(url)
        q_lower = query.lower()
        jobs = []
        for e in feed.entries:
            title = e.get("title", "")
            if q_lower in title.lower():
                company = ""
                if " at " in title:
                    company = title.split(" at ")[-1].strip()
                    title = title.split(" at ")[0].strip()
                jobs.append({
                    "title":     title,
                    "company":   company,
                    "location":  "Remote",
                    "url":       e.get("link", ""),
                    "source":    "WeWorkRemotely",
                    "posted_at": parse_date(e.get("published_parsed")),
                })
        log.info(f"  WWR        '{query}': {len(jobs)} results")
        return jobs
    except Exception as exc:
        log.warning(f"  WWR fetch failed for '{query}': {exc}")
        return []


def fetch_linkedin(query: str) -> list[dict]:
    url = (
        "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
        f"?keywords={quote_plus(query)}&location=United+States&f_TPR=r86400&start=0"
    )
    browser_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        from bs4 import BeautifulSoup
        resp = requests.get(url, headers=browser_headers, timeout=15)
        soup = BeautifulSoup(resp.text, "lxml")
        jobs = []
        for card in soup.find_all("div", class_="base-card"):
            title_el   = card.find("h3", class_="base-search-card__title")
            company_el = card.find("h4", class_="base-search-card__subtitle")
            loc_el     = card.find("span", class_="job-search-card__location")
            link_el    = card.find("a", class_="base-card__full-link")
            time_el    = card.find("time")
            if title_el and link_el:
                posted = parse_date(time_el.get("datetime") if time_el else None)
                jobs.append({
                    "title":     title_el.get_text(strip=True),
                    "company":   company_el.get_text(strip=True) if company_el else "",
                    "location":  loc_el.get_text(strip=True) if loc_el else "",
                    "url":       link_el.get("href", "").split("?")[0],
                    "source":    "LinkedIn",
                    "posted_at": posted,
                })
        log.info(f"  LinkedIn   '{query}': {len(jobs)} results")
        return jobs
    except Exception as exc:
        log.warning(f"  LinkedIn fetch failed for '{query}': {exc}")
        return []


def fetch_himalayas(query: str) -> list[dict]:
    """Fetch from Himalayas — startup/remote-focused job board with free API."""
    url = "https://himalayas.app/jobs/api/search"
    try:
        resp = requests.get(url, params={"q": query, "sort": "recent", "limit": 20},
                            headers=HEADERS, timeout=15)
        data = resp.json()
        jobs = []
        for item in data.get("jobs", []):
            location = item.get("locationRestrictions", "Remote")
            if isinstance(location, list):
                location = ", ".join(location) if location else "Remote"
            jobs.append({
                "title":     item.get("title", ""),
                "company":   item.get("companyName", ""),
                "location":  location,
                "url":       item.get("applicationLink", ""),
                "source":    "Himalayas",
                "posted_at": parse_date(item.get("pubDate")),
            })
        log.info(f"  Himalayas  '{query}': {len(jobs)} results")
        return jobs
    except Exception as exc:
        log.warning(f"  Himalayas fetch failed for '{query}': {exc}")
        return []


def fetch_jobicy(query: str) -> list[dict]:
    """Fetch from Jobicy — remote-focused job board with free public API."""
    url = "https://jobicy.com/api/v2/remote-jobs"
    try:
        resp = requests.get(url, params={"count": 50, "tag": query},
                            headers=HEADERS, timeout=15)
        data = resp.json()
        jobs = []
        for item in data.get("jobs", []):
            jobs.append({
                "title":       item.get("jobTitle", ""),
                "company":     item.get("companyName", ""),
                "location":    item.get("jobGeo", "Remote"),
                "url":         item.get("url", ""),
                "source":      "Jobicy",
                "posted_at":   parse_date(item.get("pubDate")),
                "description": strip_html(item.get("jobDescription", "")),
            })
        log.info(f"  Jobicy     '{query}': {len(jobs)} results")
        return jobs
    except Exception as exc:
        log.warning(f"  Jobicy fetch failed for '{query}': {exc}")
        return []


def fetch_remotive(query: str) -> list[dict]:
    """Fetch from Remotive — remote tech jobs with free API (rate-limited)."""
    url = "https://remotive.com/api/remote-jobs"
    try:
        resp = requests.get(url, params={"search": query, "limit": 10},
                            headers=HEADERS, timeout=15)
        data = resp.json()
        jobs = []
        for item in data.get("jobs", []):
            jobs.append({
                "title":       item.get("title", ""),
                "company":     item.get("company_name", ""),
                "location":    item.get("candidate_required_location", "Remote"),
                "url":         item.get("url", ""),
                "source":      "Remotive",
                "posted_at":   parse_date(item.get("publication_date")),
                "description": strip_html(item.get("description", "")),
            })
        log.info(f"  Remotive   '{query}': {len(jobs)} results")
        return jobs
    except Exception as exc:
        log.warning(f"  Remotive fetch failed for '{query}': {exc}")
        return []


SOURCES = [fetch_indeed, fetch_himalayas, fetch_remotive,
           fetch_remoteok, fetch_arbeitnow, fetch_weworkremotely, fetch_jobicy]
# fetch_linkedin paused


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def passes_filters(job: dict, filters: dict) -> tuple[bool, str]:
    title       = job.get("title", "").lower()
    location    = job.get("location", "").lower()
    description = job.get("description", "").lower()

    title_must_exclude = [k.lower() for k in filters.get("title_must_exclude", [])]
    desc_must_include  = [k.lower() for k in filters.get("description_must_include", [])]
    title_must_include = [k.lower() for k in filters.get("title_must_include", [])]
    title_ai_specific  = [k.lower() for k in filters.get("title_ai_specific", [])]

    # Title must not contain any exclude keyword
    for kw in title_must_exclude:
        if kw in title:
            return False, f"title '{job['title']}' blocked by '{kw}'"

    if description and desc_must_include:
        # Has description: allow broad title keywords, but description must contain AI terms
        if title_must_include and not any(kw in title for kw in title_must_include):
            return False, f"title '{job['title']}' missing required keywords"
        if not any(kw in description for kw in desc_must_include):
            return False, f"description for '{job['title']}' missing AI keywords"
    else:
        # No description: require specific AI title keywords to avoid false positives
        specific = title_ai_specific if title_ai_specific else title_must_include
        if specific and not any(kw in title for kw in specific):
            return False, f"title '{job['title']}' missing specific AI keywords (no description available)"

    # Location must match allowed list (empty location gets benefit of the doubt)
    allowed = [loc.lower() for loc in filters.get("location_allow", [])]
    if allowed and location and not any(loc in location for loc in allowed):
        return False, f"location '{job['location']}' not in allowed list"

    return True, ""


# ---------------------------------------------------------------------------
# Campaign Runner
# ---------------------------------------------------------------------------

def run_campaign(campaign_name: str, queries: list[str], filters: dict) -> list[dict]:
    all_jobs: list[dict] = []
    seen_urls: set[str] = set()
    filtered_count = 0

    for query in queries:
        log.info(f"Querying '{query}'...")
        for source_fn in SOURCES:
            for job in source_fn(query):
                url = job.get("url", "")
                if not url or url in seen_urls:
                    continue
                ok, reason = passes_filters(job, filters)
                if not ok:
                    filtered_count += 1
                    log.debug(f"  FILTERED: {reason}")
                    continue
                seen_urls.add(url)
                job["campaign"] = campaign_name
                all_jobs.append(job)
            time.sleep(0.75)

    log.info(f"  Filtered out {filtered_count} irrelevant results")
    return all_jobs


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def generate_email_digest(all_jobs: list[dict], total: int) -> str | None:
    """Generate a conversational AI narrative digest of new job matches via Claude."""
    try:
        import anthropic
        client = anthropic.Anthropic()

        job_lines = []
        for j in sorted(all_jobs, key=lambda x: x.get("score", 0), reverse=True)[:15]:
            job_lines.append(
                f"- {j['title']} at {j.get('company', 'Unknown')} "
                f"(match score: {j.get('score', '?')}/5, "
                f"why: {j.get('rationale', 'N/A')}, "
                f"best resume: {j.get('best_resume', 'N/A')}, "
                f"resume note: {j.get('resume_rationale', 'N/A')})"
            )

        prompt = (
            "You are writing a brief, conversational email digest for Corey Weil, a senior technical recruiter.\n\n"
            "Corey's background: 10+ years recruiting experience, previously at Trilogy Education "
            "(acquired for $750M), Presidents Club winner, targeting founding recruiter and senior "
            "technical recruiter roles at Series A/B startups. Also exploring AI Operations roles.\n\n"
            f"New job matches ({total} total):\n" + "\n".join(job_lines) + "\n\n"
            "Write a short, conversational email digest (3-5 sentences) that:\n"
            "1. Opens with a one-line summary (e.g. '8 new matches came in since your last check')\n"
            "2. Calls out the 1-2 strongest matches by name with a specific reason why they stand out\n"
            "3. Mentions the recommended resume for the top match\n"
            "4. Closes with a brief note if anything looks weak or worth skipping\n\n"
            "Be direct and conversational. Write flowing prose — no bullet points. "
            "No placeholder text or generic filler."
        )

        message = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()

    except Exception as exc:
        log.debug(f"Email digest generation failed: {exc}")
        return None


def send_email(config: dict, jobs_by_campaign: dict[str, list[dict]], last_email_at: datetime | None):
    cfg = config.get("email", {})
    if not cfg.get("enabled"):
        return False

    # Only include jobs posted after the last email was sent
    if last_email_at:
        filtered = {}
        for campaign, jobs in jobs_by_campaign.items():
            fresh = []
            for job in jobs:
                posted = job.get("posted_at")
                # No date available → include it (benefit of the doubt)
                if posted is None or posted >= last_email_at:
                    fresh.append(job)
                else:
                    log.debug(f"  DATE FILTERED: '{job['title']}' posted {posted.date()} before last email")
            filtered[campaign] = fresh
        jobs_by_campaign = filtered

    total = sum(len(j) for j in jobs_by_campaign.values())
    if total == 0:
        log.info("No jobs newer than last email — skipping send")
        return False

    # Flatten all jobs for digest generation
    all_jobs_flat = [j for jobs in jobs_by_campaign.values() for j in jobs]

    # Find top company for subject line
    top_job = max(all_jobs_flat, key=lambda x: x.get("score", 0), default=None)
    top_company = top_job.get("company", "") if top_job else ""
    subject = (
        f"[Job Tracker] {total} new match{'es' if total != 1 else ''} — {top_company} looks strong"
        if top_company else f"[Job Tracker] {total} new job match{'es' if total != 1 else ''}"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = cfg["username"]
    msg["To"]      = cfg.get("to", cfg["username"])

    # Generate AI narrative
    narrative = generate_email_digest(all_jobs_flat, total)

    html = ["<html><body style='font-family:Arial,sans-serif;max-width:800px;margin:auto'>"]
    html.append(f"<h1 style='color:#2c3e50'>Job Tracker &mdash; {total} New Posting(s)</h1>")
    if last_email_at:
        html.append(f"<p style='color:#666'>Jobs posted since last email: {last_email_at.strftime('%b %d at %H:%M')}</p>")

    # Add AI narrative block
    if narrative:
        html.append(
            "<div style='background:#f0f7ff;border-left:4px solid #2980b9;padding:16px 20px;"
            "margin:16px 0;border-radius:4px;font-size:15px;line-height:1.6;color:#2c3e50'>"
            f"{narrative}</div>"
        )

    for campaign, jobs in jobs_by_campaign.items():
        if not jobs:
            continue
        html.append(
            f"<h2 style='color:#2980b9;border-bottom:2px solid #2980b9;padding-bottom:4px'>"
            f"{campaign} <span style='font-size:14px;color:#666'>({len(jobs)} new)</span></h2>"
        )
        html.append("<table style='width:100%;border-collapse:collapse'>")
        html.append(
            "<tr style='background:#ecf0f1'>"
            "<th style='text-align:left;padding:8px'>Title</th>"
            "<th style='text-align:left;padding:8px'>Company</th>"
            "<th style='text-align:left;padding:8px'>Location</th>"
            "<th style='text-align:left;padding:8px'>Posted</th>"
            "<th style='text-align:left;padding:8px'>Source</th></tr>"
        )
        for i, job in enumerate(jobs):
            bg = "#fff" if i % 2 == 0 else "#f9f9f9"
            posted_str = job["posted_at"].strftime("%b %d") if job.get("posted_at") else ""
            html.append(
                f"<tr style='background:{bg}'>"
                f"<td style='padding:8px'><a href='{job['url']}' style='color:#2980b9'>{job['title']}</a></td>"
                f"<td style='padding:8px'>{job.get('company','')}</td>"
                f"<td style='padding:8px'>{job.get('location','')}</td>"
                f"<td style='padding:8px;color:#666'>{posted_str}</td>"
                f"<td style='padding:8px;color:#999'>{job.get('source','')}</td>"
                f"</tr>"
            )
        html.append("</table><br>")

    html.append("<p style='color:#999;font-size:12px'>Sent by Job Tracker &mdash; running on your machine</p>")
    html.append("</body></html>")
    msg.attach(MIMEText("\n".join(html), "html"))

    try:
        smtp_host = cfg.get("smtp_host", "smtp.gmail.com")
        smtp_port = cfg.get("smtp_port", 587)
        with smtplib.SMTP(smtp_host, smtp_port) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(cfg["username"], cfg["password"])
            smtp.send_message(msg)
        log.info(f"Email sent — {total} new jobs to {msg['To']}")
        return True
    except Exception as exc:
        log.error(f"Email failed: {exc}")
        return False


def send_desktop_notification(title: str, message: str):
    try:
        from plyer import notification
        notification.notify(title=title, message=message, app_name="Job Tracker", timeout=10)
    except Exception as exc:
        log.debug(f"Desktop notification skipped: {exc}")


# ---------------------------------------------------------------------------
# HTML Report
# ---------------------------------------------------------------------------

STATUS_COLORS = {
    "New":               "#3498db",
    "Applied":           "#e67e22",
    "Interviewing":      "#27ae60",
    "Offer":             "#f1c40f",
    "Rejected/Passed":   "#95a5a6",
}

def write_html_report(conn):
    rows     = load_all_jobs(conn)
    pipeline = get_pipeline_summary(conn)
    campaigns = sorted({r[0] for r in rows})

    html = ["""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Job Tracker Dashboard</title>
<style>
  body{font-family:Arial,sans-serif;max-width:1200px;margin:40px auto;padding:0 20px;color:#333}
  h1{color:#2c3e50} h2{color:#2980b9;border-bottom:2px solid #2980b9;padding-bottom:4px;margin-top:30px}
  table{width:100%;border-collapse:collapse;margin-bottom:30px}
  th{background:#2980b9;color:#fff;padding:10px;text-align:left}
  tr:nth-child(even){background:#f9f9f9} tr:hover{background:#eaf4ff}
  td{padding:9px;border-bottom:1px solid #eee}
  a{color:#2980b9;text-decoration:none} a:hover{text-decoration:underline}
  .badge{color:#fff;padding:3px 9px;border-radius:12px;font-size:12px;font-weight:bold}
  .source{color:#999;font-size:12px}
  .pipeline{display:flex;gap:16px;margin:20px 0}
  .pip-box{padding:14px 22px;border-radius:8px;color:#fff;text-align:center;min-width:100px}
  .pip-box .count{font-size:28px;font-weight:bold}
  .pip-box .label{font-size:12px;opacity:.9}
  .filters{margin-bottom:12px}
  .filters button{margin-right:6px;padding:5px 14px;border:1px solid #ccc;border-radius:4px;
    cursor:pointer;background:#fff;font-size:13px}
  .filters button.active{background:#2980b9;color:#fff;border-color:#2980b9}
</style>
<script>
function filterStatus(status) {
  document.querySelectorAll('tr[data-status]').forEach(r => {
    r.style.display = (!status || r.dataset.status === status) ? '' : 'none';
  });
  document.querySelectorAll('.filters button').forEach(b => {
    b.classList.toggle('active', b.dataset.filter === status);
  });
}
</script>
</head><body>"""]

    html.append("<h1>Job Tracker Dashboard</h1>")
    html.append(
        f"<p style='color:#666'>Last updated: {datetime.now().strftime('%A, %B %d %Y at %H:%M')}"
        f" &nbsp;|&nbsp; {len(rows)} total jobs tracked</p>"
    )

    # Pipeline summary boxes
    html.append("<div class='pipeline'>")
    for status, color in STATUS_COLORS.items():
        count = pipeline.get(status, 0)
        html.append(
            f"<div class='pip-box' style='background:{color}'>"
            f"<div class='count'>{count}</div>"
            f"<div class='label'>{status}</div></div>"
        )
    html.append("</div>")

    # Filter buttons
    html.append("<div class='filters'>")
    html.append("<strong>Filter: </strong>")
    html.append("<button onclick=\"filterStatus('')\" data-filter=''>All</button>")
    for status in STATUS_COLORS:
        html.append(f"<button onclick=\"filterStatus('{status}')\" data-filter='{status}'>{status}</button>")
    html.append("</div>")

    for campaign in campaigns:
        campaign_rows = [r for r in rows if r[0] == campaign]
        html.append(f"<h2>{campaign} <span style='font-size:14px;color:#666'>({len(campaign_rows)} jobs)</span></h2>")
        html.append(
            "<table><tr><th>Title</th><th>Company</th><th>Location</th>"
            "<th>Posted</th><th>Status</th><th>Source</th></tr>"
        )
        for r in campaign_rows:
            _, title, company, location, url, source, found_at, posted_at, status, *_ = r
            posted_str  = posted_at[:10] if posted_at else ""
            color       = STATUS_COLORS.get(status, "#3498db")
            html.append(
                f"<tr data-status='{status}'>"
                f"<td><a href='{url}' target='_blank'>{title}</a></td>"
                f"<td>{company}</td><td>{location}</td>"
                f"<td>{posted_str}</td>"
                f"<td><span class='badge' style='background:{color}'>{status}</span></td>"
                f"<td class='source'>{source}</td></tr>"
            )
        html.append("</table>")

    html.append("</body></html>")
    REPORT_PATH.write_text("\n".join(html), encoding="utf-8")
    log.info(f"HTML report written -> {REPORT_PATH}")


# ---------------------------------------------------------------------------
# Weekly Digest
# ---------------------------------------------------------------------------

def send_weekly_digest(config: dict, conn, since: datetime):
    cfg = config.get("email", {})
    if not cfg.get("enabled"):
        return False

    stats    = get_weekly_stats(conn, since)
    pipeline = get_pipeline_summary(conn)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Job Tracker] Weekly Digest — week of {since.strftime('%b %d')}"
    msg["From"]    = cfg["username"]
    msg["To"]      = cfg.get("to", cfg["username"])

    html = ["<html><body style='font-family:Arial,sans-serif;max-width:700px;margin:auto;color:#333'>"]
    html.append(f"<h1 style='color:#2c3e50'>Weekly Job Search Digest</h1>")
    html.append(f"<p style='color:#666'>Week of {since.strftime('%B %d')} &mdash; {datetime.now().strftime('%B %d, %Y')}</p>")

    # Pipeline
    html.append("<h2 style='color:#2980b9'>Pipeline Summary</h2>")
    html.append("<table style='border-collapse:collapse;width:300px'>")
    for status, color in STATUS_COLORS.items():
        count = pipeline.get(status, 0)
        html.append(
            f"<tr><td style='padding:7px 12px'>"
            f"<span style='background:{color};color:#fff;padding:2px 10px;border-radius:10px;font-size:12px'>{status}</span>"
            f"</td><td style='padding:7px;font-size:20px;font-weight:bold'>{count}</td></tr>"
        )
    html.append("</table>")

    # New jobs found
    html.append("<h2 style='color:#2980b9'>New Jobs Found This Week</h2>")
    if stats["new_by_campaign"]:
        html.append("<ul>")
        for campaign, count in stats["new_by_campaign"].items():
            html.append(f"<li><strong>{campaign}:</strong> {count} new postings</li>")
        html.append("</ul>")
    else:
        html.append("<p style='color:#666'>No new jobs found this week.</p>")

    # Applied this week
    html.append("<h2 style='color:#2980b9'>Applied This Week</h2>")
    if stats["applied"]:
        html.append("<ul>")
        for title, company, url, updated_at in stats["applied"]:
            date_str = updated_at[:10] if updated_at else ""
            html.append(f"<li><a href='{url}'>{title}</a> at {company} &mdash; {date_str}</li>")
        html.append("</ul>")
    else:
        html.append("<p style='color:#666'>No applications logged this week.</p>")

    # Currently interviewing
    if stats["interviewing"]:
        html.append("<h2 style='color:#27ae60'>Currently Interviewing</h2><ul>")
        for title, company, url in stats["interviewing"]:
            html.append(f"<li><a href='{url}'>{title}</a> at {company}</li>")
        html.append("</ul>")

    html.append("<p style='color:#999;font-size:12px;margin-top:30px'>Sent by Job Tracker &mdash; running on your machine</p>")
    html.append("</body></html>")
    msg.attach(MIMEText("\n".join(html), "html"))

    try:
        smtp_host = cfg.get("smtp_host", "smtp.gmail.com")
        smtp_port = cfg.get("smtp_port", 587)
        with smtplib.SMTP(smtp_host, smtp_port) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(cfg["username"], cfg["password"])
            smtp.send_message(msg)
        log.info(f"Weekly digest sent to {msg['To']}")
        return True
    except Exception as exc:
        log.error(f"Weekly digest failed: {exc}")
        return False


# ---------------------------------------------------------------------------
# Stale-job nudge system
# ---------------------------------------------------------------------------

def check_stale_jobs(conn) -> int:
    """
    Find jobs that have been sitting in a status too long and write an
    AI-generated (or rule-based fallback) nudge into the nudge column.

    Thresholds:
      New / Researching  -> 3 days
      Applied            -> 14 days
      Interviewing       -> 7 days

    Nudges are only written when nudge IS NULL so we don't overwrite an
    existing one.  They are cleared automatically when the user changes
    the status via the dashboard.
    """
    now = datetime.now(timezone.utc)
    cutoffs = {
        "New":          now - timedelta(days=3),
        "Researching":  now - timedelta(days=3),
        "Applied":      now - timedelta(days=14),
        "Interviewing": now - timedelta(days=7),
    }
    rule_nudges = {
        "New":          "Still sitting here — research the company and decide: apply or skip.",
        "Researching":  "Time to apply or move on; you've been researching for 3+ days.",
        "Applied":      "Two weeks with no reply — send a polite follow-up to the recruiter.",
        "Interviewing": "No update in a week — send a thank-you or check-in note today.",
    }

    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, title, company,
               COALESCE(status, 'New') AS status,
               status_updated_at, found_at
        FROM   seen_jobs
        WHERE  COALESCE(status, 'New') NOT IN ('Not a Fit', 'Rejected/Passed', 'Offer')
          AND  (nudge IS NULL OR nudge = '')
          AND  (
            (COALESCE(status, 'New') = 'New'
             AND CAST(COALESCE(NULLIF(status_updated_at, ''), found_at) AS TIMESTAMPTZ) < %s)
            OR
            (COALESCE(status, 'New') = 'Researching'
             AND status_updated_at IS NOT NULL AND status_updated_at <> ''
             AND CAST(status_updated_at AS TIMESTAMPTZ) < %s)
            OR
            (COALESCE(status, 'New') = 'Applied'
             AND status_updated_at IS NOT NULL AND status_updated_at <> ''
             AND CAST(status_updated_at AS TIMESTAMPTZ) < %s)
            OR
            (COALESCE(status, 'New') = 'Interviewing'
             AND status_updated_at IS NOT NULL AND status_updated_at <> ''
             AND CAST(status_updated_at AS TIMESTAMPTZ) < %s)
          )
        """,
        (cutoffs["New"], cutoffs["Researching"], cutoffs["Applied"], cutoffs["Interviewing"]),
    )
    stale = cur.fetchall()
    cur.close()

    if not stale:
        log.info("  -> 0 stale jobs to nudge")
        return 0

    try:
        import anthropic
        client = anthropic.Anthropic()
        use_llm = True
    except Exception:
        client = None
        use_llm = False

    updated = 0
    for (job_id, title, company, status, status_updated_at, found_at) in stale:
        since = parse_date(status_updated_at) or parse_date(found_at)
        days_in = int((now - since).days) if since else 0

        nudge_text = rule_nudges.get(status, "Take action or archive this job.")

        if use_llm and client:
            try:
                prompt = (
                    f"A job seeker has '{status}' status for {days_in} days:\n"
                    f"- Title: {title}\n"
                    f"- Company: {company}\n\n"
                    "Write one short, actionable nudge telling them exactly what to do next. "
                    "Be direct and specific. Under 20 words.\n"
                    'Respond ONLY with JSON: {"nudge": "<text>"}'
                )
                msg = client.messages.create(
                    model="claude-haiku-4-5",
                    max_tokens=80,
                    messages=[{"role": "user", "content": prompt}],
                )
                content = msg.content[0].text.strip()
                if content.startswith("```"):
                    content = re.sub(r"^```[a-z]*\n?", "", content)
                    content = re.sub(r"\n?```$", "", content).strip()
                result = json.loads(content)
                nudge_text = str(result.get("nudge", nudge_text))[:200]
            except Exception as exc:
                log.debug(f"Nudge LLM failed for '{title}': {exc}")

        cur2 = conn.cursor()
        cur2.execute("UPDATE seen_jobs SET nudge = %s WHERE id = %s", (nudge_text, job_id))
        conn.commit()
        cur2.close()
        updated += 1
        log.debug(f"  Nudged '{title}' ({status}, {days_in}d): {nudge_text}")

    log.info(f"  -> {updated} stale job(s) nudged")
    return updated


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    log.info("=" * 60)
    log.info("Job Tracker starting")

    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    state  = load_state()

    last_email_at: datetime | None = parse_date(state.get("last_email_at"))
    if last_email_at:
        log.info(f"Last email sent: {last_email_at.strftime('%Y-%m-%d %H:%M UTC')}")
    else:
        log.info("No previous email on record — all qualifying jobs will be included")

    # --- Phase 1: Scrape all job boards (no DB connection held open) ---
    campaigns: dict = config.get("campaigns", {})
    all_candidates: dict[str, list[dict]] = {}

    for campaign_name, campaign_cfg in campaigns.items():
        queries: list[str] = campaign_cfg.get("queries", [])
        filters: dict      = campaign_cfg.get("filters", {})
        log.info(f"--- Campaign: {campaign_name} ---")
        all_candidates[campaign_name] = run_campaign(campaign_name, queries, filters)

    # --- Phase 2: Connect to DB and save new jobs ---
    conn = init_db()
    new_jobs_by_campaign: dict[str, list[dict]] = {}

    for campaign_name, candidates in all_candidates.items():
        new_jobs = []
        for job in candidates:
            jid = job_fingerprint(job["title"], job.get("company", ""), job["url"])
            if not is_new(conn, jid):
                continue  # MD5 duplicate

            score, rationale = score_job_with_llm(
                job["title"],
                job.get("company", ""),
                job.get("description", ""),
            )
            best_resume, resume_score, resume_rationale = match_resume_to_job(
                conn,
                job["title"],
                job.get("company", ""),
                job.get("description", ""),
            )
            save_job(
                conn, jid, campaign_name,
                job["title"], job.get("company", ""),
                job.get("location", ""), job["url"], job["source"],
                job.get("posted_at"),
                score=score, rationale=rationale,
                best_resume=best_resume, resume_score=resume_score,
                resume_rationale=resume_rationale,
            )
            # Enrich job dict so email digest has full context
            job["score"]            = score
            job["rationale"]        = rationale
            job["best_resume"]      = best_resume
            job["resume_score"]     = resume_score
            job["resume_rationale"] = resume_rationale
            new_jobs.append(job)

        new_jobs_by_campaign[campaign_name] = new_jobs
        log.info(f"  -> {len(new_jobs)} NEW jobs (of {len(candidates)} found)")

    total_new = sum(len(j) for j in new_jobs_by_campaign.values())

    if total_new > 0:
        sent = send_email(config, new_jobs_by_campaign, last_email_at)
        if sent:
            state["last_email_at"] = datetime.now(timezone.utc).isoformat()
            save_state(state)

        for campaign, jobs in new_jobs_by_campaign.items():
            if jobs:
                send_desktop_notification(
                    f"Job Tracker: {len(jobs)} new",
                    f"{campaign}\n{', '.join(j['title'] for j in jobs[:3])}"
                    f"{'...' if len(jobs) > 3 else ''}",
                )

    # Weekly digest — send if 7+ days since last one
    last_digest_at: datetime | None = parse_date(state.get("last_digest_at"))
    weekly_due = (
        last_digest_at is None or
        (datetime.now(timezone.utc) - last_digest_at) >= timedelta(days=7)
    )
    if weekly_due:
        since = last_digest_at or (datetime.now(timezone.utc) - timedelta(days=7))
        log.info("Sending weekly digest...")
        sent = send_weekly_digest(config, conn, since)
        if sent:
            state["last_digest_at"] = datetime.now(timezone.utc).isoformat()
            save_state(state)

    # Nudge stale jobs — runs every cycle, only writes when nudge is NULL
    log.info("Checking for stale jobs...")
    check_stale_jobs(conn)

    write_html_report(conn)
    conn.close()
    log.info(f"Done. {total_new} new jobs found this run.")
    log.info("=" * 60)


if __name__ == "__main__":
    run()
