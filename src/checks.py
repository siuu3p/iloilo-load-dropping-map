# Data checks shared by import_workbook.py and build.py. Standard library only.
#
# check_events() returns (errors, warnings). Errors mean the data would put
# something false or broken on the map, so callers refuse to write or build.
# Warnings are things a person should look at but that can be real.
import datetime, re

DAY = 1440
EARLY = 6 * 60  # offline before 6:00 AM: load dropping here has been afternoon/evening, so suspect AM/PM
LONG = 12 * 60  # an outage over 12 hours is possible but worth a look


def hhmm(m):
    m %= DAY
    return f"{m // 60:02d}:{m % 60:02d}"


def label(e):
    return f"{e[0]} {e[1]} {hhmm(e[2])}-{hhmm(e[3])}"


def check_events(events, feeders, today=None, rows=None):
    """rows: optional workbook row number per event, used in messages."""
    errors, warnings = [], []
    today = today or datetime.date.today()
    good = []
    for i, e in enumerate(events):
        where = f"row {rows[i]}" if rows else f"event {i}"
        if not (isinstance(e, list) and len(e) == 4):
            errors.append(f"{where}: expected [date, feeder, offline minute, online minute], got {e!r}")
            continue
        day, f, s, t = e
        try:
            d = datetime.date.fromisoformat(day)
        except (TypeError, ValueError):
            errors.append(f"{where}: bad date {day!r}, want YYYY-MM-DD")
            continue
        if not all(isinstance(x, int) and not isinstance(x, bool) for x in (s, t)):
            errors.append(f"{where}: {day} {f}: times must be whole minutes, got {s!r}, {t!r}")
            continue
        if not isinstance(f, str) or f not in feeders:
            errors.append(f"{where}: {day}: unknown feeder {f!r}. Fix the spelling in the workbook, or if it is a new feeder, add it to src/geo.json with its barangays from a MORE Power coverage post")
            continue
        if not 0 <= s < DAY:
            errors.append(f"{where}: {label(e)}: offline minute {s} is outside the day (0-1439)")
            continue
        if t <= s:
            errors.append(f"{where}: {label(e)}: back online before it went offline")
            continue
        if t > 2 * DAY:
            errors.append(f"{where}: {label(e)}: online minute {t} is more than a day after the date")
            continue
        if d > today:
            errors.append(f"{where}: {label(e)}: dated in the future (today is {today})")
            continue
        if s < EARLY:
            warnings.append(f"{label(e)}: goes offline before 6:00 AM. Check for an AM/PM mix-up")
        if t - s > LONG:
            warnings.append(f"{label(e)}: lasts {(t - s) // 60}h {(t - s) % 60}m. Check the online time")
        good.append((d, e))

    seen = set()
    for _, e in good:
        k = tuple(e)
        if k in seen:
            errors.append(f"{label(e)}: listed twice")
        seen.add(k)

    # same feeder dark twice at once: one of the two rows is wrong
    spans = {}
    for d, e in good:
        base = (d - datetime.date(2000, 1, 1)).days * DAY
        spans.setdefault(e[1], []).append((base + e[2], base + e[3], e))
    for f, xs in spans.items():
        xs.sort(key=lambda x: (x[0], x[1]))
        for a, b in zip(xs, xs[1:]):
            if b[0] < a[1] and tuple(a[2]) != tuple(b[2]):
                errors.append(f"{f}: {label(a[2])} overlaps {label(b[2])}")
    return errors, warnings


def diff_events(old, new):
    """Compare two event lists keyed on (date, feeder, offline minute)."""
    key = lambda e: (e[0], e[1], e[2])
    o, n = {key(e): e for e in old}, {key(e): e for e in new}
    added = [n[k] for k in n.keys() - o.keys()]
    removed = [o[k] for k in o.keys() - n.keys()]
    changed = [(o[k], n[k]) for k in o.keys() & n.keys() if o[k] != n[k]]
    return sorted(added), sorted(removed), sorted(changed)


def summary(events):
    days = sorted({e[0] for e in events})
    d0, d1 = datetime.date.fromisoformat(days[0]), datetime.date.fromisoformat(days[-1])
    every = {(d0 + datetime.timedelta(n)).isoformat() for n in range((d1 - d0).days + 1)}
    return {
        "outages": len(events),
        "feeders": len({e[1] for e in events}),
        "first": d0, "last": d1,
        "missing": sorted(every - set(days)),
    }


def short(d):
    return f"{d:%b} {d.day}"


def stale_text(template, events):
    """Hand-written lines in the template that no longer match the data."""
    s = summary(events)
    out = []
    want = f"{s['outages']} outages across {s['feeders']} feeders"
    for m in re.finditer(r"(\d+) outages across (\d+) feeders", template):
        if m.group(0) != want:
            out.append(f"meta/OG text says {m.group(0)!r}, data says {want!r}")
    rng = f"{short(s['first'])} to {short(s['last'])}, {s['last'].year}"
    for m in re.finditer(r"[A-Z][a-z]{2} \d{1,2} to [A-Z][a-z]{2} \d{1,2}, \d{4}", template):
        if m.group(0) != rng:
            out.append(f"meta/OG text says {m.group(0)!r}, data says {rng!r}")
    sub = f"{s['feeders']} feeders · {s['outages']} outages · {short(s['first'])} – {short(s['last'])}, {s['last'].year}"
    m = re.search(r'id="sub">([^<]*?) · Source', template)
    if m and m.group(1) != sub:
        out.append(f"no-JS subtitle says {m.group(1)!r}, data says {sub!r}")
    m = re.search(r"No posts were logged for ([^.]*)\.", template)
    if m:
        miss = [datetime.date.fromisoformat(x) for x in s["missing"]]
        if not miss:
            out.append(f"About says 'No posts were logged for {m.group(1)}' but every day now has data")
        else:
            got = set(map(int, re.findall(r"\d+", m.group(1))))
            if got != {d.day for d in miss}:
                out.append(f"About says no posts for {m.group(1)!r}, data is missing {', '.join(short(d) for d in miss)}")
    return out


def stale_readme(readme, events):
    """Counts and date range written into README.md that no longer match the data."""
    s = summary(events)
    out = []
    want = f"{s['outages']} outages across {s['feeders']} feeders"
    for m in re.finditer(r"(\d+) outages across (\d+) feeders", readme):
        if m.group(0) != want:
            out.append(f"README.md says {m.group(0)!r}, data says {want!r}")
    rng = f"{short(s['first'])} – {short(s['last'])}, {s['last'].year}"
    for m in re.finditer(r"[A-Z][a-z]{2} \d{1,2} – [A-Z][a-z]{2} \d{1,2}, \d{4}", readme):
        if m.group(0) != rng:
            out.append(f"README.md says {m.group(0)!r}, data says {rng!r}")
    return out
