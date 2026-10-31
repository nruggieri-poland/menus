"""
build_pages.py
Generates WCAG 2.1 AA accessible, responsive, static HTML for each school/menutype:

  {school}/{menutype}/calendar/index.html   <- default / recommended embed target
      A single page (not one file per week/month) that boots the same
      client-side widget engine used for Finalsite embeds — it fetches the
      feed's JSON once and does all month/week navigation in place with JS,
      exactly like the widget. No per-date files to generate or regenerate.

  {school}/{menutype}/embed.html
      The current month's calendar as a bare, no-JS static fragment (no
      <html>/<head>/<body> wrapper), for pasting directly into a Finalsite
      "Custom HTML" component as a last-resort fallback if neither the
      widget script nor an iframe works there. Re-generated on every build,
      but a pasted copy only reflects data as of the last paste.

Run after fetch_menus.py (and generate_pdf.py, if PDF links should resolve).
"""

import csv
import html
import json
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
SITE = ROOT / "site"

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

REPO_SLUG = "nruggieri-poland/menus"
PAGES_BASE = "https://nruggieri-poland.github.io/menus"
REPO_BLOB_BASE = f"https://github.com/{REPO_SLUG}/blob/master"


# ── Data helpers ──────────────────────────────────────────────────────────

def load_menu_list() -> list[dict]:
    with open(Path(__file__).parent / "menu-list.csv", newline="") as f:
        return list(csv.DictReader(f))


_rollup_cache: dict[tuple[str, str], dict | None] = {}


def load_rollup(school: str, menutype: str) -> dict | None:
    key = (school, menutype)
    if key not in _rollup_cache:
        path = DATA / f"{menutype}-{school}.json"
        _rollup_cache[key] = json.loads(path.read_text()) if path.exists() else None
    return _rollup_cache[key]


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def fmt_date_long(d: date) -> str:
    return d.strftime("%A, %B ") + str(d.day)


def item_map(school: str, menutype: str) -> dict[str, list[dict]]:
    """The whole rollup's days as a single date -> sections lookup — the
    rollup holds full history, so no per-month filtering is needed to use
    it. Each section is {"title": "Homestyle" | "Fan Favorite" | None,
    "items": [...]}; days saved before sections were captured fall back to
    one untitled section."""
    data = load_rollup(school, menutype)
    if not data:
        return {}
    return {day["date"]: day.get("sections") or [{"title": None, "items": day["items"]}]
            for day in data.get("days", [])}


def sections_html(sections: list[dict]) -> str:
    out = []
    for section in sections:
        if section["title"]:
            out.append(f'<p class="cal-section">{esc(section["title"])}</p>')
        out.append("<ul>" + "".join(f"<li>{esc(it)}</li>" for it in section["items"]) + "</ul>")
    return "".join(out)


# ── Shared styling ───────────────────────────────────────────────────────

