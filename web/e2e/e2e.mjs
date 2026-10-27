// Test de bout en bout dans un vrai navigateur (Playwright) contre l'API et l'interface lancées.
// Usage : make e2e   (ou : TWIN_UI_URL=http://localhost:5173 node web/e2e/e2e.mjs)
//
// 1. prix de l'électricité +10 % saisi dans l'inspecteur → OPEX énergie +10,0 %, TRI en baisse ;
// 2. captures de 3 scénarios dans docs/screenshots/ (+ comparaison).
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const SHOTS = resolve(ROOT, "docs/screenshots");
const URL = process.env.TWIN_UI_URL ?? "http://localhost:5173/";
mkdirSync(SHOTS, { recursive: true });

const failures = [];
const check = (ok, label) => {
  console.log(`${ok ? "✔" : "✘"} ${label}`);
  if (!ok) failures.push(label);
};

const confirmed = (page) => page.waitForFunction(
  () => document.body.innerText.includes("terminé") && !document.body.innerText.includes("provisoire"),
  null, { timeout: 120000 }).then(() => page.waitForTimeout(1200));

async function setNumber(page, path, value) {
  const input = page.locator(`#param-${path.replace(/\./g, "-")}`);
  await input.fill(String(value));
  await input.press("Enter");
}

async function kpiText(page, label) {
  return (await page.getByRole("button", { name: new RegExp(`^${label} :`) }).innerText()).replace(/\s+/g, " ");
}

async function save(page, name) {
  await page.getByRole("button", { name: /Sauvegarder/ }).click();
  const input = page.getByLabel("Nom du scénario");
  await input.fill(name);
  await input.press("Enter");
  await page.waitForTimeout(800);
}

const browser = await chromium.launch({
  executablePath: process.env.PLAYWRIGHT_CHROMIUM || undefined,
  args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
});
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
const pageErrors = [];
page.on("pageerror", (e) => pageErrors.push(e.message));

try {
  await page.goto(URL, { waitUntil: "networkidle" });
  await page.waitForSelector("text=Cockpit financier", { timeout: 180000 });
  await confirmed(page);

  // ------------------------------------------------------------------ scénario 1 : cas de base
  await page.screenshot({ path: `${SHOTS}/1-cas-de-base.png` });
  const baseOpex = await kpiText(page, "OPEX énergie année 1");
  check(baseOpex.includes("="), `cas de base : OPEX énergie sans écart (${baseOpex})`);

  // ------------------------------------------------------------------ prix +10 % (bout en bout)
  await page.getByRole("button", { name: "Poste électrique" }).click();
  const price = Number((await page.locator("#param-params-price-flat_usd_per_mwh").inputValue()).replace(",", "."));
  await setNumber(page, "params.price.flat_usd_per_mwh", Math.round(price * 1.1 * 100) / 100);
  await confirmed(page);
  const opex = await kpiText(page, "OPEX énergie année 1");
  const irrEquity = await kpiText(page, "TRI equity");
  const irrProject = await kpiText(page, "TRI projet");
  check(/\+10,0\s%/.test(opex), `prix +10 % → OPEX énergie +10,0 % (${opex})`);
  check(/−\d/.test(irrEquity.split("base")[1] ?? ""), `prix +10 % → TRI equity en baisse (${irrEquity})`);
  check(/−\d/.test(irrProject.split("base")[1] ?? ""), `prix +10 % → TRI projet en baisse (${irrProject})`);
  await page.getByRole("button", { name: "Revenir au cas de base" }).click();
  await confirmed(page);

  // ------------------------------------------------------------------ scénario 2 : densité 30 kW/rack
  await page.getByRole("button", { name: "Halls informatiques" }).click();
  await setNumber(page, "params.geometry.kw_per_rack", 30);
  await confirmed(page);
  const alert = page.getByRole("button", { name: /Appel réseau/ });
  check((await alert.count()) > 0, "30 kW/rack → alerte de dépassement de la capacité réseau");
  await save(page, "Densité 30 kW/rack");
  await alert.first().click();
  await page.waitForTimeout(1500);
  check(await page.getByRole("heading", { name: "Poste électrique" }).isVisible(),
        "clic sur l'alerte → inspecteur du poste électrique");
  await page.getByRole("button", { name: "Halls informatiques" }).click();
  await page.getByRole("button", { name: "Vue d'ensemble" }).click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${SHOTS}/2-densite-30kw.png` });

  // ------------------------------------------------------------------ scénario 3 : liquide + batterie + HP/HC + refinancement
  await page.getByRole("button", { name: "Revenir au cas de base" }).click();
  await page.getByRole("button", { name: "Centrale de refroidissement" }).click();
  await page.getByLabel("Type de refroidissement").click();
  await page.getByRole("option", { name: /Liquide/ }).click();
  await page.getByRole("button", { name: "Parc batterie" }).click();
  await setNumber(page, "params.battery.power_mw", 10);
  await setNumber(page, "params.battery.energy_mwh", 40);
  await page.getByRole("button", { name: "Poste électrique" }).click();
  await page.getByLabel("Tarif d'électricité").click();
  await page.getByRole("option", { name: "Plages horaires" }).click();
  await setNumber(page, "params.price.tou_default_usd_per_mwh", 90);
  await page.getByRole("button", { name: "Ajouter une plage" }).click();
  await page.getByLabel("Plage 1 : heure de début").fill("17");
  await page.getByLabel("Plage 1 : heure de fin (exclue)").fill("21");
  await page.getByLabel("Plage 1 : prix").fill("220");
  await page.getByLabel("Plage 1 : jours").click();
  await page.getByRole("option", { name: "Jours ouvrés" }).click();
  await page.getByRole("button", { name: "Fermer l'inspecteur" }).click();
  await page.getByRole("button", { name: /Hypothèses marché/ }).click();
  await page.getByLabel("Dette permanente (refinancement)").click();
  await page.getByRole("button", { name: /Hypothèses marché/ }).click();
  await confirmed(page);
  const dscr = await kpiText(page, "DSCR min");
  check(/\d,\d\d\sx/.test(dscr), `refinancement → DSCR min calculé (${dscr})`);
  await save(page, "Liquide + batterie + HP/HC");
  await page.getByRole("button", { name: "Vue d'ensemble" }).click();
  await page.getByRole("button", { name: /Carte thermique/ }).click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${SHOTS}/3-liquide-batterie-hphc.png` });
  await page.getByRole("button", { name: /Carte thermique/ }).click();

  // ------------------------------------------------------------------ comparaison des 3 scénarios
  for (const name of ["Cas de base", "Densité 30 kW/rack", "Liquide + batterie + HP/HC"]) {
    await page.getByLabel(`Comparer ${name}`).check();
  }
  await page.waitForTimeout(2500);
  const rows = await page.locator("table >> text=TRI equity").count();
  check(rows > 0, "comparaison : tableau des KPI affiché");
  await page.screenshot({ path: `${SHOTS}/4-comparaison.png` });
} catch (error) {
  failures.push(String(error));
  console.error(error);
  await page.screenshot({ path: `${SHOTS}/echec.png` }).catch(() => {});
} finally {
  await browser.close();
}

check(pageErrors.length === 0, `aucune erreur JavaScript (${pageErrors.join(" | ") || "—"})`);
console.log(failures.length ? `\n${failures.length} échec(s)` : "\nTous les contrôles passent.");
process.exit(failures.length ? 1 : 0);
