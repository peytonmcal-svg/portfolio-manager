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

## Run the tests
```
.venv\Scripts\activate
pytest
```
