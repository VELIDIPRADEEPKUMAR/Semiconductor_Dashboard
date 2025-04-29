import sqlite3
import pandas as pd
import yfinance as yf
import requests
import time
from datetime import datetime, timedelta
import streamlit as st
from textblob import TextBlob
import matplotlib.pyplot as plt
import seaborn as sns
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# Set wide layout and custom page config
st.set_page_config(layout="wide", page_title="Semiconductor Dashboard", page_icon="📊")
st.markdown("<style> .block-container { padding-bottom: 100px; } </style>", unsafe_allow_html=True)

# Constants
db_path = 'semiconductor_data.db'
API_KEY = 'd025kahr01qt2u325g1gd025kahr01qt2u325g20'
BASE_NEWS_URL = 'https://finnhub.io/api/v1/company-news'
PROFILE_URL = 'https://finnhub.io/api/v1/stock/profile2'
METRIC_URL = 'https://finnhub.io/api/v1/stock/metric?metric=all'

# Updated footer CSS
CSS = """
<style>
body {
    font-family: 'Arial', sans-serif;
    background-color: #f9fafb;
}
h1, h2, h3 {
    color: #003087;
}
.ticker-footer {
    display: flex;
    flex-wrap: nowrap;
    overflow-x: auto;
    padding: 10px 20px;
    background: #ffffff;
    border-top: 1px solid #e5e7eb;
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    z-index: 100;
    height: 60px;
    align-items: center;
}
.ticker-item {
    flex: 0 0 auto;
    margin-right: 6px;
    background: #e6f0ff;
    border-radius: 10px;
    padding: 4px 8px;
    font-size: 11px;
    font-weight: 500;
    color: #003087;
    cursor: pointer;
    transition: background 0.2s, transform 0.2s;
    position: relative;
    max-width: 60px;
    text-align: center;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.ticker-item:hover {
    background: #b3d4ff;
    transform: scale(1.05);
}
.ticker-item.new {
    background: #d1fae5;
}
.ticker-item.new:hover {
    background: #a7f3d0;
}
.ticker-tooltip {
    visibility: hidden;
    background: #1f2937;
    color: #ffffff;
    font-size: 9px;
    padding: 3px 6px;
    border-radius: 4px;
    position: absolute;
    bottom: 20px;
    left: 50%;
    transform: translateX(-50%);
    white-space: nowrap;
    z-index: 10;
    transition: visibility 0.2s;
}
.ticker-item:hover .ticker-tooltip {
    visibility: visible;
}
.ticker-footer::-webkit-scrollbar {
    height: 6px;
}
.ticker-footer::-webkit-scrollbar-thumb {
    background: #d1d5db;
    border-radius: 4px;
}
.ticker-footer::-webkit-scrollbar-thumb:hover {
    background: #9ca3af;
}
.stButton>button {
    background-color: #003087;
    color: white;
    border-radius: 6px;
    padding: 8px 16px;
}
.stButton>button:hover {
    background-color: #0044cc;
}
.stTabs [data-baseweb="tab"] {
    font-size: 16px;
    padding: 10px 20px;
    color: #003087;
}
.stTabs [aria-selected="true"] {
    background-color: #f1f5f9;
    border-bottom: 2px solid #003087;
}
</style>
"""

