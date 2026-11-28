# python -m unittest discover tests
# Each test copies src/ to a temp folder and runs the real scripts there,
# so the repo's own events.json and index.html are never touched.
import datetime, json, pathlib, shutil, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from checks import check_events, diff_events, stale_text  # noqa: E402
from xlsx_fixture import COLUMNS, frac, serial, workbook_from_events, write_xlsx  # noqa: E402

EVENTS = json.loads((ROOT / "src/events.json").read_text(encoding="utf8"))
FEEDERS = json.loads((ROOT / "src/geo.json").read_text(encoding="utf8"))["F"]["feeders"]
TODAY = "2026-11-28"
# a day after the last one in the data, so "new day" tests keep working as real days are added
_next = datetime.date.fromisoformat(max(e[0] for e in EVENTS)) + datetime.timedelta(days=1)
NEXT = _next.isoformat()
NEXT_LABEL = f"{_next:%b} {_next.day}, {_next.year}"


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        shutil.copytree(ROOT / "src", self.tmp / "src")
        self.xlsx = self.tmp / "book.xlsx"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_import(self, *args):
        p = subprocess.run([sys.executable, str(self.tmp / "src/import_workbook.py"), str(self.xlsx), "--today", TODAY, *args],
                           capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr

    def events_now(self):
        return json.loads((self.tmp / "src/events.json").read_text(encoding="utf8"))


class ImportGuardrails(Sandbox):
    def test_round_trip_is_no_change(self):
        workbook_from_events(self.xlsx, EVENTS)
        code, out = self.run_import()
        self.assertEqual(code, 0, out)
        self.assertIn("0 added, 0 changed, 0 removed", out)
        self.assertEqual(self.events_now(), EVENTS)

    def test_new_day_is_added_and_backed_up(self):
        new = [NEXT, "Jaro Feeder 1", 1080, 1170]
        workbook_from_events(self.xlsx, EVENTS + [new])
        code, out = self.run_import()
        self.assertEqual(code, 0, out)
        self.assertIn("1 added", out)
        self.assertEqual(self.events_now()[-1], new)
        self.assertEqual(json.loads((self.tmp / "src/events.json.bak").read_text()), EVENTS)

    def test_dry_run_writes_nothing(self):
        workbook_from_events(self.xlsx, EVENTS + [[NEXT, "Jaro Feeder 1", 1080, 1170]])
        code, out = self.run_import("--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("dry run", out)
        self.assertEqual(self.events_now(), EVENTS)

    def test_unknown_feeder_stops(self):
        workbook_from_events(self.xlsx, EVENTS + [[NEXT, "Jaro Feeder 9", 1080, 1170]])
        code, out = self.run_import()
        self.assertEqual(code, 1)
        self.assertIn("unknown feeder 'Jaro Feeder 9'", out)
        self.assertEqual(self.events_now(), EVENTS)

    def test_missing_rows_stop_without_flag(self):
        workbook_from_events(self.xlsx, EVENTS[:-5])
        code, out = self.run_import()
        self.assertEqual(code, 1)
        self.assertIn("5 outages in src/events.json are not in the workbook", out)
        self.assertEqual(self.events_now(), EVENTS)
        code, out = self.run_import("--allow-removals")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.events_now()), len(EVENTS) - 5)

    def test_ampm_mixup_is_fixed_from_duration(self):
        # typed 3:00 AM, online 4:30 PM, duration 1h30m -> offline should be 3:00 PM
        rows = [COLUMNS] + [[serial(e[0]), e[1], frac(e[2]), frac(e[3]), frac(e[3] - e[2])] for e in EVENTS]
        rows.append([serial(NEXT), "Molo Feeder 1", frac(180), frac(990), frac(90)])
        write_xlsx(self.xlsx, {"Combined Data": rows})
        code, out = self.run_import()
        self.assertEqual(code, 0, out)
        self.assertIn("does not match the 1h 30m duration, using 15:00", out)
        self.assertEqual(self.events_now()[-1], [NEXT, "Molo Feeder 1", 900, 990])

    def test_overlap_stops(self):
        workbook_from_events(self.xlsx, EVENTS + [[NEXT, "Jaro Feeder 1", 1080, 1170],
                                                  [NEXT, "Jaro Feeder 1", 1100, 1200]])
        code, out = self.run_import()
        self.assertEqual(code, 1)
        self.assertIn("overlaps", out)

    def test_future_date_stops(self):
        workbook_from_events(self.xlsx, EVENTS + [["2027-09-16", "Jaro Feeder 1", 1080, 1170]])
        code, out = self.run_import()
        self.assertEqual(code, 1)
        self.assertIn("in the future", out)

    def test_text_time_stops_with_row_number(self):
        rows = [COLUMNS] + [[serial(NEXT), "Jaro Feeder 1", "6:00 PM", frac(1170), frac(90)]]
        write_xlsx(self.xlsx, {"Combined Data": rows})
        code, out = self.run_import()
        self.assertEqual(code, 1)
        self.assertIn("row 2: Offline Time is '6:00 PM', not an Excel time", out)

    def test_wrong_tab_names_tabs_found(self):
        write_xlsx(self.xlsx, {"Sep 16": [COLUMNS]})
        code, out = self.run_import()
        self.assertEqual(code, 1)
        self.assertIn("no 'Combined Data' tab. Tabs found: Sep 16", out)

    def test_missing_column_stops(self):
        write_xlsx(self.xlsx, {"Combined Data": [["Date", "Feeder", "Offline Time", "Online Time"]]})
        code, out = self.run_import()
        self.assertEqual(code, 1)
        self.assertIn("missing Duration", out)

    def test_not_an_xlsx(self):
        self.xlsx.write_text("Date,Feeder\n")
        code, out = self.run_import()
        self.assertEqual(code, 1)
        self.assertIn("not an .xlsx file", out)


