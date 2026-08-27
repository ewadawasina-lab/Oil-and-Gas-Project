"""
Nigerian Fuel & Energy Price Tracker - Interactive Dashboard
================================================================
Step 4: Polished, professional layout - tabs, interactive Plotly charts,
a state-level bubble map, and metric deltas.

HOW TO RUN:
1. pip install -r requirements.txt
2. In your terminal, run:  streamlit run fuel_price_dashboard.py
3. It opens automatically in your browser at http://localhost:8501

HOW TO USE REAL DATA:
Replace the generate_sample_data() function with:
    df = pd.read_csv("your_real_data.csv", parse_dates=["date"])
Just make sure your columns are named: date, state, product, price_naira_per_litre
Product values should be one of: PMS, AGO, DPK, LPG, CNG

FOR THE COLOR THEME:
Place the accompanying .streamlit/config.toml file in a folder named
".streamlit" right next to this script (same folder). Streamlit picks it
up automatically - no code changes needed.
"""

import pandas as pd
import plotly.express as px
import streamlit as st
from sklearn.linear_model import LinearRegression
import numpy as np
from datetime import datetime
import feedparser
import re
import os
import csv
from supabase import create_client, Client

# -----------------------------------------------------------------------
# PAGE CONFIG
# -----------------------------------------------------------------------
st.set_page_config(
    page_title="Nigerian Fuel Price Tracker",
    page_icon="⛽",
    layout="wide"
)

st.title("⛽ Nigerian Fuel & Energy Price Tracker")
st.caption(
    f"Tracking fuel price trends across all 36 states + FCT · "
    f"By Emmanuel Wadawasina · Data shown as of {datetime.now().strftime('%B %Y')}"
)
st.divider()

# -----------------------------------------------------------------------
# REFERENCE DATA: states with approximate capital-city coordinates
# (used for the bubble map). Replace/extend if you want ward-level detail.
# -----------------------------------------------------------------------
STATE_COORDS = {
    "Abia": (5.5333, 7.4833), "Adamawa": (9.2000, 12.4833),
    "Akwa Ibom": (5.0333, 7.9333), "Anambra": (6.2107, 7.0740),
    "Bauchi": (10.3158, 9.8442), "Bayelsa": (4.9247, 6.2676),
    "Benue": (7.7322, 8.5391), "Borno": (11.8333, 13.1500),
    "Cross River": (4.9517, 8.3220), "Delta": (6.2000, 6.7333),
    "Ebonyi": (6.3249, 8.1137), "Edo": (6.3350, 5.6037),
    "Ekiti": (7.6167, 5.2167), "Enugu": (6.4413, 7.4988),
    "Gombe": (10.2833, 11.1667), "Imo": (5.4833, 7.0333),
    "Jigawa": (11.7564, 9.3392), "Kaduna": (10.5167, 7.4333),
    "Kano": (12.0000, 8.5167), "Katsina": (12.9908, 7.6018),
    "Kebbi": (12.4539, 4.1975), "Kogi": (7.8000, 6.7333),
    "Kwara": (8.5000, 4.5500), "Lagos": (6.6018, 3.3515),
    "Nasarawa": (8.4939, 8.5168), "Niger": (9.6139, 6.5569),
    "Ogun": (7.1608, 3.3489), "Ondo": (7.2500, 5.1950),
    "Osun": (7.7719, 4.5567), "Oyo": (7.3775, 3.9470),
    "Plateau": (9.8965, 8.8583), "Rivers": (4.8156, 7.0498),
    "Sokoto": (13.0059, 5.2476), "Taraba": (8.8833, 11.3667),
    "Yobe": (11.7469, 11.9608), "Zamfara": (12.1704, 6.6641),
    "FCT Abuja": (9.0765, 7.3986),
}
ALL_STATES = list(STATE_COORDS.keys())

PRODUCTS = {
    "PMS": "Petrol (PMS)",
    "AGO": "Diesel (AGO)",
    "DPK": "Kerosene (DPK)",
    "LPG": "Cooking Gas (LPG, per kg)",
    "CNG": "Compressed Natural Gas (CNG, per kg)",
}
PER_KG_PRODUCTS = {"LPG", "CNG"}

BASE_PRICE_RANGE = {
    "PMS": (950, 1350), "AGO": (1400, 1900), "DPK": (1100, 1600),
    "LPG": (1400, 1900), "CNG": (230, 350),
}

