#!/usr/bin/env python3
"""
Embedded & Systems Job Aggregator & Google Sheets Bot
------------------------------------------------------
Sources: LinkedIn, Instahyre, HackerNews, Remotive.
Strict Domain Filter: Embedded Engineer, Embedded Linux, Firmware, C/C++ Systems, Microcontrollers.
"""

import csv
import json
import os
import re
import sys
import urllib.request
import urllib.parse
from datetime import datetime

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
    """Strict Embedded domain matching. Rejects non-embedded roles (DevOps, Data Analyst, Web, AI, etc.)."""
    text_lower = job_text.lower()
    title_lower = title.lower()

    # Comprehensive Exclude list for non-embedded roles
    strict_excludes = [
        "data analyst", "data engineer", "business analyst", "data scientist", "data science",
        "analyst", "qa analyst", "qa engineer", "test engineer", "software test",
        "react", "angular", "vue", "node", "java developer", "python developer", "web developer",
        "devops", "cloud", "frontend", "backend", "full stack", "fullstack", "ui/ux",
        "hr", "human resources", "recruiter", "sales", "marketing", "finance", "accountant",
        "scrum master", "product manager", "project manager", "business development",
        "3d modeller", "designer", "teachers", "senior staff", "lead architect", "director", "principal",
        "video editor", "ai engineer", "ai specialist", "cinematic"
    ] + [ex.lower() for ex in exclude_keywords]

    for ex in strict_excludes:
        if ex in title_lower:
            return 0, [f"Excluded title term: '{ex}'"]

    primary_embedded_terms = [
        "embedded", "firmware", "embedded linux", "microcontroller", "rtos",
        "freertos", "device driver", "kernel", "can bus", "uart", "i2c", "spi",
        "bare metal", "c++ developer", "c developer", "low-level", "pic18f4580",
        "board support", "bsp", "soc", "fpga", "dsp"
    ]

    matched_keys = []
    score = 0

    title_matched = False
    for term in primary_embedded_terms:
        if term in title_lower:
            matched_keys.append(f"Title:{term}")
            score += 30
            title_matched = True

    if title_matched:
        for kw in include_keywords:
            pattern = r"\b" + re.escape(kw.lower()) + r"\b"
            if re.search(pattern, text_lower):
                matched_keys.append(kw)
                score += 10

    # Strict requirement: Job title MUST explicitly match embedded domain
    if not title_matched or score < 30:
        return 0, ["Title does not match embedded engineering domain"]

    return score, matched_keys


def http_get(url, extra_headers=None):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9"
    }
    if extra_headers:
        headers.update(extra_headers)

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            if response.status == 200:
                return response.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"Warning: HTTP GET failed for {url}: {e}")
    return None


def fetch_linkedin_jobs():
    """Fetches public LinkedIn job listings for Embedded C/C++ roles."""
    print("Fetching jobs from LinkedIn...")
    keywords = urllib.parse.quote("Embedded Firmware C++ Linux")
    url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={keywords}&location=India&start=0"

    html = http_get(url)
    jobs = []
    if html:
        job_blocks = html.split("<li")
        for block in job_blocks[1:]:
            title_match = re.search(r'class="base-search-card__title"[^>]*>\s*([^<]+)\s*<', block)
            company_match = re.search(r'class="base-search-card__subtitle"[^>]*>\s*([^<]+)\s*<', block)
            location_match = re.search(r'class="job-search-card__location"[^>]*>\s*([^<]+)\s*<', block)
            link_match = re.search(r'href="(https://[^"]+linkedin\.com/jobs/view/[^"?]+)', block)

            if title_match and link_match:
                title = title_match.group(1).strip()
                company = company_match.group(1).strip() if company_match else "LinkedIn Company"
                location = location_match.group(1).strip() if location_match else "India / Remote"
                link = link_match.group(1).strip()

                jobs.append({
                    "source": "LinkedIn",
                    "title": title,
                    "company": company,
                    "location": location,
                    "link": link,
                    "date_posted": datetime.now().strftime("%Y-%m-%d"),
                    "full_text": f"{title} {company} {location}"
                })
    return jobs


