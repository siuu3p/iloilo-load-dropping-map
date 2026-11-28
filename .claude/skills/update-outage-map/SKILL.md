---
name: update-outage-map
description: Update the Iloilo City load dropping map with new outages and rebuild it safely. Use whenever someone wants to add new MORE Power load dropping posts, import or re-import the "Manual Load Dropping in Iloilo City" workbook, fix an outage time, add a feeder, refresh index.html, or says the map is out of date, even if they only say "update the map", "add Sep 16", "may bagong brownout" or paste a MORE Power post. Also use when they ask to put outage data straight into events.json, since that path skips the checks.
---

# Update the outage map

This repo publishes a public map of MORE Power's manual load dropping in Iloilo City. People use it to see how long their barangay went without power, and it gets shared on Facebook. A wrong time or an invented outage is worse than a missing one: it spreads, and it undercuts the whole map. So the job here is not just "get new rows in". It is **get only sourced rows in, show the person exactly what changed, and stop when the data looks wrong.**

The scripts already enforce most of this. Your part is to run them in the right order, read what they print, and bring the person every decision that is theirs.

## The pipeline

```
workbook (.xlsx, "Combined Data" tab)
  -> python src/import_workbook.py <xlsx> --dry-run     # check + show the change, writes nothing
  -> python src/import_workbook.py <xlsx>               # writes src/events.json (old copy in events.json.bak)
  -> python src/build.py                                # checks again, writes index.html, prints STALE lines
  -> fix STALE text in src/template2.html, build again
  -> node .claude/skills/update-outage-map/scripts/smoke_test.js   # page loads, map draws, counts match
  -> python -m unittest discover tests                  # only if you touched a script
```

`index.html` and `src/events.json` are generated. Do not edit either by hand, even for a one-row fix: hand edits skip every check below, and the next import overwrites them anyway. The fix belongs in the workbook (or, for a live correction, the volunteer sheet).

## Step by step

### 1. Find the input and its source

You need the workbook path. If the person pasted a MORE Power post or typed times instead, do not invent a workbook row from it yourself and do not write it into `events.json`. Tell them the row to add to the workbook's Combined Data tab (Date, Feeder, Offline Time, Online Time, Duration), formatted as Excel date/time cells, and ask them to send the updated file.

Only MORE Power's own posts count as a source. If the outage came from a neighbour, a comment, a group chat or "I think", say it can't go on the map as an official drop and suggest the volunteer sheet if they run one. Ask; don't decide for them.

### 2. Dry run first, always

```bash
python src/import_workbook.py "<workbook>.xlsx" --dry-run
```

Read every line. It prints four kinds:

| Prefix | Meaning | What you do |
|---|---|---|
| `STOPPED:` | Data would be wrong or lost. Nothing was written. | Go to step 3. Do not work around it. |
| `fixed:` | The importer corrected an offline time from the duration (usually an AM/PM typo). | Tell the person each one, with the row number, and ask them to fix the workbook cell too so the source is right. |
| `check:` | Allowed but unusual (offline before 6 AM, outage over 12h). | List them and ask if they are real. Usually fine to continue if the person confirms. |
| `change:` + `+ ~ -` lines | Added, changed, removed outages vs the current map. | Show this to the person. It is the real summary of the update. |

### 3. When it stops

Every stop is a question for the person, not a puzzle for you to solve. Report the exact message, your best guess at the cause, and the choice they need to make. Do not edit the workbook, `events.json` or `geo.json` to make the error go away.

- **Unknown feeder**: either a typo or a new feeder. If one known feeder in `src/geo.json` is an obvious match, name it and ask them to fix the workbook. If it might be new, say so: a new feeder needs its barangay list from a MORE Power coverage post before it goes in `geo.json`. Never add a feeder with guessed barangays. The shading tells people their area was hit; a guess there is a false statement on the map.
- **Outages would be removed**: usually the workbook is filtered, truncated or an old copy. List how many and the date range they cover. Only rerun with `--allow-removals` after the person says, in this conversation, that those outages really should go (for example MORE Power retracted a post). A general "just make it work" is not that.
- **Overlap / listed twice**: two rows for the same feeder at once. One is wrong. Show both and ask which.
- **Future date, text time, missing column, wrong tab, not an .xlsx**: say what the file needs (the message names the row) and ask for a fixed copy.

If the person wants to override a stop in a way the scripts don't offer, explain what the check protects and that you'd rather they fix the source. Do not add a bypass flag, comment out a check, or loosen a threshold to get a run through. Changing a check is a separate, deliberate code change: do it only if they ask for that specifically, and run the tests after.

### 4. Import for real

When the dry run is clean (or every `fixed:`/`check:` line is acknowledged), run it without `--dry-run`. If the person already said "go ahead" for this update and there was nothing to raise, you don't need a second round of confirmation for this step.

### 5. Build and fix stale text

```bash
python src/build.py
```

The subtitle, date range and headline update themselves. Some lines are hand-written in `src/template2.html` and the build prints `STALE:` for each one that no longer matches the data: the meta description, `og:description`, the no-JS subtitle, and the About line "No posts were logged for ...". Update those to match the numbers the build printed (`data: N outages, N feeders, ...`), keep the existing wording and style, and build again until no `STALE:` lines remain.

Things the build can't check, which you should still look at and mention:
- **`og.jpg`**, the Facebook share image. It shows old numbers. You can't regenerate it reliably; tell the person it needs a new screenshot.
- **About notes** that describe specific data fixes (like the Molo F3 AM/PM note). If this import added a new `fixed:` correction, suggest a matching About line, and add it if they agree.
- **Hiligaynon labels** (`HIL` table) don't need changes for new data. The About section is English only.

### 6. Verify the page

```bash
node .claude/skills/update-outage-map/scripts/smoke_test.js index.html
```

It fails if the page throws an error, the map doesn't draw, or the subtitle counts don't match `events.json`. A build that passes but a page that's broken is still broken, so don't report success before this passes. If Playwright isn't available, say the page wasn't checked in a browser.

### 7. Report

End with a short report the person can act on. Keep this order, and keep it honest: if a step was skipped or failed, say so.

```
Map updated: <before> -> <after> outages, <first> to <last>.
Added: <n> (<dates>)   Changed: <n>   Removed: <n>
Auto-fixed times: <row, feeder, what changed>   (or "none")
Needs a look: <check: lines, og.jpg, About note suggestions>
Checks: import ok, build ok, stale text fixed, smoke test passed   (or what failed)
Next: <e.g. "fix row 201 in the workbook", "commit and push when ready">
```

## Things that need the person's yes first

- Committing or pushing (the live site is GitHub Pages, so a push publishes). Never commit the workbook or `src/events.json.bak`.
- `--allow-removals`.
- Adding or changing a feeder in `src/geo.json` or `feeder-coverage.json`.
- Setting `SHEET_CSV` in the template. The volunteer feed is public-facing and anyone with the form link can submit; only use a URL the person gives you.
- Changing any check in `src/checks.py`, `import_workbook.py` or `build.py`.

## Volunteer sheet questions

If someone asks why a volunteer report isn't showing, the page's rules are in the README ("Live volunteer feed"). Bad rows are skipped in the browser console, not by these scripts. A volunteer row with the same date, feeder and time off as a built-in outage replaces it, which is how live corrections work without a rebuild.
