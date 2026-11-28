# Rebuild events.json from the workbook's "Combined Data" tab.
#   python src/import_workbook.py "Manual Load Dropping in Iloilo City.xlsx" [--dry-run] [--allow-removals]
# Then run build.py. Standard library only: an .xlsx is a zip of XML.
#
# Failsafes:
#   - Every row is checked (see checks.py). Any error stops the import and
#     src/events.json is left as it was.
#   - The change against the current events.json is printed: added, changed, removed.
#   - Rows that would disappear stop the import unless --allow-removals is given,
#     because a short or filtered workbook would otherwise wipe real outages.
#   - --dry-run checks and prints the change without writing anything.
#   - The previous events.json is kept as src/events.json.bak.
import argparse, datetime, json, pathlib, shutil, sys, zipfile, xml.etree.ElementTree as ET

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from checks import check_events, diff_events, hhmm, label  # noqa: E402

M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
SHEET = "Combined Data"
COLUMNS = ["Date", "Feeder", "Offline Time", "Online Time", "Duration"]
here = pathlib.Path(__file__).parent


class Stop(Exception):
    pass


def read_sheet(path, name):
    try:
        z = zipfile.ZipFile(path)
    except FileNotFoundError:
        raise Stop(f"{path}: file not found")
    except zipfile.BadZipFile:
        raise Stop(f"{path}: not an .xlsx file (save it as Excel Workbook, not .xls or .csv)")
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    sheets = list(ET.fromstring(z.read("xl/workbook.xml")).iter(M + "sheet"))
    sheet = next((s for s in sheets if s.get("name") == name), None)
    if sheet is None:
        raise Stop(f"no {name!r} tab. Tabs found: {', '.join(s.get('name') for s in sheets)}")
    strings = []
    if "xl/sharedStrings.xml" in z.namelist():
        strings = ["".join(t.text or "" for t in si.iter(M + "t")) for si in ET.fromstring(z.read("xl/sharedStrings.xml"))]
    target = rels[sheet.get(R)]
    target = target.removeprefix("/xl/") if target.startswith("/xl/") else target
    rows = []
    for row in ET.fromstring(z.read("xl/" + target)).iter(M + "row"):
        cells = {}
        for c in row:
            col = "".join(ch for ch in c.get("r") if ch.isalpha())
            v = c.find(M + "v")
            if c.get("t") == "inlineStr":
                cells[col] = "".join(t.text or "" for t in c.iter(M + "t"))
            elif v is not None:
                cells[col] = strings[int(v.text)] if c.get("t") == "s" else v.text
        rows.append(cells)
    return rows


def to_minute(v, what):
    """Excel time (fraction of a day) to minutes. Text times are refused, not guessed."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{what} is {v!r}, not an Excel time. Format the cell as Time")
    if x >= 1:  # a date-time cell: keep the time part
        x -= int(x)
    return round(x * 1440)


def to_day(v):
    try:
        return (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(float(v)))).isoformat()
    except (TypeError, ValueError):
        raise ValueError(f"Date is {v!r}, not an Excel date. Format the cell as Date")


def parse(rows, notes):
    if not rows:
        raise Stop(f"the {SHEET!r} tab is empty")
    head = {str(v).strip(): k for k, v in rows[0].items()}
    missing = [c for c in COLUMNS if c not in head]
    if missing:
        raise Stop(f"header row is missing {', '.join(missing)}. Found: {', '.join(head) or 'nothing'}")
    col = lambda r, name: r.get(head[name])
    events, bad, where = [], [], []
    for n, r in enumerate(rows[1:], start=2):
        if not col(r, "Date") and not col(r, "Feeder"):
            continue  # blank row
        if not col(r, "Date") or not col(r, "Feeder"):
            bad.append(f"row {n}: has a {'Feeder' if col(r, 'Feeder') else 'Date'} but no {'Date' if col(r, 'Feeder') else 'Feeder'}")
            continue
        try:
            day = to_day(col(r, "Date"))
            f = " ".join(str(col(r, "Feeder")).split())
            if col(r, "Online Time") in (None, ""):
                raise ValueError("no Online Time. Ongoing outages go in the volunteer sheet, not the workbook")
            s, e = to_minute(col(r, "Offline Time"), "Offline Time"), to_minute(col(r, "Online Time"), "Online Time")
            dur = None if col(r, "Duration") in (None, "") else to_minute(col(r, "Duration"), "Duration")
        except ValueError as x:
            bad.append(f"row {n}: {x}")
            continue
        if e < s and s - e > 720:  # back on after midnight
            e += 1440
        if dur is None:
            notes.append(f"row {n}: {day} {f}: no Duration, so the offline time could not be cross-checked")
        elif abs((e - s) - dur) > 1:
            # a mistyped time: trust online time and duration (e.g. Molo F3, Aug 27: 3:21 AM for PM)
            notes.append(f"row {n}: {day} {f}: offline {hhmm(s)} does not match the {dur // 60}h {dur % 60}m duration, using {hhmm(e - dur)}")
            s = e - dur
        events.append([day, f, s, e])
        where.append(n)
    if bad:
        raise Stop("rows that could not be read:\n  " + "\n  ".join(bad))
    if not events:
        raise Stop(f"the {SHEET!r} tab has a header but no outages")
    return events, where


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("xlsx")
    ap.add_argument("--dry-run", action="store_true", help="check and show the change, write nothing")
    ap.add_argument("--allow-removals", action="store_true", help="let outages that are in events.json but not in the workbook be dropped")
    ap.add_argument("--today", help=argparse.SUPPRESS)  # tests only
    a = ap.parse_args(argv)
    out = here / "events.json"
    notes = []
    try:
        events, where = parse(read_sheet(a.xlsx, SHEET), notes)
        feeders = json.loads((here / "geo.json").read_text(encoding="utf8"))["F"]["feeders"]
        today = datetime.date.fromisoformat(a.today) if a.today else None
        errors, warnings = check_events(events, feeders, today, where)
        for x in notes:
            print("fixed:", x)
        for x in warnings:
            print("check:", x)
        if errors:
            raise Stop("the workbook has problems:\n  " + "\n  ".join(errors))
        old = json.loads(out.read_text(encoding="utf8")) if out.exists() else []
        added, removed, changed = diff_events(old, events)
        print(f"change: {len(added)} added, {len(changed)} changed, {len(removed)} removed")
        for e in added:
            print("  + " + label(e))
        for o, n in changed:
            print(f"  ~ {label(o)}  ->  {label(n)}")
        for e in removed:
            print("  - " + label(e))
        if removed and not a.allow_removals:
            raise Stop(f"{len(removed)} outages in src/events.json are not in the workbook. "
                       "If the workbook is complete and they really should go, run again with --allow-removals")
        if a.dry_run:
            print("dry run: nothing written")
            return 0
        if old == events:
            print("no change: src/events.json already matches")
            return 0
        if out.exists():
            shutil.copyfile(out, here / "events.json.bak")
        out.write_text(json.dumps(events, separators=(",", ":")), encoding="utf8")
        print(len(events), "outages,", len({x[0] for x in events}), "days, written to src/events.json (old copy: src/events.json.bak)")
        return 0
    except Stop as x:
        print("STOPPED:", x, file=sys.stderr)
        print("src/events.json was not changed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