BASE_CSS = """
:root{
  --navy:#07194a; --navy-mid:#0d2870; --brand-blue:#1a3e9c; --ink:#1a1a2e; --muted:#475569;
  --white:#ffffff; --paper:#ffffff; --border:#d8dee9; --row-bg:#eef0f2; --row-bg-today:#dce6fb;
  --pill-bg:#2d3748; --pill-bg-hover:#1c2536;
  --gold-bg:#f5a623; --gold-ink:#5c3d00; --focus:#0b57d0;
}
.menu-embed *,.menu-embed *::before,.menu-embed *::after{box-sizing:border-box;}
.menu-embed{
  font-family:-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  color:var(--ink); background:var(--paper); line-height:1.5; margin:0;
}
.menu-embed a{color:var(--navy-mid);}
.menu-embed a:focus-visible,.menu-embed button:focus-visible{outline:3px solid var(--focus);outline-offset:2px;}
.menu-embed .sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;}
.menu-embed .skip-link{position:absolute;left:-999px;top:auto;background:var(--navy);color:#fff;padding:.75rem 1rem;z-index:100;text-decoration:none;border-radius:0 0 6px 0;}
.menu-embed .skip-link:focus{left:0;top:0;}

.menu-embed .site-header{background:var(--navy);color:#fff;padding:1.25rem 1.5rem;}
.menu-embed .site-header h1{margin:0;font-size:clamp(1.3rem,4vw,1.9rem);}
.menu-embed .site-header p{margin:.3rem 0 0;color:#cfe0ff;font-size:.95rem;}

.menu-embed main{padding:1.25rem 1.25rem 2rem;max-width:1100px;margin:0 auto;}

/* Page head (used by the static no-JS embed.html fragment) */
.menu-embed .page-head{max-width:1100px;margin:0 auto;padding:1.25rem 1.25rem 0;}
.menu-embed .eyebrow{font-size:.8rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin:0 0 .2rem;}
.menu-embed .page-head h1{color:var(--brand-blue);font-size:clamp(1.4rem,4vw,2rem);margin:0;line-height:1.2;}

.menu-embed .site-footer{padding:1.5rem 1.25rem 1rem;color:var(--muted);font-size:.85rem;text-align:center;}

/* Monthly calendar table (used by the static no-JS embed.html fragment) */
.menu-embed table.cal{border-collapse:collapse;width:100%;margin-top:1rem;table-layout:fixed;}
.menu-embed table.cal caption{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;}
.menu-embed table.cal th,.menu-embed table.cal td{border:1px solid var(--border);vertical-align:top;padding:.5rem;}
.menu-embed table.cal thead th{background:var(--brand-blue);color:#fff;text-align:center;padding:.6rem;font-size:.9rem;}
.menu-embed table.cal td{width:20%;}
.menu-embed table.cal td.empty{background:#f2f4f8;}
.menu-embed .cal-daynum{font-weight:700;color:var(--brand-blue);display:block;text-align:right;margin-bottom:.3rem;font-size:.85rem;}
.menu-embed table.cal ul{list-style:none;margin:0;padding:0;font-size:.8rem;}
.menu-embed table.cal ul li{margin-bottom:.25rem;color:#333;}
.menu-embed .cal-section{font-size:.65rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--brand-blue);margin:.4rem 0 .2rem;}
.menu-embed .cal-section:first-of-type{margin-top:0;}

@media (max-width: 700px){
  .menu-embed table.cal thead{position:absolute;left:-9999px;top:-9999px;}
  .menu-embed table.cal, .menu-embed table.cal tbody, .menu-embed table.cal tr, .menu-embed table.cal td{display:block;width:100%;}
  .menu-embed table.cal tr{margin-bottom:1rem;border:1px solid var(--border);border-radius:8px;overflow:hidden;}
  .menu-embed table.cal td{border:none;border-bottom:1px solid var(--border);}
  .menu-embed table.cal td:last-child{border-bottom:none;}
  .menu-embed table.cal td.empty{display:none;}
  .menu-embed table.cal td::before{content:attr(data-day);font-weight:700;color:var(--brand-blue);display:block;font-size:.7rem;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.3rem;}
  .menu-embed .cal-daynum{text-align:left;}
}

@media print{
  .menu-embed .skip-link{display:none !important;}
  .menu-embed .site-header{background:#fff !important;color:#000 !important;border-bottom:3px solid #000;}
  .menu-embed .site-header p{color:#333 !important;}
  .menu-embed{background:#fff !important;}
  .menu-embed table.cal thead th{background:#e5e5e5 !important;color:#000 !important;-webkit-print-color-adjust:exact;print-color-adjust:exact;}
  @page{size:landscape;margin:0.4in;}
}
""".strip()


def page_shell(title: str, description: str, body: str, canonical: str | None = None) -> str:
    canonical_tag = f'<link rel="canonical" href="{esc(canonical)}">' if canonical else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
{canonical_tag}
<style>
html,body{{margin:0;padding:0;}}
{BASE_CSS}
</style>
</head>
<body class="menu-embed">
<a class="skip-link" href="#main">Skip to main content</a>
{body}
</body>
</html>
"""


# ── Feed page (one file per feed — the widget does all the navigating) ────

def build_feed_pages():
    """One page per feed, not one page per week/month: the same client-side
    widget engine used for Finalsite embeds is booted here too, so month and
    week navigation happens in place via JS against a single fetched JSON
    file, with no server-rendered per-date pages to generate or keep in
    sync."""
    widget_url = f"{PAGES_BASE}/embed/menu-widget.js"
    out_paths = []
    for row in load_menu_list():
        school, display_name, menutype = row["school"].strip(), row["display_name"].strip(), row["menutype"].strip()
        out_dir = SITE / school / menutype / "calendar"
        out_dir.mkdir(parents=True, exist_ok=True)

        script_src = (
            f"{widget_url}?school={quote(school)}&menutype={quote(menutype)}"
            f"&displayName={quote(display_name)}"
        )
        pdf_href = f"../../../pdfs/current-{menutype}-{school}.pdf"

        body = f"""
