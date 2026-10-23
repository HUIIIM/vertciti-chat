// Vendored from HUIIIM/.github standards/a11y/contrast_audit.js - change it there, then re-copy.
// Readable-text audit: every visible piece of text (incl. buttons, disabled controls,
// input values and placeholders) must reach WCAG contrast against what is actually
// painted behind it. Effective colour = text colour (or -webkit-text-fill-color, which
// iOS uses for disabled inputs) x cumulative ancestor opacity, over the composited
// background stack. Exits non-zero on any failure.
//   node contrast_audit.js <url> [--width 390] [--scheme light|dark] [--inject file.html] [--click selector]
const { chromium } = require('playwright');

const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
const url = args[0];
const width = Number(opt('--width', 390));
const scheme = opt('--scheme', 'light');
const inject = opt('--inject', null);
const click = opt('--click', null);

(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width, height: 900 }, colorScheme: scheme });
  // apps that poll or stream never go network-idle: load first, then give idle at most 10 s
  await p.goto(url, { waitUntil: 'load' });
  await p.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
  if (inject) {
    const html = require('fs').readFileSync(inject, 'utf8');
    await p.evaluate((h) => {
      const t = document.createElement('div'); t.innerHTML = h;
      t.querySelectorAll('style').forEach((s) => document.head.appendChild(s.cloneNode(true)));
      t.querySelectorAll('script').forEach((s) => { const n = document.createElement('script'); n.textContent = s.textContent; document.body.appendChild(n); });
    }, html);
  }
  if (click) { await p.click(click).catch(() => {}); }
  // scroll the whole page so scroll-triggered reveals run, then let transitions finish
  await p.evaluate(async () => { const h = document.documentElement.scrollHeight;
    for (let y = 0; y <= h; y += Math.max(200, innerHeight / 2)) { scrollTo(0, y); await new Promise((r) => setTimeout(r, 60)); }
    scrollTo(0, 0); });
  // wait for every running CSS animation/transition to finish (reveal effects), capped at 5 s
  await p.evaluate(() => Promise.race([
    Promise.all(document.getAnimations().filter((a) => a.effect && a.effect.getTiming().iterations !== Infinity).map((a) => a.finished.catch(() => {}))),
    new Promise((r) => setTimeout(r, 5000))]));
  await p.waitForTimeout(300);
  await p.evaluate(() => { window.__audit = (onlyTagged) => {
    // any CSS colour (rgb, lab, oklab, color(), …) -> rgba via the browser's own canvas
    const cv = document.createElement('canvas'); cv.width = cv.height = 1; const cx = cv.getContext('2d', { willReadFrequently: true });
    const memo = new Map();
    const parse = (c) => { if (!c) return null; if (memo.has(c)) return memo.get(c);
      cx.clearRect(0, 0, 1, 1); cx.fillStyle = 'rgba(0,0,0,0)'; cx.fillStyle = c; cx.fillRect(0, 0, 1, 1);
      const d = cx.getImageData(0, 0, 1, 1).data; const v = { r: d[0], g: d[1], b: d[2], a: d[3] / 255 }; memo.set(c, v); return v; };
    const over = (top, under) => ({ r: top.r * top.a + under.r * (1 - top.a), g: top.g * top.a + under.g * (1 - top.a), b: top.b * top.a + under.b * (1 - top.a), a: 1 });
    const lum = (c) => { const f = (x) => { x /= 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
    const ratio = (a, c) => { const x = lum(a), y = lum(c); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
    const bgOf = (el) => { // composite backgrounds from root down
      const chain = []; for (let e = el; e && e.nodeType === 1; e = e.parentElement) chain.push(e);
      let acc = { r: 255, g: 255, b: 255, a: 1 };
      const rootBg = parse(getComputedStyle(document.documentElement).backgroundColor);
      const bodyBg = parse(getComputedStyle(document.body).backgroundColor);
      if (rootBg && rootBg.a > 0) acc = over(rootBg, acc);
      if (bodyBg && bodyBg.a > 0) acc = over(bodyBg, acc);
      for (const e of chain.reverse()) { if (e === document.documentElement || e === document.body) continue;
        const c = parse(getComputedStyle(e).backgroundColor); if (c && c.a > 0) acc = over(c, acc); }
      return acc;
    };
    const opac = (el) => { let o = 1; for (let e = el; e && e.nodeType === 1; e = e.parentElement) o *= Number(getComputedStyle(e).opacity); return o; };
    // really on screen: has a box, not hidden, and not clipped away by an overflow:hidden/clip ancestor or off-canvas
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
      if (!(r.width > 0 && r.height > 0) || s.visibility === 'hidden' || s.display === 'none') return false;
      if (r.right <= 0 || r.left >= document.documentElement.clientWidth) return false;
      for (let e = el.parentElement; e && e !== document.body; e = e.parentElement) { const es = getComputedStyle(e);
        if (es.visibility === 'hidden' || es.display === 'none') return false;
        if (/(hidden|clip)/.test(es.overflow + es.overflowX + es.overflowY)) { const pr = e.getBoundingClientRect();
          if (pr.width < 1 || pr.height < 1 || r.right <= pr.left || r.left >= pr.right || r.bottom <= pr.top || r.top >= pr.bottom) return false; } }
      return true; };
    const out = []; const seen = new Set();
    const check = (el, text, color, kind) => {
      // WCAG 1.4.3 exempts logotypes: mark them data-contrast-exempt="logo" (explicit, reviewable)
      if (!text.trim() || !visible(el) || el.closest('[data-contrast-exempt="logo"]')) return;
      const s = getComputedStyle(el); const fg = parse(color); if (!fg) return;
      const bg = bgOf(el); const eff = over({ ...fg, a: fg.a * opac(el) }, bg);
      const size = parseFloat(s.fontSize), bold = Number(s.fontWeight) >= 700;
      const need = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5;
      const r = ratio(eff, bg);
      const key = kind + '|' + text.trim().slice(0, 40);
      if (onlyTagged && !el.hasAttribute('data-cafail')) return;
      if (r < need && !seen.has(key)) { seen.add(key); el.setAttribute('data-cafail', '1'); out.push({ kind, text: text.trim().slice(0, 50), ratio: Math.round(r * 100) / 100, need, tag: el.tagName.toLowerCase() + (el.disabled ? '[disabled]' : '') }); }
    };
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let n; while ((n = w.nextNode())) { const el = n.parentElement; if (!el || ['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(el.tagName)) continue;
      const s = getComputedStyle(el); const fill = s.webkitTextFillColor; check(el, n.nodeValue, fill && parse(fill).a > 0 ? fill : s.color, 'text'); }
    document.querySelectorAll('input,textarea,select').forEach((el) => {
      const s = getComputedStyle(el); const fill = s.webkitTextFillColor; const col = fill && parse(fill).a > 0 ? fill : s.color;
      if (el.value && el.type !== 'hidden' && el.type !== 'checkbox' && el.type !== 'radio') check(el, el.value, col, 'value');
      if (!el.value && el.placeholder) { const ps = getComputedStyle(el, '::placeholder'); const pf = ps.webkitTextFillColor; check(el, el.placeholder, pf && parse(pf).a > 0 ? pf : ps.color, 'placeholder'); }
    });
    return out;
  }; });
  let fails = await p.evaluate(() => window.__audit(false));
  if (fails.length) { // second pass: bring each suspect on screen, let reveal effects settle, measure again
    const n = await p.evaluate(() => document.querySelectorAll('[data-cafail]').length);
    for (let i = 0; i < n; i++) {
      await p.evaluate((k) => document.querySelectorAll('[data-cafail]')[k].scrollIntoView({ block: 'center' }), i);
      await p.waitForTimeout(700);
    }
    await p.evaluate(() => Promise.race([Promise.all(document.getAnimations().map((a) => a.finished.catch(() => {}))), new Promise((r) => setTimeout(r, 3000))]));
    fails = await p.evaluate(() => { const els = [...document.querySelectorAll('[data-cafail]')];
      return els.length ? window.__audit(true) : []; });
  }
  console.log(`${url} [${width}px ${scheme}] ${fails.length ? 'FAIL ' + fails.length : 'PASS'}`);
  for (const f of fails) console.log(`  ${f.ratio}:1 < ${f.need}  ${f.kind} <${f.tag}> "${f.text}"`);
  await b.close();
  process.exit(fails.length ? 1 : 0);
})();
