"""
generate_pdf.py
Generates printable monthly menu calendar PDFs from the JSON data files, in
the newsletter layout used by the district's previous Nutrislice PDFs:
a header banner, a left info sidebar (director contact, "what makes a meal",
a la carte options, fruit/veg choices, prices, USDA notice), and the Mon-Fri
grid on the right.

Sidebar copy comes from menu_content.py — edit that file when prices or
option lists change. Banner images are optional; see menu_content.py's
docstring for the expected file paths.

Output: site/pdfs/{year}-{month:02d}-{menutype}-{school}.pdf
"""

import calendar
import json
from datetime import date, datetime
from pathlib import Path

from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth

from menu_content import get_content, DIRECTOR, USDA_NOTICE

# ---------------------------------------------------------------------------
# Brand colors — built around the school color, #00328f. White page
# background throughout (this PDF is meant to print on plain white paper).
# ---------------------------------------------------------------------------
SCHOOL_BLUE = colors.HexColor("#00328f")
NAVY        = SCHOOL_BLUE
INK         = colors.HexColor("#222222")
MUTED       = colors.HexColor("#555555")
WHITE       = colors.white
BORDER      = colors.HexColor("#c7d0e6")
GRID_HEAD   = SCHOOL_BLUE

# Pastel sidebar box backgrounds + a matching darker heading color for each,
# following the district's reference designs — the heading color always
# matches the hue of its own box (blue heading on the blue box, red heading
# on the pink box, etc.), not the box's semantic content.
BOX_COLORS = {
    "blue":   colors.HexColor("#d9e0ee"),
    "pink":   colors.HexColor("#fbdbdb"),
    "tan":    colors.HexColor("#fdf1cf"),
    "green":  colors.HexColor("#dcefdc"),
    "purple": colors.HexColor("#e3ddf5"),
    "gray":   colors.HexColor("#e6e6e6"),
}
HEAD_COLORS = {
    "blue":   SCHOOL_BLUE,
    "pink":   colors.HexColor("#a33333"),
    "tan":    SCHOOL_BLUE,
    "green":  colors.HexColor("#1f6b3a"),
    "purple": colors.HexColor("#4a3f8a"),
}

# ---------------------------------------------------------------------------
# Layout constants  (landscape letter = 11 × 8.5 in)
# ---------------------------------------------------------------------------
PAGE_W, PAGE_H = landscape(letter)
MARGIN      = 0.4 * inch

HEADER_H    = 1.15 * inch
SIDEBAR_W   = 2.55 * inch
GAP         = 0.16 * inch

GRID_X      = MARGIN + SIDEBAR_W + GAP
GRID_TOP    = PAGE_H - MARGIN - HEADER_H
GRID_BOT    = MARGIN
GRID_H      = GRID_TOP - GRID_BOT
GRID_W      = PAGE_W - MARGIN - GRID_X

DAYS        = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
NUM_COLS    = 5
COL_W       = GRID_W / NUM_COLS

DATA_DIR    = Path(__file__).parent.parent / "data"
ASSETS_DIR  = Path(__file__).parent.parent / "assets" / "images"
# PDFs live under site/ so GitHub Pages actually publishes them (site/ is the
# only path uploaded by the Pages deploy workflow).
PDF_DIR     = Path(__file__).parent.parent / "site" / "pdfs"
PDF_DIR.mkdir(parents=True, exist_ok=True)

MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_rollup(school: str, menutype: str) -> dict | None:
    path = DATA_DIR / f"{menutype}-{school}.json"
    if not path.exists():
        print(f"  ⚠ Missing rollup file: {path.name}")
        return None
    with open(path) as f:
        return json.load(f)


