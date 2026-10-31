"""
fetch_menus.py
Pulls menu data from Nutrislice for all schools/mealtypes defined in
menu-list.csv and merges it into one rollup JSON file per school/menutype
covering all available history.

Nutrislice's API is queried by week regardless of how we store results, so
there's no need to bucket output by month: "monthly" PDF/HTML views are just
a filter over this rollup at render time. Storing one rollup per feed also
means each Sunday-anchored week is fetched exactly once for the whole run,
instead of being re-fetched at every month boundary it touches.

Default mode: refreshes a rolling window — 1 month back, current month, 1
month ahead (matches the daily workflow). Pass --back/--ahead for a wider
backfill, or --year/--month to target a single month. A fetch only touches
the date range requested; everything else in the rollup is left as-is.

Output: data/{menutype}-{school}.json
"""

import argparse
import calendar
import csv
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SchoolMenuBot/1.0)",
    "Accept": "application/json",
}


# ── Date helpers ─────────────────────────────────────────────────────────

def add_months(d: datetime, delta: int) -> datetime:
    month = d.month - 1 + delta
    year = d.year + month // 12
    month = month % 12 + 1
    return datetime(year, month, 1)


def last_day_of_month(d: datetime) -> datetime:
    return datetime(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def compute_range(center: datetime, months_back: int, months_ahead: int) -> tuple[datetime, datetime]:
    start = add_months(center, -months_back)
    end = last_day_of_month(add_months(center, months_ahead))
    return start, end


def sundays_covering(start: datetime, end: datetime) -> list[datetime]:
    """Every Sunday whose week (Sun-Sat) touches [start, end], each exactly once."""
    days_to_sunday = (6 - start.weekday()) % 7
    first_sunday = start + timedelta(days=days_to_sunday)
    sunday_before = first_sunday - timedelta(days=7)

    sundays = [sunday_before]
    current = first_sunday
    while current <= end:
        sundays.append(current)
        current += timedelta(days=7)
    return sundays


# ── Fetching ─────────────────────────────────────────────────────────────

def parse_sections(entries: list[dict]) -> list[dict]:
    """Group a day's menu_items under Nutrislice's station headers (e.g.
    "Homestyle", "Fan Favorite"). Each header row is a text-only entry with
    is_section_title/is_station_header set; the food rows after it belong
    to it until the next header. Items before any header get title None.
    Item names are de-duplicated across the whole day, preserving order."""
    sections: list[dict] = []
    seen: set[str] = set()
    for entry in entries:
        if entry.get("is_section_title") or entry.get("is_station_header"):
            title = (entry.get("text") or "").strip()
            if title:
                sections.append({"title": title, "items": []})
            continue
        food = entry.get("food")
        if not (food and food.get("name")):
            continue
        name = food["name"].strip()
        if not name or name.lower() == "none" or name in seen:
            continue
        seen.add(name)
        if not sections:
            sections.append({"title": None, "items": []})
        sections[-1]["items"].append(name)
    return [s for s in sections if s["items"]]


def fetch_week(api_url: str, sunday: datetime) -> list[dict]:
    """Fetch one week of menu data starting on sunday. Returns list of day dicts."""
    url = f"{api_url}/{sunday.strftime('%Y/%m/%d')}/"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"    ⚠ Failed {url}: {e}")
        return []

    days = []
    for day in resp.json().get("days", []):
        date_str = day.get("date", "")
        sections = parse_sections(day.get("menu_items", []))
        items = [item for section in sections for item in section["items"]]

        if items:
            days.append({"date": date_str, "items": items, "sections": sections})
        else:
            print(f"    – No items for {date_str}")

    return days


def fetch_range(api_url: str, start: datetime, end: datetime) -> dict[str, dict]:
    """Fetch every week touching [start, end], each Sunday hit exactly once."""
    sundays = sundays_covering(start, end)
    print(f"    {len(sundays)} weeks to fetch ({start.date()} → {end.date()})")

    fetched: dict[str, dict] = {}
    for sunday in sundays:
        for day in fetch_week(api_url, sunday):
            fetched[day["date"]] = day
        time.sleep(0.8)  # be polite to Nutrislice

    return fetched


# ── Rollup storage ───────────────────────────────────────────────────────

def rollup_path(school: str, menutype: str) -> Path:
    return DATA_DIR / f"{menutype}-{school}.json"


def load_rollup_days(school: str, menutype: str) -> dict[str, dict]:
    path = rollup_path(school, menutype)
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    return {d["date"]: d for d in data.get("days", [])}


def save_rollup(school: str, display_name: str, menutype: str, days: dict[str, dict]) -> Path:
    payload = {
        "school":       school,
        "display_name": display_name,
        "menutype":     menutype,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "days":         [days[d] for d in sorted(days)],
    }
    path = rollup_path(school, menutype)
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"    ✓ Saved {path.name} ({len(days)} days total)")
    return path


# ── Orchestration ────────────────────────────────────────────────────────

def process_school(school: str, display_name: str, menutype: str,
                    api_url: str, start: datetime, end: datetime) -> None:
    print(f"\n{'─'*60}")
    print(f"  {display_name} / {menutype}")
    print(f"{'─'*60}")

    fetched = fetch_range(api_url, start, end)
    existing = load_rollup_days(school, menutype)
    existing.update(fetched)  # freshly fetched range wins on overlap
    save_rollup(school, display_name, menutype, existing)


def process_all(input_csv: Path, start: datetime, end: datetime) -> None:
    with open(input_csv, newline="") as f:
        rows = list(csv.DictReader(f))

    print(f"\n🗓  Fetching {start.date()} → {end.date()} for {len(rows)} feeds\n")

    for row in rows:
        process_school(
            school       = row["school"].strip(),
            display_name = row["display_name"].strip(),
            menutype     = row["menutype"].strip(),
            api_url      = row["api"].strip(),
            start        = start,
            end          = end,
        )


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Nutrislice menu data into rollup files")
    parser.add_argument("--year",  type=int, help="Fetch a single year (requires --month)")
    parser.add_argument("--month", type=int, help="Fetch a single month 1-12 (requires --year)")
    parser.add_argument("--back",  type=int, default=1,
                        help="Months to look back from today (default: 1)")
    parser.add_argument("--ahead", type=int, default=1,
                        help="Months to look ahead from today (default: 1)")
    args = parser.parse_args()

    csv_path = Path(__file__).parent / "menu-list.csv"

    if args.year and args.month:
        center = datetime(args.year, args.month, 1)
        start, end = center, last_day_of_month(center)
        print(f"Single-month mode: {args.year}-{args.month:02d}")
    else:
        today = datetime.today()
        start, end = compute_range(today, months_back=args.back, months_ahead=args.ahead)
        print(f"Rolling window mode: {args.back} back → {args.ahead} ahead "
              f"({start.date()} → {end.date()})")

    process_all(csv_path, start, end)
    print("\n✅ Done.")


if __name__ == "__main__":
    main()