MONTHS = pd.date_range("2026-01-01", periods=6, freq="MS")

# -----------------------------------------------------------------------
# REGULATORY & COMPLIANCE: key oil & gas laws, briefly summarized.
# Sources checked via web search on the date noted; laws and interpretations
# can change, so treat this as a starting reference, not legal advice.
# -----------------------------------------------------------------------
REGULATORY_LAWS = [
    {
        "name": "Petroleum Industry Act (PIA), 2021",
        "year": "2021",
        "summary": (
            "Nigeria's most significant oil & gas law in two decades, signed August 2021. "
            "It overhauled how the sector is governed, taxed, and regulated. It split "
            "regulation into two independent bodies (NUPRC for upstream, NMDPRA for "
            "midstream/downstream), converted NNPC into a commercial company (NNPC Ltd), "
            "and introduced a Host Communities Development framework requiring operators "
            "to fund trusts for communities near their operations."
        ),
        "authority": "NUPRC & NMDPRA",
        "download_url": "https://ngfcp.nuprc.gov.ng/wp-content/uploads/2022/09/Petroleum-Industry-Act-2021-pdf-searchable.pdf",
        "download_label": "Download full Act (PDF, via NUPRC)"
    },
    {
        "name": "Nigeria Tax Act (NTA), 2025 — Hydrocarbon Tax provisions",
        "year": "2025 (effective Jan 2026)",
        "summary": (
            "Part of Nigeria's broader 2025 tax reform, which consolidated over 50 tax "
            "laws. For oil & gas, it replaced the decades-old Petroleum Profits Tax Act "
            "with a new Hydrocarbon Tax applying specifically to upstream crude oil, "
            "condensates, and natural gas liquids. This sits on top of the standard 30% "
            "Companies Income Tax, pushing the effective tax rate for upstream operators "
            "as high as 60%. It also expanded VAT exemptions on oil & gas exports and "
            "suspended VAT on CNG, LNG, and LPG pending a ministerial order."
        ),
        "authority": "Nigeria Revenue Service (NRS)",
        "download_url": "https://www.nrs.gov.ng/uploads/NIGERIA_TAX_ACT_2025_ef6bb812a5.pdf",
        "download_label": "Download full Act (PDF, via NRS)"
    },
    {
        "name": "NMDPRA (Nigerian Midstream & Downstream Petroleum Regulatory Authority)",
        "year": "Established 2021",
        "summary": (
            "Created under the PIA and became operational in August 2021, merging three "
            "former agencies (PPPRA, PEF Management Board, and DPR's midstream/downstream "
            "divisions). It regulates transportation, storage, refining, distribution, "
            "and marketing of petroleum products, and holds responsibility for the "
            "framework behind pump price determination — this is the body most directly "
            "tied to the fuel prices this dashboard tracks."
        ),
        "authority": "Self (NMDPRA)",
        "download_url": "https://ngfcp.nuprc.gov.ng/wp-content/uploads/2022/09/Petroleum-Industry-Act-2021-pdf-searchable.pdf",
        "download_label": "Download PIA 2021 (PDF) — the law that established NMDPRA"
    },
    {
        "name": "NNPC Limited (commercial entity under the PIA)",
        "year": "Converted 2021",
        "summary": (
            "The PIA converted the former state oil corporation, NNPC, into NNPC Limited "
            "— a commercial, profit-driven company incorporated like any private business. "
            "It no longer regulates the industry (that role moved to NUPRC and NMDPRA); "
            "its job now is purely commercial — producing, refining, and trading — while "
            "paying the same taxes and royalties as any other operator."
        ),
        "authority": "NUPRC & NMDPRA (as regulators of NNPC Ltd's operations)",
        "download_url": "https://ngfcp.nuprc.gov.ng/wp-content/uploads/2022/09/Petroleum-Industry-Act-2021-pdf-searchable.pdf",
        "download_label": "Download PIA 2021 (PDF) — the law that established NNPC Ltd"
    },
    {
        "name": "Deep Offshore & Inland Basin PSC Act (as amended 2019)",
        "year": "1999, amended 2019",
        "summary": (
            "Governs Production Sharing Contracts (PSCs) between government/NNPC and "
            "international oil companies operating in deep offshore areas (beyond 200m "
            "water depth) and inland basins. The 2019 amendment replaced the old fixed "
            "royalty system with a combined production- and price-based royalty regime, "
            "with rates rising as oil prices climb above $20/barrel — closing a gap that "
            "had reportedly left Nigeria under-collecting revenue for years."
        ),
        "authority": "NUPRC",
        "download_url": "https://www.nuprc.gov.ng/upload/nuprc_laws/Compendium_of_Oil_and_Gas_Laws_Regulations__Pre_PIA__60cfabaae08d844cc8ca469b.pdf",
        "download_label": "Download full text (PDF, via NUPRC compendium)"
    },
    {
        "name": "Gas Flaring, Venting & Methane Emissions Regulations, 2023",
        "year": "2023",
        "summary": (
            "Issued by NUPRC under the PIA to curb routine gas flaring — the practice of "
            "burning off natural gas during oil production instead of capturing it. "
            "Operators must submit flare-reduction plans and face penalties for "
            "non-compliance, supporting Nigeria's broader goal (via the Nigerian Gas "
            "Flare Commercialization Programme) of ending routine flaring and instead "
            "capturing that gas for productive use."
        ),
        "authority": "NUPRC",
        "download_url": "https://www.nuprc.gov.ng/gazetted-regulations/",
        "download_label": "Download regulation (via NUPRC gazetted regulations page)"
    },
    {
        "name": "Oil and Gas Export Free Zone Act, 1996 (OGFZA)",
        "year": "1996",
        "summary": (
            "Established the Oil and Gas Export Free Zones Authority (OGFZA), which "
            "licenses, regulates, and manages Nigeria's oil and gas free trade zones — "
            "most notably the Onne Oil and Gas Free Zone in Rivers State. Companies "
            "operating within these zones (oilfield services, fabrication, equipment "
            "manufacturing, logistics) get significant incentives, including exemption "
            "from federal, state, and local taxes, levies, and VAT. This law is about "
            "investment and trade incentives for service companies rather than fuel "
            "pricing directly, but it's a foundational part of the sector's structure."
        ),
        "authority": "OGFZA",
        "download_url": "https://www.ogfza.gov.ng/wp-content/uploads/2019/11/OGFZA-ACT-1996.pdf",
        "download_label": "Download full Act (PDF, via OGFZA)"
    },
]