def build_week_grid(data: dict, year: int, month: int) -> list[list]:
    """
    Returns a list of weeks; each week is a list of 5 slots (Mon–Fri).
    Each slot is (day_num | None, sections), where sections is a list of
    {"title": str | None, "items": [str, ...]} — Nutrislice's station
    groups like "Homestyle" / "Fan Favorite". Older rollup days saved
    before sections were captured fall back to one untitled section.
    """
    items_by_date: dict[str, list[dict]] = {}
    for day in data.get("days", []):
        items_by_date[day["date"]] = day.get("sections") or [{"title": None, "items": day["items"]}]

    first = date(year, month, 1)
    last  = date(year, month, calendar.monthrange(year, month)[1])

    week_start = first - __import__('datetime').timedelta(days=first.weekday())

    weeks = []
    current = week_start
    while current <= last:
        week = []
        for i in range(5):
            d = current + __import__('datetime').timedelta(days=i)
            key = d.strftime("%Y-%m-%d")
            if d.month == month:
                week.append((d.day, items_by_date.get(key, [])))
            else:
                week.append((None, []))
        weeks.append(week)
        current += __import__('datetime').timedelta(days=7)

    return weeks


def wrap_text_lines(text: str, max_chars: int) -> list[str]:
    """Simple word-wrap into lines of at most max_chars."""
    words = text.split()
    lines, current = [], ""
    for w in words:
        if current and len(current) + 1 + len(w) > max_chars:
            lines.append(current)
            current = w
        else:
            current = (current + " " + w).strip() if current else w
    if current:
        lines.append(current)
    return lines


def load_image(path: Path) -> ImageReader | None:
    if not path.exists():
        return None
    try:
        return ImageReader(str(path))
    except Exception as e:
        print(f"  ⚠ Could not load image {path.name}: {e}")
        return None


# ---------------------------------------------------------------------------
# Header banner
# ---------------------------------------------------------------------------

def draw_header(c: canvas.Canvas, school: str, menutype: str, year: int, month: int,
                 banner_title: str):
    top = PAGE_H - MARGIN
    left = MARGIN
    dx = PAGE_W - MARGIN

    # School name / meal type / month (left side)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(left, top - 16, banner_title)
    title_w = c.stringWidth(banner_title, "Helvetica-Bold", 15)

    month_line = f"{menutype.upper()} - {MONTH_NAMES[month].upper()} {year}"
    c.setFont("Helvetica-Bold", 22)
    c.drawString(left, top - 38, month_line)
    month_w = c.stringWidth(month_line, "Helvetica-Bold", 22)

    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(colors.HexColor("#c00000"))
    subject = "MENUS SUBJECT TO CHANGE"
    c.drawString(left, top - 53, subject)
    subject_w = c.stringWidth(subject, "Helvetica-Bold", 10)
    c.setLineWidth(0.75)
    c.line(left, top - 55, left + subject_w, top - 55)

    left_block_w = max(title_w, month_w, subject_w)

    # Director contact block (top-right), logo beside it.
    logo_img = load_image(ASSETS_DIR / "the-nutrition-group.png")
    logo_w = logo_h = 0.42 * inch
    text_right = dx
    if logo_img is not None:
        try:
            text_right = dx - logo_w - 6
            c.drawImage(logo_img, dx - logo_w, top - 33 - logo_h / 2, width=logo_w, height=logo_h,
                        preserveAspectRatio=True, anchor='c', mask='auto')
        except Exception as e:
            print(f"  ⚠ Could not draw logo: {e}")

    director_lines = [
        ("Food Service Director:", "Helvetica-Bold", 7),
        (DIRECTOR["name"], "Helvetica-Bold", 7.5),
        (DIRECTOR["email"], "Helvetica", 7),
        (DIRECTOR["phone"], "Helvetica", 7),
    ]
    right_block_w = max(c.stringWidth(t, f, s) for t, f, s in director_lines)

    # Banner photo (optional) — sized to its own aspect ratio (never
    # stretched/distorted) and centered in the empty gap between the left
    # text block and the right director/logo block, so it never overlaps
    # text and doesn't need a legibility scrim.
    banner_img = load_image(ASSETS_DIR / f"{school}-menu-header.jpg") or load_image(ASSETS_DIR / f"{school}-menu-header.png")
    if banner_img is not None:
        gap_x0 = left + left_block_w + 16
        gap_x1 = text_right - right_block_w - 16
        gap_w = gap_x1 - gap_x0
        if gap_w > 30:  # skip drawing if the text left basically no room
            try:
                c.drawImage(banner_img, gap_x0, top - HEADER_H, width=gap_w, height=HEADER_H,
                            preserveAspectRatio=True, anchor='c', mask='auto')
            except Exception as e:
                print(f"  ⚠ Could not draw banner image: {e}")

    c.setFont("Helvetica-Bold", 7)
    c.setFillColor(INK)
    c.drawRightString(text_right, top - 10, "Food Service Director:")
    c.setFont("Helvetica-Bold", 7.5)
    c.drawRightString(text_right, top - 20, DIRECTOR["name"])
    c.setFont("Helvetica", 7)
    c.setFillColor(MUTED)
    c.drawRightString(text_right, top - 29, DIRECTOR["email"])
    c.drawRightString(text_right, top - 38, DIRECTOR["phone"])

    # Divider under the whole header band
    c.setStrokeColor(BORDER)
    c.setLineWidth(1)
    c.line(MARGIN, top - HEADER_H, PAGE_W - MARGIN, top - HEADER_H)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

