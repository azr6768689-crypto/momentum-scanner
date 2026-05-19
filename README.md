# Momentum Decision-Support System

A professional, institutional-style **LONG momentum** decision-support system
for US stocks and liquid ETFs. Built for short-to-medium swing trades
(1–10 trading days).

**What this system is:**

- A daily ranked watchlist generator
- A scoring engine for momentum setups (0–100)
- A structured trade-plan builder: entry trigger, stop, targets, risk/reward,
  invalidation, and "what to wait for"

**What this system is *not*:**

- It is **not** an auto-trading bot
- It **does not** place real orders
- It **never** says "buy now" — it says "watch above X, trigger if Y,
  invalidated if Z"
- It does **not** promise 65–70% win rates. See the *Honest Expectations*
  section below.

---

## Quick Start (macOS)

> These steps assume you're on a Mac and comfortable opening Terminal.
> Each command is meant to be copy-pasted into Terminal one line at a time.

### 1. Install Homebrew (if you don't have it)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### 2. Install Python 3.11 and git

```bash
brew install python@3.11 git
```

### 3. Clone or copy the project, then enter the folder

```bash
cd ~/momentum_system
```

### 4. Create a virtual environment and activate it

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

After activation your prompt should show `(.venv)` at the front.

### 5. Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 6. Set up your `.env` file

```bash
cp .env.example .env
```

Open `.env` in a text editor. For your **first run, leave everything as-is**.
The default `DATA_PROVIDER=demo` lets you sanity-check the system without
any API key.

When you're ready for real data, get a free key at
[tiingo.com](https://www.tiingo.com) and paste it into `TIINGO_API_KEY`,
then change `DATA_PROVIDER=tiingo`.

### 7. Run the daily scan (will be available after Group 7)

```bash
python scripts/run_daily.py
```

### 8. Open the dashboard (will be available after Group 9)

```bash
streamlit run dashboard/app.py
```

---

## Folder Structure

```
momentum_system/
├── config/             # all tunable parameters (YAML)
├── data/
│   ├── cache/          # local market-data cache (Parquet)
│   ├── universe/       # ticker lists
│   └── reports/        # daily CSV outputs
├── logs/               # runtime logs
├── src/
│   ├── data/           # data provider adapters (Tiingo, Polygon, Alpaca)
│   ├── analytics/      # indicators, patterns, market regime
│   ├── strategies/     # 14 strategy modules (6 active in Phase 1)
│   ├── scanners/       # 3 scanner modes
│   ├── scoring/        # score engine + status classifier
│   ├── reporting/      # CSV writer, summary builder
│   ├── backtest/       # Phase 4
│   ├── paper_tracking/ # Phase 3
│   └── pipeline.py     # main orchestrator
├── dashboard/          # Streamlit app
├── scripts/            # CLI entry points
└── tests/              # unit tests
```

---

## Configuration

Every tunable parameter lives in `config/`:

| File | Purpose |
|---|---|
| `settings.yaml` | data provider, rate limits, filter thresholds, scoring weights |
| `universe.yaml` | which tickers to scan |
| `strategies.yaml` | per-strategy parameters |

Edit YAML files in any text editor; no code changes needed for tuning.

---

## Data Providers

The data layer is **provider-agnostic**. Phase 1 supports:

- **demo** — uses bundled sample data; no API key needed.
- **tiingo** — Phase 1 recommended (clean daily EOD data, ~$10/mo paid tier).
- **polygon** — Phase 2 recommended for intraday (~$29/mo Stocks Starter).
- **alpaca** — alternative; useful if you'll later use Alpaca for paper trading.

Switch provider by editing `DATA_PROVIDER` in `.env` and adding the
appropriate key. The rest of the system requires no changes.

---

## Phases (Roadmap)

| Phase | What it adds | Status |
|---|---|---|
| 1 | Daily scanner, 6 strategies, scoring, Streamlit dashboard, CSV report | **building** |
| 2 | Intraday data, 6 more strategies (ORB, VWAP, gap-and-go, etc.) | scaffolded |
| 3 | Paper signal tracking with daily logs | scaffolded |
| 4 | Backtesting + performance reports per strategy | scaffolded |
| 5 | Parameter optimization, walk-forward, more strategies | planned |
| 6 | Market-regime filtering, advanced validation | planned |
| 7 | (Only after enough proof) broker integration — manual, never auto | future |

---

## Honest Expectations

Plain truth, because you asked for it:

- A **65–70% win rate** on breakout/momentum setups is **not realistic** out
  of sample after slippage and fees. Numbers like that almost always come
  from curve-fitting. Real, properly-tested momentum systems on US equities
  typically land at **45–58% win rate with profit factor 1.3–1.8** and
  per-trade expectancy of **0.15R–0.35R**.

- A higher win rate is not the goal — **expectancy is the goal**. A 45% win
  rate with average winners 3× larger than average losers is materially
  better than a 65% win rate with 1:1 payoffs.

- This is a **decision-support tool**, not a prediction engine. It surfaces,
  ranks, and frames opportunities. Discretion to take or skip a trade is
  yours.

- Live results are typically **20–40% worse** than backtest results. Plan
  for it.

- Long-momentum systems work in trending markets and underperform in
  choppy/down markets. Market-regime filtering is a defense, not a cure.

---

## Safety Rules

- API keys live in `.env` only — **never** in code, **never** committed to git.
- Rate limits are enforced for every external provider.
- Data is cached locally to avoid hammering APIs.
- The system never places trades. Phase 7 is the earliest broker integration
  is considered, and even then only after substantial paper-tracking proof.

---

## Support

This is a personal research system. There is no support contract. The code
is documented to help a non-daily-programmer maintain it. When in doubt,
read the comments in the relevant file in `src/`.
