# Rebuild events.json from the workbook's "Combined Data" tab.
#   python src/import_workbook.py "Manual Load Dropping in Iloilo City.xlsx"
# Then run build.py. Standard library only: an .xlsx is a zip of XML.
import datetime, json, pathlib, sys, zipfile, xml.etree.ElementTree as ET

M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
here = pathlib.Path(__file__).parent


def read_sheet(path, name):
    z = zipfile.ZipFile(path)
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    sheet = next(s for s in ET.fromstring(z.read("xl/workbook.xml")).iter(M + "sheet") if s.get("name") == name)
    strings = []
    if "xl/sharedStrings.xml" in z.namelist():
        strings = ["".join(t.text or "" for t in si.iter(M + "t")) for si in ET.fromstring(z.read("xl/sharedStrings.xml"))]
    rows = []
    for row in ET.fromstring(z.read("xl/" + rels[sheet.get(R)].removeprefix("/xl/"))).iter(M + "row"):
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


def main(xlsx):
    rows = read_sheet(xlsx, "Combined Data")
    head = {v: k for k, v in rows[0].items()}
    col = lambda r, name: r.get(head[name])
    feeders = json.loads((here / "geo.json").read_text(encoding="utf8"))["F"]["feeders"]
    minute = lambda frac: round(float(frac) * 1440)
    events = []
    for n, r in enumerate(rows[1:], start=2):
        if not col(r, "Date") or not col(r, "Feeder"):
            continue
        day = (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(float(col(r, "Date"))))).isoformat()
        f, s, e, dur = col(r, "Feeder").strip(), minute(col(r, "Offline Time")), minute(col(r, "Online Time")), minute(col(r, "Duration"))
        if e < s and s - e > 720:  # back on after midnight
            e += 1440
        if abs((e - s) - dur) > 1:  # a mistyped time: trust online time and duration (e.g. Molo F3, Aug 27: 3:21 AM for PM)
            print(f"row {n}: {day} {f} offline {s // 60:02d}:{s % 60:02d} does not match duration, using {(e - dur) // 60:02d}:{(e - dur) % 60:02d}")
            s = e - dur
        if f not in feeders:
            print(f"row {n}: unknown feeder {f!r}, add it to geo.json")
        events.append([day, f, s, e])
    (here / "events.json").write_text(json.dumps(events, separators=(",", ":")), encoding="utf8")
    print(len(events), "outages,", len({x[0] for x in events}), "days, written to src/events.json")


if __name__ == "__main__":
    main(sys.argv[1])
