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
import os
from datetime import date, datetime, timedelta
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

    weeks = []
    current = first - timedelta(days=first.weekday())
    while current <= last:
        week = []
        for i in range(5):
            d = current + timedelta(days=i)
            if d.month == month:
                week.append((d.day, items_by_date.get(d.strftime("%Y-%m-%d"), [])))
            else:
                week.append((None, []))
        # A month starting on a weekend (e.g. Nov 2026 starts Sunday) would
        # otherwise get a leading Mon–Fri row with no days of the month in
        # it at all — a whole row of dead space the other rows pay for.
        if any(day_num is not None for day_num, _ in week):
            weeks.append(week)
        current += timedelta(days=7)

    return weeks


# ---------------------------------------------------------------------------
# Text layout
# ---------------------------------------------------------------------------
# Every block of text is laid out ONCE into a list of positioned lines, and
# that same list is used both to measure it (Block.h) and to draw it — so a
# measured height can never disagree with what actually gets drawn, which
# is what used to let text spill past box and cell edges. All wrapping uses
# real glyph widths (stringWidth), never character-count guesses.

LEADING = 1.2   # line height as a multiple of font size
HANG    = 0.9   # hanging indent for wrapped continuation lines, in ems —
                # so "Tropical Pineapple / Tidbits" reads as one item, not two

WARNINGS: list[str] = []


def warn(msg: str) -> None:
    WARNINGS.append(msg)
    # Surfaces as a yellow annotation on the GitHub Actions run summary.
    prefix = "::warning::" if os.environ.get("GITHUB_ACTIONS") else "  ⚠ "
    print(f"{prefix}{msg}")


def wrap(text: str, font: str, size: float, width: float, indent: float = 0.0) -> list[str]:
    """Word-wrap to `width` (continuation lines get `width - indent`). A
    single word wider than the line is hard-broken with a hyphen instead of
    being allowed to run past the edge."""
    lines: list[str] = []
    cur = ""
    for word in text.split():
        avail = width - (indent if lines else 0)
        trial = f"{cur} {word}" if cur else word
        if stringWidth(trial, font, size) <= avail:
            cur = trial
            continue
        if cur:
            lines.append(cur)
            avail = width - indent
        while len(word) > 1 and stringWidth(word, font, size) > avail:
            # Prefer a natural break right after "/" or "," ("Turkey/Ham/
            # Cheese,Egg"); only hyphenate mid-word as a last resort.
            natural = [i + 1 for i, ch in enumerate(word[:-1]) if ch in "/,"
                       and stringWidth(word[:i + 1], font, size) <= avail]
            if natural:
                cut = natural[-1]
                lines.append(word[:cut])
            else:
                cut = len(word) - 1
                while cut > 1 and stringWidth(word[:cut] + "-", font, size) > avail:
                    cut -= 1
                lines.append(word[:cut] + "-")
            word = word[cut:]
            avail = width - indent
        cur = word
    if cur or not lines:
        lines.append(cur)
    return lines


def fit_size(text: str, font: str, size: float, width: float, floor: float = 5.0) -> float:
    """Largest size <= `size` at which `text` fits on one line of `width`."""
    while size > floor and stringWidth(text, font, size) > width:
        size -= 0.25
    return size


class Block:
    """Lines positioned relative to the block's top-left corner, plus the
    block's exact height. Build it, read .h to measure, then .draw()."""

    def __init__(self):
        self.lines: list[tuple] = []   # (dx, baseline_dy, font, size, color, text, centered)
        self.h = 0.0

    def add(self, text_lines: list[str], font: str, size: float, color,
            indent: float = 0.0, dx: float = 0.0, centered: bool = False,
            leading: float = LEADING) -> None:
        # Helvetica: ascent 0.718em, descent 0.207em; center the glyph box
        # within the line height.
        baseline = (leading - 0.925) / 2 * size + 0.718 * size
        for i, t in enumerate(text_lines):
            self.lines.append((dx + (indent if i else 0.0), self.h + baseline,
                               font, size, color, t, centered))
            self.h += size * leading

    def space(self, h: float) -> None:
        self.h += h

    def place(self, other: "Block", dx: float) -> None:
        """Lay `other` in at the current bottom, shifted right by dx (for
        side-by-side columns — caller advances .h afterwards)."""
        for odx, ody, *rest in other.lines:
            self.lines.append((dx + odx, self.h + ody, *rest))

    def draw(self, c: canvas.Canvas, x: float, y_top: float) -> None:
        for dx, dy, font, size, color, text, centered in self.lines:
            c.setFont(font, size)
            c.setFillColor(color)
            if centered:
                c.drawCentredString(x + dx, y_top - dy, text)
            else:
                c.drawString(x + dx, y_top - dy, text)