<header class="site-header">
  <h1>{esc(display_name)}</h1>
  <p>{esc(menutype.capitalize())} Menu</p>
</header>
<main id="main">
  <script defer src="{esc(script_src)}"></script>
  <noscript>
    <p>This menu needs JavaScript enabled. You can also view the
    <a href="{esc(pdf_href)}">PDF calendar</a> instead.</p>
  </noscript>
</main>
<footer class="site-footer">Menu subject to change &middot; Poland Local School District &middot; Data sourced from Nutrislice</footer>
""".strip()

        canonical = f"{PAGES_BASE}/{school}/{menutype}/calendar/"
        page = page_shell(
            f"{menutype.capitalize()} Menu — {display_name}",
            f"{menutype.capitalize()} menu calendar for {display_name}.",
            body,
            canonical=canonical,
        )
        out_path = out_dir / "index.html"
        out_path.write_text(page)
        out_paths.append(out_path)

    print(f"  Feed pages built: {len(out_paths)}")


# ── Static no-JS fallback fragment (current month only) ───────────────────

def build_week_grid(day_items: dict[str, list[dict]], year: int, month: int) -> list[list[tuple[int | None, list[dict]]]]:
    first = date(year, month, 1)
    last_day = (date(year, month + 1, 1) - timedelta(days=1)) if month < 12 else date(year, 12, 31)
    week_start = first - timedelta(days=first.weekday())

    weeks = []
    current = week_start
    while current <= last_day:
        week = []
        for i in range(5):
            d = current + timedelta(days=i)
            key = d.strftime("%Y-%m-%d")
            if d.month == month:
                week.append((d.day, day_items.get(key, [])))
            else:
                week.append((None, []))
        weeks.append(week)
        current += timedelta(days=7)
    return weeks


def render_calendar_fragment(school: str, display_name: str, menutype: str, year: int, month: int) -> str:
    """Chromeless current-month table — no nav, no JS — for the static
    embed.html fallback only."""
    day_items = item_map(school, menutype)
    weeks = build_week_grid(day_items, year, month)

    header_cells = "".join(f'<th scope="col">{esc(d)}</th>' for d in DAYS)

    rows = []
    for week in weeks:
        cells = []
        for day_name, (day_num, sections) in zip(DAYS, week):
            if day_num is None:
                cells.append(f'<td class="empty" data-day="{esc(day_name)}"></td>')
                continue
            items_html = sections_html(sections)
            d_full = date(year, month, day_num)
            cells.append(
                f'<td data-day="{esc(day_name)}">'
                f'<span class="sr-only">{esc(fmt_date_long(d_full))}: </span>'
                f'<span class="cal-daynum" aria-hidden="true">{day_num}</span>{items_html}</td>'
            )
        rows.append("<tr>" + "".join(cells) + "</tr>")

    month_label = f"{MONTH_NAMES[month]} {year}"
    caption = f"{esc(menutype.capitalize())} menu &mdash; {esc(display_name)} &mdash; {esc(month_label)}"

    return f"""
<div class="page-head">
  <p class="eyebrow">{esc(menutype.capitalize())} &middot; {esc(display_name)}</p>
  <h1>{esc(month_label)}</h1>
</div>
<main id="main">
  <table class="cal">
    <caption>{caption}</caption>
    <thead><tr>{header_cells}</tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</main>
