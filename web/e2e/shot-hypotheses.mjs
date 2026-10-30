// Capture du cas de base avec le panneau « Hypothèses marché » ouvert.
// Usage : TWIN_UI_URL=http://localhost:5173 SHOT=chemin.png node web/e2e/shot-hypotheses.mjs
import { chromium } from "playwright";

const URL = process.env.TWIN_UI_URL ?? "http://localhost:5173/";
const browser = await chromium.launch({
  executablePath: process.env.PLAYWRIGHT_CHROMIUM || undefined,
  args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
});
const page = await browser.newPage({ viewport: { width: 1600, height: 2000 } });
await page.goto(URL, { waitUntil: "networkidle" });
await page.waitForSelector("text=Cockpit financier", { timeout: 180000 });
await page.waitForFunction(() => document.body.innerText.includes("terminé") && !document.body.innerText.includes("provisoire"),
                           null, { timeout: 120000 });
await page.getByRole("button", { name: /Hypothèses marché/ }).click();
await page.waitForTimeout(1500);
await page.screenshot({ path: process.env.SHOT ?? "hypotheses.png", fullPage: false });
await browser.close();
