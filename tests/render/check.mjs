// Open the generated HTML headlessly and assert: every node is inside the viewport after the
// initial fit, and selecting a project in the sidebar updates the state counts, the checks
// panel and the table consistently. Usage: node check.mjs <path-to-html>
import { chromium } from "playwright";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";

const file = process.argv[2];
if (!file) { console.error("usage: node check.mjs <html>"); process.exit(2); }
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
const errors = [];
page.on("pageerror", e => errors.push(String(e)));
await page.goto(pathToFileURL(resolve(file)).href);
await page.waitForSelector("#g .node");

const fail = msg => { console.error("FAIL:", msg); process.exitCode = 1; };

const inside = await page.evaluate(() => {
  const box = document.querySelector("#g").getBoundingClientRect();
  return [...document.querySelectorAll("#g .node circle")].map(p => {
    const r = p.getBoundingClientRect();
    return r.left >= box.left - 1 && r.right <= box.right + 1 && r.top >= box.top - 1 && r.bottom <= box.bottom + 1;
  });
});
if (!inside.length) fail("no nodes rendered");
const out = inside.filter(x => !x).length;
if (out) fail(`${out} of ${inside.length} nodes outside the viewport`);

const projects = await page.$$eval("#side button[data-key]", bs => bs.map(b => b.dataset.key).filter(Boolean));
if (projects.length < 2) fail("sidebar lists fewer than two projects");
for (const key of projects) {
  await page.click(`#side button[data-key="${key}"]`);
  const stateFiles = await page.$eval("#states", el => Number(el.textContent.match(/files\s+(\d+)/)[1]));
  const tableRows = await page.$$eval("#table tbody tr", rows => rows.filter(r => !r.textContent.includes("Missing")).length);
  const panelFiles = await page.$eval("#issues tbody tr td:nth-child(2)", td => Number(td.textContent));
  if (stateFiles !== tableRows || stateFiles !== panelFiles) fail(`${key}: states=${stateFiles} table=${tableRows} checks=${panelFiles} disagree`);
}
if (errors.length) fail("page errors: " + errors.join(" | "));
await browser.close();
if (!process.exitCode) console.log(`ok: ${inside.length} nodes in view, ${projects.length} projects in sync`);