def fetch_instahyre_jobs():
    """Fetches real job listings from Instahyre's public API for Embedded & Firmware roles."""
    print("Fetching jobs from Instahyre...")
    designations = ["Embedded", "Firmware", "Embedded Linux", "Microcontroller", "C++ Developer", "Systems Engineer"]
    jobs = []
    seen_urls = set()

    for des in designations:
        url = f"https://www.instahyre.com/api/v1/job_search?designation={urllib.parse.quote(des)}"
        data = http_get(url, extra_headers={"Accept": "application/json"})
        if data:
            try:
                parsed = json.loads(data)
                for item in parsed.get("objects", []):
                    public_url = item.get("public_url", "").strip()
                    if not public_url or public_url in seen_urls:
                        continue
                    seen_urls.add(public_url)

                    title = item.get("title", "").strip()
                    employer = item.get("employer", {}) if isinstance(item.get("employer"), dict) else {}
                    company = employer.get("company_name", "").strip() or "Instahyre Hiring Company"
                    location = item.get("locations", "").strip() or "India"
                    keywords = item.get("keywords", [])
                    kw_str = " ".join(keywords) if isinstance(keywords, list) else str(keywords)

                    jobs.append({
                        "source": "Instahyre",
                        "title": title,
                        "company": company,
                        "location": location,
                        "link": public_url,
                        "date_posted": datetime.now().strftime("%Y-%m-%d"),
                        "full_text": f"{title} {company} {location} {kw_str}"
                    })
            except Exception as e:
                print(f"Warning parsing Instahyre response for '{des}': {e}")
    return jobs


def fetch_hackernews_jobs():
    """Fetches embedded tech job postings from HackerNews (Who is Hiring) via Algolia API."""
    print("Fetching jobs from HackerNews (Who is Hiring)...")
    url = "https://hn.algolia.com/api/v1/search?query=embedded+hiring&tags=comment"
    data = http_get(url, extra_headers={"Accept": "application/json"})
    jobs = []
    if data:
        try:
            parsed = json.loads(data)
            for item in parsed.get("hits", []):
                comment_text = item.get("comment_text", "")
                object_id = item.get("objectID", "")
                link = f"https://news.ycombinator.com/item?id={object_id}"

                clean_text = re.sub(r'<[^>]+>', ' ', comment_text)
                first_line = clean_text.strip().split("\n")[0][:120]
                first_line_lower = first_line.lower()

                if any(k in first_line_lower for k in ["embedded", "firmware", "microcontroller", "hardware", "rtos", "bsp"]):
                    jobs.append({
                        "source": "HackerNews",
                        "title": first_line,
                        "company": "HN Startup / Tech Company",
                        "location": "Remote / Tech Hub",
                        "link": link,
                        "date_posted": datetime.now().strftime("%Y-%m-%d"),
                        "full_text": clean_text
                    })
        except Exception as e:
            print(f"Warning parsing HackerNews response: {e}")
    return jobs


def fetch_remotive_jobs():
    """Fetches remote embedded jobs from Remotive API."""
    print("Fetching jobs from Remotive Remote API...")
    url = "https://remotive.com/api/remote-jobs?search=embedded"
    data = http_get(url, extra_headers={"Accept": "application/json"})
    jobs = []
    if data:
        try:
            parsed = json.loads(data)
            for item in parsed.get("jobs", []):
                title = item.get("title", "")
                company = item.get("company_name", "")
                link = item.get("url", "")
                desc = re.sub(r'<[^>]+>', ' ', item.get("description", ""))

                jobs.append({
                    "source": "Remotive",
                    "title": title,
                    "company": company,
                    "location": item.get("candidate_required_location", "Remote"),
                    "link": link,
                    "date_posted": datetime.now().strftime("%Y-%m-%d"),
                    "full_text": f"{title} {company} {desc}"
                })
        except Exception as e:
            print(f"Warning parsing Remotive response: {e}")
    return jobs


