# Portfolio Manager

A desktop app to track an investment portfolio. All data stays on this computer.

## First-time setup (Windows)
Open a terminal in this folder (VS Code: Terminal > New Terminal), then:
```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -e .
```

## Run the app
```
.venv\Scripts\activate
python -m portfolio_app
```

## Manage holdings
Enter a ticker, number of shares, buy price, and buy date, then choose **Add holding**.
Select a row to change it or delete it. Holdings are saved in `data/portfolio.db`
on this computer.

Choose **Refresh prices** to retrieve the latest available prices from Yahoo Finance.
Market value and gain/loss are calculated for each holding and totaled at the bottom.
Prices are cached on this computer; when a refresh fails, saved prices remain visible
and holdings without a saved price are excluded from the totals.

## Run the tests
```
.venv\Scripts\activate
pytest
```