def item_list(items: list[str], font: str, size: float, color, width: float,
              gap: float = 0.18, leading: float = LEADING) -> Block:
    """Items stacked with a hanging indent on wraps and `gap` ems of extra
    space between items, so where one item ends and the next begins is
    obvious."""
    b = Block()
    for i, item in enumerate(items):
        if i:
            b.space(size * gap)
        b.add(wrap(item, font, size, width, HANG * size), font, size, color,
              indent=HANG * size, leading=leading)
    return b


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
    max_left_w = PAGE_W * 0.46
    c.setFillColor(INK)
    title_size = fit_size(banner_title, "Helvetica-Bold", 15, max_left_w)
    c.setFont("Helvetica-Bold", title_size)
    c.drawString(left, top - 16, banner_title)
    title_w = c.stringWidth(banner_title, "Helvetica-Bold", title_size)

    month_line = f"{menutype.upper()} - {MONTH_NAMES[month].upper()} {year}"
    month_size = fit_size(month_line, "Helvetica-Bold", 22, max_left_w)
    c.setFont("Helvetica-Bold", month_size)
    c.drawString(left, top - 38, month_line)
    month_w = c.stringWidth(month_line, "Helvetica-Bold", month_size)

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
COL_GAP     = 0.08 * inch
BAND_H      = 22
SIDEBAR_FONT_MAX, SIDEBAR_FONT_MIN = 8.0, 5.0


def layout_box(section: dict, size: float) -> Block:
    """One rounded sidebar box's text (heading + 1 or 2 body columns),
    positioned relative to the box's inner top-left; .h includes padding."""
    inner = SIDEBAR_W - 2 * SIDEBAR_PAD
    heading_size = size + 1.3
    heading_font = "Helvetica-BoldOblique" if section.get("heading_italic", True) else "Helvetica-Bold"
    body_font = "Helvetica-Oblique" if section.get("body_italic", True) else "Helvetica"

    b = Block()
    b.space(SIDEBAR_PAD)
    b.add(wrap(section["heading"], heading_font, heading_size, inner), heading_font,
          heading_size, HEAD_COLORS[section["color"]], dx=inner / 2, centered=True)
    b.space(size * 0.6)

    items = section["body"]
    if section.get("columns", 1) == 1:
        body = item_list(items, body_font, size, INK, inner)
        b.place(body, 0)
        b.h += body.h
    else:
        # Split where the two columns come out closest in height, not just
        # by item count — wrapped items make counts a poor proxy.
        col_w = (inner - COL_GAP) / 2
        best = None
        for k in range(1, len(items)):
            left = item_list(items[:k], body_font, size, INK, col_w)
            right = item_list(items[k:], body_font, size, INK, col_w)
            if best is None or max(left.h, right.h) < max(best[0].h, best[1].h):
                best = (left, right)
        left, right = best or (item_list(items, body_font, size, INK, col_w), Block())
        b.place(left, 0)
        b.place(right, col_w + COL_GAP)
        b.h += max(left.h, right.h)
    b.space(SIDEBAR_PAD)
    return b


def usda_block(size: float = 6.5) -> Block:
    b = Block()
    b.add(wrap(USDA_NOTICE, "Helvetica", size, SIDEBAR_W), "Helvetica", size, MUTED)
    return b


def placeholder_block() -> Block:
    b = Block()
    msg = "Pricing/options for this menu are placeholders — update menu_content.py."
    b.add(wrap(msg, "Helvetica-Oblique", 6.5, SIDEBAR_W), "Helvetica-Oblique", 6.5,
          colors.HexColor("#a33333"))
    return b


def sidebar_height(content: dict, size: float) -> float:
    h = 0.0
    for section in content["sections"]:
        h += (BAND_H if section["kind"] == "band" else layout_box(section, size).h) + SIDEBAR_GAP
    if content.get("placeholder"):
        h += placeholder_block().h + SIDEBAR_GAP
    return h + usda_block().h


def fit_sidebar_font_size(content: dict) -> float:
    """Largest body size at which every box (and the USDA line) fits
    between the header and the bottom margin."""
    available = GRID_TOP - GRID_BOT
    size = SIDEBAR_FONT_MAX
    while size > SIDEBAR_FONT_MIN and sidebar_height(content, size) > available:
        size = round(size - 0.1, 2)
    if sidebar_height(content, size) > available:
        warn(f"sidebar text doesn't fit even at {size}pt — shorten menu_content.py lists")
    return size


