// Browser check of the "Ask your statements" box against a running API (OCR can be off) through the Vite dev server.
//   node e2e/ask.mjs <digital-statement.pdf> <expected-upi-total e.g. 86,657.17> [screenshots-dir]
import { chromium } from "playwright";
import fs from "node:fs";

const [pdf, expected, shots] = process.argv.slice(2);
if (!pdf || !expected) { console.error("usage: node e2e/ask.mjs <statement.pdf> <expected UPI total> [dir]"); process.exit(2); }
const base = process.env.UI_URL ?? "http://127.0.0.1:5173";
if (shots) fs.mkdirSync(shots, { recursive: true });
const ok = (cond, msg) => { if (!cond) throw new Error("FAILED: " + msg); console.log("ok  " + msg); };

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const page = await browser.newPage({ viewport: { width: 1000, height: 1000 } });
page.on("pageerror", (e) => { throw e; });
const ask = async (q) => {
  await page.getByTestId("ask-input").fill(q);
  const reply = page.waitForResponse((r) => r.url().endsWith("/query"));   // the old reply is still on screen until this lands
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await reply;
  await page.waitForFunction((question) => {
    const el = document.querySelector('[data-testid="answer"],[data-testid="refusal"]');
    return el && !document.querySelector("form button")?.textContent?.includes("Asking") && el.isConnected;
  }, q);
  await page.waitForTimeout(150);
  return page.getByTestId("ask").innerText();
};
try {
  await page.goto(base);
  await page.getByTestId("file-input").setInputFiles(pdf);
  const link = page.getByRole("link", { name: /\.pdf/ });
  await link.waitFor({ timeout: 60000 });
  await page.getByTestId("ask").waitFor();
  ok(await page.getByTestId("ask-input").isDisabled(), "the box is disabled until a statement is approved");

  const id = (await link.getAttribute("href")).split("/s/")[1];
  ok((await page.request.post(`${base}/api/statements/${id}/approve`)).ok(), "statement approved");
  await page.reload();
  await page.getByTestId("ask").waitFor();
  ok(!(await page.getByTestId("ask-input").isDisabled()), "the box is enabled once a statement is approved");

  let text = await ask("How much did I spend on UPI in April 2025?");
  ok(text.includes("₹" + expected), `UPI total is ₹${expected}`);
  ok(text.includes("total debits, of type UPI") && text.includes("read by rules"), "shows how the question was understood");
  ok((await page.getByRole("link", { name: "Open" }).count()) > 0, "shows the rows behind the answer");

  text = await ask("Spending by category");
  ok(text.includes("UPI") && text.includes("EMI") && (await page.getByRole("link", { name: "Open" }).count()) === 0, "grouped answer, no stray rows");

  text = await ask("Will I be able to afford a car next year?");
  ok(text.includes("No answer.") && (await page.getByTestId("answer").count()) === 0, "an unanswerable question is refused");

  text = await ask("outlay on cash machines, please");
  ok(text.includes("I did not understand 'outlay'"), "an unknown word is named, not guessed");
  if (shots) await page.screenshot({ path: `${shots}/ask.png` });
  console.log("\nALL CHECKS PASSED");
} finally {
  await browser.close();
}
