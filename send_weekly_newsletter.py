"""
Weekly Newsletter Sender
================================================================
Standalone script (NOT part of the Streamlit app) that:
1. Reads newsletter_subscribers.csv
2. Builds a personalized price-trend + news summary per subscriber,
   based on the products they chose
3. Sends each subscriber a plain-text email via SMTP

WHY THIS IS SEPARATE FROM THE DASHBOARD:
Streamlit apps only run while someone has the page open - there's no
built-in way to run code "in the background" on a schedule. So this
script is designed to be triggered on a timer by GitHub Actions instead
(see .github/workflows/weekly-newsletter.yml).

REQUIRED ENVIRONMENT VARIABLES (set as GitHub Secrets - see README):
  EMAIL_ADDRESS       - the Gmail address to send FROM
  EMAIL_APP_PASSWORD  - a Gmail "App Password" (NOT your normal password -
                         see setup instructions in the README)

HOW TO RUN LOCALLY (for testing):
  1. pip install -r requirements.txt
  2. Set the two environment variables above, e.g. on Windows:
       set EMAIL_ADDRESS=youraddress@gmail.com
       set EMAIL_APP_PASSWORD=your16digitapppassword
     On Mac/Linux:
       export EMAIL_ADDRESS=youraddress@gmail.com
       export EMAIL_APP_PASSWORD=your16digitapppassword
  3. python send_weekly_newsletter.py
"""

import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import pandas as pd
import numpy as np
import feedparser
import re
from datetime import datetime

SUBSCRIBERS_FILE = "newsletter_subscribers.csv"

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465

PRODUCTS = {
    "PMS": "Petrol (PMS)",
    "AGO": "Diesel (AGO)",
    "DPK": "Kerosene (DPK)",
    "LPG": "Cooking Gas (LPG)",
    "CNG": "Compressed Natural Gas (CNG)",
}

ALL_STATES = [
    "Abia", "Adamawa", "Akwa Ibom", "Anambra", "Bauchi", "Bayelsa", "Benue",
    "Borno", "Cross River", "Delta", "Ebonyi", "Edo", "Ekiti", "Enugu",
    "Gombe", "Imo", "Jigawa", "Kaduna", "Kano", "Katsina", "Kebbi", "Kogi",
    "Kwara", "Lagos", "Nasarawa", "Niger", "Ogun", "Ondo", "Osun", "Oyo",
    "Plateau", "Rivers", "Sokoto", "Taraba", "Yobe", "Zamfara", "FCT Abuja"
]

BASE_PRICE_RANGE = {
    "PMS": (950, 1350), "AGO": (1400, 1900), "DPK": (1100, 1600),
    "LPG": (1400, 1900), "CNG": (230, 350),
}

MONTHS = pd.date_range("2026-01-01", periods=6, freq="MS")

NATIONAL_FEEDS = [
    "https://punchng.com/feed/",
    "https://www.vanguardngr.com/feed/",
    "https://guardian.ng/feed/",
]
INTERNATIONAL_FEEDS = [
    "https://oilprice.com/rss/main",
    "https://www.eia.gov/rss/todayinenergy.xml",
    "https://www.rigzone.com/news/rss/rigzone_latest.aspx",
]
ENERGY_KEYWORDS = [
    "oil", "gas", "petrol", "diesel", "fuel", "nnpc", "nnpcl", "crude",
    "refinery", "opec", "energy", "lng", "lpg", "cng", "pms", "ago",
    "dangote refinery", "nmdpra", "depot", "petroleum", "gantry"
]


def generate_sample_data():
    """Same placeholder-data logic as the dashboard. IMPORTANT: once you
    wire the dashboard up to real data, update this function to match -
    ideally both scripts should read from the same real CSV file so the
    newsletter and the live dashboard never disagree."""
    rng = np.random.default_rng(seed=42)
    rows = []
    for product in PRODUCTS:
        low, high = BASE_PRICE_RANGE[product]
        for state in ALL_STATES:
            state_baseline = rng.uniform(low, high)
            for i, month in enumerate(MONTHS):
                trend = i * rng.uniform(5, 25)
                noise = rng.normal(0, 15)
                price = max(state_baseline + trend + noise, 100)
                rows.append({
                    "date": month, "state": state, "product": product,
                    "price_naira_per_litre": round(price, 2)
                })
    return pd.DataFrame(rows)


def _strip_html(raw_text):
    return re.sub("<[^>]+>", "", raw_text or "").strip()


