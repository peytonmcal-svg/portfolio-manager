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

## Run the tests
```
.venv\Scripts\activate
pytest
```