""".strip()


def build_embed_fragments():
    today = date.today()
    count = 0
    for row in load_menu_list():
        school, display_name, menutype = row["school"].strip(), row["display_name"].strip(), row["menutype"].strip()
        fragment_body = render_calendar_fragment(school, display_name, menutype, today.year, today.month)
        embed_url = f"{PAGES_BASE}/{school}/{menutype}/embed.html"
        fragment = f"<!-- Poland Schools menu embed — {esc(display_name)} {esc(menutype)}. " \
                   f"Regenerated on every build; re-copy from {embed_url} to stay current if " \
                   f"pasted as static HTML instead of used via the widget/iframe. -->\n" \
                   f"<div class=\"menu-embed\">\n<style>{BASE_CSS}</style>\n{fragment_body}\n</div>\n"
        (SITE / school / menutype / "embed.html").write_text(fragment)
        count += 1
    print(f"  Static embed fragments built: {count}")


# ── Embed guide ───────────────────────────────────────────────────────────

def current_and_next_month() -> list[tuple[str, int, int]]:
    """(label, year, month) for the two PDFs generate_pdf.py always
    produces — current-*.pdf and next-*.pdf, filenames that never change,
    with the year/month here used only for display labels."""
    today = date.today()
    this_month = (today.year, today.month)
    next_month = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    return [("current", *this_month), ("next", *next_month)]


def build_embed_guide():
    """A human-facing page listing ready-to-copy embed snippets for whoever
    manages the Finalsite pages — not linked from anywhere automatically
    consumed by CI, just a convenience reference."""
    widget_url = f"{PAGES_BASE}/embed/menu-widget.js"
    sections = []
    for row in load_menu_list():
        school, display_name, menutype = row["school"].strip(), row["display_name"].strip(), row["menutype"].strip()
        cal_url = f"{PAGES_BASE}/{school}/{menutype}/calendar/"
        embed_url = f"{PAGES_BASE}/{school}/{menutype}/embed.html"

        widget_snippet = f'<script defer src="{widget_url}?school={school}&menutype={menutype}"></script>'
        widget_file_url = f"{REPO_BLOB_BASE}/widgets/{school}-{menutype}.html"

        pdf_dir = SITE / "pdfs"
        month_labels = current_and_next_month()
        if (pdf_dir / f"current-{menutype}-{school}.pdf").exists():
            stable_lines = []
            for label, py, pm in month_labels:
                stem = f"{label}-{menutype}-{school}"
                thumb_url = f"{PAGES_BASE}/pdfs/thumbnails/{stem}.png"
                pdf_url = f"{PAGES_BASE}/pdfs/{stem}.pdf"
                stable_lines.append(
                    f"{label.capitalize()} month ({MONTH_NAMES[pm]} {py}) image: {thumb_url}\n"
                    f"{label.capitalize()} month ({MONTH_NAMES[pm]} {py}) links to: {pdf_url}"
                )

            pdf_photo_note = (
                "Use these permanent URLs for the two \"photo\" components on the school site — paste "
                "them once and never touch them again. current-*.pdf/.png and next-*.pdf/.png are the "
                "<em>only</em> PDFs and preview images this repo ever produces (no dated files to clean "
                "up) — the same two filenames, regenerated in place as the month rolls over, so nothing "
                "on the Finalsite side ever needs updating. Each preview image is a branded card with "
                "the month/year prominent plus an actual preview of the calendar page, not a screenshot "
                "of the calendar grid alone (illegible at thumbnail size) or a graphic with no preview "
                "at all — both of those were tried first."
            )
            pdf_photo_snippet = f'<pre><code>{esc(chr(10).join(stable_lines))}</code></pre>'
        else:
            pdf_photo_note = "No PDF has been generated for this feed yet — run generate_pdf.py."
            pdf_photo_snippet = ""

        cal_iframe_snippet = (
            f'<iframe src="{cal_url}" title="{esc(display_name)} {esc(menutype)} menu" '
            f'style="width:100%;max-width:900px;border:0;min-height:900px" loading="lazy"></iframe>'
        )

        sections.append(f"""
    <section aria-labelledby="h-{esc(school)}-{esc(menutype)}">
      <h2 id="h-{esc(school)}-{esc(menutype)}">{esc(display_name)} &mdash; {esc(menutype.capitalize())}</h2>

      <h3>Recommended for Finalsite: paste the widget file</h3>
      <p>Open <a href="{esc(widget_file_url)}">{esc(widget_file_url)}</a>, click "Copy raw file"
      (or select all and copy), and paste the whole thing into this page's Custom HTML component
      &mdash; no other markup needed, the script creates its own container. Every class/id/data
      attribute in the file is namespaced to this specific feed
      (<code>.psmenu-{esc(school)}-{esc(menutype)}-*</code>), so it's safe to paste alongside any
      of the other three widget files on the same page with zero risk of collision. The menu data
      itself is never hardcoded &mdash; the only network request it makes at runtime is fetching
      the current JSON from the repo, so it always shows live data with no rebuild/re-paste
      needed. Month view and list view are both built in, with an in-page toggle button &mdash;
      one page, no separate URLs. Built on semantic HTML (a real <code>&lt;table&gt;</code> for
      the grid, focus-visible states, 44px touch targets) rather than a calendar library's
      non-semantic div grid.</p>

      <h3>Lighter alternative: one script tag, shared engine</h3>
      <p>Functionally identical, but loads the engine from one shared external file instead of
      inlining it &mdash; less to paste per page, at the cost of not being self-contained. Config
      lives in the script's own <code>src</code>, which a CMS sanitizer can't strip without
      breaking the script load itself (unlike a separate <code>data-*</code> attribute or
      container div, which some Finalsite "Custom HTML" sanitizers silently strip on save).</p>
      <pre><code>{esc(widget_snippet)}</code></pre>
      <p>Add <code>&amp;view=week</code> to the URL to start in list view instead of month view.</p>

      <h3>Alternative: iframe</h3>
      <p>Simpler, but some Finalsite CSP configurations block framed content outright (that's
      what happened when we first tried this route) &mdash; use one of the options above if this
      gets silently blocked. Same page as above, so month/list view toggle is included.</p>
      <pre><code>{esc(cal_iframe_snippet)}</code></pre>

      <h3>Fallback: static fragment</h3>
      <p>Only if none of the above works. Copy the contents of
      <a href="{esc(embed_url)}">{esc(embed_url)}</a> directly into the Custom HTML block
      (renders the monthly calendar as of the last rebuild, no JS, no list view). It is
      regenerated on every build, but a pasted copy freezes at paste time &mdash; you'd need to
      re-copy it each time the menu changes to stay current.</p>

      <h3>PDF calendar &mdash; "Download" photo for Finalsite</h3>
      <p>{pdf_photo_note}</p>
      {pdf_photo_snippet}

    </section>""")

    body = f"""