def fetch_news(feed_urls, keyword_filter=None, limit=5):
    articles = []
    for url in feed_urls:
        try:
            parsed = feedparser.parse(url)
            source_name = parsed.feed.get("title", url)
            for entry in parsed.entries:
                title = entry.get("title", "").strip()
                summary = _strip_html(entry.get("summary", entry.get("description", "")))
                link = entry.get("link", "")
                time_struct = entry.get("published_parsed") or entry.get("updated_parsed")
                pub_date = datetime(*time_struct[:6]) if time_struct else datetime.min

                if keyword_filter:
                    haystack = f"{title} {summary}".lower()
                    if not any(kw in haystack for kw in keyword_filter):
                        continue
                if not title or not link:
                    continue

                articles.append({
                    "title": title, "link": link, "date": pub_date, "source": source_name
                })
        except Exception:
            continue
    articles.sort(key=lambda a: a["date"], reverse=True)
    return articles[:limit]


def build_price_summary(df, product_code):
    """Builds a short text summary of this week's price picture for one product."""
    product_df = df[df["product"] == product_code]
    latest_month = product_df["date"].max()
    latest = product_df[product_df["date"] == latest_month]

    avg_price = latest["price_naira_per_litre"].mean()
    cheapest = latest.loc[latest["price_naira_per_litre"].idxmin()]
    priciest = latest.loc[latest["price_naira_per_litre"].idxmax()]
    unit = "kg" if product_code in ("LPG", "CNG") else "litre"

    lines = [
        f"{PRODUCTS[product_code]}:",
        f"  National average: ₦{avg_price:,.0f}/{unit}",
        f"  Cheapest: {cheapest['state']} (₦{cheapest['price_naira_per_litre']:,.0f})",
        f"  Most expensive: {priciest['state']} (₦{priciest['price_naira_per_litre']:,.0f})",
    ]
    return "\n".join(lines)


def build_email_body(products_wanted, df, national_news, international_news):
    lines = [
        f"Your Weekly Fuel & Energy Price Update — {datetime.now().strftime('%B %d, %Y')}",
        "=" * 60, ""
    ]

    codes = list(PRODUCTS.keys()) if products_wanted == ["ALL"] else products_wanted
    lines.append("PRICE SUMMARY")
    lines.append("-" * 60)
    for code in codes:
        if code in PRODUCTS:
            lines.append(build_price_summary(df, code))
            lines.append("")

    lines.append("TOP NATIONAL NEWS")
    lines.append("-" * 60)
    for article in national_news[:3]:
        lines.append(f"- {article['title']} ({article['source']})")
        lines.append(f"  {article['link']}")
    lines.append("")

    lines.append("TOP INTERNATIONAL NEWS")
    lines.append("-" * 60)
    for article in international_news[:3]:
        lines.append(f"- {article['title']} ({article['source']})")
        lines.append(f"  {article['link']}")
    lines.append("")
    lines.append("-" * 60)
    lines.append("You're receiving this because you subscribed on the Fuel & Energy "
                  "Price Tracker. Reply to this email to unsubscribe.")

    return "\n".join(lines)


def send_email(to_address, subject, body, from_address, app_password):
    msg = MIMEMultipart()
    msg["From"] = from_address
    msg["To"] = to_address
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
        server.login(from_address, app_password)
        server.sendmail(from_address, to_address, msg.as_string())


def main():
    from_address = os.environ.get("EMAIL_ADDRESS")
    app_password = os.environ.get("EMAIL_APP_PASSWORD")

    if not from_address or not app_password:
        raise SystemExit(
            "Missing EMAIL_ADDRESS or EMAIL_APP_PASSWORD environment variables. "
            "See the README for setup instructions."
        )

    if not os.path.isfile(SUBSCRIBERS_FILE):
        print(f"No {SUBSCRIBERS_FILE} found - nothing to send.")
        return

    subscribers = pd.read_csv(SUBSCRIBERS_FILE)
    if subscribers.empty:
        print("Subscriber list is empty - nothing to send.")
        return

    print("Generating price data...")
    df = generate_sample_data()

    print("Fetching news...")
    national_news = fetch_news(NATIONAL_FEEDS, keyword_filter=ENERGY_KEYWORDS, limit=5)
    international_news = fetch_news(INTERNATIONAL_FEEDS, keyword_filter=None, limit=5)

    sent_count = 0
    failed_count = 0

    for _, row in subscribers.iterrows():
        email = row["email"]
        products_wanted = str(row["products"]).split(",")

        try:
            body = build_email_body(products_wanted, df, national_news, international_news)
            subject = "Your Weekly Fuel & Energy Price Update"
            send_email(email, subject, body, from_address, app_password)
            print(f"  Sent to {email}")
            sent_count += 1
        except Exception as e:
            print(f"  FAILED to send to {email}: {e}")
            failed_count += 1

    print(f"\nDone. Sent: {sent_count}, Failed: {failed_count}")


if __name__ == "__main__":
    main()
