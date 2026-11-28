# Rebuild ../index.html from the template, data and base image in this folder.
#   python src/build.py [--check]
# --check builds in memory and reports, without writing index.html.
#
# Failsafes:
#   - events.json and geo.json must parse and pass checks.py, or nothing is built.
#   - The built page must have no leftover placeholders and a sane size.
#   - Hand-written text in template2.html (meta/OG description, no-JS subtitle,
#     About "No posts were logged for ...") and README.md counts is compared with the data and any
#     mismatch is printed as STALE. og.jpg cannot be checked: look at it yourself.
import base64, json, pathlib, sys

here = pathlib.Path(__file__).parent
sys.path.insert(0, str(here))
from checks import check_events, stale_readme, stale_text, summary  # noqa: E402

PLACEHOLDERS = ["__LEAFLETCSS__", "__EVENTS__", "__GEO__", "__IMG__", "__LEAFLETJS__"]
MIN_KB, MAX_KB = 1500, 8000  # current page is about 2.7 MB


def fail(msg):
    print("BUILD STOPPED:", msg, file=sys.stderr)
    print("index.html was not changed.", file=sys.stderr)
    sys.exit(1)


def main(argv):
    read = lambda n: (here / n).read_text(encoding="utf8")
    template = read("template2.html")
    missing = [p for p in PLACEHOLDERS if p not in template]
    if missing:
        fail(f"template2.html lost placeholder(s) {', '.join(missing)}")
    try:
        events, geo = json.loads(read("events.json")), json.loads(read("geo.json"))
        feeders = geo["F"]["feeders"]
    except (ValueError, KeyError) as x:
        fail(f"events.json or geo.json is not valid: {x}")
    if not events:
        fail("events.json has no outages")
    errors, warnings = check_events(events, feeders)
    if errors:
        fail("events.json has problems:\n  " + "\n  ".join(errors))
    for w in warnings:
        print("check:", w)

    html = (template
            .replace("__LEAFLETCSS__", read("leaflet.css"))
            .replace("__EVENTS__", read("events.json"))
            .replace("__GEO__", read("geo.json"))
            .replace("__IMG__", "data:image/webp;base64," + base64.b64encode((here / "base.webp").read_bytes()).decode()))
    if "__" in html.split('<script type="module">')[-1][:200]:
        fail("unreplaced placeholder at the top of the module script")
    # Leaflet goes in last so the replacements above never scan its source
    html = html.replace("__LEAFLETJS__", read("leaflet.js"))
    left = [p for p in PLACEHOLDERS if p in html]
    if left:
        fail(f"unreplaced placeholder(s) {', '.join(left)}")
    kb = len(html.encode("utf8")) // 1024
    if not MIN_KB <= kb <= MAX_KB:
        fail(f"built page is {kb} KB, expected {MIN_KB}-{MAX_KB} KB. Is base.webp or leaflet.js missing or replaced?")

    stale = stale_text(template, events)
    readme = here.parent / "README.md"
    if readme.exists():
        stale += stale_readme(readme.read_text(encoding="utf8"), events)
    for s in stale:
        print("STALE:", s)
    s = summary(events)
    print(f"data: {s['outages']} outages, {s['feeders']} feeders, {s['first']} to {s['last']}"
          + (f", no data for {', '.join(s['missing'])}" if s["missing"] else ""))
    if "--check" in argv:
        print("check only:", kb, "KB, index.html not written")
    else:
        (here.parent / "index.html").write_text(html, encoding="utf8")
        print("built", kb, "KB")
    if stale:
        print(f"{len(stale)} hand-written line(s) in src/template2.html or README.md are out of date. Fix them, then build again. "
              "Also check og.jpg and the About notes.")


if __name__ == "__main__":
    main(sys.argv[1:])
