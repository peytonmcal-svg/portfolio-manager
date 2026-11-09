"""Read holdings from a CSV file with columns ticker, shares, buy_price, buy_date."""
import csv
from datetime import datetime
import io
from pathlib import Path

from portfolio_app.db.holdings import NewHolding, validate_holding

REQUIRED_COLUMNS = ("ticker", "shares", "buy_price")
EXPECTED_COLUMNS = "ticker, shares, buy_price, buy_date"


class CsvImportError(ValueError):
    """The file can't be imported; ``problems`` lists every reason found."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


def read_holdings_csv(path: Path) -> list[NewHolding]:
    """Read every row, or raise CsvImportError without returning any.

    Column names ignore case and spaces. ``buy_date`` may be blank or left
    out (the holding is marked "date missing"). Numbers may include "$" and
    thousands commas; dates may be YYYY-MM-DD or M/D/YYYY.
    """
    try:
        # utf-8-sig also handles the hidden marker Excel adds to CSV files.
        text = Path(path).read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as error:
        raise CsvImportError(["This doesn't look like a CSV text file."]) from error

    reader = csv.DictReader(io.StringIO(text))
    columns = {_column_key(name): name for name in reader.fieldnames or []}
    missing = [name for name in REQUIRED_COLUMNS if name not in columns]
    if missing:
        raise CsvImportError(
            [f"Missing column(s): {', '.join(missing)}. Expected: {EXPECTED_COLUMNS}."]
        )

    holdings: list[NewHolding] = []
    problems: list[str] = []
    for row in reader:
        values = {
            key: (row.get(original) or "").strip() for key, original in columns.items()
        }
        if not any(values.values()):
            continue  # skip blank lines
        try:
            holdings.append(
                NewHolding(
                    *validate_holding(
                        values["ticker"],
                        _number(values["shares"], "Shares"),
                        _number(values["buy_price"], "Buy price"),
                        _iso_date(values.get("buy_date", "")),
                    )
                )
            )
        except ValueError as error:
            problems.append(f"Line {reader.line_num}: {error}")

    if problems:
        raise CsvImportError(problems)
    if not holdings:
        raise CsvImportError(["The file has no holdings in it."])
    return holdings


def _column_key(name: str | None) -> str:
    return (name or "").strip().lower().replace(" ", "_")


def _number(text: str, label: str) -> float:
    cleaned = text.replace("$", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        raise ValueError(f"{label} must be a number (found “{text}”).") from None


def _iso_date(text: str) -> str | None:
    if not text:
        return None
    for date_format in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, date_format).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Buy date “{text}” isn't a date (use YYYY-MM-DD).")
