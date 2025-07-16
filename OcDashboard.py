
import streamlit as st
import pandas as pd
import requests
from streamlit_autorefresh import st_autorefresh
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib

from datetime import datetime, time
import pytz

def is_market_open():
    india = pytz.timezone("Asia/Kolkata")
    now = datetime.now(india).time()
    return time(9, 15) <= now <= time(15, 30)


# ========== CONFIG ==========
st.set_page_config("📈 Option Chain Dashboard", layout="wide")
st_autorefresh(interval=900000, limit=None, key="refresh")
st.title("📘 Option Chain Dashboard (NSE Live)")

# ========== EMAIL ALERT FUNCTION ==========
def send_email_alert(subject, message, to_email="mdrinfotech79@gmail.com"):
    from_email = "rajasinha2000@gmail.com"
    from_password = "hefy otrq yfji ictv"
    try:
        msg = MIMEMultipart()
        msg['From'] = from_email
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(message, 'plain'))
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(from_email, from_password)
        server.send_message(msg)
        server.quit()
    except Exception as e:
        st.warning(f"📧 Email failed: {e}")

# ========== FETCH OPTION CHAIN ==========
def get_option_chain(symbol):
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Referer": "https://www.nseindia.com/option-chain"
    }
    session = requests.Session()
    session.headers.update(headers)
    session.get("https://www.nseindia.com", timeout=5)
    url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    response = session.get(url, timeout=10)
    data = response.json()
    records = data['records']['data']
    underlying = float(data['records']['underlyingValue'])

    rows = []
    for item in records:
        strike = item['strikePrice']
        ce = item.get('CE', {})
        pe = item.get('PE', {})
        rows.append({
            "Strike": strike,
            "CE_OI": ce.get("openInterest", 0),
            "PE_OI": pe.get("openInterest", 0),
            "Underlying": underlying
        })

    df = pd.DataFrame(rows)
    df = df[df["Strike"] % 50 == 0]
    df = df.drop_duplicates(subset="Strike", keep="last")
    df = df.sort_values("Strike").reset_index(drop=True)
    return df