SIDEBAR_GAP = 0.09 * inch
SIDEBAR_PAD = 0.09 * inch
COL_GAP = 0.08 * inch


def _wrap_column(items: list[str], col_w: float, font_size: float, pad: float) -> list[str]:
    max_chars = max(6, int((col_w - pad) / (font_size * 0.52)))
    wrapped: list[str] = []
    for item in items:
        wrapped.extend(wrap_text_lines(item, max_chars) or [""])
    return wrapped


def _section_columns(section: dict, w: float, font_size: float, pad: float) -> list[list[str]]:
    """Splits a section's body into 1 or 2 wrapped-line columns."""
    items = section["body"]
    n_cols = section.get("columns", 1)
    if n_cols == 1:
        return [_wrap_column(items, w - 2 * pad, font_size, pad)]
    col_w = (w - 2 * pad - COL_GAP) / 2
    split = (len(items) + 1) // 2
    return [_wrap_column(items[:split], col_w, font_size, pad),
            _wrap_column(items[split:], col_w, font_size, pad)]


def section_height(section: dict, w: float, font_size: float, heading_size: float, pad: float) -> float:
    heading_max_chars = max(8, int((w - 2 * pad) / (heading_size * 0.52)))
    heading_lines = wrap_text_lines(section["heading"], heading_max_chars) or [section["heading"]]
    line_h = font_size + 2.6
    columns = _section_columns(section, w, font_size, pad)
    body_lines = max(len(c) for c in columns)
    return pad + len(heading_lines) * (heading_size + 2) + 4 + body_lines * line_h + pad


def draw_section(c: canvas.Canvas, section: dict, x: float, y_top: float, w: float,
                  font_size: float, heading_size: float, pad: float = SIDEBAR_PAD) -> float:
    """Draws one rounded sidebar box (1 or 2 body columns), returns the y of its bottom edge."""
    bg = BOX_COLORS[section["color"]]
    heading_color = HEAD_COLORS[section["color"]]
    heading_max_chars = max(8, int((w - 2 * pad) / (heading_size * 0.52)))
    heading_lines = wrap_text_lines(section["heading"], heading_max_chars) or [section["heading"]]
    columns = _section_columns(section, w, font_size, pad)
    content_h = section_height(section, w, font_size, heading_size, pad)
    y_bot = y_top - content_h

    c.setFillColor(bg)
    c.roundRect(x, y_bot, w, content_h, radius=4, fill=1, stroke=0)

    heading_font = "Helvetica-BoldOblique" if section.get("heading_italic", True) else "Helvetica-Bold"
    ty = y_top - pad - heading_size
    c.setFont(heading_font, heading_size)
    c.setFillColor(heading_color)
    for hl in heading_lines:
        c.drawCentredString(x + w / 2, ty, hl)
        ty -= heading_size + 2

    body_top = ty - 2
    line_h = font_size + 2.6
    body_font = "Helvetica-Oblique" if section.get("body_italic", True) else "Helvetica"
    col_w = w - 2 * pad if len(columns) == 1 else (w - 2 * pad - COL_GAP) / 2
    for i, col_lines in enumerate(columns):
        cx = x + pad + i * (col_w + COL_GAP)
        cy = body_top
        c.setFont(body_font, font_size)
        c.setFillColor(INK)
        for line in col_lines:
            cy -= line_h
            c.drawString(cx, cy + (line_h - font_size), line)

    return y_bot


