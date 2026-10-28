// vertciti chat — shortcut registry and copy table tests (node:test, no deps).
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const SC = require("../shortcuts.js");
const I = require("../i18n.js");

function ev(key, extra) {
  return Object.assign({ key, metaKey: false, ctrlKey: false, altKey: false, isComposing: false,
                         keyCode: 0, target: { tagName: "BODY" } }, extra || {});
}
const input = { tagName: "INPUT" };

test("INT-1: no duplicate bindings in the registry", () => {
  const keys = SC.SHORTCUTS.filter((s) => s.keys).map((s) => s.keys);
  assert.equal(new Set(keys).size, keys.length);
  const ids = SC.SHORTCUTS.map((s) => s.id);
  assert.equal(new Set(ids).size, ids.length);
});

test("INT-1: core bindings exist (palette, /, ?, Esc, G-chords)", () => {
  assert.equal(SC.match(ev("k", { metaKey: true }), { isMac: true }), "palette");
  assert.equal(SC.match(ev("k", { ctrlKey: true }), { isMac: false }), "palette");
  assert.equal(SC.match(ev("/")), "focus");
  assert.equal(SC.match(ev("?")), "help");
  assert.equal(SC.match(ev("Escape")), "stop");
  assert.equal(SC.startsChord(ev("g")), "g");
  assert.equal(SC.match(ev("n"), { pending: "g" }), "new");
  assert.equal(SC.match(ev("l"), { pending: "g" }), "lang");
  assert.equal(SC.match(ev("n")), null);
});

test("INT-7: single-key shortcuts never fire while typing", () => {
  assert.equal(SC.match(ev("/", { target: input })), null);
  assert.equal(SC.match(ev("?", { target: input })), null);
  assert.equal(SC.startsChord(ev("g", { target: input })), null);
  assert.equal(SC.match(ev("n", { target: input }), { pending: "g" }), null);
  assert.equal(SC.match(ev("x", { target: { tagName: "DIV", isContentEditable: true } })), null);
  // modifier shortcuts and Escape still work in the input
  assert.equal(SC.match(ev("k", { ctrlKey: true, target: input })), "palette");
  assert.equal(SC.match(ev("Escape", { target: input })), "stop");
});

test("INT-7: nothing fires during IME composition (isComposing / keyCode 229)", () => {
  assert.equal(SC.match(ev("/", { isComposing: true })), null);
  assert.equal(SC.match(ev("Escape", { isComposing: true })), null);
  assert.equal(SC.match(ev("k", { ctrlKey: true, keyCode: 229 })), null);
  assert.equal(SC.startsChord(ev("g", { isComposing: true })), null);
});

test("INT-2: hazardous actions have no single-key binding", () => {
  for (const s of SC.SHORTCUTS.filter((x) => x.hazard)) assert.equal(s.keys, null);
});

test("DES-5: every copy key has both zh and en, and en has no CJK", () => {
  const cjk = /[一-鿿]/;
  for (const [key, entry] of Object.entries(I.table)) {
    assert.ok(entry.zh && entry.en, `missing language for ${key}`);
    if (key !== "langSwitch") assert.ok(!cjk.test(entry.en), `CJK in en copy for ${key}`);
  }
  for (const s of SC.SHORTCUTS) assert.ok(I.table[s.label], `no copy for shortcut ${s.id}`);
});

test("shortcut display uses platform glyphs", () => {
  assert.equal(SC.display("mod+k", true), "⌘K");
  assert.equal(SC.display("mod+k", false), "Ctrl+K");
  assert.equal(SC.display("g n", false), "G then N");
});
