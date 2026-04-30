-- =====================================================
-- SQL Analysis Tables for AAPL Case Study
-- Calculations performed entirely in SQL using window functions
-- =====================================================

-- 1. Daily Returns Table (simple LAG for previous close)
DROP TABLE IF EXISTS daily_returns;
CREATE TABLE daily_returns (
    date TEXT PRIMARY KEY,
    close REAL,
    prev_close REAL,
    daily_return REAL,
    log_return REAL
);

INSERT INTO daily_returns
SELECT 
    date,
    close,
    LAG(close, 1) OVER (ORDER BY date) AS prev_close,
    CASE 
        WHEN LAG(close, 1) OVER (ORDER BY date) IS NOT NULL 
        THEN (close - LAG(close, 1) OVER (ORDER BY date)) / LAG(close, 1) OVER (ORDER BY date)
        ELSE NULL 
    END AS daily_return,
    CASE 
        WHEN LAG(close, 1) OVER (ORDER BY date) IS NOT NULL 
        THEN LOG(close / LAG(close, 1) OVER (ORDER BY date))
        ELSE NULL 
    END AS log_return
FROM stock_prices;

-- 2. Moving Averages & Bollinger Bands Foundation (window functions)
-- Note: Full Bollinger requires stddev which SQLite doesn't have natively in window context.
-- We create the base and let Python fill advanced indicators if needed.
DROP TABLE IF EXISTS moving_averages;
CREATE TABLE moving_averages (
    date TEXT PRIMARY KEY,
    close REAL,
    ma_20 REAL,
    ma_50 REAL,
    ma_200 REAL,
    bb_middle REAL,
    bb_upper REAL,
    bb_lower REAL
);

INSERT INTO moving_averages
SELECT 
    date,
    close,
    AVG(close) OVER (ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS ma_20,
    AVG(close) OVER (ORDER BY date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW) AS ma_50,
    AVG(close) OVER (ORDER BY date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) AS ma_200,
    AVG(close) OVER (ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS bb_middle,
    NULL AS bb_upper,   -- Placeholder - calculated in Python for precision
    NULL AS bb_lower
FROM stock_prices;

-- 3. Drawdown Analysis Table (requires running maximum - possible with window + subquery)
DROP TABLE IF EXISTS drawdown_analysis;
CREATE TABLE drawdown_analysis (
    date TEXT PRIMARY KEY,
    close REAL,
    running_max REAL,
    drawdown REAL
);

INSERT INTO drawdown_analysis
SELECT 
    date,
    close,
    MAX(close) OVER (ORDER BY date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_max,
    (close - MAX(close) OVER (ORDER BY date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)) / 
        MAX(close) OVER (ORDER BY date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS drawdown
FROM stock_prices;

-- 4. Yearly Performance Summary (GROUP BY + aggregates)
DROP TABLE IF EXISTS yearly_performance;
CREATE TABLE yearly_performance (
    year TEXT PRIMARY KEY,
    start_close REAL,
    end_close REAL,
    total_return REAL,
    avg_daily_vol REAL,
    max_drawdown REAL,
    trading_days INTEGER
);

INSERT INTO yearly_performance
SELECT 
    strftime('%Y', date) AS year,
    (SELECT close FROM stock_prices s2 WHERE strftime('%Y', s2.date) = strftime('%Y', s1.date) ORDER BY s2.date LIMIT 1) AS start_close,
    (SELECT close FROM stock_prices s3 WHERE strftime('%Y', s3.date) = strftime('%Y', s1.date) ORDER BY s3.date DESC LIMIT 1) AS end_close,
    ((SELECT close FROM stock_prices s3 WHERE strftime('%Y', s3.date) = strftime('%Y', s1.date) ORDER BY s3.date DESC LIMIT 1) - 
     (SELECT close FROM stock_prices s2 WHERE strftime('%Y', s2.date) = strftime('%Y', s1.date) ORDER BY s2.date LIMIT 1)) / 
     (SELECT close FROM stock_prices s2 WHERE strftime('%Y', s2.date) = strftime('%Y', s1.date) ORDER BY s2.date LIMIT 1) AS total_return,
    AVG(volume) / 1000000 AS avg_daily_vol,
    MIN((close - MAX(close) OVER (PARTITION BY strftime('%Y', date) ORDER BY date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)) / 
        MAX(close) OVER (PARTITION BY strftime('%Y', date) ORDER BY date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)) AS max_drawdown,
    COUNT(*) AS trading_days
FROM stock_prices s1
GROUP BY strftime('%Y', date);

-- 5. Technical Signals Summary (example of SQL-detected events)
DROP TABLE IF EXISTS technical_signals;
CREATE TABLE technical_signals (
    signal_date TEXT,
    signal_type TEXT,
    close_price REAL,
    description TEXT
);

-- Golden Cross detection (50-day MA crosses above 200-day MA)
INSERT INTO technical_signals
SELECT 
    m1.date,
    'Golden Cross' AS signal_type,
    m1.close,
    '50-day MA crossed above 200-day MA - Bullish signal' AS description
FROM moving_averages m1
JOIN moving_averages m2 ON m1.date = m2.date
WHERE m1.ma_50 > m1.ma_200 
  AND (SELECT ma_50 FROM moving_averages WHERE date < m1.date ORDER BY date DESC LIMIT 1) <= 
      (SELECT ma_200 FROM moving_averages WHERE date < m1.date ORDER BY date DESC LIMIT 1)
  AND m1.ma_50 IS NOT NULL AND m1.ma_200 IS NOT NULL;

-- Death Cross (opposite)
INSERT INTO technical_signals
SELECT 
    m1.date,
    'Death Cross' AS signal_type,
    m1.close,
    '50-day MA crossed below 200-day MA - Bearish signal' AS description
FROM moving_averages m1
JOIN moving_averages m2 ON m1.date = m2.date
WHERE m1.ma_50 < m1.ma_200 
  AND (SELECT ma_50 FROM moving_averages WHERE date < m1.date ORDER BY date DESC LIMIT 1) >= 
      (SELECT ma_200 FROM moving_averages WHERE date < m1.date ORDER BY date DESC LIMIT 1)
  AND m1.ma_50 IS NOT NULL AND m1.ma_200 IS NOT NULL;

-- 6. RSI-ready table (base for further Python or advanced SQL)
-- Note: Full RSI requires iterative calculation; here we prepare the delta/gain/loss foundation
DROP TABLE IF EXISTS rsi_base;
CREATE TABLE rsi_base (
    date TEXT PRIMARY KEY,
    close REAL,
    price_change REAL,
    gain REAL,
    loss REAL
);

INSERT INTO rsi_base
SELECT 
    date,
    close,
    close - LAG(close, 1) OVER (ORDER BY date) AS price_change,
    MAX(0, close - LAG(close, 1) OVER (ORDER BY date)) AS gain,
    MAX(0, LAG(close, 1) OVER (ORDER BY date) - close) AS loss
FROM stock_prices;

-- =====================================================
-- Example Analysis Queries (run these after creation)
-- =====================================================

-- Query 1: Latest indicators
-- SELECT * FROM moving_averages ORDER BY date DESC LIMIT 5;

-- Query 2: Oversold periods (would join with RSI if computed)
-- SELECT date, close, daily_return FROM daily_returns WHERE daily_return < -0.03 ORDER BY date;

-- Query 3: Best performing years
-- SELECT year, ROUND(total_return * 100, 2) || '%' as return_pct, trading_days FROM yearly_performance ORDER BY total_return DESC;

-- Query 4: Bullish signals count
-- SELECT signal_type, COUNT(*) as occurrences FROM technical_signals GROUP BY signal_type;