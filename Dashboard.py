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
import plotly.graph_objects as go
from io import BytesIO
import io
import logging
from dateutil.relativedelta import relativedelta
from pandas_datareader import data as pdr
from alpha_vantage.timeseries import TimeSeries
import os
import investpy 


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Streamlit page config
st.set_page_config(layout="wide", page_title="Semiconductor Dashboard", page_icon="📊")
st.markdown("<style> .block-container { padding-bottom: 100px; } </style>", unsafe_allow_html=True)

# Constants
db_path = 'semiconductor_data.db'
API_KEY = 'd025kahr01qt2u325g1gd025kahr01qt2u325g20'  # Replace with your Finnhub API key
BASE_NEWS_URL = 'https://finnhub.io/api/v1/company-news'
PROFILE_URL = 'https://finnhub.io/api/v1/stock/profile2'
METRIC_URL = 'https://finnhub.io/api/v1/stock/metric?metric=all'

# Custom CSS for styling
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
.chart-container {
    margin-bottom: 20px;
}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# Database initialization
def init_db(reset_financials=False, reset_news=False):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('DROP TABLE IF EXISTS historical')
    c.execute('''CREATE TABLE IF NOT EXISTS historical (
        Date TEXT,
        Ticker TEXT,
        Open REAL,
        High REAL,
        Low REAL,
        Close REAL,
        Volume INTEGER,
        PRIMARY KEY(Date,Ticker)
    )''')
    if reset_financials:
        c.execute('DROP TABLE IF EXISTS financials')
    c.execute('''CREATE TABLE IF NOT EXISTS financials (
        Ticker TEXT PRIMARY KEY,
        Name TEXT,
        Sector TEXT,
        PE_Ratio REAL,
        EPS REAL,
        Market_Cap REAL,
        Dividend_Yield REAL,
        Forward_PE REAL,
        PEG_Ratio REAL,
        Debt_To_Equity REAL,
        Revenue_Growth REAL,
        Last_Update TEXT
    )''')
    if reset_news:
        c.execute('DROP TABLE IF EXISTS news')
    c.execute('''CREATE TABLE IF NOT EXISTS news (
        Ticker TEXT,
        Date TEXT,
        Headline TEXT,
        URL TEXT,
        Sentiment REAL,
        Summary TEXT,
        PRIMARY KEY(Ticker,Date,Headline)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS social_trends (
        Ticker TEXT,
        Date TEXT,
        Post_Count INTEGER,
        Sentiment REAL,
        PRIMARY KEY(Ticker,Date)
    )''')
    c.execute("PRAGMA table_info(financials)")
    columns = [col[1] for col in c.fetchall()]
    if 'Last_Update' not in columns:
        c.execute("ALTER TABLE financials ADD COLUMN Last_Update TEXT")
        logging.info("Added Last_Update column to financials table.")
    conn.commit()
    conn.close()
    logging.info("Database initialized with optimized schema.")


# Alpha Vantage API key (replace with your own or set as environment variable)
ALPHA_VANTAGE_API_KEY = os.getenv('ALPHA_VANTAGE_API_KEY', 'UKDMXB5TMJLFWGL7')

# Tiingo requires an API key (free tier available)
TIINGO_API_KEY = 'd1fc81c0309fb459a34ec0114889761d4ff0ab03'

# No-key sources remain as fallbacks

