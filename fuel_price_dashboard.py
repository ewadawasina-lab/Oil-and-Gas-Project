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
                    "link": link,
                    "date": pub_date,
                    "source": source_name,
                })
        except Exception:
            continue  # one broken feed shouldn't take down the whole section

    articles.sort(key=lambda a: a["date"], reverse=True)
    return articles[:limit]


# -----------------------------------------------------------------------
# FEEDBACK & NEWSLETTER: local file storage helpers
# These write to plain CSV files next to the script. This works reliably
# when running locally. On Streamlit Community Cloud, the filesystem is
# NOT permanent — files can be wiped on redeploy/restart, so treat this as
# fine for getting started, but consider a real database (e.g. Google
# Sheets via API, or a hosted DB) before relying on it for real signups.
# -----------------------------------------------------------------------
FEEDBACK_FILE = "feedback.csv"
SUBSCRIBERS_FILE = "newsletter_subscribers.csv"


def save_feedback(name, email, message, rating):
    """Appends one feedback entry to feedback.csv, creating the file with
    headers on first use."""
    file_exists = os.path.isfile(FEEDBACK_FILE)
    with open(FEEDBACK_FILE, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "name", "email", "rating", "message"])
        writer.writerow([datetime.now().isoformat(), name, email, rating, message])


def save_subscriber(email, products_wanted):
    """Appends one newsletter signup to newsletter_subscribers.csv.
    products_wanted is a list of product codes, or ["ALL"] for everything.
    Skips (and reports) duplicate emails so people don't get signed up twice.
    """
    products_str = ",".join(products_wanted)
    file_exists = os.path.isfile(SUBSCRIBERS_FILE)

    if file_exists:
        existing = pd.read_csv(SUBSCRIBERS_FILE)
        if email.lower() in existing["email"].str.lower().values:
            return False  # already subscribed

    with open(SUBSCRIBERS_FILE, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["email", "products", "subscribed_date"])
        writer.writerow([email, products_str, datetime.now().date().isoformat()])
    return True


# -----------------------------------------------------------------------
# LOAD DATA (swap this function out for a real CSV once you have one)
# -----------------------------------------------------------------------
@st.cache_data
def generate_sample_data():
    """Generates placeholder data so the dashboard is fully usable before
    real data is wired in. Replace with:
        return pd.read_csv("your_real_data.csv", parse_dates=["date"])
    """
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

with st.spinner("Loading fuel price data…"):
    df = generate_sample_data()

# -----------------------------------------------------------------------
# SIDEBAR FILTERS
# -----------------------------------------------------------------------
st.sidebar.header("🔎 Filters")

product_choice = st.sidebar.selectbox(
    "Product", options=list(PRODUCTS.keys()), format_func=lambda p: PRODUCTS[p]
)

select_all = st.sidebar.checkbox("Select all states", value=False)
default_states = ALL_STATES if select_all else ["Lagos", "FCT Abuja", "Kano", "Rivers"]

states = st.sidebar.multiselect("State(s)", options=ALL_STATES, default=default_states)

if not states:
    st.warning("Select at least one state from the sidebar to see data.")
    st.stop()

filtered = df[(df['product'] == product_choice) & (df['state'].isin(states))].copy()
unit_label = "₦/kg" if product_choice in PER_KG_PRODUCTS else "₦/litre"

if filtered.empty:
    st.error(
        "No data matches your current filters. Try selecting a different "
        "product or adding more states."
    )
    st.stop()

st.sidebar.divider()
st.sidebar.download_button(
    label="⬇️ Download filtered data (CSV)",
    data=filtered.to_csv(index=False).encode("utf-8"),
    file_name=f"{product_choice}_prices_filtered.csv",
    mime="text/csv",
    use_container_width=True,
)

st.sidebar.divider()

with st.sidebar.expander("📧 Weekly Newsletter"):
    st.write(
        "Get a weekly email summarizing price trends and the top energy news — "
        "pick exactly what you want to hear about."
    )
    with st.form("newsletter_form", clear_on_submit=True):
        sub_email = st.text_input("Email address")
        want_all = st.checkbox("Send me everything (all products + full news roundup)")
        sub_products = st.multiselect(
            "Or pick specific products to track",
            options=list(PRODUCTS.keys()),
            format_func=lambda p: PRODUCTS[p],
            disabled=want_all
        )
        submitted = st.form_submit_button("Subscribe")

        if submitted:
            if not sub_email or "@" not in sub_email:
                st.error("Please enter a valid email address.")
            elif not want_all and not sub_products:
                st.error("Pick at least one product, or check 'Send me everything.'")
            else:
                chosen = ["ALL"] if want_all else sub_products
                added = save_subscriber(sub_email, chosen)
                if added:
                    st.success(f"Subscribed! You'll get a weekly summary at {sub_email}.")
                else:
                    st.info("That email is already subscribed.")
    st.caption(
        "Emails go out weekly. You can unsubscribe any time by replying to any "
        "newsletter email."
    )