# ========== ANALYSIS FUNCTION ==========
def analyze_option_chain(df):
    cmp = df["Underlying"].iloc[0]
    atm_strike = round(cmp / 50) * 50
    df["PCR"] = (df["PE_OI"] / df["CE_OI"]).replace([float("inf"), -float("inf")], 0).fillna(0).round(2)

    df["Signal"] = df["PCR"].apply(lambda p: "🟢 Bullish" if p > 1.2 else "🔴 Bearish" if p < 0.9 else "🟠 Neutral")
    df["Breakout"] = df.apply(
        lambda row: "🔥 High" if abs(row["CE_OI"] - row["PE_OI"]) / (row["CE_OI"] + row["PE_OI"] + 1) < 0.15
        else "🌥️ Medium" if abs(row["CE_OI"] - row["PE_OI"]) / (row["CE_OI"] + row["PE_OI"] + 1) < 0.3
        else "❄️ Low", axis=1
    )
    df["Trend"] = df["Signal"].map({
        "🟢 Bullish": "🔼 Uptrend",
        "🔴 Bearish": "🔽 Downtrend",
        "🟠 Neutral": "⏸ Sideways"
    })

    def classify_oi_shift(row):
        if row["PE_OI"] > row["CE_OI"] and row["PE_OI"] > 100:
            return "🔼 Support Up"
        elif row["CE_OI"] > row["PE_OI"] and row["CE_OI"] > 100:
            return "🔽 Resistance Down"
        else:
            return "↔ No Shift"

    df["OI_Shift"] = df.apply(classify_oi_shift, axis=1)

    def trade_suggestion(row):
        if row["Trend"] == "🔼 Uptrend" and row["Breakout"] == "🔥 High" and row["OI_Shift"] == "🔼 Support Up":
            return "✅ Buy CE"
        elif row["Trend"] == "🔽 Downtrend" and row["Breakout"] == "🔥 High" and row["OI_Shift"] == "🔽 Resistance Down":
            return "✅ Buy PE"
        elif row["Trend"] == "⏸ Sideways":
            return "❌ Avoid / Wait"
        else:
            return "❌ Avoid / Wait"

    df["Trade"] = df.apply(trade_suggestion, axis=1)
    df["✅ Final Call"] = df["Trade"].apply(lambda x: "✅ Yes" if "Buy" in x else "❌ No")

    df_near = df[(df["Strike"] >= cmp - 300) & (df["Strike"] <= cmp + 300)].copy()

    def highlight_atm(row):
        color = 'background-color: blue' if abs(row["Strike"] - atm_strike) < 1e-2 else ''
        return [color] * len(row)

    st.subheader(f"📌 CMP: {cmp}")
    st.dataframe(
        df_near[["Strike", "CE_OI", "PE_OI", "PCR", "Signal", "Breakout", "Trend", "OI_Shift", "Trade", "✅ Final Call"]]
        .style.apply(highlight_atm, axis=1), use_container_width=True
    )

    max_ce = df_near.loc[df_near["CE_OI"].idxmax(), "Strike"]
    max_pe = df_near.loc[df_near["PE_OI"].idxmax(), "Strike"]
    total_pcr = round(df_near["PE_OI"].sum() / df_near["CE_OI"].sum(), 2)
    sentiment = "🟢 Bullish" if total_pcr > 1.2 else "🔴 Bearish" if total_pcr < 0.8 else "🟠 Neutral"

    st.markdown(f"""
    ### 📋 Summary:
    - 🔼 Max CE OI (Resistance): `{max_ce}`
    - 🔽 Max PE OI (Support): `{max_pe}`
    - ⚖️ Total PCR: `{total_pcr}` → {sentiment}
    - 📍 CMP: `{cmp}`
    """)

    best_trade = df_near[df_near["✅ Final Call"] == "✅ Yes"].copy()
    if not best_trade.empty:
        best_trade["Score"] = best_trade["Breakout"].map({"🔥 High": 3, "🌥️ Medium": 2, "❄️ Low": 1})
        best_trade = best_trade.sort_values(["Score", "PCR"], ascending=False).head(1)
        trade = best_trade.iloc[0]
        strike = trade["Strike"]
        side = "CE" if "CE" in trade["Trade"] else "PE"
        entry = strike
        stop = strike - 40 if side == "CE" else strike + 40
        target = strike + 80 if side == "CE" else strike - 80

        if (
            (side == "CE" and trade["Trend"] == "🔼 Uptrend" and trade["Breakout"] == "🔥 High" and trade["OI_Shift"] == "🔼 Support Up") or
            (side == "PE" and trade["Trend"] == "🔽 Downtrend" and trade["Breakout"] == "🔥 High" and trade["OI_Shift"] == "🔽 Resistance Down")
        ):
            st.success(f"""
            ### 🎯 Best Trade Now:
            - 📈 **{side} BUY @ {entry}**
            - 🎯 Target: `{target}`
            - 🛑 Stoploss: `{stop}`
            - 🔍 Trend: `{trade['Trend']}` | Breakout: `{trade['Breakout']}` | OI: `{trade['OI_Shift']}`
            """)
            if is_market_open():
                send_email_alert(
                    f"Option Chain Alert: {side} BUY {strike}",
                    f"Trade Signal: {side} Buy @ {entry}\nTarget: {target}\nStop: {stop}\nCMP: {cmp}"
                )
            else:
                st.info("⏰ Market closed. Email alert skipped.")
        else:
            st.info("⚠️ Trade is valid but not strong enough to send an email.")
    else:
        st.info("⚠️ No strong trade opportunity found near CMP.")

# ========== MAIN APP ==========
symbol = st.selectbox("Choose Index", ["NIFTY", "BANKNIFTY"])
try:
    df = get_option_chain(symbol)
    analyze_option_chain(df)
except Exception as e:
    st.error(f"❌ Error: {e}")