def draw_sidebar(c: canvas.Canvas, school: str, menutype: str):
    content = get_content(school, menutype)
    x = MARGIN
    w = SIDEBAR_W
    y = GRID_TOP
    size = fit_sidebar_font_size(content)

    for section in content["sections"]:
        if section["kind"] == "band":
            c.setFillColor(BOX_COLORS["gray"])
            c.roundRect(x, y - BAND_H, w, BAND_H, radius=4, fill=1, stroke=0)
            # Label + value on one line; shrink both together if needed.
            label, value = section["label"], section["value"]
            band_size = 8.0
            while band_size > 5 and (stringWidth(label + "  ", "Helvetica-Bold", band_size)
                                     + stringWidth(value, "Helvetica-Oblique", band_size - 0.5)
                                     > w - 2 * SIDEBAR_PAD):
                band_size -= 0.25
            c.setFont("Helvetica-Bold", band_size)
            c.setFillColor(INK)
            c.drawString(x + SIDEBAR_PAD, y - 14, label)
            c.setFont("Helvetica-Oblique", band_size - 0.5)
            c.setFillColor(MUTED)
            c.drawString(x + SIDEBAR_PAD + stringWidth(label + "  ", "Helvetica-Bold", band_size),
                         y - 14, value)
            y -= BAND_H + SIDEBAR_GAP
        else:
            box = layout_box(section, size)
            c.setFillColor(BOX_COLORS[section["color"]])
            c.roundRect(x, y - box.h, w, box.h, radius=4, fill=1, stroke=0)
            box.draw(c, x + SIDEBAR_PAD, y)
            y -= box.h + SIDEBAR_GAP

    if content.get("placeholder"):
        note = placeholder_block()
        note.draw(c, x, y)

    usda = usda_block()
    usda.draw(c, x, GRID_BOT + usda.h)


# ---------------------------------------------------------------------------
# Grid (Mon–Fri calendar)
# ---------------------------------------------------------------------------

SUBHEAD_H   = 0.24 * inch
CELL_PAD    = 4
DAYNUM_SIZE = 8.5
CELL_HEAD   = DAYNUM_SIZE + 2.5          # day number line + gap under it
MIN_ROW_H   = 2 * CELL_PAD + CELL_HEAD + 18
CELL_FONT_MAX, CELL_FONT_MIN = 9.0, 5.0
# Equal-height rows look tidiest, so they win unless they'd cost more than
# this much font size versus letting busy weeks take extra height.
EQUAL_ROWS_TOLERANCE = 0.5


def layout_day(sections: list[dict], size: float) -> Block:
    """A day cell's station labels ("HOMESTYLE", "FAN FAVORITE") and items.
    Cells are narrow (~1.5in) and a full lunch day is 8–10 lines, so
    spacing here is tighter than the sidebar's — every point of vertical
    space saved goes straight into a bigger font for the whole page. The
    first station's label isn't laid out here: draw_grid puts it on the
    day-number line, which would otherwise be mostly empty."""
    width = COL_W - 2 * CELL_PAD
    label_size = size * 0.78
    b = Block()
    for i, section in enumerate(sections):
        if i:
            b.space(size * 0.35)
        if section["title"] and i:
            b.add(wrap(section["title"].upper(), "Helvetica-Bold", label_size, width),
                  "Helvetica-Bold", label_size, SCHOOL_BLUE, leading=1.3)
        body = item_list(section["items"], "Helvetica", size, INK, width, gap=0.08, leading=1.13)
        b.place(body, 0)
        b.h += body.h
    return b


def row_heights_needed(weeks: list[list], size: float) -> list[float]:
    return [max([MIN_ROW_H] + [2 * CELL_PAD + CELL_HEAD + layout_day(sections, size).h
                               for _, sections in week if sections])
            for week in weeks]


def plan_grid(weeks: list[list]) -> tuple[float, list[float], bool]:
    """Picks one item font size for the whole page and each row's height.
    Returns (font_size, row_heights, fits)."""
    grid_h = GRID_TOP - SUBHEAD_H - GRID_BOT
    n = len(weeks)

    def largest(fits) -> float | None:
        size = CELL_FONT_MAX
        while size >= CELL_FONT_MIN:
            if fits(row_heights_needed(weeks, size)):
                return size
            size = round(size - 0.1, 2)
        return None

    free_size = largest(lambda rows: sum(rows) <= grid_h)
    equal_size = largest(lambda rows: max(rows) * n <= grid_h)

    if equal_size is not None and free_size - equal_size <= EQUAL_ROWS_TOLERANCE:
        return equal_size, [grid_h / n] * n, True
    if free_size is not None:
        rows = row_heights_needed(weeks, free_size)
        extra = (grid_h - sum(rows)) / n
        return free_size, [r + extra for r in rows], True

    # Even the smallest size overflows: scale rows to the page and clip
    # each cell (draw_grid) rather than let text run into its neighbors.
    rows = row_heights_needed(weeks, CELL_FONT_MIN)
    total = sum(rows)
    return CELL_FONT_MIN, [r * grid_h / total for r in rows], False


