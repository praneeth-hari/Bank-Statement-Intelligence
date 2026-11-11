// Browser check of the one-click samples, the sidebar note and the CSV download, from an empty install.
//   (start the API on an empty data folder, then the UI)   node e2e/samples.mjs [screenshots-dir]
import { chromium } from "playwright";
import fs from "node:fs";

const shots = process.argv[2];
const base = process.env.UI_URL ?? "http://127.0.0.1:5173";
if (shots) fs.mkdirSync(shots, { recursive: true });
const ok = (cond, msg) => { if (!cond) throw new Error("FAILED: " + msg); console.log("ok  " + msg); };

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const page = await browser.newPage({ viewport: { width: 1500, height: 950 } });
page.on("pageerror", (e) => { throw e; });
try {
  await page.goto(base + "/#/statements");
  await page.getByTestId("samples").waitFor();
  ok((await page.getByTestId("privacy").innerText()).includes("Files stay on this computer"), "the sidebar says files stay on this computer");
  await page.getByRole("button", { name: "Load sample statements" }).click();
  await page.getByRole("link", { name: /\.pdf/ }).first().waitFor({ timeout: 20000 });
  ok((await page.getByRole("link", { name: /\.pdf/ }).count()) >= 3, "the samples were loaded");
  await page.waitForFunction(() => document.querySelector('[data-testid="sidenote"]').textContent.includes("approved") && !document.querySelector('[data-testid="sidenote"]').textContent.includes("No approved"));
  ok(true, "the sidebar count updated without a reload");
  ok((await page.getByTestId("samples").count()) === 0, "the samples card goes away once there are statements");

  await page.goto(base + "/#/");
  await page.getByTestId("download").waitFor();
  const [dl] = await Promise.all([page.waitForEvent("download"), page.getByTestId("download").click()]);
  const text = fs.readFileSync(await dl.path(), "utf8");
  const lines = text.trim().split("\n");
  ok(dl.suggestedFilename() === "approved-transactions.csv", "the download is named approved-transactions.csv");
  ok(lines[0] === "date,description,reference,debit,credit,balance,type,statement,statement_id,row" && lines.length > 100, `the CSV has the right columns and ${lines.length - 1} rows`);
  if (shots) await page.screenshot({ path: `${shots}/dashboard-samples.png` });
  console.log("\nALL CHECKS PASSED");
} finally {
  await browser.close();
}
