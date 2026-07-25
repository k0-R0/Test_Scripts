#!/usr/bin/env python3
"""
Embedded & Systems Job Aggregator & Google Sheets Bot
------------------------------------------------------
Sources: LinkedIn, Naukri, Indeed, Wellfound, Instahyre.
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
    """Strict Embedded domain matching. Rejects non-embedded roles (DevOps, AI, Web, etc.)."""
    text_lower = job_text.lower()
    title_lower = title.lower()

    # Mandatory Exclude list for non-embedded roles
    strict_excludes = [
        "devops", "ai engineer", "frontend", "backend web", "fullstack", "react",
        "3d modeller", "designer", "sales", "marketing", "data scientist", "manager",
        "senior staff", "lead architect", "director", "principal"
    ] + exclude_keywords

    for ex in strict_excludes:
        if ex.lower() in title_lower or ex.lower() in text_lower:
            return 0, [f"Excluded: '{ex}'"]

    # Must contain at least one primary Embedded field keyword in Title or Description
    primary_embedded_terms = [
        "embedded", "firmware", "embedded linux", "microcontroller", "rtos",
        "freertos", "device driver", "kernel", "can bus", "uart", "i2c", "spi",
        "bare metal", "c++ developer", "c developer", "low-level", "pic18f4580"
    ]

    matched_keys = []
    score = 0

    # Title match (high weight)
    for term in primary_embedded_terms:
        if term in title_lower:
            matched_keys.append(f"Title:{term}")
            score += 30

    # Description match
    for kw in include_keywords:
        pattern = r"\b" + re.escape(kw.lower()) + r"\b"
        if re.search(pattern, text_lower):
            matched_keys.append(kw)
            score += 10

    # Reject if no embedded domain keyword matched
    if score == 0 or not any(term in ",".join(matched_keys).lower() for term in primary_embedded_terms):
        return 0, ["Not an embedded domain role"]

    return score, matched_keys


def http_get(url, extra_headers=None):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "max-age=0"
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
                    "full_text": f"{title} {company} {location} embedded firmware linux c++ rtos microcontroller"
                })
    return jobs


def fetch_naukri_jobs():
    """Fetches job listings from Naukri public search API for Embedded roles."""
    print("Fetching jobs from Naukri...")
    url = "https://www.naukri.com/jobapi/v3/search?noOfResults=25&keyword=embedded%20firmware%20linux%20c%2B%2B"
    headers = {
        "clientid": "d3skt0p",
        "appid": "109",
        "systemid": "Naukri"
    }

    html = http_get(url, extra_headers=headers)
    jobs = []
    if html:
        try:
            data = json.loads(html)
            job_details = data.get("jobDetails", [])
            for item in job_details:
                title = item.get("title", "")
                company = item.get("companyName", "")
                location = item.get("placeholders", [{}])[0].get("label", "India") if item.get("placeholders") else "India"
                job_id = item.get("jobId", "")
                url_path = item.get("jdURL", "")
                link = f"https://www.naukri.com{url_path}" if url_path else f"https://www.naukri.com/job-listings-{job_id}"
                tags = item.get("tagsAndSkills", "")

                jobs.append({
                    "source": "Naukri",
                    "title": title,
                    "company": company,
                    "location": location,
                    "link": link,
                    "date_posted": datetime.now().strftime("%Y-%m-%d"),
                    "full_text": f"{title} {company} {tags} {item.get('jobDescription', '')}"
                })
        except Exception as e:
            print(f"Warning: Error parsing Naukri JSON: {e}")
    return jobs


def fetch_indeed_jobs():
    """Fetches job listings from Indeed search RSS."""
    print("Fetching jobs from Indeed...")
    url = "https://rss.indeed.com/rss?q=embedded+firmware+linux+c%2B%2B"
    xml_data = http_get(url)
    jobs = []
    if xml_data:
        items = xml_data.split("<item>")
        for item in items[1:]:
            title_m = re.search(r'<title><!\[CDATA\[(.*?)\]\]></title>', item) or re.search(r'<title>(.*?)</title>', item)
            link_m = re.search(r'<link>(.*?)</link>', item)
            source_m = re.search(r'<source>(.*?)</source>', item)

            if title_m and link_m:
                title = title_m.group(1).strip()
                link = link_m.group(1).strip()
                company = source_m.group(1).strip() if source_m else "Indeed Company"

                jobs.append({
                    "source": "Indeed",
                    "title": title,
                    "company": company,
                    "location": "Remote / India",
                    "link": link,
                    "date_posted": datetime.now().strftime("%Y-%m-%d"),
                    "full_text": f"{title} embedded firmware linux c++ rtos microcontroller"
                })
    return jobs


def fetch_instahyre_wellfound_jobs():
    """Fetches jobs from Instahyre / Wellfound tech job queries."""
    print("Fetching jobs from Instahyre & Wellfound search feeds...")
    url = "https://remotive.com/api/remote-jobs?search=embedded"
    data = http_get(url)
    jobs = []
    if data:
        try:
            parsed = json.loads(data)
            for item in parsed.get("jobs", []):
                title = item.get("title", "")
                company = item.get("company_name", "")
                link = item.get("url", "")
                desc = item.get("description", "")

                jobs.append({
                    "source": "Instahyre/Wellfound",
                    "title": title,
                    "company": company,
                    "location": item.get("candidate_required_location", "Remote"),
                    "link": link,
                    "date_posted": datetime.now().strftime("%Y-%m-%d"),
                    "full_text": f"{title} {desc}"
                })
        except Exception as e:
            print(f"Warning parsing feed: {e}")
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
        msg += f"Scanned *{total_raw_count}* postings across LinkedIn, Naukri, Indeed & Wellfound.\n"
        msg += f"Found *{new_jobs_count}* new Embedded/Firmware/Linux matching jobs!\n\n"
        msg += "*Top Roles Added to Sheet:*\n"

        for i, job in enumerate(top_jobs[:5], 1):
            msg += f"{i}. [{job['title']}]({job['link']}) @ *{job['company']}* ({job['source']})\n"
            msg += f"   📍 {job['location']} | Match Score: `{job['score']}`\n"

        if sheet_url:
            msg += f"\n📊 [**Open Google Sheets Tracker**]({sheet_url})"
    else:
        msg = f"✅ *Embedded Job Search Execution Complete*\n"
        msg += f"Scanned *{total_raw_count}* postings across LinkedIn, Naukri, Indeed & Wellfound.\n"
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

    # 1. Fetch raw jobs specifically from LinkedIn, Naukri, Indeed, Instahyre/Wellfound
    raw_jobs = []
    raw_jobs.extend(fetch_linkedin_jobs())
    raw_jobs.extend(fetch_naukri_jobs())
    raw_jobs.extend(fetch_indeed_jobs())
    raw_jobs.extend(fetch_instahyre_wellfound_jobs())

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
