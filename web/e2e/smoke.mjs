// End-to-end check against a running API (default http://127.0.0.1:8000) through the Vite dev server.
//   python -m stmtai.api &  &&  npm run dev &  &&  node e2e/smoke.mjs <path-to-scan.pdf> [screenshots-dir]
import { chromium } from "playwright";
import fs from "node:fs";

const [pdf, shots] = [process.argv[2], process.argv[3]];
if (!pdf) { console.error("usage: node e2e/smoke.mjs <statement.pdf> [screenshots-dir]"); process.exit(2); }
const base = process.env.UI_URL ?? "http://127.0.0.1:5173";
if (shots) fs.mkdirSync(shots, { recursive: true });
const shot = async (page, name) => shots && page.screenshot({ path: `${shots}/${name}.png` });
const ok = (cond, msg) => { if (!cond) throw new Error("FAILED: " + msg); console.log("ok  " + msg); };
const count = async (page) => Number((await page.getByTestId("queue-title").innerText()).match(/(\d+)/)[1]);

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1.5 });
page.on("pageerror", (e) => { throw e; });
try {
  await page.goto(base);
  await page.getByText("Drop a bank statement PDF here").waitFor();
  await page.getByTestId("file-input").setInputFiles(pdf);
  await page.getByRole("link", { name: /scan_medium\.pdf/ }).waitFor({ timeout: 120000 });
  await shot(page, "1-list");
  ok(true, "uploaded and extracted");

  await page.getByRole("link", { name: /scan_medium\.pdf/ }).click();
  await page.getByTestId("focus").waitFor();
  const start = await count(page);
  ok(start > 0, `review queue loaded (${start} items)`);
  ok((await page.getByTestId("focus").innerText()).includes("Balance, row"), "balance problem is shown first");
  const read = await page.getByTestId("read-value").innerText();
  const suggested = await page.getByTestId("suggested-value").innerText();
  ok(read === "12,334.42" && suggested === "1,23,344.20", `read ${read}, suggested ${suggested}`);
  ok((await page.getByTestId("focus").innerText()).includes("The next row agrees"), "arithmetic shown");
  await page.waitForFunction(() => [...document.images].every((i) => i.complete && i.naturalWidth > 0));
  await page.waitForTimeout(1200);
  await shot(page, "2-review");

  await page.keyboard.press("Enter");                       // accept the suggestion from the keyboard
  await page.waitForFunction((n) => Number(document.querySelector('[data-testid="queue-title"]').textContent.match(/(\d+)/)[1]) < n, start);
  const afterFix = await count(page);
  ok(afterFix < start, `accepting the suggestion cleared ${start - afterFix} items (the credit flag cleared with it)`);
  ok(await page.locator(".chip.good").first().isVisible(), "balance now adds up on all rows");

  await page.getByRole("button", { name: /Undo/ }).click();
  await page.waitForFunction((n) => Number(document.querySelector('[data-testid="queue-title"]').textContent.match(/(\d+)/)[1]) === n, start);
  ok(true, "undo restored the queue");
  await page.keyboard.press("Enter");
  await page.waitForFunction((n) => Number(document.querySelector('[data-testid="queue-title"]').textContent.match(/(\d+)/)[1]) < n, start);

  const before = await count(page);
  await page.getByRole("button", { name: /Confirm all/ }).click();
  await page.waitForFunction((n) => Number(document.querySelector('[data-testid="queue-title"]')?.textContent.match(/(\d+)/)[1]) < n, before);
  ok((await count(page)) < before, "confirm-all cleared a whole group");
  await shot(page, "3-after-bulk");
  ok(await page.getByTestId("approve").isDisabled(), "approve stays locked while items remain");

  // edit flow with validation
  await page.keyboard.press("e");
  await page.locator("#edit-value").fill("not a date or amount");
  await page.keyboard.press("Enter");
  const key = await page.getByTestId("focus").locator("h2").innerText();
  await page.getByRole("alert").waitFor({ timeout: 5000 });
  ok((await page.getByRole("alert").innerText()).includes("not"), `bad input is refused with a message on ${key}`);
  await page.keyboard.press("Escape");

  // work through everything else from the keyboard
  for (let i = 0; i < 80 && (await page.getByTestId("all-clear").count()) === 0; i++) {
    const body = await page.getByTestId("focus").innerText();
    if (body.includes("Everything is checked")) break;
    await page.locator("body").click({ position: { x: 5, y: 5 } });
    await page.keyboard.press("Enter");
    await page.waitForTimeout(150);
  }
  await page.getByTestId("all-clear").waitFor({ timeout: 10000 });
  ok(true, "queue worked down to zero");
  await shot(page, "4-all-clear");
  await page.getByTestId("approve").click();
  await page.getByTestId("approved").waitFor();
  ok((await page.getByRole("link", { name: "Export CSV" }).count()) > 0, "approved; export is available");
  await shot(page, "5-approved");

  const csv = await (await page.request.get(`${base}/api/statements/${page.url().split("/s/")[1]}/export.csv`)).text();
  ok(csv.split("\n").length > 50 && csv.startsWith("date,"), "CSV export downloads");
  const fb = await (await page.request.get(`${base}/api/feedback`)).json();
  ok(fb.overall.reviewed > 0, `feedback logged ${fb.overall.reviewed} reviewed cells`);
  console.log("\nALL CHECKS PASSED");
} finally {
  await browser.close();
}