<header class="site-header">
  <h1>Embedding These Menus</h1>
  <p>Copy-paste snippets for the school website / Finalsite</p>
</header>
<main id="main">
  <p>The <strong>widget files</strong> below (also in the repo's <code>widgets/</code> folder) are
  the recommended approach: paste one whole file into a Custom HTML component and it fetches the
  menu JSON straight from this repo client-side and renders it in the page &mdash; no HTML markup
  beyond the paste, no framing (which avoids the CSP <code>frame-src</code> blocks some Finalsite
  configurations apply to iframes), and everything namespaced so multiple feeds coexist safely on
  one page. Month view is the default, with an in-page button to switch to list view &mdash; one
  page handles both, same as this site's own menu pages.</p>
  {''.join(sections)}
</main>
<footer class="site-footer">Internal reference page &mdash; not linked from the public menu pages.</footer>
""".strip()

    extra_css = """
.menu-embed pre{background:#0d1330;color:#e8edff;padding:1rem;border-radius:8px;overflow-x:auto;font-size:.85rem;}
.menu-embed code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;}
.menu-embed section{border-top:1px solid var(--border);padding-top:1.25rem;margin-top:1.5rem;}
"""
    page = page_shell(
        "Embedding These Menus — Reference",
        "Copy-paste iframe and fallback embed snippets for Finalsite.",
        body,
    ).replace("</style>", extra_css + "</style>")

    out_dir = SITE / "embed-guide"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(page)
    print("  Embed guide built: site/embed-guide/index.html")


# ── Landing page ─────────────────────────────────────────────────────────

MEAL_ICONS = {"breakfast": "🥞", "lunch": "🍕"}

# The public-facing landing page groups by the three actual schools
# families think in terms of — not by data "feed". McKinley Elementary and
# Poland Middle share one building and one Nutrislice feed/menu, so both
# names point at the same mckinley-middle feed; Poland Seminary High has
# its own.
SCHOOL_GROUPS = [
    ("McKinley Elementary School", "mckinley-middle"),
    ("Poland Middle School", "mckinley-middle"),
    ("Poland Seminary High School", "pshs"),
]


MEAL_ORDER = ["lunch", "breakfast"]


def build_index_page():
    menu_list = load_menu_list()
    rows_by_school = {}
    for row in menu_list:
        rows_by_school.setdefault(row["school"].strip(), []).append(row)

    school_sections = []
    for display_name, feed_school in SCHOOL_GROUPS:
        menutypes_available = {row["menutype"].strip() for row in rows_by_school.get(feed_school, [])}

        meal_groups = []
        for menutype in MEAL_ORDER:
            if menutype not in menutypes_available:
                continue
            icon = MEAL_ICONS.get(menutype, "🍽️")

            pdf_cards = []
            for label, year, month in current_and_next_month():
                stem = f"{label}-{menutype}-{feed_school}"
                if not (SITE / "pdfs" / f"{stem}.pdf").exists():
                    continue
                month_label = f"{MONTH_NAMES[month]} {year}"
                pdf_cards.append(f"""
          <a class="pdf-card" href="pdfs/{stem}.pdf">
            <img src="pdfs/thumbnails/{stem}.png" alt="{esc(month_label)} {esc(menutype)} calendar for {esc(display_name)} (PDF)" loading="lazy">
            <span>{'Current' if label == 'current' else 'Next'} Month &middot; {esc(month_label)}</span>
          </a>""")

            meal_groups.append(f"""
      <div class="meal-group">
        <h3><span aria-hidden="true">{icon}</span> {esc(menutype.capitalize())}
          <a class="online-link" href="{feed_school}/{menutype}/calendar/">View online &rarr;</a></h3>
        <div class="pdf-row">{''.join(pdf_cards) if pdf_cards else '<p class="pdf-empty">PDF not generated yet.</p>'}</div>
      </div>""")

        school_sections.append(f"""
    <section class="school-panel">
      <h2>{esc(display_name)}</h2>
      {''.join(meal_groups)}
    </section>""")

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Poland Schools Menu System</title>
<meta name="description" content="Weekly and monthly school breakfast/lunch menus for Poland Local Schools.">
<style>
  *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;}}
  :root{{ --navy:#07194a; --accent:#7cd0ff; --white:#fff; --gray:#a9c2e8; --ink:#1a1a2e; }}
  body{{ font-family:-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; background:var(--navy); color:var(--white);
    min-height:100vh; display:flex; flex-direction:column; align-items:center; padding:48px 20px 60px; }}
  a{{ color:inherit; }}
  a:focus-visible{{ outline:3px solid var(--accent); outline-offset:2px; }}
  h1{{ font-size:clamp(32px,5vw,52px); letter-spacing:1px; margin-bottom:6px; text-align:center; }}
  h1 span{{ color:var(--accent); }}
  .subtitle{{ font-size:17px; color:var(--gray); margin-bottom:48px; text-align:center; max-width:32em; }}
  .schools{{ display:flex; flex-direction:column; gap:24px; max-width:820px; width:100%; }}
  .school-panel{{ background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.15); border-radius:18px; padding:28px; }}
  .school-panel h2{{ font-size:22px; font-weight:700; margin-bottom:20px; }}
  .meal-group + .meal-group{{ margin-top:24px; }}
  .meal-group h3{{ font-size:16px; font-weight:700; display:flex; align-items:center; gap:8px; margin-bottom:12px; }}
  .online-link{{ margin-left:auto; font-size:13px; font-weight:600; color:var(--accent); text-decoration:none; }}
  .online-link:hover{{ text-decoration:underline; }}
  .pdf-row{{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:16px; }}
  .pdf-card{{ background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.12); border-radius:12px;
    padding:10px; text-decoration:none; color:var(--white); display:flex; flex-direction:column; gap:8px;
    font-size:13px; font-weight:600; transition:transform .15s, border-color .15s; }}
  .pdf-card:hover{{ transform:translateY(-2px); border-color:var(--accent); }}
  .pdf-card img{{ width:100%; border-radius:8px; display:block; }}
  .pdf-empty{{ color:var(--gray); font-size:13px; }}
</style>
</head>
<body>
  <h1>Poland <span>Schools</span></h1>
  <p class="subtitle">Find your child&rsquo;s school below for this month&rsquo;s breakfast and lunch menu.</p>

  <div class="schools">{''.join(school_sections)}</div>
</body>
</html>
"""
    (SITE / "index.html").write_text(page)
    print("  Landing page built: site/index.html")


if __name__ == "__main__":
    build_feed_pages()
    build_embed_fragments()
    build_embed_guide()
    build_index_page()
    print("Accessible pages built.")