with st.sidebar.expander("💬 Feedback"):
    st.write("Tell me what you think, or what you'd like to see improved.")
    with st.form("feedback_form", clear_on_submit=True):
        fb_name = st.text_input("Name (optional)")
        fb_email = st.text_input("Email (optional, if you'd like a reply)")
        fb_rating = st.select_slider(
            "How would you rate this dashboard?",
            options=["1 - Poor", "2", "3", "4", "5 - Excellent"],
            value="3"
        )
        fb_message = st.text_area("Your feedback", height=120)
        fb_submitted = st.form_submit_button("Send Feedback")

        if fb_submitted:
            if not fb_message.strip():
                st.error("Please write a message before submitting.")
            else:
                save_feedback(fb_name, fb_email, fb_message, fb_rating)
                st.success("Thanks for the feedback! It's been recorded.")

st.sidebar.divider()
st.sidebar.caption(
    "Data source: placeholder/generated. Swap in real NBS/NMDPRA data "
    "by editing generate_sample_data()."
)

# -----------------------------------------------------------------------
# KEY METRICS ROW (with deltas for a "live" feel)
# -----------------------------------------------------------------------
avg_by_state = filtered.groupby('state')['price_naira_per_litre'].mean().sort_values(ascending=False)
monthly_avg = filtered.groupby('date')['price_naira_per_litre'].mean().sort_index()

latest_price = monthly_avg.iloc[-1]
prev_price = monthly_avg.iloc[-2] if len(monthly_avg) > 1 else latest_price
mom_change_pct = ((latest_price - prev_price) / prev_price * 100) if prev_price else 0

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("📈 Most expensive", avg_by_state.idxmax(), f"₦{avg_by_state.max():.0f}")
with col2:
    st.metric("📉 Cheapest", avg_by_state.idxmin(), f"₦{avg_by_state.min():.0f}")
with col3:
    st.metric(
        f"⛽ Avg. {product_choice} price",
        f"₦{latest_price:.0f}",
        f"{mom_change_pct:+.1f}% vs last month",
        delta_color="inverse"  # rising fuel prices are "bad" news, so red for up
    )
with col4:
    st.metric("🗓️ Latest data", monthly_avg.index.max().strftime("%B %Y"))

st.divider()

# -----------------------------------------------------------------------
# TABS
# -----------------------------------------------------------------------
tab_trend, tab_map, tab_compare, tab_change, tab_forecast, tab_news, tab_regulatory, \
tab_about = st.tabs(
    ["📈 Price Trends", "🗺️ State Map", "📊 State Comparison", "🔁 Monthly Change",
     "🔮 Forecast", "📰 News", "⚖️ Regulatory & Compliance", "ℹ️ About"]
)

# --- TAB 1: Price trend line chart ---
with tab_trend:
    st.subheader(f"{PRODUCTS[product_choice]} Price Trend Over Time")
    fig_trend = px.line(
        filtered, x="date", y="price_naira_per_litre", color="state",
        markers=True, labels={"price_naira_per_litre": f"Price ({unit_label})", "date": "Month"}
    )
    fig_trend.update_layout(hovermode="x unified", legend_title_text="State")
    st.plotly_chart(fig_trend, use_container_width=True)

# --- TAB 2: Bubble map ---
with tab_map:
    st.subheader(f"{PRODUCTS[product_choice]} Price by State — Latest Month")
    latest_month = filtered['date'].max()
    map_data = filtered[filtered['date'] == latest_month].copy()
    map_data['lat'] = map_data['state'].map(lambda s: STATE_COORDS[s][0])
    map_data['lon'] = map_data['state'].map(lambda s: STATE_COORDS[s][1])

    fig_map = px.scatter_mapbox(
        map_data, lat="lat", lon="lon", size="price_naira_per_litre",
        color="price_naira_per_litre", hover_name="state",
        hover_data={"price_naira_per_litre": ":.0f", "lat": False, "lon": False},
        color_continuous_scale="YlOrRd", size_max=35, zoom=4.6,
        center={"lat": 9.0, "lon": 8.0},
        labels={"price_naira_per_litre": f"Price ({unit_label})"}
    )
    fig_map.update_layout(
        mapbox_style="open-street-map",
        margin={"r": 0, "t": 0, "l": 0, "b": 0},
        height=550
    )
    st.plotly_chart(fig_map, use_container_width=True)
    st.caption("Bubble size and color both reflect price — bigger/redder means more expensive.")

# --- TAB 3: State comparison bar chart ---
with tab_compare:
    st.subheader(f"Average {PRODUCTS[product_choice]} Price by State")
    bar_data = avg_by_state.sort_values().reset_index()
    bar_data.columns = ["state", "price"]
    fig_bar = px.bar(
        bar_data, x="price", y="state", orientation="h",
        color="price", color_continuous_scale="Blues",
        labels={"price": f"Average Price ({unit_label})", "state": ""}
    )
    fig_bar.update_layout(height=max(400, len(states) * 30), coloraxis_showscale=False)
    st.plotly_chart(fig_bar, use_container_width=True)