def fetch_historical(tickers, period: str = '5y', delay_sec: int = 1, table_name: str = 'historical'):
    """
    Incrementally fetch historical OHLCV data for given tickers over `period` using:
      1) Tiingo (requires TIINGO_API_KEY),
      2) Stooq (no key),
      3) yfinance (no key, built-in retry/backoff).
    Inserts only missing rows into SQLite `table_name`.
    """
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    now = datetime.now()

    # Compute full start date
    if period.endswith('y'):
        start_full = now - relativedelta(years=int(period[:-1]))
    elif period.endswith('d'):
        start_full = now - timedelta(days=int(period[:-1]))
    else:
        start_full = now - relativedelta(years=5)

    for ticker in tickers:
        # Check existing coverage
        c.execute(f"SELECT MIN(Date), MAX(Date) FROM {table_name} WHERE Ticker=?", (ticker,))
        min_date_str, max_date_str = c.fetchone()
        if min_date_str and max_date_str:
            min_date = pd.to_datetime(min_date_str)
            max_date = pd.to_datetime(max_date_str)
            if min_date <= start_full and max_date >= now:
                logging.info(f"{ticker}: up-to-date, skipping fetch.")
                continue

        with st.spinner(f"Fetching historical data for {ticker}..."):
            # Determine fetch window
            if max_date_str:
                fetch_start = pd.to_datetime(max_date_str) + pd.Timedelta(days=1)
                if fetch_start.date() >= now.date():
                    logging.info(f"{ticker}: no new data needed.")
                    continue
            else:
                fetch_start = start_full
            fetch_end = now

            # Prepare date parameters
            start_str = fetch_start.strftime('%Y-%m-%d')
            end_str = fetch_end.strftime('%Y-%m-%d')
            df = pd.DataFrame()

            # 1) Try Tiingo
            if TIINGO_API_KEY:
                try:
                    tiingo_url = (
                        f"https://api.tiingo.com/tiingo/daily/{ticker}/prices"
                        f"?startDate={start_str}&endDate={end_str}&token={TIINGO_API_KEY}"
                    )
                    resp = requests.get(tiingo_url, timeout=10)
                    resp.raise_for_status()
                    data = resp.json()
                    if isinstance(data, list) and data:
                        df_tiingo = pd.DataFrame(data)
                        df_tiingo['Date'] = pd.to_datetime(df_tiingo['date']).dt.strftime('%Y-%m-%d')
                        df = df_tiingo.rename(
                            columns={
                                'adjOpen': 'Open',
                                'adjHigh': 'High',
                                'adjLow': 'Low',
                                'adjClose': 'Close',
                                'adjVolume': 'Volume'
                            }
                        )[['Date','Open','High','Low','Close','Volume']]
                        logging.info(f"Tiingo: fetched {len(df)} rows for {ticker}.")
                except Exception as e:
                    logging.error(f"Tiingo fetch failed for {ticker}: {e}")
            else:
                logging.warning("TIINGO_API_KEY not set; skipping Tiingo source.")

            # 2) Fallback: Stooq
            if df.empty:
                try:
                    df_stooq = pdr.DataReader(ticker, 'stooq', start=start_str, end=end_str)
                    if not df_stooq.empty:
                        df = df_stooq.reset_index()
                        logging.info(f"Stooq: fetched {len(df)} rows for {ticker}.")
                except Exception as e:
                    logging.error(f"Stooq fetch failed for {ticker}: {e}")

            # 3) Fallback: yfinance with backoff
            if df.empty:
                backoff = 1
                for attempt in range(3):
                    try:
                        df_yf = yf.download(ticker, start=start_str, end=end_str, progress=False)
                        if not df_yf.empty:
                            df = df_yf.reset_index()
                            logging.info(f"yfinance: fetched {len(df)} rows for {ticker}.")
                            break
                        else:
                            logging.info(f"yfinance: no data for {ticker} in range.")
                            break
                    except Exception as e:
                        logging.warning(f"yfinance fetch error for {ticker}, retrying... ({e})")
                        time.sleep(backoff)
                        backoff *= 2

            if df.empty:
                logging.warning(f"No data for {ticker} from any source.")
                continue

            # Normalize & insert
            df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%m-%d')
            df['Ticker'] = ticker
            df = df[['Date','Ticker','Open','High','Low','Close','Volume']]

            records = df.to_records(index=False)
            insert_sql = (
                f"INSERT OR IGNORE INTO {table_name} "
                "(Date,Ticker,Open,High,Low,Close,Volume) VALUES (?,?,?,?,?,?,?)"
            )
            conn.executemany(insert_sql, list(records))
            conn.commit()
            logging.info(f"Inserted {len(df)} rows for {ticker} into '{table_name}'.")

            time.sleep(delay_sec)

    conn.close()