def sidebar_content_height(content: dict, font_size: float, heading_size: float) -> float:
    w = SIDEBAR_W
    h = 0.0
    for section in content["sections"]:
        if section["kind"] == "band":
            h += 22
        else:
            h += section_height(section, w, font_size, heading_size, SIDEBAR_PAD)
        h += SIDEBAR_GAP
    h += 20  # USDA notice
    if content.get("placeholder"):
        h += 20
    return h


def fit_sidebar_font_size(content: dict) -> float:
    """Shrinks the sidebar font until everything fits between the header and
    the bottom margin — a long a la carte options list (PSHS has ~12 items)
    otherwise runs the boxes off the bottom of the page."""
    available = GRID_TOP - GRID_BOT
    for font_size in (7.2, 6.8, 6.4, 6.0, 5.6, 5.2, 4.8):
        heading_size = font_size + 1.3
        if sidebar_content_height(content, font_size, heading_size) <= available:
            return font_size
    return 4.8


def draw_sidebar(c: canvas.Canvas, school: str, menutype: str):
    content = get_content(school, menutype)
    x = MARGIN
    w = SIDEBAR_W
    y = GRID_TOP
    gap = SIDEBAR_GAP

    font_size = fit_sidebar_font_size(content)
    heading_size = font_size + 1.3

    for section in content["sections"]:
        if section["kind"] == "band":
            c.setFillColor(BOX_COLORS["gray"])
            c.roundRect(x, y - 22, w, 22, radius=4, fill=1, stroke=0)
            c.setFont("Helvetica-Bold", 8)
            c.setFillColor(INK)
            c.drawString(x + SIDEBAR_PAD, y - 14, section["label"])
            c.setFont("Helvetica-Oblique", 7.5)
            c.setFillColor(MUTED)
            label_w = c.stringWidth(section["label"] + "  ", "Helvetica-Bold", 8)
            c.drawString(x + SIDEBAR_PAD + label_w, y - 14, section["value"])
            y -= 22 + gap
        else:
            y = draw_section(c, section, x, y, w, font_size, heading_size) - gap

    if content.get("placeholder"):
        c.setFont("Helvetica-Oblique", 6.5)
        c.setFillColor(colors.HexColor("#a33333"))
        for l in wrap_text_lines(
            "Pricing/options for this menu are placeholders — update menu_content.py.", 60
        ):
            y -= 8
            c.drawString(x, y, l)
        y -= 4

    # USDA notice, bottom of sidebar
    c.setFont("Helvetica", 6.5)
    c.setFillColor(MUTED)
    usda_lines = wrap_text_lines(USDA_NOTICE, 62)
    uy = GRID_BOT + len(usda_lines) * 8
    for line in usda_lines:
        c.drawString(x, uy, line)
        uy -= 8


# ---------------------------------------------------------------------------
# Grid (Mon–Fri calendar)
# ---------------------------------------------------------------------------

