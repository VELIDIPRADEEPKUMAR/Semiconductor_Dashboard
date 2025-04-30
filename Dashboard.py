
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
import uuid
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Set wide layout and custom page config
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
def init_db():
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    # Drop existing table to ensure correct schema (optional, use with caution)
    c.execute('DROP TABLE IF EXISTS historical')
    c.execute('''CREATE TABLE IF NOT EXISTS historical (
        Date TEXT, Ticker TEXT, Open REAL, High REAL, Low REAL, Close REAL, 
        Volume INTEGER, MA50 REAL, MA200 REAL, PRIMARY KEY(Date,Ticker)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS financials (
        Ticker TEXT PRIMARY KEY, Name TEXT, Sector TEXT, PE_Ratio REAL, EPS REAL, 
        Market_Cap REAL, Dividend_Yield REAL, Forward_PE REAL, PEG_Ratio REAL, 
        Debt_To_Equity REAL, Revenue_Growth REAL
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS news (
        Ticker TEXT, Date TEXT, Headline TEXT, URL TEXT, Sentiment REAL, Summary TEXT,
        PRIMARY KEY(Ticker,Date,Headline)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS social_trends (
        Ticker TEXT, Date TEXT, Post_Count INTEGER, Sentiment REAL,
        PRIMARY KEY(Ticker,Date)
    )''')
    conn.commit()
    conn.close()
    logging.info("Database initialized with correct schema.")

# Fetch historical data
def fetch_historical(tickers, period='5y'):
    conn = sqlite3.connect(db_path)
    for t in tickers:
        with st.spinner(f"Fetching historical data for {t}..."):
            try:
                df = yf.download(t, period=period, progress=False)
                if df.empty:
                    st.warning(f"No historical data for '{t}'.")
                    logging.warning(f"No historical data for '{t}'.")
                    continue
                df['MA50'] = df['Close'].rolling(window=50).mean()
                df['MA200'] = df['Close'].rolling(window=200).mean()
                df = df.reset_index()
                df['Ticker'] = t
                df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%m-%d')
                rows = df[['Date', 'Ticker', 'Open', 'High', 'Low', 'Close', 'Volume', 'MA50', 'MA200']].to_records(index=False)
                conn.executemany('INSERT OR REPLACE INTO historical VALUES (?,?,?,?,?,?,?,?)', rows.tolist())
                conn.commit()
                logging.info(f"Historical data fetched for {t}.")
            except Exception as e:
                st.warning(f"Error fetching '{t}': {e}")
                logging.error(f"Error fetching historical data for '{t}': {e}")
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
                    logging.warning(f"No financial profile for '{t}'.")
                    continue
                conn.execute('INSERT OR REPLACE INTO financials VALUES (?,?,?,?,?,?,?,?,?,?,?)', (
                    t, p.get('name'), p.get('finnhubIndustry'),
                    m.get('peBasicExclExtraTTM'), m.get('epsBasicExclExtraItemsTTM'),
                    m.get('marketCapitalization'), m.get('dividendYieldIndicatedAnnual'),
                    m.get('peForward'), m.get('pegRatio'), m.get('totalDebt/totalEquityAnnual'),
                    m.get('revenueGrowth')
                ))
                conn.commit()
                logging.info(f"Financials fetched for {t}.")
                time.sleep(1)
            except Exception as e:
                st.warning(f"Error fetching financials '{t}': {e}")
                logging.error(f"Error fetching financials for '{t}': {e}")
    conn.close()

# Fetch news and sentiment
def fetch_news(tickers):
    conn = sqlite3.connect(db_path)
    for t in tickers:
        with st.spinner(f"Fetching news for {t}..."):
            url = f"{BASE_NEWS_URL}?symbol={t}&from={(datetime.now()-timedelta(days=30)).strftime('%Y-%m-%d')}&to={datetime.now().strftime('%Y-%m-%d')}&token={API_KEY}"
            try:
                articles = requests.get(url).json()
                for art in articles:
                    date = datetime.fromtimestamp(art.get('datetime', 0)).strftime('%Y-%m-%d')
                    h = art.get('headline', '')
                    link = art.get('url', '')
                    if h and link:
                        try:
                            response = requests.get(link, timeout=5)
                            soup = BeautifulSoup(response.text, 'html.parser')
                            summary = ' '.join([p.text for p in soup.find_all('p')[:2]])
                            text = f"{h}. {summary}"
                            polarity = TextBlob(text).sentiment.polarity
                            conn.execute('INSERT OR REPLACE INTO news VALUES (?,?,?,?,?,?)', 
                                        (t, date, h, link, polarity, summary[:500]))
                        except:
                            polarity = TextBlob(h).sentiment.polarity
                            conn.execute('INSERT OR REPLACE INTO news VALUES (?,?,?,?,?,?)', 
                                        (t, date, h, link, polarity, ''))
                conn.commit()
                logging.info(f"News fetched for {t}.")
                time.sleep(0.5)
            except Exception as e:
                st.warning(f"Error fetching news '{t}': {e}")
                logging.error(f"Error fetching news for '{t}': {e}")
    conn.close()