# Fetch financials
def fetch_financials(tickers):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    now = datetime.now().isoformat()
    for t in tickers:
        with st.spinner(f"Fetching financials for {t}…"):
            c.execute("SELECT Last_Update FROM financials WHERE Ticker=?", (t,))
            result = c.fetchone()
            if result and result[0]:
                last_update = datetime.fromisoformat(result[0])
                if (datetime.now() - last_update).total_seconds() < 86400:
                    logging.info(f"Skipping {t}, last updated {last_update}")
                    continue
            try:
                p = requests.get(f"{PROFILE_URL}?symbol={t}&token={API_KEY}").json()
                m = requests.get(f"{METRIC_URL}&symbol={t}&token={API_KEY}").json().get('metric', {})
                if not p or 'name' not in p:
                    st.warning(f"No financial profile for '{t}'.")
                    logging.warning(f"No financial profile for '{t}'.")
                    continue
                conn.execute('INSERT OR REPLACE INTO financials VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(
                    t, p.get('name'), p.get('finnhubIndustry'),
                    m.get('peBasicExclExtraTTM'), m.get('epsBasicExclExtraItemsTTM'),
                    m.get('marketCapitalization'), m.get('dividendYieldIndicatedAnnual'),
                    m.get('peForward'), m.get('pegRatio'), m.get('totalDebt/totalEquityAnnual'),
                    m.get('revenueGrowth'), now
                ))
                conn.commit()
                logging.info(f"Financials updated for {t}.")
                time.sleep(1)
            except Exception as e:
                st.warning(f"Error fetching financials '{t}': {e}")
                logging.error(f"Error fetching financials for '{t}': {e}")
    conn.close()

# Fetch news
def fetch_news(tickers):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("PRAGMA table_info(news)")
    columns = [col[1] for col in c.fetchall()]
    if 'Fetched_At' not in columns:
        c.execute("ALTER TABLE news ADD COLUMN Fetched_At TEXT")
        conn.commit()
        logging.info("Added Fetched_At column to news table.")
    for t in tickers:
        c.execute("SELECT MAX(Fetched_At) FROM news WHERE Ticker=?", (t,))
        last_fetched_str = c.fetchone()[0]
        if last_fetched_str:
            try:
                last_fetched = datetime.fromisoformat(last_fetched_str)
                if (datetime.now() - last_fetched).total_seconds() < 43200:
                    logging.info(f"Skipping news fetch for {t} as it was fetched less than 12 hours ago.")
                    continue
            except Exception as e:
                logging.error(f"Error parsing Fetched_At for {t}: {e}")
        with st.spinner(f"Fetching news for {t}…"):
            url = f"{BASE_NEWS_URL}?symbol={t}&from={(datetime.now()-timedelta(days=30)).strftime('%Y-%m-%d')}&to={datetime.now().strftime('%Y-%m-%d')}&token={API_KEY}"
            try:
                articles = requests.get(url).json()
                now_str = datetime.now().isoformat()
                for art in articles:
                    date = datetime.fromtimestamp(art.get('datetime', 0)).strftime('%Y-%m-%d')
                    h = art.get('headline', '')
                    link = art.get('url', '')
                    if h and link:
                        try:
                            resp = requests.get(link, timeout=5)
                            soup = BeautifulSoup(resp.text, 'html.parser')
                            summary = ' '.join([p.text for p in soup.find_all('p')[:2]])
                            text = f"{h}. {summary}"
                            polarity = TextBlob(text).sentiment.polarity
                            conn.execute(
                                'INSERT OR REPLACE INTO news VALUES (?,?,?,?,?,?,?)',
                                (t, date, h, link, polarity, summary[:500], now_str)
                            )
                        except:
                            polarity = TextBlob(h).sentiment.polarity
                            conn.execute(
                                'INSERT OR REPLACE INTO news VALUES (?,?,?,?,?,?,?)',
                                (t, date, h, link, polarity, '', now_str)
                            )
                conn.commit()
                logging.info(f"News fetched for {t}.")
                time.sleep(0.1)
            except Exception as e:
                st.warning(f"Error fetching news '{t}': {e}")
                logging.error(f"Error fetching news for '{t}': {e}")
    conn.close()

# Fetch live stock price
def fetch_live_price(ticker):
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={API_KEY}"
        response = requests.get(url)
        data = response.json()
        price = data.get('c', None)
        return round(price, 2) if price else None
    except Exception as e:
        st.warning(f"Error fetching live price for {ticker}: {e}")
        logging.error(f"Error fetching live price for {ticker}: {e}")
        return None

