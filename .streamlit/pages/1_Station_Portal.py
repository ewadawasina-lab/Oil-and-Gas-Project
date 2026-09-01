"""
Filling Station Portal
================================================================
A separate Streamlit app where filling stations sign up, log in, and
submit their daily fuel prices along with a photo of their price board.

Submissions land in Supabase with status='pending' until approved via
the admin_review.py panel — they do NOT appear on the public dashboard
until then.

HOW TO RUN:
1. pip install -r requirements.txt
2. Create .streamlit/secrets.toml (see secrets_template.toml) with your
   real Supabase Project URL and Publishable (anon) key
3. streamlit run station_portal.py

REQUIRES (set up once in Supabase, before this will work):
- The stations & submissions tables (see supabase_schema.sql)
- A Storage bucket named "price-board-photos" set to PUBLIC
  (Supabase dashboard -> Storage -> New bucket -> name it exactly
  "price-board-photos" -> toggle "Public bucket" ON)
"""

import streamlit as st
from supabase import create_client, Client
from datetime import datetime, timezone
import uuid

st.set_page_config(page_title="Station Portal — Fuel Price Tracker", page_icon="⛽", layout="centered")

# -----------------------------------------------------------------------
# CONNECT TO SUPABASE
# -----------------------------------------------------------------------
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
except Exception:
    st.error(
        "Missing Supabase credentials. Create a .streamlit/secrets.toml file "
        "with SUPABASE_URL and SUPABASE_KEY — see secrets_template.toml."
    )
    st.stop()


@st.cache_resource
def get_supabase_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


supabase = get_supabase_client()

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

st.title("⛽ Filling Station Portal")
st.caption("Sign up, log in, and submit today's prices with a photo of your price board.")

if "user" not in st.session_state:
    st.session_state.user = None


# -----------------------------------------------------------------------
# LOGGED OUT: show Login / Sign Up
# -----------------------------------------------------------------------
if st.session_state.user is None:
    tab_login, tab_signup = st.tabs(["Log In", "Sign Up"])

    with tab_login:
        with st.form("login_form"):
            login_email = st.text_input("Email")
            login_password = st.text_input("Password", type="password")
            login_submit = st.form_submit_button("Log In")

            if login_submit:
                try:
                    result = supabase.auth.sign_in_with_password(
                        {"email": login_email, "password": login_password}
                    )
                    st.session_state.user = result.user
                    st.rerun()
                except Exception as e:
                    st.error(f"Login failed: {e}")

    with tab_signup:
        st.write("Create an account for your filling station.")
        with st.form("signup_form"):
            signup_email = st.text_input("Email", key="signup_email")
            signup_password = st.text_input(
                "Password (min 6 characters)", type="password", key="signup_password"
            )
            signup_submit = st.form_submit_button("Create Account")

            if signup_submit:
                if len(signup_password) < 6:
                    st.error("Password must be at least 6 characters.")
                else:
                    try:
                        supabase.auth.sign_up(
                            {"email": signup_email, "password": signup_password}
                        )
                        st.success(
                            "Account created! Check your email to confirm it, "
                            "then log in above."
                        )
                    except Exception as e:
                        st.error(f"Sign-up failed: {e}")

# -----------------------------------------------------------------------
# LOGGED IN
# -----------------------------------------------------------------------
else:
    user = st.session_state.user
    st.sidebar.success(f"Logged in as {user.email}")
    if st.sidebar.button("Log Out"):
        supabase.auth.sign_out()
        st.session_state.user = None
        st.rerun()

    # Check whether this user already has a station profile
    station_query = supabase.table("stations").select("*").eq("user_id", user.id).execute()

    # --- No profile yet: ask them to complete it first ---
    if not station_query.data:
        st.subheader("Complete Your Station Profile")
        st.write("Before submitting prices, tell us about your station.")

        with st.form("profile_form"):
            business_name = st.text_input("Business / Station Name")
            address = st.text_input("Full Address")
            state = st.selectbox("State", ALL_STATES)
            lga = st.text_input("LGA (optional)")
            phone = st.text_input("Phone Number (optional)")
            profile_submit = st.form_submit_button("Save Profile")

            if profile_submit:
                if not business_name or not address:
                    st.error("Business name and address are required.")
                else:
                    try:
                        supabase.table("stations").insert({
                            "user_id": user.id,
                            "business_name": business_name,
                            "address": address,
                            "state": state,
                            "lga": lga or None,
                            "phone": phone or None,
                        }).execute()
                        st.success("Profile saved!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not save profile: {e}")

    # --- Profile exists: show the submission form ---
    else:
        station = station_query.data[0]
        st.subheader(f"Welcome, {station['business_name']}")
        if station.get("verified"):
            st.caption("✅ Verified station")

        st.divider()
        st.subheader("📸 Submit Today's Prices")

        with st.form("submission_form", clear_on_submit=True):
            product = st.selectbox(
                "Product", options=list(PRODUCTS.keys()), format_func=lambda p: PRODUCTS[p]
            )
            price = st.number_input("Price (₦)", min_value=1.0, step=1.0)
            photo = st.file_uploader(
                "Upload a photo of your price board", type=["jpg", "jpeg", "png"]
            )
            submit_price = st.form_submit_button("Submit")

            if submit_price:
                if not photo:
                    st.error("Please upload a photo of your price board.")
                else:
                    # Prevent duplicate submissions for the same product today
                    today = datetime.now(timezone.utc).date().isoformat()
                    existing = (
                        supabase.table("submissions")
                        .select("id")
                        .eq("station_id", station["id"])
                        .eq("product", product)
                        .gte("submitted_at", today)
                        .execute()
                    )

                    if existing.data:
                        st.warning(
                            f"You've already submitted {PRODUCTS[product]} prices today. "
                            "Come back tomorrow!"
                        )
                    else:
                        try:
                            file_bytes = photo.read()
                            file_ext = photo.name.split(".")[-1]
                            file_path = (
                                f"{station['id']}/{product}_{uuid.uuid4().hex}.{file_ext}"
                            )

                            supabase.storage.from_("price-board-photos").upload(
                                file_path, file_bytes, {"content-type": photo.type}
                            )
                            photo_url = supabase.storage.from_(
                                "price-board-photos"
                            ).get_public_url(file_path)

                            supabase.table("submissions").insert({
                                "station_id": station["id"],
                                "product": product,
                                "price": price,
                                "photo_url": photo_url,
                            }).execute()

                            st.success(
                                f"Submitted! {PRODUCTS[product]} at ₦{price:,.0f} "
                                "is now pending review."
                            )
                        except Exception as e:
                            st.error(f"Submission failed: {e}")

        st.divider()
        st.subheader("Your Recent Submissions")

        recent = (
            supabase.table("submissions")
            .select("*")
            .eq("station_id", station["id"])
            .order("submitted_at", desc=True)
            .limit(10)
            .execute()
        )

        if recent.data:
            status_emoji = {"pending": "🕓", "approved": "✅", "rejected": "❌"}
            for sub in recent.data:
                emoji = status_emoji.get(sub["status"], "")
                st.write(
                    f"{emoji} {PRODUCTS.get(sub['product'], sub['product'])} — "
                    f"₦{sub['price']:,.0f} — {sub['submitted_at'][:10]} — "
                    f"{sub['status'].title()}"
                )
        else:
            st.info("No submissions yet — use the form above to add your first one.")
