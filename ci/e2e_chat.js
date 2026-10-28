// vertciti chat — end-to-end check of the real page against the real backend
// and a mock runtime (ci/check-e2e.sh starts all three). Each check prints
// PASS/FAIL with the clause it covers; any FAIL exits non-zero.
//   NODE_PATH=<dir with playwright> CHAT_ADMIN_KEY=... node ci/e2e_chat.js
"use strict";
const { chromium } = require("playwright");

const WEB = process.env.WEB || "http://127.0.0.1:3120/";
const API = process.env.API || "http://127.0.0.1:8120";
const ADMIN = process.env.CHAT_ADMIN_KEY;
const SHOTS = process.env.SHOTS || "";
let failures = 0;

function check(name, ok, info) {
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${info ? "  :: " + info : ""}`);
  if (!ok) failures++;
}

async function risk(action) {
  const body = action === "kill"
    ? { scope: "module", reason_code: "e2e", actor: "e2e" } : { scope: "module", actor: "e2e" };
  const h = { "X-API-Key": ADMIN, "Content-Type": "application/json" };
  const p = await (await fetch(`${API}/v1/risk/${action}`, { method: "POST", headers: h, body: JSON.stringify(body) })).json();
  const r = await fetch(`${API}/v1/risk/confirm`, { method: "POST", headers: h,
    body: JSON.stringify({ challenge_id: p.challenge_id, confirm_phrase: p.confirm_phrase }) });
  return r.status;
}

async function page(browser, opts) {
  const ctx = await browser.newContext(Object.assign({ viewport: { width: 1280, height: 900 } }, opts || {}));
  const p = await ctx.newPage();
  p.errors = [];
  p.on("console", (m) => { if (m.type() === "error") p.errors.push(m.text()); });
  p.on("pageerror", (e) => p.errors.push(e.message));
  return { ctx, p };
}

const texts = (p) => p.$$eval(".msg", (els) => els.map((e) => e.innerText.replace(/\n+/g, " | ")));
const send = async (p, text) => { await p.fill("#input", text); await p.press("#input", "Enter"); };

(async () => {
  const browser = await chromium.launch();
  try {
    // --- 1. first visit: no key, live status, honest footer -------------------------
    const { ctx, p } = await page(browser);
    const resp = await p.goto(WEB, { waitUntil: "load" });
    const csp = resp.headers()["content-security-policy"] || "";
    check("SEC-A6 frontend sends a CSP without unsafe-inline", csp.includes("script-src 'self'") && !csp.includes("unsafe-inline"), csp);
    check("DES-6 no API key field on the public page", (await p.$("#apiKey")) === null);
    await p.waitForFunction(() => document.getElementById("status").dataset.state === "live", null, { timeout: 8000 })
      .catch(() => {});
    check("OPS-3 status chip shows live from /health", (await p.getAttribute("#status", "data-state")) === "live",
      await p.textContent("#statusText"));
    check("DES-6 footer states the retention period", /30/.test(await p.textContent("#footText")));

    // --- 2. send and stream ------------------------------------------------------
    await send(p, "hello");
    await p.waitForFunction(() => /done\./.test(document.querySelector(".msg.assistant:last-of-type .body")?.textContent || ""), null, { timeout: 8000 }).catch(() => {});
    await p.waitForSelector("#sendBtn", { state: "visible", timeout: 8000 }).catch(() => {}); // reply finished
    const t1 = await texts(p);
    check("CHAT streamed reply rendered", t1.some((t) => t.includes("Mock runtime reply")), JSON.stringify(t1));
    check("SEC-A7 runtime markup rendered as text", (await p.$(".msg.assistant b")) === null && t1.join().includes("<b>not bold</b>"));
    check("DES-4 meter shows remaining quota and cost", /\d/.test(await p.textContent("#meter")), await p.textContent("#meter"));
    const sid = new URL(p.url()).searchParams.get("s");
    check("INT-5 session id is in the URL", !!sid, p.url());

    // --- 3. reload resumes the conversation ----------------------------------------
    await p.reload({ waitUntil: "load" });
    await p.waitForSelector(".msg.assistant", { timeout: 5000 }).catch(() => {});
    const restored = await texts(p);
    check("INT-5 reload restores the conversation", restored.length === 2 && !/已停止|Stopped/.test(restored[1]), JSON.stringify(restored));

    // --- 4. stop a slow reply --------------------------------------------------------
    await send(p, "slow please");
    await p.waitForFunction(() => /Mock/.test(document.querySelector(".msg.assistant:last-of-type .body")?.textContent || ""), null, { timeout: 8000 }).catch(() => {});
    check("INT-4 stop button visible while streaming", await p.isVisible("#stopBtn"));
    await p.keyboard.press("Escape");
    await p.waitForSelector(".msg.assistant:last-of-type .note.warn", { timeout: 5000 }).catch(() => {});
    const stoppedNote = await p.$eval(".msg.assistant:last-of-type", (e) => e.innerText).catch(() => "");
    check("INT-3/MOT-4 Esc stops the reply and says so", /已停止|Stopped/.test(stoppedNote), stoppedNote);
    check("INT-4 send button back after stop", await p.isVisible("#sendBtn"));
    await p.waitForTimeout(500);
    const detail = await p.evaluate(async ([api, s]) => {
      const tok = localStorage.getItem("vc_visitor");
      const r = await fetch(`${api}/v1/chat/sessions/${s}`, { headers: { "X-Visitor-Token": tok } });
      return (await r.json()).messages.map((m) => m.status);
    }, [API, sid]);
    check("ARCH-5 server recorded the stopped reply as interrupted", detail.includes("interrupted"), JSON.stringify(detail));

    // --- 5. runtime failure: honest, retryable ----------------------------------------
    const before = (await texts(p)).length;
    await send(p, "fail now");
    await p.waitForSelector(".msg.user:last-of-type .note.bad", { timeout: 5000 }).catch(() => {});
    const failText = await p.$eval(".msg.user:last-of-type", (e) => e.innerText).catch(() => "");
    check("INT-3 unaccepted message is marked not sent, with retry", /未发送|Not sent/.test(failText) && /重试|Retry/.test(failText), failText);
    check("HONESTY no assistant bubble fabricated on failure", (await texts(p)).length === before + 1);

    // --- 6. keyboard: palette, help, slash, typing safety -------------------------------
    await p.click("body");
    await p.keyboard.press("Control+k");
    check("INT-1 Ctrl+K opens the command palette", await p.isVisible("#paletteDialog"));
    await p.keyboard.type("new");
    const items = await p.$$eval("#paletteList .palette-item", (els) => els.map((e) => e.textContent));
    check("INT-1 palette filters commands", items.length >= 1 && /新对话|New chat/.test(items[0]), JSON.stringify(items));
    await p.keyboard.press("Enter");
    check("INT-1 palette command runs (new chat)", (await texts(p)).length === 0 && !(new URL(p.url()).searchParams.get("s")));
    await p.click("body");
    await p.keyboard.press("?");
    check("INT-1 ? opens the shortcut sheet", await p.isVisible("#helpDialog"));
    const rows = await p.$$eval("#helpList dt", (e) => e.length);
    check("INT-1 sheet is generated from the registry", rows >= 5, String(rows));
    await p.keyboard.press("Escape");
    await p.click("body");
    await p.keyboard.press("/");
    check("INT-1 / focuses the message box", await p.evaluate(() => document.activeElement.id === "input"));
    await p.keyboard.type("a/b?");
    check("INT-7 typing / and ? in the box does not trigger shortcuts",
      (await p.inputValue("#input")) === "a/b?" && !(await p.isVisible("#helpDialog")));
    await p.fill("#input", "");

    // --- 7. history + two-step delete ------------------------------------------------------
    await p.goto(WEB + "?s=" + sid, { waitUntil: "load" });
    await p.waitForSelector(".msg", { timeout: 5000 }).catch(() => {});
    await p.click("#historyBox summary");
    await p.waitForSelector("#historyList a", { timeout: 5000 }).catch(() => {});
    check("INT-5 history lists the visitor's chats", (await p.$$("#historyList a")).length >= 1);
    await p.click("#deleteChat");
    check("INT-2 first delete click only arms", (await texts(p)).length > 0 && /再点|again/.test(await p.textContent("#deleteChat")));
    await p.click("#deleteChat");
    await p.waitForTimeout(800);
    const gone = await p.evaluate(async ([api, s]) => (await fetch(`${api}/v1/chat/sessions/${s}`,
      { headers: { "X-Visitor-Token": localStorage.getItem("vc_visitor") } })).status, [API, sid]);
    check("PRIV-erasure second click deletes on the server", gone === 404, String(gone));
    // The browser logs every non-2xx response; the 503/404 above are deliberate.
    const real = p.errors.filter((e) => !/^Failed to load resource: the server responded with a status of (503|404)/.test(e));
    check("DES-6 no script errors or CSP violations", real.length === 0, JSON.stringify(real));
    await ctx.close();

    // --- 8. English mode -----------------------------------------------------------------
    {
      const { ctx: c2, p: en } = await page(browser);
      await en.goto(WEB + "?lang=en", { waitUntil: "load" });
      await send(en, "inline hi");
      await en.waitForSelector(".msg.assistant", { timeout: 5000 }).catch(() => {});
      await en.waitForSelector(".cta", { timeout: 3000 }).catch(() => {});
      const cjk = (await en.evaluate(() => document.body.innerText)).match(/[一-鿿]+/g) || [];
      check("DES-5 English page shows no Chinese except the language switch", cjk.every((w) => w === "中文"), JSON.stringify(cjk));
      check("DES-5 <html lang> and title follow the language",
        (await en.evaluate(() => document.documentElement.lang)) === "en" && !/[一-鿿]/.test(await en.title()));
      await c2.close();
    }

    // --- 9. kill switch is visible and honest ----------------------------------------------
    if (ADMIN) {
      check("KILL two-step kill via admin API", (await risk("kill")) === 200);
      const { ctx: c3, p: k } = await page(browser);
      await k.goto(WEB, { waitUntil: "load" });
      await k.waitForFunction(() => document.getElementById("status").dataset.state === "killed", null, { timeout: 8000 }).catch(() => {});
      check("OPS-3 status chip shows the service stopped", (await k.getAttribute("#status", "data-state")) === "killed");
      await risk("unkill");
      await c3.close();
    } else {
      check("KILL admin key provided to e2e", false, "set CHAT_ADMIN_KEY");
    }

    // --- 10. phone width, dark mode, reduced motion, offline --------------------------------------
    {
      const { ctx: c4, p: ph } = await page(browser, { viewport: { width: 390, height: 844 }, colorScheme: "dark", reducedMotion: "reduce" });
      await ph.goto(WEB, { waitUntil: "load" });
      await send(ph, "inline phone");
      await ph.waitForSelector(".msg.assistant", { timeout: 5000 }).catch(() => {});
      check("390px no horizontal scroll", await ph.evaluate(() => document.documentElement.scrollWidth <= 390));
      check("MOT-1/MOT-6 no running animations", await ph.evaluate(() => document.getAnimations().length === 0));
      if (SHOTS) await ph.screenshot({ path: `${SHOTS}/e2e-390-dark.png`, fullPage: true });
      await c4.setOffline(true);
      await ph.evaluate(() => window.dispatchEvent(new Event("offline")));
      check("OPS-3 going offline shows unreachable", (await ph.getAttribute("#status", "data-state")) === "down");
      await c4.close();
    }
  } finally {
    await browser.close();
  }
  console.log(failures ? `e2e: ${failures} FAILED` : "e2e: ALL PASS");
  process.exit(failures ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