# Fetch tickers from Yahoo Finance
def fetch_tickers_and_names():
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get("https://finance.yahoo.com/screener/predefined/semiconductors", headers=headers)
        if response.status_code != 200:
            logging.error(f"Failed to fetch Yahoo Finance page: {response.status_code}")
            return []
        soup = BeautifulSoup(response.text, 'html.parser')
        table = soup.find('table', {'class': 'expandable-table'})
        if not table:
            logging.warning("Table not found on Yahoo Finance page. Falling back to alternative method.")
            return fallback_tickers()
        data = []
        for row in table.find('tbody').find_all('tr'):
            cells = row.find_all('td')
            if len(cells) >= 2:
                ticker = cells[0].text.strip().split(" ")[0]
                name = cells[0].text.strip().split(" ")[1]
                data.append((ticker, name))
        logging.info(f"Fetched {len(data)} tickers.")
        return data
    except Exception as e:
        logging.error(f"Error fetching tickers: {e}")
        return fallback_tickers()

def fallback_tickers():
    logging.info("Using fallback tickers.")
    return [
        ("NVDA", "NVIDIA Corporation"),
        ("AMD", "Advanced Micro Devices, Inc."),
        ("INTC", "Intel Corporation"),
        ("TSM", "Taiwan Semiconductor Manufacturing Company Limited"),
        ("QCOM", "Qualcomm Incorporated")
    ]

# Plot candlestick chart
def plot_candlestick(df_t, ticker):
    df_t = df_t.sort_index()
    fig = go.Figure(data=[
        go.Candlestick(x=df_t.index, open=df_t['Open'], high=df_t['High'], low=df_t['Low'], close=df_t['Close'], name='Price'),
        go.Scatter(x=df_t.index, y=df_t['MA50'], line=dict(color='orange'), name='MA50'),
        go.Scatter(x=df_t.index, y=df_t['MA200'], line=dict(color='purple'), name='MA200')
    ])
    fig.update_layout(title=f'{ticker} Price History with Moving Averages', yaxis_title='Price (USD)', xaxis_title='Date', template='plotly_white', margin=dict(l=40,r=40,t=40,b=40))
    return fig

# Sector comparison chart
def sector_comparison():
    etfs = {'Semiconductors':'SOXX','Technology':'XLK','Healthcare':'XLV'}
    try:
        data = yf.download(list(etfs.values()), period='1y', progress=False)['Close']
        returns = data.pct_change().cumsum()*100
        fig, ax = plt.subplots(figsize=(10,6))
        for col,name in zip(returns.columns,etfs.keys()):
            ax.plot(returns.index, returns[col], label=name)
        ax.set_title('Sector Performance (1-Year Cumulative Returns)')
        ax.set_ylabel('Cumulative Return (%)')
        ax.legend()
        ax.grid(True)
        return fig
    except Exception as e:
        st.warning(f"Error plotting sector comparison: {e}")
        logging.error(f"Error plotting sector comparison: {e}")
        return None

# Top performers
def top_performers(hist):
    try:
        latest = hist[hist['Date']==hist['Date'].max()].copy()
        latest['Daily_Change'] = (latest['Close']-latest['Open'])/latest['Open']*100
        gainers = latest.nlargest(5,'Daily_Change')[['Ticker','Daily_Change']].round(2)
        losers  = latest.nsmallest(5,'Daily_Change')[['Ticker','Daily_Change']].round(2)
        return gainers, losers
    except Exception as e:
        st.warning(f"Error calculating top performers: {e}")
        logging.error(f"Error calculating top performers: {e}")
        return pd.DataFrame(), pd.DataFrame()

