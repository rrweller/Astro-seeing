// A small line-based bridge from pytest to Playwright (ticket #52).
//
// pytest starts `node driver.cjs`, writes one JSON command per line on stdin and reads
// one JSON answer per line on stdout: {"ok": true, "value": ...} or {"ok": false,
// "error": "..."}. The browser tests stay in Python (tests/page_browser.py) while the
// browser is driven by Playwright for Node, which is pre-installed in cloud sessions
// and installed from tests/browser/package-lock.json in CI.
//
// Every request the page makes is recorded. Requests to any origin other than the
// test server's are aborted and recorded as blocked, so a test can prove that no
// request leaves the host.
"use strict";

const readline = require("node:readline");

function loadPlaywright() {
  for (const name of ["playwright-core", "playwright"]) {
    try {
      return require(name);
    } catch (err) {
      if (err.code !== "MODULE_NOT_FOUND") throw err;
    }
  }
  throw new Error("neither playwright-core nor playwright can be loaded");
}

const { chromium } = loadPlaywright();
let browser = null;
let context = null;
let page = null;
let allowedOrigin = null;
const requests = [];
const consoleErrors = [];

const commands = {
  async launch({ origin, viewport, deviceScaleFactor }) {
    const channel = process.env.PAGE_TEST_BROWSER_CHANNEL || undefined;
    browser = await chromium.launch({ channel });
    allowedOrigin = origin;
    context = await browser.newContext({ viewport, deviceScaleFactor: deviceScaleFactor || 1 });
    page = await context.newPage();
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });
    page.on("pageerror", (err) => consoleErrors.push(String(err)));
    await context.route("**/*", async (route) => {
      const url = route.request().url();
      const local = url.startsWith(allowedOrigin + "/");
      requests.push({ url, method: route.request().method(), blocked: !local });
      if (local) await route.continue();
      else await route.abort("blockedbyclient");
    });
    return browser.version();
  },
  async clockInstall({ time }) {
    await page.clock.install({ time });
  },
  async clockRunFor({ ms }) {
    await page.clock.runFor(ms);
  },
  async goto({ url }) {
    await page.goto(url, { waitUntil: "load" });
  },
  async waitForFunction({ expr, timeout }) {
    await page.waitForFunction(expr, null, { timeout: timeout || 10000, polling: 50 });
  },
  async eval({ expr }) {
    return await page.evaluate(expr);
  },
  async click({ selector }) {
    await page.click(selector);
  },
  async screenshot({ path, fullPage }) {
    await page.screenshot({ path, fullPage: Boolean(fullPage) });
  },
  async requests() {
    return requests;
  },
  async consoleErrors() {
    return consoleErrors;
  },
  async close() {
    if (browser) await browser.close();
    browser = null;
  },
};

const rl = readline.createInterface({ input: process.stdin });
let queue = Promise.resolve();
rl.on("line", (line) => {
  queue = queue.then(async () => {
    let answer;
    try {
      const { op, ...args } = JSON.parse(line);
      if (!(op in commands)) throw new Error(`unknown command ${op}`);
      const value = await commands[op](args);
      answer = { ok: true, value: value === undefined ? null : value };
    } catch (err) {
      answer = { ok: false, error: String(err && err.stack ? err.stack : err) };
    }
    process.stdout.write(JSON.stringify(answer) + "\n");
  });
});
rl.on("close", () => {
  queue.then(() => (browser ? browser.close() : null)).then(() => process.exit(0));
});