# --- TAB 4: Month-over-month % change ---
with tab_change:
    st.subheader("Month-over-Month % Change")
    filtered_copy = filtered.copy()
    filtered_copy['month'] = filtered_copy['date'].dt.to_period('M')
    pivot = filtered_copy.pivot_table(index='month', columns='state', values='price_naira_per_litre')
    pct_change = (pivot.pct_change() * 100).round(2)
    st.dataframe(
        pct_change.style.format("{:+.2f}%", na_rep="—").background_gradient(cmap="RdYlGn_r", axis=None),
        use_container_width=True
    )

# --- TAB 5: Simple forecast ---
with tab_forecast:
    st.subheader("Simple 3-Month Forecast")
    st.caption("Basic linear trend projection — not a substitute for real market analysis, just a starting signal.")

    forecast_state = st.selectbox("Pick a state to forecast", options=states)
    state_data = filtered[filtered['state'] == forecast_state].copy().sort_values('date')
    state_data['month_index'] = range(len(state_data))

    X = state_data[['month_index']]
    y = state_data['price_naira_per_litre']
    model = LinearRegression().fit(X, y)

    future_idx = np.array(range(len(state_data), len(state_data) + 3)).reshape(-1, 1)
    future_preds = model.predict(future_idx)

    last_date = state_data['date'].max()
    future_dates = pd.date_range(last_date, periods=4, freq='MS')[1:]

    history = state_data[['date', 'price_naira_per_litre']].rename(
        columns={'price_naira_per_litre': 'price'})
    history['type'] = 'Actual'
    forecast_part = pd.DataFrame({
        'date': future_dates, 'price': future_preds.round(0), 'type': 'Forecast'
    })
    combined = pd.concat([history, forecast_part], ignore_index=True)

    fig_forecast = px.line(
        combined, x='date', y='price', color='type', markers=True,
        color_discrete_map={'Actual': '#2E86AB', 'Forecast': '#F2A900'},
        labels={'price': f'Price ({unit_label})', 'date': 'Month'}
    )
    st.plotly_chart(fig_forecast, use_container_width=True)

    forecast_df = pd.DataFrame({
        "Month": future_dates.strftime("%B %Y"),
        f"Predicted Price ({unit_label})": future_preds.round(0)
    })
    st.table(forecast_df)

# --- TAB 6: Oil & Gas / Energy News ---
with tab_news:
    st.subheader("📰 Oil & Gas / Energy News")
    st.caption("Pulled live from public news sources · refreshes every 30 minutes")

    news_national_tab, news_intl_tab = st.tabs(["🇳🇬 National", "🌍 International"])

    def render_articles(articles, empty_message):
        if not articles:
            st.info(empty_message)
            return
        for article in articles:
            st.markdown(f"**{article['title']}**")
            date_str = article["date"].strftime("%d %b %Y") if article["date"] != datetime.min else ""
            meta_line = " · ".join(part for part in [article["source"], date_str] if part)
            st.caption(meta_line)
            if article["summary"]:
                st.write(article["summary"])
            st.markdown(f"[Continue reading →]({article['link']})")
            st.divider()

    with news_national_tab:
        with st.spinner("Fetching national energy news…"):
            national_articles = fetch_news(NATIONAL_FEEDS, keyword_filter=ENERGY_KEYWORDS, limit=5)
        render_articles(
            national_articles,
            "No national energy news could be loaded right now — try refreshing in a bit."
        )

    with news_intl_tab:
        with st.spinner("Fetching international energy news…"):
            international_articles = fetch_news(INTERNATIONAL_FEEDS, keyword_filter=None, limit=5)
        render_articles(
            international_articles,
            "No international energy news could be loaded right now — try refreshing in a bit."
        )

# --- TAB 7: Regulatory & Compliance ---
with tab_regulatory:
    st.subheader("⚖️ Regulatory & Compliance Overview")
    st.caption(
        "Key laws shaping Nigeria's oil & gas sector, briefly summarized. "
        "Not legal advice — consult a qualified professional for compliance decisions. "
        "Download links point to official government sources where available; if a "
        "link is broken, the source agency's website is the next best place to check."
    )
    for law in REGULATORY_LAWS:
        with st.expander(f"**{law['name']}** · {law['year']}"):
            st.write(law["summary"])
            st.caption(f"Administered by: {law['authority']}")
            if law.get("download_url"):
                st.markdown(f"[📄 {law['download_label']}]({law['download_url']})")

# --- TAB 8: About ---
with tab_about:
    st.subheader("ℹ️ About This Dashboard")
    st.markdown(ABOUT_TEXT)

# -----------------------------------------------------------------------
# FOOTER
# -----------------------------------------------------------------------
st.divider()
st.caption(
    "Built by Emmanuel Wadawasina · Data: NBS Petrol/Diesel Price Watch "
    "Not for commercial or financial decision-making at the moment."
)

# -----------------------------------------------------------------------
# NEXT STEPS (comments only — not shown in the app):
# 1. Replace generate_sample_data() with a real downloaded NBS/NMDPRA dataset
# 2. Deploy for free on Streamlit Community Cloud (share.streamlit.io)
# 3. Add a correlation check against Brent crude oil prices in Naira
# -----------------------------------------------------------------------
