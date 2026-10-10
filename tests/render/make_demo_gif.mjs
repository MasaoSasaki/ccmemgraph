// Record the README GIF from the demo data: graph, hover, one project, checks, table.
// Usage: node make_demo_gif.mjs <html> <out.gif> [frames-dir]
import { chromium } from "playwright";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";
import { mkdirSync, writeFileSync } from "node:fs";
import { PNG } from "pngjs";
import gifenc from "gifenc";
const { GIFEncoder, quantize, applyPalette } = gifenc;

const [html, outGif, framesDir = "out/frames"] = process.argv.slice(2);
if (!html || !outGif) { console.error("usage: node make_demo_gif.mjs <html> <out.gif> [frames-dir]"); process.exit(2); }
mkdirSync(framesDir, { recursive: true });
const W = 1000, H = 620;
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
await page.goto(pathToFileURL(resolve(html)).href);
await page.waitForSelector("#g .node");
await page.waitForTimeout(800);

const gif = GIFEncoder();
let n = 0;
async function frame(delayMs, name) {
  const buf = await page.screenshot({ type: "png" });
  writeFileSync(`${framesDir}/${String(++n).padStart(2, "0")}-${name}.png`, buf);
  const { data, width, height } = PNG.sync.read(buf);
  const palette = quantize(data, 256);
  const index = applyPalette(data, palette);
  gif.writeFrame(index, width, height, { palette, delay: delayMs });
}

await frame(2200, "all-projects");
// hover the biggest node so the tooltip shows the state, age and description
const bigIndex = await page.evaluate(() => { const cs = [...document.querySelectorAll("#g .node circle")]; return cs.indexOf(cs.slice().sort((a, b) => +b.getAttribute("r") - +a.getAttribute("r"))[0]); });
await page.locator("#g .node circle").nth(bigIndex).hover();
await page.waitForTimeout(300);
await frame(2200, "hover");
await page.mouse.move(5, 5);
await page.click('#side button[data-key="-home-demo-Projects-beta"]');
await page.waitForTimeout(600);
await frame(2000, "one-project");
await page.click("#btn-issues");
await page.waitForTimeout(300);
await frame(2600, "checks");
await page.click("#btn-table");
await page.waitForTimeout(300);
await frame(2000, "table");
await page.click("#btn-table");
await page.click('#side button[data-key=""]');
await page.waitForTimeout(600);
await frame(1400, "all-again");
gif.finish();
writeFileSync(outGif, gif.bytes());
await browser.close();
console.log(`wrote ${outGif} (${(gif.bytes().length / 1024).toFixed(0)} KB, ${n} frames)`);
