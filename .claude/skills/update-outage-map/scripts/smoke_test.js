// Open the built page in headless Chromium and check it really works.
//   node .claude/skills/update-outage-map/scripts/smoke_test.js [index.html] [screenshot.png]
// Exits 1 if the page throws, the map never draws, or the subtitle does not
// match src/events.json. Web-font failures are ignored (the page works offline).
const path = require("path"), fs = require("fs");
const { chromium } = require("playwright");
const root = path.resolve(__dirname, "../../../..");
const page_ = path.resolve(process.argv[2] || path.join(root, "index.html"));
const shot = process.argv[3];
const events = JSON.parse(fs.readFileSync(path.join(root, "src/events.json"), "utf8"));
const want = `${new Set(events.map(e => e[1])).size} feeders · ${events.length} outages`;
(async () => {
  const browser = await chromium.launch();
  const p = await browser.newPage({ viewport: { width: 1280, height: 860 } });
  const errors = [];
  p.on("pageerror", e => errors.push("page error: " + e.message));
  p.on("console", m => { if (m.type() === "error" && !/font|fonts\.g|ERR_|net::/i.test(m.text())) errors.push("console: " + m.text()); });
  await p.goto("file://" + page_, { waitUntil: "load", timeout: 60000 });
  await p.waitForTimeout(2500);
  const sub = (await p.textContent("#sub").catch(() => "")) || "";
  const paths = await p.locator(".leaflet-overlay-pane path").count();
  if (shot) await p.screenshot({ path: shot });
  await browser.close();
  const fails = [...errors];
  if (!sub.includes(want)) fails.push(`subtitle is "${sub}", expected it to contain "${want}"`);
  if (paths < 100) fails.push(`only ${paths} map shapes drawn, expected the 180 barangays`);
  console.log(`subtitle: ${sub}\nmap shapes: ${paths}`);
  if (fails.length) { console.log("SMOKE TEST FAILED:\n  " + fails.join("\n  ")); process.exit(1); }
  console.log("smoke test passed");
})().catch(e => { console.log("SMOKE TEST FAILED: " + e.message); process.exit(1); });