ABOUT_TEXT = """
This dashboard tracks fuel and energy prices across Nigeria's 36 states and the FCT,
covering five products: Petrol (PMS), Diesel (AGO), Kerosene (DPK), Cooking Gas (LPG),
and Compressed Natural Gas (CNG).

**What it does:**
- Visualizes price trends over time, by state and product
- Compares prices across states on a map and in charts
- Projects a simple 3-month forward trend using linear regression
- Pulls live oil & gas news from national and international sources
- Summarizes key regulatory and compliance laws shaping the industry

**Data source:** Currently running on generated placeholder data for demonstration.
The intended real-world source is the National Bureau of Statistics (NBS) Petrol/Diesel
Price Watch reports, published monthly.

**Limitations:** The 3-month forecast is a simple linear trend, not a market model —
treat it as a directional signal, not a prediction. Regulatory summaries are for general
awareness only and are not legal advice; consult a qualified professional for anything
compliance-critical.

**Built by:** Emmanuel Wadawasina, as a personal project applying a Mathematics
background to real-world energy sector data.
"""

# -----------------------------------------------------------------------
# NEWS: RSS feed sources
# National feeds are general-news outlets, filtered by energy keywords below.
# International feeds are dedicated energy/oil & gas publications, so no
# keyword filter is needed there. Add or swap URLs here if a feed goes down.
# -----------------------------------------------------------------------
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


def _strip_html(raw_text):
    """Removes HTML tags from RSS summary text so it renders as plain text."""
    return re.sub("<[^>]+>", "", raw_text or "").strip()


@st.cache_data(ttl=1800)  # refresh every 30 minutes
def fetch_news(feed_urls, keyword_filter=None, limit=5):
    """Pulls and merges articles from a list of RSS feeds.
    Skips any feed that fails to load instead of crashing the app.
    If keyword_filter is given, only articles matching at least one
    keyword (in title or summary) are kept.
    """
    articles = []
    for url in feed_urls:
        try:
            parsed = feedparser.parse(url)
            source_name = parsed.feed.get("title", url)
            for entry in parsed.entries:
                title = entry.get("title", "").strip()
                raw_summary = entry.get("summary", entry.get("description", ""))
                summary = _strip_html(raw_summary)
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
                    "title": title,
                    "summary": (summary[:220] + "…") if len(summary) > 220 else summary,
