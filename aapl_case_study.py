#!/usr/bin/env python3
"""
Educational Case Study: Apple Inc. (AAPL) Stock Performance Analysis
Demonstration of financial data pipeline using simulated market data,
CSV/SQLite storage, SQL window functions, technical indicators, 
and visualization (for portfolio review / skill demonstration)

Note: Price data is simulated via Geometric Brownian Motion (no internet access).
All analysis is for educational purposes only.

Date: April 2026
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import sqlite3
import os
from datetime import datetime

# Configuration
sns.set_style('whitegrid')
plt.rcParams['figure.figsize'] = (12, 6)
plt.rcParams['font.size'] = 10
plt.rcParams['axes.titlesize'] = 14
plt.rcParams['axes.labelsize'] = 11

TICKER = 'AAPL'
START_DATE = '2023-01-01'
END_DATE = '2025-04-25'
DB_PATH = '/home/workdir/artifacts/finance_case_study.db'
CSV_PATH = '/home/workdir/artifacts/aapl_stock_data.csv'
PLOTS_DIR = '/home/workdir/artifacts/plots/'

def generate_mock_yfinance_data(start_date: str, end_date: str, ticker: str) -> pd.DataFrame:
    """
    Simulate realistic AAPL stock data as if downloaded via yfinance.download()
    Includes Open, High, Low, Close, Adj Close, Volume
    """
    dates = pd.date_range(start=start_date, end=end_date, freq='B')  # Business days only
    n = len(dates)
    
    np.random.seed(42)  # Reproducible results
    
    # Realistic parameters for AAPL (2023-2025 period)
    # ~0.09% daily drift (~25% annualized), ~1.6% daily vol (~25% ann. vol)
    daily_drift = 0.00092
    daily_vol = 0.0165
    
    returns = np.random.normal(daily_drift, daily_vol, n)
    close_prices = 128.0 * np.cumprod(1 + returns)  # Realistic start ~$128-130 in early 2023
    
    # Generate realistic OHLCV
    open_prices = close_prices * (1 + np.random.uniform(-0.004, 0.004, n))
    high_prices = np.maximum(open_prices, close_prices) * (1 + np.random.uniform(0.003, 0.022, n))
    low_prices = np.minimum(open_prices, close_prices) * (1 + np.random.uniform(-0.022, -0.003, n))
    
    # Volume: base + spike on high volatility days
    base_volume = np.random.randint(45_000_000, 95_000_000, n)
    volume = (base_volume * (1 + np.abs(returns) * 8)).astype(int)
    
    df = pd.DataFrame({
        'Date': dates,
        'Open': np.round(open_prices, 2),
        'High': np.round(high_prices, 2),
        'Low': np.round(low_prices, 2),
        'Close': np.round(close_prices, 2),
        'Adj Close': np.round(close_prices, 2),  # Simplified - no splits/dividends modeled
        'Volume': volume
    })
    
    # Ensure logical OHLC relationships
    df['High'] = df[['Open', 'Close', 'High']].max(axis=1)
    df['Low'] = df[['Open', 'Close', 'Low']].min(axis=1)
    
    df.set_index('Date', inplace=True)
    return df

def calculate_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute key technical indicators (MA, RSI, Bollinger, drawdown) and risk metrics."""
    df = df.copy()
    
    # Returns
    df['daily_return'] = df['Close'].pct_change()
    df['log_return'] = np.log(df['Close'] / df['Close'].shift(1))
    
    # Moving Averages (trend following)
    df['ma_20'] = df['Close'].rolling(window=20).mean()
    df['ma_50'] = df['Close'].rolling(window=50).mean()
    df['ma_200'] = df['Close'].rolling(window=200).mean()
    
    # Rolling Volatility (annualized)
    df['volatility_30d'] = df['daily_return'].rolling(window=30).std() * np.sqrt(252)
    
    # RSI (14-period) - momentum oscillator
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi_14'] = 100 - (100 / (1 + rs))
    
    # Bollinger Bands (20, 2)
    bb_std = df['Close'].rolling(window=20).std()
    df['bb_middle'] = df['ma_20']
    df['bb_upper'] = df['ma_20'] + (bb_std * 2)
    df['bb_lower'] = df['ma_20'] - (bb_std * 2)
    
    # Drawdown (for risk analysis)
    df['cum_max'] = df['Close'].cummax()
    df['drawdown'] = (df['Close'] - df['cum_max']) / df['cum_max']
    
    return df

