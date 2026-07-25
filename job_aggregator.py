#!/usr/bin/env python3
"""
Embedded & Systems Job Aggregator & Google Sheets Bot
------------------------------------------------------
Features:
1. Aggregates Embedded, Firmware, C/C++, and Linux Systems jobs from multiple APIs.
2. Filters by skillset keywords extracted from Prayush B Menon's portfolio.
3. Connects to Google Sheets via `gspread` (Service Account JSON) to deduplicate and log jobs.
4. Sends Telegram notifications with run status, job count, top matches, and a direct Google Sheets link.
"""

import json
import os
import re
import sys
import urllib.request
import urllib.parse
from datetime import datetime

# Attempt to import gspread for Google Sheets integration
try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config():
    if not os.path.exists(CONFIG_PATH):
        print(f"Error: Config file not found at {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def calculate_match_score(title, job_text, include_keywords, exclude_keywords):
    """Calculates match score based on keyword frequency, title relevance, and exclusion rules."""
    text_lower = job_text.lower()
    title_lower = title.lower()

    # Check for deal-breaker exclude keywords
    for ex in exclude_keywords:
        if ex.lower() in text_lower or ex.lower() in title_lower:
            return 0, [f"Excluded: '{ex}'"]

    matched_keys = []
    score = 0

    core_title_terms = [
        "embedded", "firmware", "c++", "linux", "systems",
        "kernel", "device driver", "rtos", "low-level", "microcontroller"
    ]
    for term in core_title_terms:
        if term in title_lower:
            matched_keys.append(f"Title:{term}")
            score += 25

    for kw in include_keywords:
        pattern = r"\b" + re.escape(kw.lower()) + r"\b"
        if re.search(pattern, text_lower):
            matched_keys.append(kw)
            score += 10

    return score, matched_keys


def http_get_json(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            if response.status == 200:
                body = response.read().decode("utf-8")
                return json.loads(body)
    except Exception as e:
        print(f"Warning: HTTP GET failed for {url}: {e}")
    return None


def fetch_remoteok_jobs():
    print("Fetching jobs from RemoteOK API...")
    data = http_get_json("https://remoteok.com/api")
    jobs = []
    if data and isinstance(data, list):
        for item in data[1:]:
            title = item.get("position", "")
            company = item.get("company", "")
            description = item.get("description", "")
            tags = item.get("tags", [])
            link = item.get("url", item.get("apply_url", ""))
            date_str = item.get("date", datetime.now().strftime("%Y-%m-%d"))

            full_text = f"{title} {' '.join(tags)} {description}"
            jobs.append({
                "source": "RemoteOK",
                "title": title,
                "company": company,
                "location": "Remote",
                "link": link,
                "date_posted": date_str,
                "full_text": full_text
            })
    return jobs


def fetch_remotive_jobs():
    print("Fetching jobs from Remotive API...")
    data = http_get_json("https://remotive.com/api/remote-jobs?category=software-dev")
    jobs = []
    if data and isinstance(data, dict):
        items = data.get("jobs", [])
        for item in items:
            title = item.get("title", "")
            company = item.get("company_name", "")
            description = item.get("description", "")
            link = item.get("url", "")
            date_str = item.get("publication_date", datetime.now().strftime("%Y-%m-%d"))

            full_text = f"{title} {description}"
            jobs.append({
                "source": "Remotive",
                "title": title,
                "company": company,
                "location": item.get("candidate_required_location", "Remote"),
                "link": link,
                "date_posted": date_str,
                "full_text": full_text
            })
    return jobs


def fetch_hn_jobs():
    print("Fetching hiring posts from Hacker News API...")
    query_url = "https://hn.algolia.com/api/v1/search_by_date?tags=story&query=" + urllib.parse.quote("Ask HN: Who is hiring?")
    data = http_get_json(query_url)
    jobs = []
    if data and "hits" in data:
        hits = data["hits"][:2]
        for hit in hits:
            story_id = hit.get("objectID")
            if not story_id:
                continue
            comments_url = f"https://hn.algolia.com/api/v1/search?tags=comment,story_{story_id}&hitsPerPage=100"
            comments_data = http_get_json(comments_url)
            if comments_data and "hits" in comments_data:
                for c in comments_data["hits"]:
                    text = c.get("comment_text", "")
                    hn_url = f"https://news.ycombinator.com/item?id={c.get('objectID')}"
                    lines = [line.strip() for line in text.split("\n") if line.strip()]
                    title_line = lines[0] if lines else "HN Job Posting"
                    jobs.append({
                        "source": "HackerNews Hiring",
                        "title": title_line[:100],
                        "company": "HN Poster",
                        "location": "Various / Remote",
                        "link": hn_url,
                        "date_posted": datetime.now().strftime("%Y-%m-%d"),
                        "full_text": text
                    })
    return jobs


def get_google_sheet_client():
    if not GSPREAD_AVAILABLE:
        print("Warning: gspread/google-auth not installed. Google Sheets update disabled.")
        return None

    json_str = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    local_service_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "service_account.json")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]

    try:
        if json_str:
            info = json.loads(json_str)
            creds = Credentials.from_service_account_info(info, scopes=scopes)
            return gspread.authorize(creds)
        elif os.path.exists(local_service_file):
            creds = Credentials.from_service_account_file(local_service_file, scopes=scopes)
            return gspread.authorize(creds)
        else:
            print("Notice: GOOGLE_SERVICE_ACCOUNT_JSON not provided. Google Sheets sync skipped.")
            return None
    except Exception as e:
        print(f"Error connecting to Google Sheets API: {e}")
        return None