def get_google_sheet_client():
    if not GSPREAD_AVAILABLE:
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
    except Exception as e:
        print(f"Error connecting to Google Sheets API: {e}")
    return None


def update_google_sheet(sheet_id, worksheet_name, matched_jobs):
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
        headers = ["Date Added", "Source", "Job Title", "Location", "Match Score", "Matched Keywords", "Link", "Status", "Company Name"]

        if not existing_data:
            worksheet.append_row(headers, table_range="A1", value_input_option="USER_ENTERED")
            existing_links = set()
        else:
            header_row = existing_data[0]
            link_col_idx = header_row.index("Link") if "Link" in header_row else 6
            existing_links = {row[link_col_idx].strip() for row in existing_data[1:] if len(row) > link_col_idx}

            if "Company Name" not in header_row:
                try:
                    worksheet.update(range_name="A1:I1", values=[headers], value_input_option="USER_ENTERED")
                except Exception as e:
                    print(f"Warning updating headers: {e}")

        new_rows = []
        for j in matched_jobs:
            if j["Link"] not in existing_links:
                new_rows.append([
                    j["Date Added"],
                    j["Source"],
                    j["Job Title"],
                    j["Location"],
                    j["Match Score"],
                    j["Matched Keywords"],
                    j["Link"],
                    j["Status"],
                    j["Company"]  # Company Name in the last column
                ])
                existing_links.add(j["Link"])

        if new_rows:
            worksheet.append_rows(new_rows, table_range="A1", value_input_option="USER_ENTERED")
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
        msg += f"Scanned *{total_raw_count}* postings across LinkedIn, Instahyre, HackerNews & Remotive.\n"
        msg += f"Found *{new_jobs_count}* new Embedded/Firmware/Linux matching jobs!\n\n"
        msg += "*Top Roles Added to Sheet:*\n"

        for i, job in enumerate(top_jobs[:5], 1):
            msg += f"{i}. [{job['title']}]({job['link']}) @ *{job['company']}* ({job['source']})\n"
            msg += f"   📍 {job['location']} | Match Score: `{job['score']}`\n"

        if sheet_url:
            msg += f"\n📊 [**Open Google Sheets Tracker**]({sheet_url})"
    else:
        msg = f"✅ *Embedded Job Search Execution Complete*\n"
        msg += f"Scanned *{total_raw_count}* postings across LinkedIn, Instahyre, HackerNews & Remotive.\n"
        msg += f"No new Embedded roles found in this run. Your sheet is up to date!\n"
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
            else:
                body = response.read().decode('utf-8')
                print(f"Telegram error response: {body}")
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

    # 1. Fetch raw jobs specifically from LinkedIn, Instahyre, HackerNews, & Remotive
    raw_jobs = []
    raw_jobs.extend(fetch_linkedin_jobs())
    raw_jobs.extend(fetch_instahyre_jobs())
    raw_jobs.extend(fetch_hackernews_jobs())
    raw_jobs.extend(fetch_remotive_jobs())

    total_raw_count = len(raw_jobs)
    print(f"Total raw jobs fetched: {total_raw_count}")

    # 2. Filter & score with strict Embedded Domain rules
    matched_jobs = []
    for j in raw_jobs:
        link = j["link"].strip()

        score, matches = calculate_match_score(j["title"], j["full_text"], inc_kw, exc_kw)
        if score > 0:
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
    print(f"Strict Embedded field roles matched: {len(matched_jobs)}")

    # 3. Update Google Sheet
    added_count = 0
    if sheet_id and sheet_id != "YOUR_SPREADSHEET_ID_HERE":
        added_count, _ = update_google_sheet(sheet_id, worksheet_name, matched_jobs)
    else:
        print("Notice: SPREADSHEET_ID not set in env.")
        added_count = len(matched_jobs)

    # 4. Telegram Alert
    if telegram_token and telegram_token != "YOUR_TELEGRAM_BOT_TOKEN":
        top_jobs = [
            {
                "title": j["Job Title"],
                "company": j["Company"],
                "location": j["Location"],
                "link": j["Link"],
                "score": j["Match Score"],
                "source": j["Source"]
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