class BuildGuardrails(Sandbox):
    def build(self, *args):
        p = subprocess.run([sys.executable, str(self.tmp / "src/build.py"), *args], capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr

    def test_current_data_builds_clean(self):
        code, out = self.build()
        self.assertEqual(code, 0, out)
        self.assertNotIn("STALE", out)
        self.assertEqual((self.tmp / "index.html").read_bytes(), (ROOT / "index.html").read_bytes())

    def test_bad_events_block_build(self):
        (self.tmp / "src/events.json").write_text(json.dumps(EVENTS + [[NEXT, "Nowhere Feeder", 1, 2]]))
        code, out = self.build()
        self.assertEqual(code, 1)
        self.assertIn("BUILD STOPPED", out)
        self.assertFalse((self.tmp / "index.html").exists())

    def test_lost_placeholder_blocks_build(self):
        t = self.tmp / "src/template2.html"
        t.write_text(t.read_text(encoding="utf8").replace("__GEO__", "{}"), encoding="utf8")
        code, out = self.build()
        self.assertEqual(code, 1)
        self.assertIn("__GEO__", out)

    def test_new_day_flags_stale_text(self):
        (self.tmp / "src/events.json").write_text(json.dumps(EVENTS + [[NEXT, "Jaro Feeder 1", 1080, 1170]]))
        code, out = self.build("--check")
        self.assertEqual(code, 0, out)
        self.assertIn(f"{len(EVENTS) + 1} outages across {len({e[1] for e in EVENTS})} feeders", out)
        self.assertIn(NEXT_LABEL, out)
        self.assertFalse((self.tmp / "index.html").exists())


class Checks(unittest.TestCase):
    def test_current_data_is_clean(self):
        self.assertEqual(check_events(EVENTS, FEEDERS, datetime.date(2026, 11, 28)), ([], []))

    def test_early_offline_warns(self):
        errs, warns = check_events([[NEXT, "Jaro Feeder 1", 200, 300]], FEEDERS, datetime.date(2026, 11, 28))
        self.assertEqual(errs, [])
        self.assertIn("AM/PM", warns[0])

    def test_duplicate_errors(self):
        e = [NEXT, "Jaro Feeder 1", 1080, 1170]
        errs, _ = check_events([e, list(e)], FEEDERS, datetime.date(2026, 11, 28))
        self.assertTrue(any("listed twice" in x for x in errs))

    def test_overnight_overlap_across_days(self):
        errs, _ = check_events([["2026-09-16", "Jaro Feeder 1", 1400, 1500],
                                ["2026-09-17", "Jaro Feeder 1", 30, 90]], FEEDERS, datetime.date(2026, 11, 28))
        self.assertTrue(any("overlaps" in x for x in errs))

    def test_diff(self):
        a = [["d", "f", 1, 2], ["d", "f", 5, 6]]
        b = [["d", "f", 1, 3], ["d", "g", 7, 8]]
        self.assertEqual(diff_events(a, b), ([["d", "g", 7, 8]], [["d", "f", 5, 6]], [(["d", "f", 1, 2], ["d", "f", 1, 3])]))

    def test_stale_about_missing_days(self):
        t = '<p class="sub" id="sub">x · Source</p>No posts were logged for Sep 6, 12 and 13.'
        out = stale_text(t, EVENTS + [["2026-09-12", "Jaro Feeder 1", 1080, 1170]])
        self.assertTrue(any("Sep 6, Sep 13" in x for x in out))


if __name__ == "__main__":
    unittest.main()