def _wrap_to_width(text: str, font: str, size: float, width: float) -> list[str]:
    lines, current = [], ""
    for w in text.split():
        trial = f"{current} {w}" if current else w
        if current and stringWidth(trial, font, size) > width:
            lines.append(current)
            current = w
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def _fit_cell(sections: list[dict], width: float, avail_h: float, size: float = 8.0):
    """Lay out a day cell's station labels ("HOMESTYLE", "FAN FAVORITE")
    and items, shrinking the font from 8pt until everything fits — a full
    lunch day (5 Homestyle items + Fan Favorite) doesn't fit at 8pt, and
    clipping would always drop the Fan Favorite since it's listed last.
    Returns (lines, font_size, line_h, label_size, label_h) where lines are
    ("label" | "item" | "gap", text) tuples."""
    while True:
        line_h = size + 2.2
        label_size = size * 0.8
        label_h = label_size + 3
        lines, used = [], 0.0
        for idx, section in enumerate(sections):
            if section["title"]:
                if idx > 0:
                    lines.append(("gap", ""))
                    used += 1.5
                lines.append(("label", section["title"].upper()))
                used += label_h
            for item in section["items"]:
                for line in _wrap_to_width(item, "Helvetica", size, width):
                    lines.append(("item", line))
                    used += line_h
        if used <= avail_h or size <= 5.5:
            return lines, size, line_h, label_size, label_h
        size -= 0.25


def draw_grid(c: canvas.Canvas, data: dict, year: int, month: int):
    weeks = build_week_grid(data, year, month)
    num_rows = len(weeks)
    row_h = GRID_H / num_rows
    subhead_h = 0.24 * inch
    grid_top = GRID_TOP - subhead_h
    grid_h = grid_top - GRID_BOT
    row_h = grid_h / num_rows

    # Day-name header row
    c.setFillColor(GRID_HEAD)
    c.rect(GRID_X, GRID_TOP - subhead_h, GRID_W, subhead_h, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 10)
    for col, day_name in enumerate(DAYS):
        cx = GRID_X + col * COL_W + COL_W / 2
        c.drawCentredString(cx, GRID_TOP - subhead_h + 0.07 * inch, day_name)

    # One font size for the whole page — the largest every cell fits at —
    # so a busy day doesn't sit next to a lighter one in visibly bigger type.
    avail_h = (row_h - 20 + 8) - 3
    page_size = min((_fit_cell(sections, COL_W - 10, avail_h)[1]
                     for week in weeks for day_num, sections in week if sections),
                    default=8.0)

    for row_idx, week in enumerate(weeks):
        row_top = grid_top - row_idx * row_h
        row_bot = row_top - row_h

        for col_idx, (day_num, sections) in enumerate(week):
            cell_x = GRID_X + col_idx * COL_W
            if day_num is None:
                c.setFillColor(colors.HexColor("#f2f4f8"))
                c.rect(cell_x, row_bot, COL_W, row_h, fill=1, stroke=0)
                continue

            c.setFillColor(INK)
            c.setFont("Helvetica-Bold", 8.5)
            c.drawString(cell_x + 5, row_top - 11, str(day_num))

            if sections:
                lines, font_size, line_h, label_size, label_h = _fit_cell(sections, COL_W - 10, avail_h, page_size)
                text_y = row_top - 20
                for kind, text in lines:
                    if kind == "gap":
                        text_y -= 1.5
                    elif kind == "label":
                        c.setFillColor(SCHOOL_BLUE)
                        c.setFont("Helvetica-Bold", label_size)
                        c.drawString(cell_x + 5, text_y, text)
                        text_y -= label_h
                    else:
                        c.setFillColor(INK)
                        c.setFont("Helvetica", font_size)
                        c.drawString(cell_x + 5, text_y, text)
                        text_y -= line_h

    # Grid lines
    c.setStrokeColor(BORDER)
    c.setLineWidth(0.5)
    for col in range(NUM_COLS + 1):
        x = GRID_X + col * COL_W
        c.line(x, GRID_BOT, x, grid_top)
    for row in range(num_rows + 1):
        y = grid_top - row * row_h
        c.line(GRID_X, y, PAGE_W - MARGIN, y)
    c.setStrokeColor(GRID_HEAD)
    c.setLineWidth(1)
    c.line(GRID_X, GRID_TOP, PAGE_W - MARGIN, GRID_TOP)


# ---------------------------------------------------------------------------
# Page assembly
# ---------------------------------------------------------------------------

