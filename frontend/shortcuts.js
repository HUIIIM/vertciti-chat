/* vertciti chat — one keyboard shortcut registry. Clean-room original.
   The `?` sheet and the command palette are both generated from SHORTCUTS,
   so they cannot drift apart. frontend/tests/shortcuts.test.js proves there
   are no duplicate bindings and that single-key shortcuts never fire while
   typing or while a Chinese IME is composing (isComposing / keyCode 229). */
(function (root) {
  "use strict";

  // keys: "mod+k" (⌘ on macOS, Ctrl elsewhere), "/", "?", "escape", "g n".
  // single: a plain printable key, ignored inside editable fields.
  // hazard: needs a second, independent confirmation before it runs.
  var SHORTCUTS = [
    { id: "palette", keys: "mod+k", label: "scPalette", single: false },
    { id: "focus", keys: "/", label: "scFocus", single: true },
    { id: "help", keys: "?", label: "scHelp", single: true },
    { id: "stop", keys: "escape", label: "scStop", single: false },
    { id: "new", keys: "g n", label: "scNew", single: true },
    { id: "lang", keys: "g l", label: "scLang", single: true },
    { id: "delete", keys: null, label: "scDelete", single: false, hazard: true }
  ];

  function isEditable(el) {
    if (!el || !el.tagName) return false;
    var tag = el.tagName.toLowerCase();
    return tag === "input" || tag === "textarea" || tag === "select" || el.isContentEditable === true;
  }

  function composing(ev) {
    return ev.isComposing === true || ev.keyCode === 229;
  }

  function keyName(ev) {
    var k = (ev.key || "").toLowerCase();
    return k === "esc" ? "escape" : k;
  }

  /* Returns the matched shortcut id, or null. `pending` is the first key of a
     two-key chord ("g") when one is in progress. */
  function match(ev, opts) {
    opts = opts || {};
    if (composing(ev)) return null;
    var isMac = !!opts.isMac;
    var mod = isMac ? ev.metaKey : ev.ctrlKey;
    var key = keyName(ev);
    var editable = isEditable(ev.target);
    for (var i = 0; i < SHORTCUTS.length; i++) {
      var s = SHORTCUTS[i];
      if (!s.keys) continue;
      if (s.single && editable) continue;
      var parts = s.keys.split(" ");
      if (parts.length === 2) {
        if (opts.pending === parts[0] && key === parts[1] && !mod && !ev.altKey) return s.id;
        continue;
      }
      var combo = s.keys.split("+");
      if (combo.length === 2 && combo[0] === "mod") {
        if (mod && key === combo[1]) return s.id;
        continue;
      }
      if (!mod && !ev.altKey && key === s.keys) return s.id;
    }
    return null;
  }

  /* Is this key the start of a chord ("g")? Never inside editable fields. */
  function startsChord(ev) {
    if (composing(ev) || isEditable(ev.target) || ev.metaKey || ev.ctrlKey || ev.altKey) return null;
    var key = keyName(ev);
    for (var i = 0; i < SHORTCUTS.length; i++) {
      var k = SHORTCUTS[i].keys;
      if (k && k.indexOf(" ") > 0 && k.split(" ")[0] === key) return key;
    }
    return null;
  }

  function display(keys, isMac) {
    if (!keys) return "";
    return keys.split(" ").map(function (part) {
      return part.split("+").map(function (p) {
        if (p === "mod") return isMac ? "⌘" : "Ctrl";
        if (p === "escape") return "Esc";
        return p.length === 1 ? p.toUpperCase() : p;
      }).join(isMac ? "" : "+");
    }).join(" then ");
  }

  var api = { SHORTCUTS: SHORTCUTS, match: match, startsChord: startsChord, display: display,
              isEditable: isEditable };
  root.VC_SHORTCUTS = api;
  if (typeof module !== "undefined" && module.exports) { module.exports = api; }
})(typeof window !== "undefined" ? window : globalThis);