def create_sql_database(df: pd.DataFrame, df_ind: pd.DataFrame, db_path: str):
    """Create SQLite database with two tables: raw prices + calculated variables."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Clean previous runs
    cursor.execute("DROP TABLE IF EXISTS stock_prices")
    cursor.execute("DROP TABLE IF EXISTS technical_indicators")
    
    # Table 1: Raw stock prices (as from yfinance)
    cursor.execute("""
        CREATE TABLE stock_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            adj_close REAL NOT NULL,
            volume INTEGER NOT NULL
        )
    """)
    
    # Insert raw data
    df_reset = df.reset_index()
    df_reset['Date'] = df_reset['Date'].dt.strftime('%Y-%m-%d')
    for _, row in df_reset.iterrows():
        cursor.execute("""
            INSERT INTO stock_prices (date, open, high, low, close, adj_close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            row['Date'], float(row['Open']), float(row['High']), float(row['Low']),
            float(row['Close']), float(row['Adj Close']), int(row['Volume'])
        ))
    
    # Table 2: Technical indicators & derived variables
    cursor.execute("""
        CREATE TABLE technical_indicators (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            daily_return REAL,
            log_return REAL,
            ma_20 REAL,
            ma_50 REAL,
            ma_200 REAL,
            volatility_30d REAL,
            rsi_14 REAL,
            bb_upper REAL,
            bb_middle REAL,
            bb_lower REAL,
            drawdown REAL
        )
    """)
    
    # Prepare indicators (replace NaN with NULL for SQLite)
    df_ind_reset = df_ind.reset_index()
    df_ind_reset = df_ind_reset.where(pd.notnull(df_ind_reset), None)
    df_ind_reset['Date'] = df_ind_reset['Date'].dt.strftime('%Y-%m-%d')
    
    for _, row in df_ind_reset.iterrows():
        cursor.execute("""
            INSERT INTO technical_indicators 
            (date, daily_return, log_return, ma_20, ma_50, ma_200, 
             volatility_30d, rsi_14, bb_upper, bb_middle, bb_lower, drawdown)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row['Date'],
            row['daily_return'], row['log_return'],
            row['ma_20'], row['ma_50'], row['ma_200'],
            row['volatility_30d'], row['rsi_14'],
            row['bb_upper'], row['bb_middle'], row['bb_lower'],
            row['drawdown']
        ))
    
    conn.commit()
    
    # Quick verification
    print("\n[SQL] Verification queries:")
    print("stock_prices sample:")
    print(pd.read_sql_query("SELECT * FROM stock_prices LIMIT 3", conn).to_string(index=False))
    print("\ntechnical_indicators sample (non-null MA):")
    print(pd.read_sql_query(
        "SELECT date, ROUND(daily_return*100,2) as ret_pct, ROUND(ma_50,2) as ma50, ROUND(rsi_14,1) as rsi FROM technical_indicators WHERE ma_50 IS NOT NULL LIMIT 3", 
        conn
    ).to_string(index=False))
    
    conn.close()
    print(f"\n[SQL] Database saved to: {db_path}")
    print("[SQL] See sql_analysis_tables.sql for additional pure-SQL analysis tables (standard window functions; syntax is compatible with BigQuery for demonstration)")

def generate_visualizations(df: pd.DataFrame, df_ind: pd.DataFrame, plots_dir: str, ticker: str):
    """Generate 6 educational visualizations for technical analysis demonstration."""
    os.makedirs(plots_dir, exist_ok=True)
    
    # 1. Price Trend + Moving Averages (core trend analysis)
    fig, ax = plt.subplots(figsize=(14, 7))
    ax.plot(df.index, df['Close'], label='Close Price', linewidth=1.8, color='#1f77b4')
    ax.plot(df.index, df_ind['ma_20'], label='20-Day MA', linewidth=1.2, color='#ff7f0e', alpha=0.85)
    ax.plot(df.index, df_ind['ma_50'], label='50-Day MA', linewidth=1.2, color='#2ca02c', alpha=0.85)
    ax.plot(df.index, df_ind['ma_200'], label='200-Day MA (Golden/Death Cross Ref)', linewidth=1.8, color='#d62728', alpha=0.9)
    ax.set_title(f'{ticker} Stock Price with Moving Averages\n(Jan 2023 – Apr 2025)', fontsize=15, fontweight='bold', pad=15)
    ax.set_xlabel('Date')
    ax.set_ylabel('Adjusted Close Price (USD)')
    ax.legend(loc='upper left', framealpha=0.95)
    ax.grid(True, alpha=0.25)
    plt.tight_layout()
    plt.savefig(f'{plots_dir}01_price_trend_ma.png', dpi=160, bbox_inches='tight')
    plt.close()
    
    # 2. Daily Returns Distribution (statistical view)
    fig, ax = plt.subplots(figsize=(11, 6))
    returns = df_ind['daily_return'].dropna() * 100
    sns.histplot(returns, bins=60, kde=True, color='#2ca02c', alpha=0.75, ax=ax, edgecolor='white')
    mean_ret = returns.mean()
    std_ret = returns.std()
    ax.axvline(mean_ret, color='#d62728', linestyle='--', linewidth=2, label=f'Mean: {mean_ret:.2f}%')
    ax.axvline(mean_ret + std_ret, color='#ff7f0e', linestyle=':', linewidth=1.5, label=f'+1σ: {mean_ret+std_ret:.2f}%')
    ax.axvline(mean_ret - std_ret, color='#ff7f0e', linestyle=':', linewidth=1.5, label=f'-1σ: {mean_ret-std_ret:.2f}%')
    ax.set_title(f'{ticker} Daily Returns Distribution\n(Normal-ish with fat tails typical of equities)', fontsize=14, fontweight='bold')
    ax.set_xlabel('Daily Return (%)')
    ax.set_ylabel('Frequency')
    ax.legend(loc='upper right')
    plt.tight_layout()
    plt.savefig(f'{plots_dir}02_returns_distribution.png', dpi=160, bbox_inches='tight')
    plt.close()
    
    # 3. Cumulative Returns (performance over time)
    cum_ret = (1 + df_ind['daily_return'].fillna(0)).cumprod() - 1
    fig, ax = plt.subplots(figsize=(13, 6))
    ax.plot(df.index, cum_ret * 100, color='#d62728', linewidth=2.2, label='Cumulative Return')
    ax.fill_between(df.index, cum_ret * 100, 0, where=(cum_ret >= 0), alpha=0.35, color='#2ca02c')
    ax.fill_between(df.index, cum_ret * 100, 0, where=(cum_ret < 0), alpha=0.35, color='#d62728')
    ax.axhline(0, color='black', linewidth=0.9, linestyle='-')
    ax.set_title(f'{ticker} Cumulative Total Return (%) — {START_DATE} to {END_DATE}', fontsize=14, fontweight='bold')
    ax.set_xlabel('Date')
    ax.set_ylabel('Cumulative Return (%)')
    ax.legend(loc='upper left')
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(f'{plots_dir}03_cumulative_returns.png', dpi=160, bbox_inches='tight')
    plt.close()
    
    # 4. Bollinger Bands (volatility & mean-reversion)
    fig, ax = plt.subplots(figsize=(14, 7))
    ax.plot(df.index, df['Close'], label='Close Price', color='black', linewidth=1.3)
    ax.plot(df.index, df_ind['bb_upper'], label='Upper Band (+2σ)', color='#9467bd', linestyle='--', alpha=0.75)
    ax.plot(df.index, df_ind['bb_middle'], label='Middle Band (20-MA)', color='#1f77b4', linewidth=1.5)
    ax.plot(df.index, df_ind['bb_lower'], label='Lower Band (-2σ)', color='#9467bd', linestyle='--', alpha=0.75)
    ax.fill_between(df.index, df_ind['bb_upper'], df_ind['bb_lower'], alpha=0.08, color='#1f77b4')
    ax.set_title(f'{ticker} Bollinger Bands (20-period, 2 std dev)\nVolatility Squeeze & Expansion Zones', fontsize=14, fontweight='bold')
    ax.set_xlabel('Date')
    ax.set_ylabel('Price (USD)')
    ax.legend(loc='upper left', fontsize=9)
    ax.grid(True, alpha=0.25)
    plt.tight_layout()
    plt.savefig(f'{plots_dir}04_bollinger_bands.png', dpi=160, bbox_inches='tight')
    plt.close()
    
    # 5. Price + RSI (momentum oscillator)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8.5), gridspec_kw={'height_ratios': [3.2, 1]})
    
    ax1.plot(df.index, df['Close'], color='#1f77b4', linewidth=1.6)
    ax1.set_ylabel('Price (USD)', fontsize=11)
    ax1.set_title(f'{ticker} Price Action & RSI(14) Momentum Indicator', fontsize=14, fontweight='bold', pad=10)
    ax1.grid(True, alpha=0.25)
    
    ax2.plot(df.index, df_ind['rsi_14'], color='#8c564b', linewidth=1.4)
    ax2.axhline(70, color='#d62728', linestyle='--', alpha=0.8, linewidth=1.2, label='Overbought (70)')
    ax2.axhline(30, color='#2ca02c', linestyle='--', alpha=0.8, linewidth=1.2, label='Oversold (30)')
    ax2.fill_between(df.index, 70, df_ind['rsi_14'].clip(upper=70), where=(df_ind['rsi_14'] > 70), alpha=0.35, color='#d62728')
    ax2.fill_between(df.index, 30, df_ind['rsi_14'].clip(lower=30), where=(df_ind['rsi_14'] < 30), alpha=0.35, color='#2ca02c')
    ax2.set_ylim(15, 85)
    ax2.set_ylabel('RSI (14)', fontsize=11)
    ax2.set_xlabel('Date')
    ax2.legend(loc='upper right', fontsize=9)
    ax2.grid(True, alpha=0.25)
    
    plt.tight_layout()
    plt.savefig(f'{plots_dir}05_price_rsi.png', dpi=160, bbox_inches='tight')
    plt.close()
    
    # 6. Underwater Drawdown Chart (risk visualization)
    fig, ax = plt.subplots(figsize=(13, 5))
    dd_pct = df_ind['drawdown'] * 100
    ax.fill_between(df.index, dd_pct, 0, color='#d62728', alpha=0.65)
    ax.plot(df.index, dd_pct, color='#8c0000', linewidth=1.2)
    ax.axhline(0, color='black', linewidth=1)
    ax.set_title(f'{ticker} Drawdown Profile (Peak-to-Trough Declines)', fontsize=14, fontweight='bold')
    ax.set_xlabel('Date')
    ax.set_ylabel('Drawdown from Peak (%)')
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(f'{plots_dir}06_drawdown.png', dpi=160, bbox_inches='tight')
    plt.close()
    
    print(f"\n[Visualizations] All 6 plots saved to {plots_dir}")

def main():
    print("=" * 70)
    print("AAPL STOCK EDUCATIONAL CASE STUDY - Technical Demonstration")
    print("=" * 70)
    
    # Step 1: "Download" data (mock yfinance)
    print("\n[1/6] Generating mock yfinance data (realistic AAPL 2023-2025)...")
    df = generate_mock_yfinance_data(START_DATE, END_DATE, TICKER)
    print(f"       → {len(df)} trading days | Close range: ${df['Close'].min():.2f} – ${df['Close'].max():.2f}")
    
    # Step 2: CSV Export
    print("\n[2/6] Exporting to CSV...")
    df.to_csv(CSV_PATH, index=True, index_label='Date')
    print(f"       → Saved: {CSV_PATH}")
    
    # Step 3: Calculate indicators
    print("\n[3/6] Computing technical indicators & risk variables...")
    df_ind = calculate_technical_indicators(df)
    
    # Step 4: SQL tables
    print("\n[4/6] Creating SQLite database with raw + derived tables...")
    create_sql_database(df, df_ind, DB_PATH)
    
    # Step 5: Analysis summary
    print("\n[5/6] Running quantitative analysis...")
    total_ret = (df['Close'].iloc[-1] / df['Close'].iloc[0] - 1) * 100
    ann_ret = ((df['Close'].iloc[-1] / df['Close'].iloc[0]) ** (252 / len(df)) - 1) * 100
    ann_vol = df_ind['daily_return'].std() * np.sqrt(252) * 100
    sharpe = (ann_ret / 100 - 0.02) / (ann_vol / 100)
    max_dd = df_ind['drawdown'].min() * 100
    avg_vol_m = df['Volume'].mean() / 1_000_000
    
    print(f"""
    ╔══════════════════════════════════════════════════════════════════╗
    ║                    KEY PERFORMANCE METRICS                       ║
    ╠══════════════════════════════════════════════════════════════════╣
    ║  Period: {START_DATE} to {END_DATE} ({len(df)} trading days)     ║
    ║  Total Return:          {total_ret:>8.2f}%                              ║
    ║  Annualized Return:     {ann_ret:>8.2f}%                              ║
    ║  Annualized Volatility: {ann_vol:>8.2f}%                              ║
    ║  Sharpe Ratio (rf=2%):  {sharpe:>8.2f}                               ║
    ║  Maximum Drawdown:      {max_dd:>8.2f}%                              ║
    ║  Avg Daily Volume:      {avg_vol_m:>8.1f}M shares                         ║
    ╚══════════════════════════════════════════════════════════════════╝
    """)
    
    last_row = df_ind.iloc[-1]
    print(f"    Latest Close ({last_row.name.strftime('%Y-%m-%d')}): ${last_row['Close']:.2f}")
    print(f"    50-MA: ${last_row['ma_50']:.2f}  |  200-MA: ${last_row['ma_200']:.2f}")
    print(f"    RSI(14): {last_row['rsi_14']:.1f}  |  30d Ann. Vol: {last_row['volatility_30d']*100:.1f}%")
    
    # Step 6: Visualizations
    print("\n[6/6] Generating intermediate visualizations...")
    generate_visualizations(df, df_ind, PLOTS_DIR, TICKER)
    
    print("\n" + "=" * 70)
    print("EDUCATIONAL CASE STUDY COMPLETE!")
    print(f"  • CSV:           {CSV_PATH}")
    print(f"  • SQLite DB:     {DB_PATH} (2 tables: stock_prices + technical_indicators)")
    print(f"  • Visualizations: {PLOTS_DIR} (6 PNG files)")
    print("=" * 70)

if __name__ == "__main__":
    main()