import { chromium } from "file:///C:/Users/cuiya/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs";
import { mkdir } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import path from "node:path";

const root = path.resolve(import.meta.dirname);
const source = pathToFileURL(path.join(root, "faculty-crawler-ui-mockups.html")).href;
const output = path.join(root, "renders");
const pages = ["overview", "tasks", "verification", "runs", "sessions", "settings", "storage", "newrun"];

await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  executablePath: "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
});
for (const pageName of pages) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  await page.goto(`${source}?page=${pageName}&capture=1`, { waitUntil: "load" });
  await page.screenshot({ path: path.join(output, `${pageName}.png`) });
  await page.close();
}
await browser.close();