# Database initialization
def init_db():
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS historical (Date TEXT, Ticker TEXT, Open REAL, High REAL, Low REAL, Close REAL, Volume INTEGER, PRIMARY KEY(Date,Ticker))''')
    c.execute('''CREATE TABLE IF NOT EXISTS financials (Ticker TEXT PRIMARY KEY, Name TEXT, Sector TEXT, PE_Ratio REAL, EPS REAL, Market_Cap REAL, Dividend_Yield REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS news (Ticker TEXT, Date TEXT, Headline TEXT, URL TEXT, Sentiment REAL, PRIMARY KEY(Ticker,Date,Headline))''')
    conn.commit()
    conn.close()

# Fetch historical data
def fetch_historical(tickers):
    conn = sqlite3.connect(db_path)
    for t in tickers:
        with st.spinner(f"Fetching historical data for {t}..."):
            try:
                df = yf.download(t, start=datetime.now()-timedelta(days=730), end=datetime.now(), progress=False)
                if df.empty:
                    st.warning(f"No historical data for '{t}'. Please check the ticker symbol.")
                    continue
            except Exception as e:
                st.warning(f"Error fetching '{t}': {e}")
                continue
            df = df.reset_index()
            df['Ticker'] = t
            df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%m-%d')
            rows = df[['Date','Ticker','Open','High','Low','Close','Volume']].to_records(index=False)
            conn.executemany('INSERT OR REPLACE INTO historical VALUES (?,?,?,?,?,?,?)', rows.tolist())
            conn.commit()
    conn.close()

# Fetch financials
def fetch_financials(tickers):
    conn = sqlite3.connect(db_path)
    for t in tickers:
        with st.spinner(f"Fetching financials for {t}..."):
            try:
                p = requests.get(f"{PROFILE_URL}?symbol={t}&token={API_KEY}").json()
                m = requests.get(f"{METRIC_URL}&symbol={t}&token={API_KEY}").json().get('metric', {})
                if not p or 'name' not in p:
                    st.warning(f"No financial profile for '{t}'.")
                    continue
            except Exception as e:
                st.warning(f"Error fetching financials '{t}': {e}")
                continue
            conn.execute('INSERT OR REPLACE INTO financials VALUES (?,?,?,?,?,?,?)',(
                t, p.get('name',''), p.get('finnhubIndustry',''),
                m.get('peBasicExclExtraTTM'), m.get('epsBasicExclExtraItemsTTM'),
                m.get('marketCapitalization'), m.get('dividendYieldIndicatedAnnual')
            ))
            conn.commit()
            time.sleep(1)
    conn.close()

# Fetch news and sentiment
def fetch_news(tickers):
    conn = sqlite3.connect(db_path)
    for t in tickers:
        with st.spinner(f"Fetching news for {t}..."):
            url = f"{BASE_NEWS_URL}?symbol={t}&from={(datetime.now()-timedelta(days=30)).strftime('%Y-%m-%d')}&to={datetime.now().strftime('%Y-%m-%d')}&token={API_KEY}"
            try:
                articles = requests.get(url).json()
            except Exception as e:
                st.warning(f"Error fetching news '{t}': {e}")
                continue
            for art in articles:
                date = datetime.fromtimestamp(art.get('datetime',0)).strftime('%Y-%m-%d')
                h = art.get('headline','')
                link = art.get('url', '')
                if h and link:
                    polarity = TextBlob(h).sentiment.polarity
                    conn.execute('INSERT OR REPLACE INTO news VALUES (?,?,?,?,?)',(t, date, h, link, polarity))
            conn.commit()
            time.sleep(0.5)
    conn.close()

# Fetch live stock price
def fetch_live_price(ticker):
    try:
        stock = yf.Ticker(ticker)
        price = stock.info.get('regularMarketPrice', None)
        if price is None:
            return None
        return round(price, 2)
    except Exception as e:
        st.warning(f"Error fetching live price for {ticker}: {e}")
        return None

# Helper function to fetch tickers from Yahoo Finance

def fetch_tickers_and_names():
    try:
        # Set headers to mimic a browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get("https://finance.yahoo.com/screener/predefined/semiconductors", headers=headers)
        
        if response.status_code != 200:
            st.error(f"Failed to fetch page: {response.status_code}")
            return []

        # Parse HTML with BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find the table using the exact class
        table = soup.find('table', {'class': 'expandable-table'})
        if not table:
            st.error("Table not found.")
            return []

        ticker_data = []
        # Extract tickers and company names from table rows
        for row in table.find('tbody').find_all('tr'):
            ticker_cell = row.find('a', {'data-testid': 'table-cell-ticker'})
            if ticker_cell:
                ticker = ticker_cell.find('span', {'class': 'symbol'}).text.strip()
                company_name = ticker_cell.find('span', {'class': 'longName'}).text.strip()
                if ticker and company_name:
                    ticker_data.append((ticker, company_name))

        if not ticker_data:
            st.error("No tickers or company names found.")
        return ticker_data

    except Exception as e:
        st.error(f"Error: {e}")
        return []
    


    
# Main Streamlit app
def main():
    st.markdown(CSS, unsafe_allow_html=True)
    st.title("Semiconductor Stock Dashboard")
    init_db()

    # Fetch data button at the top-right corner
    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("Fetch Data"):
            conn = sqlite3.connect(db_path)
            tickers = pd.read_sql_query("SELECT DISTINCT Ticker FROM historical", conn)['Ticker'].tolist()
            conn.close()
            fetch_historical(tickers)
            st.success("Data updated successfully!")

    # Sidebar for year range selection with dropdowns
    st.sidebar.header("Select Year Range for Analysis")
    current_year = datetime.now().year
    available_years = list(range(2000, current_year + 1))

    col_min, col_max = st.sidebar.columns(2)
    with col_min:
        min_year = st.selectbox(
            "Min Year:",
            options=available_years,
            index=0
        )
    with col_max:
        max_year = st.selectbox(
            "Max Year:",
            options=available_years,
            index=len(available_years) - 1
        )

    if min_year > max_year:
        st.sidebar.error("Min Year cannot be greater than Max Year. Please adjust the selection.")
        return

    # Add or select companies section
    st.sidebar.header("Manage Companies")
    tickers_and_names = fetch_tickers_and_names()
    selected_companies = st.sidebar.multiselect(
        "Select companies to add:",
        options=[f"{ticker} - {name}" for ticker, name in tickers_and_names]
    )
    if st.sidebar.button("Add Selected Companies"):
        selected_tickers = [item.split(" - ")[0] for item in selected_companies]
        if selected_tickers:
            fetch_historical(selected_tickers)
            fetch_financials(selected_tickers)
            fetch_news(selected_tickers)
            st.sidebar.success("Selected companies added successfully!")
            st.experimental_set_query_params()  # Trigger a rerun to refresh data and charts
        else:
            st.sidebar.error("Please select a valid ticker.")

    # Fetch data for the selected year range
    conn = sqlite3.connect(db_path)
    hist = pd.read_sql_query("SELECT * FROM historical", conn)
    fin = pd.read_sql_query("SELECT * FROM financials", conn)
    news = pd.read_sql_query("SELECT * FROM news ORDER BY Date DESC", conn)
    conn.close()
    hist['Date'] = pd.to_datetime(hist['Date'])
    hist = hist[(hist['Date'].dt.year >= min_year) & (hist['Date'].dt.year <= max_year)]

    # Layout adjustments
    with col1:
        # Tabs for main content
        t1, t2, t3 = st.tabs(["Overview", "Charts", "Individual Analysis"])

        with t1:
            st.header("Market Overview")
            st.subheader("Top Performers by Market Cap")
            top_market_cap = fin.nlargest(5, 'Market_Cap')[['Ticker', 'Name', 'Market_Cap']]
            top_market_cap['Name'] = top_market_cap.apply(
                lambda row: f"[{row['Name']}](https://finance.yahoo.com/quote/{row['Ticker']})", axis=1
            )
            st.markdown(top_market_cap.to_html(escape=False, index=False), unsafe_allow_html=True)

            st.subheader("Volatility Analysis")
            pivot_close = hist.pivot_table(index='Date', columns='Ticker', values='Close')
            returns_daily = pivot_close.pct_change().dropna()
            volatility = returns_daily.std() * (252**0.5)
            if not volatility.empty:
                fig_vol, ax_vol = plt.subplots(figsize=(8, 5))
                volatility.sort_values(ascending=False).plot.bar(ax=ax_vol, color='#003087')
                ax_vol.set_ylabel('Annualized Volatility')
                ax_vol.set_title('Stock Volatility (Selected Years)')
                st.pyplot(fig_vol)
            else:
                st.warning("No data available for volatility analysis in the selected year range.")

            st.subheader("Dividend Yield Comparison")
            dividend_yield = fin[['Ticker', 'Dividend_Yield']].dropna()
            fig_div, ax_div = plt.subplots(figsize=(8, 5))
            dividend_yield.set_index('Ticker')['Dividend_Yield'].plot.bar(ax=ax_div, color='#003087')
            ax_div.set_ylabel('Dividend Yield (%)')
            ax_div.set_title('Dividend Yield Comparison')
            st.pyplot(fig_div)

        with t2:
            st.header("Performance Charts")
            st.subheader("Closing Price Trends")
            close = hist.pivot_table(index='Ticker', columns=hist['Date'].dt.year, values='Close', aggfunc='last')
            valid_years = [year for year in range(min_year, max_year + 1) if year in close.columns]
            if valid_years:
                st.line_chart(close[valid_years].T)
            else:
                st.warning("No valid years selected for analysis or data is unavailable for the selected years.")

        with t3:
            st.header("Individual Semiconductor Company Analysis")
            existing = hist['Ticker'].unique()
            choice = st.selectbox("Select company to inspect:", existing)
            df_t = hist[hist['Ticker'] == choice].set_index('Date')

            live_price = fetch_live_price(choice)
            if live_price is not None:
                st.metric(f"Current Price ({choice})", f"${live_price}")
            else:
                st.warning(f"Unable to fetch live price for {choice}.")

            st.subheader(f"Price History for {choice}")
            st.line_chart(df_t['Close'])
            if not df_t.empty:
                change = (df_t['Close'].iloc[-1] - df_t['Close'].iloc[0]) / df_t['Close'].iloc[0] * 100
                st.metric("Change Since Start", f"{change:.2f}%")
            st.subheader(f"Recent News for {choice}")
            for _, row in news[news['Ticker'] == choice].head(5).iterrows():
                st.markdown(f"**{row['Date']}**: [{row['Headline']}]({row['URL']}) _(Sentiment: {row['Sentiment']:.2f})_")

    with col2:
        # News section on the right-hand side
        st.header("Latest News")
        for _, row in news.head(10).iterrows():
            st.markdown(f"""
            <div style="padding: 10px; margin-bottom: 10px; border-radius: 8px; background-color: #1e293b; color: #f1f5f9;">
                <strong>{row['Date']} - {row['Ticker']}</strong><br>
                <a href="{row['URL']}" target="_blank" style="color: #60a5fa; text-decoration: none; font-weight: bold;">{row['Headline']}</a><br>
                <small>Sentiment: {row['Sentiment']:.2f}</small>
            </div>
            """, unsafe_allow_html=True)

if __name__ == '__main__':
    main()