def draw_page(c: canvas.Canvas, data: dict, year: int, month: int,
              school_display: str, menutype: str, school: str):
    content = get_content(school, menutype)
    c.setFillColor(WHITE)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)

    draw_header(c, school, menutype, year, month, content["banner_title"])
    draw_sidebar(c, school, menutype)
    draw_grid(c, data, year, month)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def generate_all(labeled_months: list[tuple[str, int, int]]):
    """labeled_months: (filename_label, year, month) triples. The label IS
    the output filename's prefix — e.g. ("current", 2026, 9) writes
    current-{menutype}-{school}.pdf. There's no separate dated file and no
    copy step: this is the only PDF generated for that label, so the site
    only ever has exactly as many PDFs as labels passed in."""
    import csv

    csv_path = Path(__file__).parent / "menu-list.csv"
    with open(csv_path, newline="") as f:
        rows = list(csv.DictReader(f))

    for label, year, month in labeled_months:
        for row in rows:
            school       = row["school"].strip()
            display_name = row["display_name"].strip()
            menutype     = row["menutype"].strip()

            print(f"\n→ PDF ({label}): {display_name} / {menutype} — {MONTH_NAMES[month]} {year}")
            data = load_rollup(school, menutype)
            if data is None:
                continue

            out_path = PDF_DIR / f"{label}-{menutype}-{school}.pdf"
            c = canvas.Canvas(str(out_path), pagesize=landscape(letter))

            # Document metadata — reportlab defaults to a blank Title, which
            # is why PDF viewers/tabs show "Untitled" instead of anything
            # useful. DisplayDocTitle tells the viewer to actually show that
            # Title (some default to the filename otherwise), and Lang lets
            # screen readers pick the right pronunciation/voice.
            title = f"{menutype.capitalize()} Menu — {display_name} — {MONTH_NAMES[month]} {year}"
            c.setTitle(title)
            c.setAuthor("Poland Local School District")
            c.setSubject(f"{menutype.capitalize()} menu calendar for {display_name}, {MONTH_NAMES[month]} {year}")
            c.setCreator("Poland Schools Menu System")
            c.setKeywords(f"{display_name}, {menutype}, school menu, {MONTH_NAMES[month]} {year}")
            c.setViewerPreference("DisplayDocTitle", "true")
            c.setCatalogEntry("Lang", "en-US")

            draw_page(c, data, year, month, display_name, menutype, school)
            c.showPage()
            c.save()
            print(f"  ✓ {out_path.name}")


def prune_other_pdfs(keep_labels: set[str]):
    """Removes any PDF (and its preview card) whose filename doesn't start
    with one of keep_labels — covers leftover dated files from before this
    script wrote directly to current-/next-, and any one-off manual/preview
    output, so the site only ever has exactly the current set."""
    removed = 0
    for pdf_path in PDF_DIR.glob("*.pdf"):
        if pdf_path.stem.split("-", 1)[0] not in keep_labels:
            pdf_path.unlink()
            thumb = PDF_DIR / "thumbnails" / f"{pdf_path.stem}.png"
            if thumb.exists():
                thumb.unlink()
            removed += 1
    if removed:
        print(f"\n  Pruned {removed} PDF(s)/preview card(s) outside {sorted(keep_labels)}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--year",  type=int, help="Single year (requires --month) — writes a one-off preview-*.pdf, doesn't touch current-/next-")
    parser.add_argument("--month", type=int, help="Single month 1-12 (requires --year)")
    args = parser.parse_args()

    if args.year and args.month:
        generate_all([("preview", args.year, args.month)])
    else:
        # The only PDFs the site ever has: current month and next month,
        # under permanent filenames (current-*.pdf / next-*.pdf) — nothing
        # dated, nothing to prune month to month, no URL ever changes.
        today = date.today()
        this_month = (today.year, today.month)
        next_month = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
        generate_all([
            ("current", *this_month),
            ("next", *next_month),
        ])
        prune_other_pdfs({"current", "next"})

    print("\n✅ PDFs generated.")