def draw_grid(c: canvas.Canvas, data: dict, year: int, month: int):
    weeks = build_week_grid(data, year, month)
    size, row_heights, fits = plan_grid(weeks)
    if not fits:
        warn(f"{MONTH_NAMES[month]} {year}: menu text doesn't fit even at "
             f"{CELL_FONT_MIN}pt — some cells are clipped")
    grid_top = GRID_TOP - SUBHEAD_H

    # Day-name header row
    c.setFillColor(GRID_HEAD)
    c.rect(GRID_X, grid_top, GRID_W, SUBHEAD_H, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 10)
    for col, day_name in enumerate(DAYS):
        cx = GRID_X + col * COL_W + COL_W / 2
        c.drawCentredString(cx, grid_top + 0.07 * inch, day_name)

    row_top = grid_top
    row_edges = [row_top]
    for week, row_h in zip(weeks, row_heights):
        row_bot = row_top - row_h
        for col_idx, (day_num, sections) in enumerate(week):
            cell_x = GRID_X + col_idx * COL_W
            if day_num is None:
                c.setFillColor(colors.HexColor("#f2f4f8"))
                c.rect(cell_x, row_bot, COL_W, row_h, fill=1, stroke=0)
                continue

            daynum_y = row_top - CELL_PAD - DAYNUM_SIZE * 0.75
            c.setFillColor(INK)
            c.setFont("Helvetica-Bold", DAYNUM_SIZE)
            c.drawString(cell_x + CELL_PAD, daynum_y, str(day_num))
            if sections and sections[0]["title"]:
                label_x = cell_x + CELL_PAD + stringWidth(str(day_num), "Helvetica-Bold", DAYNUM_SIZE) + 5
                label = sections[0]["title"].upper()
                label_size = fit_size(label, "Helvetica-Bold", min(size * 0.78, 7),
                                      cell_x + COL_W - CELL_PAD - label_x)
                c.setFillColor(SCHOOL_BLUE)
                c.setFont("Helvetica-Bold", label_size)
                c.drawString(label_x, daynum_y, label)

            if sections:
                content = layout_day(sections, size)
                c.saveState()
                if not fits:
                    path = c.beginPath()
                    path.rect(cell_x, row_bot, COL_W, row_h)
                    c.clipPath(path, stroke=0, fill=0)
                content.draw(c, cell_x + CELL_PAD, row_top - CELL_PAD - CELL_HEAD)
                c.restoreState()
        row_top = row_bot
        row_edges.append(row_top)

    # Grid lines
    c.setStrokeColor(BORDER)
    c.setLineWidth(0.5)
    for col in range(NUM_COLS + 1):
        x = GRID_X + col * COL_W
        c.line(x, row_edges[-1], x, grid_top)
    for y in row_edges:
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


def check_all() -> int:
    """Lays out every month present in every feed's rollup (no PDFs
    written) and reports the font sizes chosen and anything that doesn't
    fit. Returns the number of problems found."""
    import csv
    with open(Path(__file__).parent / "menu-list.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    problems = 0
    for row in rows:
        school, menutype = row["school"].strip(), row["menutype"].strip()
        content = get_content(school, menutype)
        side = fit_sidebar_font_size(content)
        side_ok = sidebar_height(content, side) <= GRID_TOP - GRID_BOT
        data = load_rollup(school, menutype) or {"days": []}
        months = sorted({tuple(map(int, d["date"].split("-")[:2])) for d in data["days"]})
        print(f"\n{menutype}-{school}  (sidebar {side}pt{'' if side_ok else ' — OVERFLOWS'})")
        problems += not side_ok
        for year, month in months:
            weeks = build_week_grid(data, year, month)
            size, row_heights, fits = plan_grid(weeks)
            layout = "equal rows" if len(set(round(h, 3) for h in row_heights)) == 1 else "fitted rows"
            print(f"  {year}-{month:02d}: {len(weeks)} weeks, items {size}pt, {layout}"
                  f"{'' if fits else '  — OVERFLOWS (clipped)'}")
            problems += not fits
    print(f"\n{'✅ Everything fits.' if not problems else f'⚠ {problems} problem(s).'}")
    return problems


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help="Lay out every month in the data and report fit problems; writes no PDFs")
    parser.add_argument("--year",  type=int, help="Single year (requires --month) — writes a one-off preview-*.pdf, doesn't touch current-/next-")
    parser.add_argument("--month", type=int, help="Single month 1-12 (requires --year)")
    args = parser.parse_args()

    if args.check:
        raise SystemExit(1 if check_all() else 0)
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
