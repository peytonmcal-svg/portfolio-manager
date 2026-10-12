# Portfolio Manager: Project Spec

## About the builder
Mac is a finance student with no coding experience. Claude Code writes all the code.
- Explain what you did in plain, simple English (no jargon without a short definition).
- After every change, tell Mac exactly how to run and test it, step by step.
- Build one small feature at a time. Minimum viable version first, then improve.
- If something needs to be installed, give exact instructions for Windows.

## Goal
A desktop app (Windows + Mac) that tracks Mac's investment portfolio, analyzes value and dividend
stocks, and shows country/region exposure. Version 1 is for Mac's own account only. Version 2 will
add multiple portfolios for clients, so keep the code organized so that is possible later
(e.g., holdings belong to a "portfolio" record, not stored globally).

## Version 1 features
1. **Holdings tracker:** add/edit/delete holdings manually (ticker, shares, buy price, buy date).
2. **Live prices:** current price, market value, gain/loss ($ and %) per holding and in total.
3. **Allocation chart:** breakdown by holding and by sector.
4. **Performance:** portfolio value history chart, dividend income log, comparison vs. S&P 500 (SPY).
5. **E*TRADE sync:** READ-ONLY import of positions and balances via the E*TRADE API
   (OAuth 1.0a, individual key). Sandbox first, then production.
6. **Value/dividend scorecard:** for each holding: P/E, dividend yield, payout ratio, dividend growth.
7. **Screener:** filter stocks by P/E, yield, payout ratio, sector.
8. **Country/region exposure:** breakdown by country and region. ETFs are labeled by their main
   focus (no look-through).
9. **Packaging:** installable app for Windows and Mac.

## Not in version 1
Client accounts, CSV import, PDF reports, AI features (Claude API), returns in other currencies.

## Tech stack
- Python 3.12+
- PySide6 for the desktop window/UI
- SQLite for local storage (one database file in `data/`)
- yfinance for prices and fundamentals (free); pandas for calculations
- matplotlib embedded in PySide6 for charts
- E*TRADE API via OAuth 1.0a (read-only)
- PyInstaller for packaging; GitHub Actions to build the Mac version

## Rules (always follow)
- **E*TRADE is read-only.** Never write code that previews, places, changes, or cancels orders.
- **Secrets:** API keys and tokens go in a `.env` file only. Never commit, print, or log them.
- **Privacy:** all financial data stays on this computer. `data/` and `.env` are in `.gitignore`.
- **No advice:** the app shows metrics and filters; it never tells the user what to buy or sell.
- **Free data limits:** cache prices and fundamentals; refresh fundamentals at most once a day.
  If a data source fails, show the last saved value and a clear message instead of crashing.
- **Cross-platform:** use `pathlib` for file paths; nothing Windows-only.
- **Tests:** write simple tests for every financial calculation (returns, yield, allocation).
- **Git:** after each working change, make a commit with a clear message so we can roll back.
- **Progress:** when a step below is finished, check it off in this file.

## Roadmap and progress
### Phase 0: Setup
- [x] Python, Git, Claude Code confirmed working
- [x] Project structure, virtual environment, dependencies, Git repo, first commit
- [x] Blank app window opens
### Phase 1: Core tracker
- [x] Manual holdings entry saved to database
- [ ] Live prices and gain/loss table
- [ ] Allocation chart
### Phase 2: Performance
- [ ] Portfolio value history, dividend log, S&P 500 comparison
### Phase 3: E*TRADE sync
- [ ] Sandbox connection (read-only)
- [ ] Production connection (read-only)
### Phase 4: Value/dividend tools
- [ ] Scorecard for holdings
- [ ] Screener
### Phase 5: Country exposure
- [ ] Country and region breakdown
### Phase 6: Package
- [ ] Windows installer
- [ ] Mac build via GitHub Actions