# Fetch live stock price
def fetch_live_price(ticker):
    try:
        stock = yf.Ticker(ticker)
        price = stock.info.get('regularMarketPrice', None)
        return round(price, 2) if price else None
    except Exception as e:
        st.warning(f"Error fetching live price for {ticker}: {e}")
        logging.error(f"Error fetching live price for {ticker}: {e}")
        return None

# Fetch tickers from Yahoo Finance
def fetch_tickers_and_names():
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get("https://finance.yahoo.com/screener/predefined/semiconductors", headers=headers)
        if response.status_code != 200:
            logging.error(f"Failed to fetch Yahoo Finance page: {response.status_code}")
            return []
        soup = BeautifulSoup(response.text, 'html.parser')
        table = soup.find('table', {'class': 'expandable-table'})
        if not table:
            logging.error("Table not found on Yahoo Finance page.")
            return []
        ticker_data = []
        for row in table.find('tbody').find_all('tr'):
            ticker_cell = row.find('a', {'data-testid': 'table-cell-ticker'})
            if ticker_cell:
                ticker = ticker_cell.find('span', {'class': 'symbol'}).text.strip()
                company_name = ticker_cell.find('span', {'class': 'longName'}).text.strip()
                if ticker and company_name:
                    ticker_data.append((ticker, company_name))
        logging.info(f"Fetched {len(ticker_data)} tickers from Yahoo Finance.")
        return ticker_data
    except Exception as e:
        st.error(f"Error fetching tickers: {e}")
        logging.error(f"Error fetching tickers: {e}")
        return []

# Plot candlestick chart
def plot_candlestick(df_t, ticker):
    fig = go.Figure(data=[
        go.Candlestick(x=df_t.index, open=df_t['Open'], high=df_t['High'], 
                       low=df_t['Low'], close=df_t['Close'], name='Price'),
        go.Scatter(x=df_t.index, y=df_t['MA50'], line=dict(color='orange'), name='MA50'),
        go.Scatter(x=df_t.index, y=df_t['MA200'], line=dict(color='purple'), name='MA200')
    ])
    fig.update_layout(title=f'{ticker} Price History with Moving Averages', 
                      yaxis_title='Price (USD)', xaxis_title='Date',
                      template='plotly_white', margin=dict(l=40, r=40, t=40, b=40))
    return fig

# Sector comparison chart
def sector_comparison():
    etfs = {'Semiconductors': 'SOXX', 'Technology': 'XLK', 'Healthcare': 'XLV'}
    try:
        data = yf.download(list(etfs.values()), period='1y', progress=False)['Close']
        returns = data.pct_change().cumsum() * 100
        fig, ax = plt.subplots(figsize=(10, 6))
        for col, name in zip(returns.columns, etfs.keys()):
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
        latest = hist[hist['Date'] == hist['Date'].max()].copy()
        latest['Daily_Change'] = (latest['Close'] - latest['Open']) / latest['Open'] * 100
        gainers = latest.nlargest(5, 'Daily_Change')[['Ticker', 'Daily_Change']].round(2)
        losers = latest.nsmallest(5, 'Daily_Change')[['Ticker', 'Daily_Change']].round(2)
        return gainers, losers
    except Exception as e:
        st.warning(f"Error calculating top performers: {e}")
        logging.error(f"Error calculating top performers: {e}")
        return pd.DataFrame(), pd.DataFrame()

