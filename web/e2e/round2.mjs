// Browser check of Transactions, categories and Recurring, from an empty install (API on an empty data folder, then the UI).
//   node e2e/round2.mjs [screenshots-dir]
import { chromium } from "playwright";
import fs from "node:fs";

const shots = process.argv[2];
const base = process.env.UI_URL ?? "http://127.0.0.1:5173";
if (shots) fs.mkdirSync(shots, { recursive: true });
const ok = (cond, msg) => { if (!cond) throw new Error("FAILED: " + msg); console.log("ok  " + msg); };
const shot = (page, name) => shots && page.screenshot({ path: `${shots}/${name}.png`, fullPage: true });

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const page = await browser.newPage({ viewport: { width: 1500, height: 950 } });
page.on("pageerror", (e) => { throw e; });
const api = async (path) => (await page.request.get(`${base}/api${path}`)).json();
const matchedOnScreen = async () => Number((await page.getByTestId("summary").innerText()).match(/^([\d,]+)/)[1].replace(/,/g, ""));
try {
  await page.goto(base + "/#/transactions");
  await page.getByTestId("samples").waitFor();
  await page.getByRole("button", { name: "Load sample statements" }).click();
  await page.getByTestId("filters").waitFor({ timeout: 20000 });
  const all = (await api("/transactions?limit=1")).matched;
  ok((await matchedOnScreen()) === all && all > 100, `the page lists all ${all} approved transactions`);
  ok((await page.getByTestId("tx-table").locator("tbody tr").count()) === 50, "the first page has 50 rows");
  const firstRow = await page.getByTestId("tx-table").locator("tbody tr").first().innerText();
  await page.getByTestId("next").click();
  await page.waitForFunction((t) => document.querySelector('[data-testid="tx-table"] tbody tr').innerText !== t, firstRow);
  ok(true, "Next shows different rows");
  await page.goto(base + "/#/transactions");

  await page.getByTestId("filter-q").fill("upi");
  const upi = (await api("/transactions?q=upi&limit=1")).matched;
  await page.waitForFunction((n) => document.querySelector('[data-testid="summary"]')?.textContent.startsWith(String(n)), upi);
  ok((await matchedOnScreen()) === upi, `searching "upi" matches the API (${upi})`);
  await page.getByTestId("filter-q").fill("emi");
  await page.getByTestId("filter-direction").selectOption("credit");          // no EMI is ever received
  await page.getByTestId("nomatch").waitFor();
  ok((await api("/transactions?q=emi&direction=credit&limit=1")).matched === 0, "a search with no matches says so plainly, and the API agrees")
  await page.getByRole("button", { name: "Clear filters" }).first().click();
  await page.waitForFunction((n) => document.querySelector('[data-testid="summary"]')?.textContent.startsWith(String(n)), all);
  ok(true, "clearing the filters brings everything back");

  await page.getByLabel("Min ₹").fill("abc");
  await page.getByRole("alert").waitFor();
  ok(true, "a bad amount is refused with a message");
  await page.getByLabel("Min ₹").fill("");

  await page.getByTestId("toggle-categories").click();
  await page.getByTestId("suggestions").waitFor();
  const before = (await api("/categories")).suggestions.length;
  await page.getByRole("button", { name: /^Add all/ }).click();
  await page.waitForFunction(() => !document.querySelector('[data-testid="suggestions"]'));
  const cats = await api("/categories");
  ok(before > 5 && cats.rules.length === before && cats.coverage.categorised > 50 && cats.coverage.categorised < cats.coverage.total, `Add all created ${before} rules, covering ${cats.coverage.categorised} of ${cats.coverage.total}`);
  await shot(page, "transactions-categories");
  await page.getByTestId("rule-pattern").fill("zzz");
  await page.getByTestId("rule-category").fill("Test");
  await page.getByTestId("rule-add").click();
  await page.getByText("zzz").waitFor();
  await page.getByRole("button", { name: "Remove the rule for zzz" }).click();
  await page.waitForFunction(() => ![...document.querySelectorAll(".bt-rules b")].some((b) => b.textContent === "zzz"));
  ok(true, "a rule can be added and removed");

  await page.getByTestId("filter-category").selectOption("Health");
  const health = (await api("/transactions?category=Health&limit=1")).matched;
  await page.waitForFunction((n) => document.querySelector('[data-testid="summary"]')?.textContent.startsWith(String(n)), health);
  const chips = await page.locator(".bt-tx .bt-cat").allInnerTexts();
  ok(chips.length > 0 && chips.every((c) => c === "Health"), `the Health filter shows ${health} rows, all Health`);
  await shot(page, "transactions-health");

  await page.goto(base + "/#/");
  await page.getByTestId("by-category").click();
  await page.waitForFunction(() => document.querySelector(".bt-donut")?.textContent.includes("Groceries"));
  ok(true, "the Dashboard donut can switch to your categories");
  await shot(page, "dashboard-categories");

  await page.goto(base + "/#/recurring");
  await page.getByTestId("recurring-list").waitFor();
  const rec = await api("/recurring");
  ok((await page.getByTestId("recurring-count").innerText()) === String(rec.items.length), `Recurring lists ${rec.items.length} repeating payments`);
  ok((await page.getByTestId("recurring-list").innerText()).includes("EMI Home Loan"), "the loan EMI is among them");
  await shot(page, "recurring");
  console.log("\nALL CHECKS PASSED");
} finally {
  await browser.close();
}
