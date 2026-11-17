const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const path = require("node:path");

const baseUrl = process.env.REPLAY_URL || "http://127.0.0.1:8765";
const browserPath = process.env.PLAYWRIGHT_BROWSER || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";

async function seek(page, data, timestamp) {
  await page.locator("#timeline").evaluate((input, value) => {
    input.value = String(value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }, Math.max(0, Math.round(timestamp - data.timelineStart)));
  await page.waitForTimeout(80);
}

let browser;
(async () => {
  browser = await chromium.launch({ headless: true, executablePath: browserPath });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
  const errors = [];
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  page.on("pageerror", (error) => errors.push(error.message));

  await page.goto(`${baseUrl}/app/index.html?dataset=cond-c`, { waitUntil: "networkidle" });
  await page.waitForFunction(() => document.querySelector("#replayShell")?.getAttribute("aria-busy") === "false");
  assert.equal(await page.locator("#datasetSelect option:not([hidden])").count(), 5, "legacy and the four new datasets should be selectable");
  assert.equal(await page.locator("#datasetSelect").inputValue(), "cond-c");
  assert.equal(await page.locator("#groupSelect option").count(), 11);

  for (const [datasetId, groupCount] of [["legacy", 11], ["cond-a", 11], ["cond-b", 15], ["cond-d", 14], ["cond-c", 11]]) {
    await page.selectOption("#datasetSelect", datasetId);
    await page.waitForFunction((id) => document.querySelector("#datasetSelect")?.value === id && document.querySelector("#replayShell")?.getAttribute("aria-busy") === "false", datasetId);
    assert.equal(await page.locator("#groupSelect option").count(), groupCount, `${datasetId} group list should load independently`);
  }

  const selectedC = await page.evaluate(async () => {
    const catalog = await (await fetch("/data/datasets/index.json")).json();
    const dataset = catalog.datasets.find((item) => item.id === "cond-c");
    const index = await (await fetch(`/${dataset.index}`)).json();
    const meta = index.groups.find((item) => item.id === document.querySelector("#groupSelect").value);
    return await (await fetch(`/${meta.file}`)).json();
  });
  assert.ok(selectedC.chat.some((item) => item.channel === "private"), "dataset C default group should expose private AI");
  assert.ok(await page.locator('[data-channel="private"]').count(), "private AI channel should be visible");

  const firstPrivate = selectedC.chat.find((item) => item.channel === "private");
  await page.locator('[data-channel="private"]').click();
  await seek(page, selectedC, firstPrivate.t - 1);
  assert.equal(await page.locator("#chatMessages .message").count(), 0, "private AI must not appear before its timestamp");
  await seek(page, selectedC, firstPrivate.t);
  assert.ok((await page.locator("#chatMessages .message").count()) >= 1, "private AI should appear at its timestamp");
  assert.match(await page.locator("#chatMessages .message").first().innerText(), /私有 AI|私有会话/);

  await page.selectOption("#datasetSelect", "cond-d");
  await page.waitForFunction(() => document.querySelector("#replayShell")?.getAttribute("aria-busy") === "false" && document.querySelector("#datasetSelect")?.value === "cond-d");
  assert.equal(await page.locator("#groupSelect option").count(), 14);
  const targetD = await page.evaluate(async () => {
    const catalog = await (await fetch("/data/datasets/index.json")).json();
    const dataset = catalog.datasets.find((item) => item.id === "cond-d");
    const index = await (await fetch(`/${dataset.index}`)).json();
    return index.groups.find((item) => item.channels.includes("shared") && item.channels.includes("private"));
  });
  assert.ok(targetD, "dataset D should contain a group with shared and private AI");
  await page.selectOption("#groupSelect", targetD.id);
  await page.waitForFunction((id) => document.querySelector("#groupSelect")?.value === id && document.querySelector("#replayShell")?.getAttribute("aria-busy") === "false", targetD.id);
  assert.ok(await page.locator('[data-channel="shared"]').count());
  assert.ok(await page.locator('[data-channel="private"]').count());
  await page.locator('[data-channel="private"]').click();
  assert.equal(await page.locator("#privateOwnerControl").isVisible(), true, "private AI should be filterable by member when multiple members used it");
  assert.ok((await page.locator("#privateOwnerSelect option").count()) >= 3, "private AI filter should include all members plus an all-members option");
  assert.match(page.url(), new RegExp(`dataset=cond-d&group=${encodeURIComponent(targetD.id)}`));

  const selectedD = await page.evaluate(async (file) => await (await fetch(`/${file}`)).json(), targetD.file);
  const codeSnapshot = selectedD.code[Math.floor(selectedD.code.length / 2)];
  await seek(page, selectedD, codeSnapshot.t);
  assert.match(await page.locator("#codeActor").innerText(), new RegExp(codeSnapshot.actor));
  assert.ok((await page.locator("#codeView .code-line").count()) > 0);
  const renderable = [...selectedD.code].reverse().find((item) => {
    try {
      const spec = JSON.parse(item.code);
      return Boolean(spec.mark || spec.layer || spec.hconcat || spec.vconcat || spec.concat || spec.facet);
    } catch {
      return false;
    }
  });
  assert.ok(renderable, "selected new-data group should contain a complete Vega-Lite snapshot");
  await seek(page, selectedD, renderable.t);
  await page.waitForFunction(() => document.querySelector("#previewState")?.textContent === "已同步", null, { timeout: 15000 });
  assert.ok((await page.locator("#visualization svg").count()) > 0, "new-data visualization should render against results.csv at the correct snapshot");

  const analysisHref = await page.locator("#analysisLink").getAttribute("href");
  assert.match(analysisHref, new RegExp(`dataset=cond-d&group=${encodeURIComponent(targetD.id)}`));
  await page.screenshot({ path: path.join(__dirname, "multi-dataset-replay.png"), fullPage: true });
  await page.locator("#analysisLink").click();
  await page.waitForFunction(() => document.querySelector("#analysisMain")?.getAttribute("aria-busy") === "false");
  assert.equal(await page.locator("#datasetSelect").inputValue(), "cond-d");
  assert.equal(await page.locator("#groupSelect").inputValue(), targetD.id);
  assert.ok((await page.locator(".participation-row").count()) >= 2);
  assert.match(await page.locator(".analysis-warning").innerText(), /实验关系未确认/);

  await page.selectOption("#datasetSelect", "legacy");
  await page.waitForFunction(() => document.querySelector("#analysisMain")?.getAttribute("aria-busy") === "false" && document.querySelector("#datasetSelect")?.value === "legacy");
  assert.equal(await page.locator("#groupSelect option").count(), 11, "legacy groups should be selectable on the analysis page");
  assert.match(await page.locator(".analysis-warning").innerText(), /原始回放复核/);

  await page.screenshot({ path: path.join(__dirname, "multi-dataset-analysis.png"), fullPage: true });
  assert.deepEqual(errors, [], `browser errors: ${errors.join(" | ")}`);
  console.log(JSON.stringify({ datasets: 5, legacyGroups: 11, condCGroups: 11, condDGroups: 14, testedGroup: targetD.id }, null, 2));
  await browser.close();
  browser = null;
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
}).finally(async () => { if (browser) await browser.close(); });