# Main Streamlit app
def main():
    st.title("Semiconductor Stock Dashboard")
    init_db()

    # Sidebar
    st.sidebar.header("Dashboard Controls")
    period = st.sidebar.selectbox("Historical Data Period:", ['1y', '2y', '5y', '10y'], index=2)
    current_year = datetime.now().year
    available_years = list(range(2000, current_year + 1))
    col_min, col_max = st.sidebar.columns(2)
    with col_min:
        min_year = st.selectbox("Min Year:", available_years, index=0)
    with col_max:
        max_year = st.selectbox("Max Year:", available_years, index=len(available_years)-1)
    if min_year > max_year:
        st.sidebar.error("Min Year cannot be greater than Max Year.")
        return

    # Watchlist
    if 'watchlist' not in st.session_state:
        st.session_state.watchlist = []
    st.sidebar.header("Watchlist")
    watchlist_input = st.sidebar.text_input("Add to Watchlist (e.g., NVDA):")
    if st.sidebar.button("Add to Watchlist"):
        if watchlist_input.upper() in [t[0] for t in fetch_tickers_and_names()]:
            if watchlist_input.upper() not in st.session_state.watchlist:
                st.session_state.watchlist.append(watchlist_input.upper())
                st.sidebar.success(f"{watchlist_input} added to watchlist!")
        else:
            st.sidebar.error("Invalid ticker.")
    st.sidebar.write("Your Watchlist:", st.session_state.watchlist)

    # Manage companies
    st.sidebar.header("Manage Companies")
    tickers_and_names = fetch_tickers_and_names()
    selected_companies = st.sidebar.multiselect(
        "Select companies to add:", 
        options=[f"{ticker} - {name}" for ticker, name in tickers_and_names]
    )
    if st.sidebar.button("Add Selected Companies"):
        selected_tickers = [item.split(" - ")[0] for item in selected_companies]
        if selected_tickers:
            fetch_historical(selected_tickers, period)
            fetch_financials(selected_tickers)
            fetch_news(selected_tickers)
            st.sidebar.success("Companies added successfully!")

    # Fetch data button
    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("Fetch Data"):
            conn = sqlite3.connect(db_path)
            tickers = pd.read_sql_query("SELECT DISTINCT Ticker FROM historical", conn)['Ticker'].tolist()
            conn.close()
            if tickers:
                fetch_historical(tickers, period)
                fetch_financials(tickers)
                fetch_news(tickers)
                st.success("Data updated successfully!")
            else:
                st.warning("No tickers found in database. Please add companies first.")

    # Load data
    conn = sqlite3.connect(db_path)
    hist = pd.read_sql_query("SELECT * FROM historical", conn)
    fin = pd.read_sql_query("SELECT * FROM financials", conn)
    news = pd.read_sql_query("SELECT * FROM news ORDER BY Date DESC", conn)
    conn.close()

    # Check if hist is empty or lacks 'Date' column
    if hist.empty or 'Date' not in hist.columns:
        st.warning("No historical data available. Please add companies and fetch data using the sidebar.")
        logging.warning("Historical data is empty or missing 'Date' column.")
        return

    # Process historical data
    try:
        hist['Date'] = pd.to_datetime(hist['Date'])
        hist = hist[(hist['Date'].dt.year >= min_year) & (hist['Date'].dt.year <= max_year)]
    except Exception as e:
        st.error(f"Error processing historical data: {e}")
        logging.error(f"Error processing historical data: {e}")
        return

    # Tabs
    with col1:
        t1, t2, t3, t4 = st.tabs(["Overview", "Charts", "Individual Analysis", "Education"])

        with t1:
            st.header("Market Overview")
            st.subheader("Top Performers by Market Cap")
            top_market_cap = fin.nlargest(5, 'Market_Cap')[['Ticker', 'Name', 'Market_Cap']]
            top_market_cap['Name'] = top_market_cap.apply(
                lambda row: f"[{row['Name']}](https://finance.yahoo.com/quote/{row['Ticker']})", axis=1
            )
            st.markdown(top_market_cap.to_html(escape=False, index=False), unsafe_allow_html=True)
            if st.button("Export Market Cap Data"):
                csv = top_market_cap.to_csv(index=False)
                st.download_button("Download CSV", csv, "market_cap.csv", "text/csv")

            st.subheader("Top Gainers and Losers")
            gainers, losers = top_performers(hist)
            col_g, col_l = st.columns(2)
            with col_g:
                st.write("Top Gainers")
                st.table(gainers)
            with col_l:
                st.write("Top Losers")
                st.table(losers)

            st.subheader("Sector Performance")
            fig_sector = sector_comparison()
            if fig_sector:
                st.pyplot(fig_sector, use_container_width=True)

            st.subheader("Volatility Analysis")
            pivot_close = hist.pivot_table(index='Date', columns='Ticker', values='Close')
            returns_daily = pivot_close.pct_change().dropna()
            volatility = returns_daily.std() * (252**0.5)
            if not volatility.empty:
                fig_vol, ax_vol = plt.subplots(figsize=(8, 5))
                volatility.sort_values(ascending=False).plot.bar(ax=ax_vol, color='#003087')
                ax_vol.set_ylabel('Annualized Volatility')
                ax_vol.set_title('Stock Volatility (Selected Years)')
                st.pyplot(fig_vol, use_container_width=True)
                buf = BytesIO()
                fig_vol.savefig(buf, format="png")
                st.download_button("Download Volatility Chart", buf.getvalue(), "volatility.png", "image/png")
            else:
                st.warning("No data for volatility analysis.")

        with t2:
            st.header("Performance Charts")
            st.subheader("Closing Price Trends")
            close = hist.pivot_table(index='Ticker', columns=hist['Date'].dt.year, values='Close', aggfunc='last')
            valid_years = [year for year in range(min_year, max_year + 1) if year in close.columns]
            if valid_years:
                st.line_chart(close[valid_years].T)
            else:
                st.warning("No data for selected years.")

            st.subheader("Dividend Yield Comparison")
            dividend_yield = fin[['Ticker', 'Dividend_Yield']].dropna()
            fig_div, ax_div = plt.subplots(figsize=(8, 5))
            dividend_yield.set_index('Ticker')['Dividend_Yield'].plot.bar(ax=ax_div, color='#003087')
            ax_div.set_ylabel('Dividend Yield (%)')
            ax_div.set_title('Dividend Yield Comparison')
            st.pyplot(fig_div, use_container_width=True)

        with t3:
            st.header("Individual Semiconductor Company Analysis")
            existing = hist['Ticker'].unique()
            choice = st.selectbox("Select company to inspect:", existing)
            df_t = hist[hist['Ticker'] == choice].set_index('Date')
            fin_t = fin[fin['Ticker'] == choice]

            live_price = fetch_live_price(choice)
            if live_price:
                st.metric(f"Current Price ({choice})", f"${live_price}")

            st.subheader(f"Price History for {choice}")
            fig_candle = plot_candlestick(df_t, choice)
            st.plotly_chart(fig_candle, use_container_width=True)

            if not df_t.empty:
                change = (df_t['Close'].iloc[-1] - df_t['Close'].iloc[0]) / df_t['Close'].iloc[0] * 100
                st.metric("Change Since Start", f"{change:.2f}%")

            st.subheader(f"Financial Metrics for {choice}")
            if not fin_t.empty:
                metrics = fin_t[['PE_Ratio', 'Forward_PE', 'EPS', 'Market_Cap', 'Dividend_Yield', 
                                'PEG_Ratio', 'Debt_To_Equity', 'Revenue_Growth']].iloc[0]
                st.table(metrics)

            st.subheader(f"Recent News for {choice}")
            for _, row in news[news['Ticker'] == choice].head(5).iterrows():
                st.markdown(f"**{row['Date']}**: [{row['Headline']}]({row['URL']}) _(Sentiment: {row['Sentiment']:.2f})_")
                if row['Summary']:
                    with st.expander("Summary"):
                        st.write(row['Summary'])

        with t4:
            st.header("Educational Resources")
            st.subheader("Glossary")
            st.markdown("""
            - **P/E Ratio**: Price-to-Earnings ratio, measures stock price relative to earnings per share.
            - **EPS**: Earnings Per Share, company's profit divided by outstanding shares.
            - **Volatility**: Measure of stock price fluctuation, annualized using daily returns.
            - **Dividend Yield**: Annual dividend payment as a percentage of stock price.
            - **Moving Average (MA)**: Average stock price over a period (e.g., 50 or 200 days).
            """)
            st.subheader("Beginner Tips")
            st.markdown("""
            - Start with companies like TSMC or Intel for stability.
            - Use the watchlist to track stocks you're interested in.
            - Check news sentiment to gauge market perception.
            - Compare P/E ratios to assess if a stock is overvalued.
            """)
            st.subheader("Learn More")
            st.markdown("[Visit Investopedia for Investing Basics](https://www.investopedia.com/)")

    with col2:
        st.header("Latest News")
        for _, row in news.head(10).iterrows():
            st.markdown(f"""
            <div style="padding: 10px; margin-bottom: 10px; border-radius: 8px; background-color: #1e293b; color: #f1f5f9;">
                <strong>{row['Date']} - {row['Ticker']}</strong><br>
                <a href="{row['URL']}" target="_blank" style="color: #60a5fa; text-decoration: none; font-weight: bold;">{row['Headline']}</a><br>
                <small>Sentiment: {row['Sentiment']:.2f}</small>
            </div>
            """, unsafe_allow_html=True)

    # Ticker footer
    if not hist.empty:
        tickers = hist['Ticker'].unique()
        ticker_html = '<div class="ticker-footer">'
        for t in tickers:
            live_price = fetch_live_price(t)
            price_str = f"${live_price}" if live_price else "N/A"
            ticker_html += f'''
            <div class="ticker-item">
                {t}
                <span class="ticker-tooltip">{t}: {price_str}</span>
            </div>
            '''
        ticker_html += '</div>'
        st.markdown(ticker_html, unsafe_allow_html=True)

if __name__ == '__main__':
    main()