def update_google_sheet(sheet_id, worksheet_name, matched_jobs):
    """Appends new matched jobs to Google Sheet and deduplicates by URL."""
    gc = get_google_sheet_client()
    if not gc:
        return 0, set()

    try:
        sh = gc.open_by_key(sheet_id)
        try:
            worksheet = sh.worksheet(worksheet_name)
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sh.add_worksheet(title=worksheet_name, rows=1000, cols=10)

        existing_data = worksheet.get_all_values()
        headers = ["Date Added", "Source", "Job Title", "Company", "Location", "Match Score", "Matched Keywords", "Link", "Status"]

        if not existing_data:
            worksheet.append_row(headers)
            existing_links = set()
        else:
            header_row = existing_data[0]
            link_col_idx = 7
            if "Link" in header_row:
                link_col_idx = header_row.index("Link")
            existing_links = {row[link_col_idx].strip() for row in existing_data[1:] if len(row) > link_col_idx}

        new_rows = []
        for j in matched_jobs:
            if j["Link"] not in existing_links:
                new_rows.append([
                    j["Date Added"],
                    j["Source"],
                    j["Job Title"],
                    j["Company"],
                    j["Location"],
                    j["Match Score"],
                    j["Matched Keywords"],
                    j["Link"],
                    j["Status"]
                ])
                existing_links.add(j["Link"])

        if new_rows:
            worksheet.append_rows(new_rows)
            print(f"✅ Added {len(new_rows)} new rows to Google Sheet '{worksheet_name}'.")

        return len(new_rows), existing_links

    except Exception as e:
        print(f"Error updating Google Sheet: {e}")
        return 0, set()


def send_telegram_alert(bot_token, chat_id, total_raw_count, new_jobs_count, top_jobs, sheet_id):
    if not bot_token or bot_token == "YOUR_TELEGRAM_BOT_TOKEN":
        print("Telegram bot token not configured. Skipping notification.")
        return

    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}" if sheet_id and sheet_id != "YOUR_SPREADSHEET_ID_HERE" else ""

    if new_jobs_count > 0:
        msg = f"🔍 *Embedded Job Search Alert*\n"
        msg += f"Scanned *{total_raw_count}* postings across APIs.\n"
        msg += f"Found *{new_jobs_count}* new matching jobs for your profile!\n\n"
        msg += "*Top Matching Roles:*\n"

        for i, job in enumerate(top_jobs[:5], 1):
            msg += f"{i}. [{job['title']}]({job['link']}) @ *{job['company']}*\n"
            msg += f"   📍 {job['location']} | Match Score: `{job['score']}`\n"

        if sheet_url:
            msg += f"\n📊 [**Open Google Sheets Tracker**]({sheet_url})"
    else:
        msg = f"✅ *Job Search Execution Complete*\n"
        msg += f"Scanned *{total_raw_count}* postings across APIs.\n"
        msg += f"No new Embedded/Linux/Systems jobs matched this batch. Your tracker is up to date!\n"
        if sheet_url:
            msg += f"\n📊 [**Open Google Sheets Tracker**]({sheet_url})"

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": msg,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                print("Telegram notification sent successfully!")
    except Exception as e:
        print(f"Error sending Telegram notification: {e}")


def main():
    config = load_config()

    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", config.get("telegram", {}).get("bot_token"))
    telegram_chat = os.environ.get("TELEGRAM_CHAT_ID", config.get("telegram", {}).get("chat_id"))
    sheet_id = os.environ.get("SPREADSHEET_ID", config.get("google_sheets", {}).get("spreadsheet_id"))
    worksheet_name = config.get("google_sheets", {}).get("worksheet_name", "Job Tracker")

    inc_kw = config.get("include_keywords", [])
    exc_kw = config.get("exclude_keywords", [])

    # 1. Fetch raw jobs
    raw_jobs = []
    raw_jobs.extend(fetch_remoteok_jobs())
    raw_jobs.extend(fetch_remotive_jobs())
    raw_jobs.extend(fetch_hn_jobs())

    total_raw_count = len(raw_jobs)
    print(f"Total raw jobs fetched: {total_raw_count}")

    # 2. Filter & score
    matched_jobs = []
    for j in raw_jobs:
        link = j["link"].strip()

        score, matches = calculate_match_score(j["title"], j["full_text"], inc_kw, exc_kw)
        if score >= 10:  # Include match score threshold
            job_entry = {
                "Date Added": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "Source": j["source"],
                "Job Title": j["title"].strip(),
                "Company": j["company"].strip(),
                "Location": j["location"].strip(),
                "Match Score": score,
                "Matched Keywords": ", ".join(matches),
                "Link": link,
                "Status": "New"
            }
            matched_jobs.append(job_entry)

    matched_jobs.sort(key=lambda x: x["Match Score"], reverse=True)
    print(f"Matching embedded/systems roles filtered: {len(matched_jobs)}")

    # 3. Update Google Sheet
    added_count = 0
    if sheet_id and sheet_id != "YOUR_SPREADSHEET_ID_HERE":
        added_count, _ = update_google_sheet(sheet_id, worksheet_name, matched_jobs)
    else:
        print("Notice: SPREADSHEET_ID not set in env or config.")
        added_count = len(matched_jobs)

    # 4. Telegram Alert (Always send ping so user gets execution feedback!)
    if telegram_token and telegram_token != "YOUR_TELEGRAM_BOT_TOKEN":
        top_jobs = [
            {
                "title": j["Job Title"],
                "company": j["Company"],
                "location": j["Location"],
                "link": j["Link"],
                "score": j["Match Score"]
            }
            for j in matched_jobs
        ]
        send_telegram_alert(
            telegram_token,
            telegram_chat,
            total_raw_count,
            added_count,
            top_jobs,
            sheet_id
        )


if __name__ == "__main__":
    main()