# Main app
def main():
    st.title("Semiconductor Stock Dashboard")
    with st.sidebar:
        st.header("Database Management")
        if st.button("Reset Financials Table"):
            init_db(reset_financials=True, reset_news=False)
            st.success("Financials table reset. Fetch data again.")
        if st.button("Reset News Table"):
            init_db(reset_financials=False, reset_news=True)
            st.success("News table reset. Fetch data again.")
    init_db(reset_financials=False, reset_news=False)
    fetch_data = True
    st.sidebar.header("Dashboard Controls")
    period = st.sidebar.selectbox("Historical Data Period:", ['1y','2y','5y','10y'], index=2)
    year_now = datetime.now().year
    years = list(range(2000, year_now+1))
    min_y, max_y = st.sidebar.columns(2)
    with min_y:
        min_year = st.selectbox("Min Year:", years, index=0)
    with max_y:
        max_year = st.selectbox("Max Year:", years, index=len(years)-1)
    if min_year > max_year:
        st.sidebar.error("Min Year cannot exceed Max Year.")
        return
    
    if fetch_data:
        opts = fetch_tickers_and_names()
        tickers = [t for (t, n) in opts]
        fetch_data = False
        if tickers:
            with st.spinner("Fetching data for all companies..."):
                fetch_historical(tickers, period)
                fetch_financials(tickers)
                fetch_news(tickers)
            st.sidebar.success("All companies data fetched successfully!")
    
    custom_ticker = st.text_input("Enter custom ticker:", "")
    if st.button("Update Custom Ticker"):
        if custom_ticker:
            ticker = custom_ticker.upper().strip()
            with st.spinner(f"Fetching data for {ticker}..."):
                fetch_historical([ticker], period)
                fetch_financials([ticker])
                fetch_news([ticker])
            st.success(f"Data updated successfully for {ticker}!")
        else:
            st.error("Please enter a valid ticker.")
    
    col1, col2 = st.columns([3,1])
    with col2:
        if st.button("Fetch Data"):
            conn = sqlite3.connect(db_path)
            tickers = pd.read_sql("SELECT DISTINCT Ticker FROM historical", conn)['Ticker'].tolist()
            conn.close()
            if tickers:
                fetch_historical(tickers, period)
                fetch_financials(tickers)
                fetch_news(tickers)
                st.success("Data updated successfully!")
            else:
                st.warning("No tickers found. Add companies first.")
    
    # Load all data into memory once
    conn = sqlite3.connect(db_path)
    hist_full = pd.read_sql_query("SELECT * FROM historical", conn)
    fin = pd.read_sql_query("SELECT * FROM financials", conn)
    news = pd.read_sql_query("SELECT * FROM news ORDER BY Date DESC", conn)
    conn.close()

    if hist_full.empty or 'Date' not in hist_full.columns:
        st.warning("No historical data. Please add companies and fetch.")
        return
    
    hist_full['Date'] = pd.to_datetime(hist_full['Date'])
    hist = hist_full[(hist_full['Date'].dt.year >= min_year) & (hist_full['Date'].dt.year <= max_year)]

    with col1:
        t1, t2, t3, t4 = st.tabs(["Overview", "Charts", "Individual Analysis", "Education"])
        with t1:
            st.header("Market Overview")
            st.subheader("Top Performers by Market Cap")
            top_mc = fin.nlargest(5, 'Market_Cap')[['Ticker', 'Name', 'Market_Cap']]
            top_mc['Name'] = top_mc.apply(lambda r: f'<a href="https://finance.yahoo.com/quote/{r["Ticker"]}" target="_blank">{r["Name"]}</a>', axis=1)
            st.markdown(top_mc.to_html(escape=False, index=False), unsafe_allow_html=True)
            if st.button("Export Market Cap Data"):
                st.download_button("Download CSV", top_mc.to_csv(index=False), "market_cap.csv", "text/csv")
            st.subheader("Top Gainers and Losers")
            g, l = top_performers(hist)
            cg, cl = st.columns(2)
            with cg:
                st.write("Top Gainers")
                st.table(g)
            with cl:
                st.write("Top Losers")
                st.table(l)
            st.subheader("Sector Performance")
            fig_s = sector_comparison()
            if fig_s:
                st.pyplot(fig_s, use_container_width=True)
            st.subheader("Volatility Analysis")
            pivot = hist.pivot_table(index='Date', columns='Ticker', values='Close')
            vol = pivot.pct_change().dropna().std() * (252 ** 0.5)
            if not vol.empty:
                fig_v, ax_v = plt.subplots(figsize=(8, 5))
                vol.sort_values(ascending=False).plot.bar(ax=ax_v)
                ax_v.set_ylabel('Annualized Volatility')
                ax_v.set_title('Stock Volatility')
                st.pyplot(fig_v, use_container_width=True)
                buf = BytesIO()
                fig_v.savefig(buf, format='png')
                st.download_button("Download Volatility Chart", buf.getvalue(), "volatility.png", "image/png")
        with t2:
            st.header("Performance Charts")
            close = hist.pivot_table(index='Ticker', columns=hist['Date'].dt.year, values='Close', aggfunc='last')
            yrs = [y for y in range(min_year, max_year + 1) if y in close.columns]
            if yrs:
                st.line_chart(close[yrs].T)
            else:
                st.warning("No data for selected years.")
            st.subheader("Dividend Yield Comparison")
            dy = fin[['Ticker', 'Dividend_Yield']].dropna()
            fig_d, ax_d = plt.subplots(figsize=(8, 5))
            dy.set_index('Ticker')['Dividend_Yield'].plot.bar(ax=ax_d)
            ax_d.set_ylabel('Dividend Yield (%)')
            ax_d.set_title('Dividend Yield Comparison')
            st.pyplot(fig_d, use_container_width=True)
        with t3:
            st.header("Individual Semiconductor Company Analysis")
            choices = hist['Ticker'].unique()
            choice = st.selectbox("Select company:", choices)
            # Use in-memory full history for accurate MAs
            df_t_full = hist_full[hist_full['Ticker'] == choice].copy()
            df_t_full['Date'] = pd.to_datetime(df_t_full['Date'])
            df_t_full = df_t_full.set_index('Date')
            df_t_full['MA50'] = df_t_full['Close'].rolling(window=50).mean()
            df_t_full['MA200'] = df_t_full['Close'].rolling(window=200).mean()
            # Filter for display
            df_t = df_t_full[(df_t_full.index.year >= min_year) & (df_t_full.index.year <= max_year)]
            fin_t = fin[fin['Ticker'] == choice]
            lp = fetch_live_price(choice)
            if lp:
                st.metric(f"Current Price ({choice})", f"${lp}")
            st.subheader(f"Price History for {choice}")
            fig_c = plot_candlestick(df_t, choice)
            st.plotly_chart(fig_c, use_container_width=True)
            if not df_t.empty:
                ch = (df_t['Close'].iloc[-1] - df_t['Close'].iloc[0]) / df_t['Close'].iloc[0] * 100
                st.metric("Change Since Start", f"{ch:.2f}%")
            st.subheader(f"Financial Metrics for {choice}")
            if not fin_t.empty:
                metrics = fin_t[['PE_Ratio', 'Forward_PE', 'EPS', 'Market_Cap', 'Dividend_Yield', 'PEG_Ratio', 'Debt_To_Equity', 'Revenue_Growth']].iloc[0]
                st.table(metrics)
            st.subheader(f"Recent News for {choice}")
            for _, row in news[news['Ticker'] == choice].head(5).iterrows():
                st.markdown(f"**{row['Date']}**: [{row['Headline']}]({row['URL']}) _(Sentiment: {row['Sentiment']:.2f})_")
                if row.get('Summary'):
                    with st.expander("Summary"):
                        st.write(row['Summary'])
        with t4:
            st.header("Educational Resources")
            st.subheader("Glossary")
            st.markdown("""
            - **P/E Ratio**: Price-to-Earnings ratio.
            - **EPS**: Earnings Per Share.
            - **Volatility**: Annualized stock price fluctuation.
            - **Dividend Yield**: Annual dividend as % of price.
            - **Moving Average (MA)**: Average price over a window.
            """)
            st.subheader("Beginner Tips")
            st.markdown("""
            - Start with stable companies like TSMC or Intel.
            - Use the watchlist to track your favorites.
            - Check news sentiment to gauge market mood.
            - Compare P/E ratios to spot valuation differences.
            """)
            st.subheader("Learn More")
            st.markdown("[Investopedia Investing Basics](https://www.investopedia.com/)")
    with col2:
        st.header("Latest News")
        for _, row in news.head(10).iterrows():
            st.markdown(f"""
            <div style="padding:10px;margin-bottom:10px;border-radius:8px;background-color:#1e293b;color:#f1f5f9;">
                <strong>{row['Date']} - {row['Ticker']}</strong><br>
                <a href="{row['URL']}" target="_blank" style="color:#60a5fa;font-weight:bold;">{row['Headline']}</a><br>
                <small>Sentiment: {row['Sentiment']:.2f}</small>
            </div>
            """, unsafe_allow_html=True)
    
    if not hist.empty:
        html = '<div class="ticker-footer">'
        for t in hist['Ticker'].unique():
            last_close = hist[hist['Ticker'] == t]['Close'].iloc[-1]
            html += f"<div class=\"ticker-item\">{t}<span class=\"ticker-tooltip\">{t}: ${last_close:.2f}</span></div>"
        html += '</div>'
        st.markdown(html, unsafe_allow_html=True)

    st.markdown(
        """
        <div style="text-align:center; padding: 8px; font-size:12px; color:#555;">
        Credits: Pradeep Kumar Velidi, USC ID: 4514814183
        </div>
        """,
        unsafe_allow_html=True
    )

if __name__ == '__main__':
    main()
