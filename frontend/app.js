/* vertciti chat frontend — clean-room original. SSE from day one.
   No shared key in the page: it mints an anonymous visitor token
   (POST /v1/visitor) and keeps it in localStorage so "past chats" survive a
   reload. Every state the user can be in has honest copy: sending, thinking,
   streaming, stopped, not sent (with retry), quota, paused, unreachable. */
(function () {
  "use strict";
  var I = window.VC_I18N, T = I.T, SC = window.VC_SHORTCUTS;
  var isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "");

  // ---- error boundary: never fail silently -----------------------------------
  function showPageError() {
    var el = document.getElementById("pageError");
    if (el) { el.textContent = T("errPage"); el.hidden = false; }
  }
  window.addEventListener("error", showPageError);
  window.addEventListener("unhandledrejection", showPageError);

  // ---- config ---------------------------------------------------------------
  function apiBase() {
    var meta = document.querySelector('meta[name="vc-api-base"]');
    var v = (meta && meta.content) || window.CHAT_API_BASE || "";
    if (v) return v.replace(/\/$/, "");
    return location.protocol + "//" + (location.hostname || "127.0.0.1") + ":8120";
  }
  var API = apiBase();
  var SHOW_DELAY = 200, MIN_VISIBLE = 400, HEALTH_EVERY = 15000, STALE_AFTER = 45000;

  // ---- storage (best effort; the page works without it) -------------------------
  function load(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
  function save(key, val) { try { if (val == null) localStorage.removeItem(key); else localStorage.setItem(key, val); } catch (e) { /* ignore */ } }

  // ---- elements ---------------------------------------------------------------
  var $ = function (id) { return document.getElementById(id); };
  var $msgs = $("messages"), $input = $("input"), $form = $("composer"), $send = $("sendBtn"),
      $stop = $("stopBtn"), $cta = $("ctaRow"), $welcome = $("welcome"), $meter = $("meter"),
      $status = $("status"), $statusText = $("statusText"), $del = $("deleteChat"),
      $histList = $("historyList"), $histBox = $("historyBox");

  var state = {
    token: load("vc_visitor"), sessionId: null, controller: null, busy: false,
    retentionDays: 30, ctaLoaded: false, entryTracked: false, lastHealthOk: 0, killed: false,
    costCents: 0, remaining: null
  };

  // ---- HTTP -------------------------------------------------------------------
  function ApiError(status, code, message, retryAfter) {
    this.status = status; this.code = code; this.message = message; this.retryAfter = retryAfter;
  }

  function mint() {
    return fetch(API + "/v1/visitor", { method: "POST" }).then(function (r) {
      return r.json().then(function (b) {
        if (!r.ok) throw new ApiError(r.status, b.code, b.message, r.headers.get("retry-after"));
        state.token = b.visitor_token; state.retentionDays = b.retention_days || 30;
        save("vc_visitor", state.token);
        renderFoot();
      });
    });
  }

  function call(method, path, body, opts) {
    opts = opts || {};
    function go() {
      var headers = { "X-Visitor-Token": state.token || "" };
      if (body !== undefined) headers["Content-Type"] = "application/json";
      return fetch(API + path, {
        method: method, headers: headers, signal: opts.signal,
        body: body === undefined ? undefined : JSON.stringify(body)
      });
    }
    var ready = state.token ? Promise.resolve() : mint();
    return ready.then(go).then(function (r) {
      if (r.status === 401 && !opts.retried) { // token expired or secret rotated
        state.token = null; save("vc_visitor", null);
        return mint().then(function () { return call(method, path, body, { signal: opts.signal, retried: true, raw: opts.raw }); });
      }
      if (opts.raw && r.ok) return r;
      return r.text().then(function (txt) {
        var b = {}; try { b = txt ? JSON.parse(txt) : {}; } catch (e) { b = {}; }
        if (!r.ok) throw new ApiError(r.status, b.code || "http_" + r.status, b.message, r.headers.get("retry-after"));
        return b;
      });
    });
  }

  function errorText(err) {
    if (!(err instanceof ApiError)) return T("errUnreachable");
    if (err.code === "chat_killed") return T("errKilled");
    if (err.code === "quota_exceeded") return T("errQuota");
    if (err.code === "rate_limited") return T("errRate", { s: err.retryAfter || 5 });
    if (err.code === "service_unavailable" || err.code === "agent_unavailable") return T("errAgent");
    if (err.code === "stream_deadline") return T("errDeadline");
    return T("errGeneric", { code: err.code || err.status });
  }

  // ---- rendering -----------------------------------------------------------------
  function hideWelcome() { if ($welcome) $welcome.classList.add("hidden"); }

  function bubble(role, text) {
    hideWelcome();
    var div = document.createElement("div");
    div.className = "msg " + role;
    var body = document.createElement("div");
    body.className = "body";
    body.textContent = text || "";
    div.appendChild(body);
    var meta = document.createElement("div");
    meta.className = "meta";
    var tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = role === "user" ? T("you") : T("asst");
    meta.appendChild(tag);
    div.appendChild(meta);
    $msgs.appendChild(div);
    $msgs.scrollTop = $msgs.scrollHeight;
    return { el: div, body: body, meta: meta };
  }

  function note(b, text, cls) {
    var n = document.createElement("span");
    n.className = "note " + (cls || "");
    n.textContent = text;
    b.meta.appendChild(n);
    return n;
  }

  function addCopy(b) {
    var btn = document.createElement("button");
    btn.type = "button"; btn.className = "linkish"; btn.textContent = T("copy");
    btn.addEventListener("click", function () {
      var done = function () { btn.textContent = T("copied"); setTimeout(function () { btn.textContent = T("copy"); }, 1500); };
      if (navigator.clipboard) navigator.clipboard.writeText(b.body.textContent).then(done, function () {});
    });
    b.meta.appendChild(btn);
  }

  /* Loading indicator: appears only after SHOW_DELAY, then stays at least
     MIN_VISIBLE so fast replies do not flicker. Static text, no animation. */
  function thinking(b) {
    var shownAt = 0, timer = setTimeout(function () {
      shownAt = Date.now();
      b.el.setAttribute("aria-busy", "true");
      b.body.textContent = T("thinking");
      b.body.classList.add("pending");
    }, SHOW_DELAY);
    return function clear() {
      clearTimeout(timer);
      var wait = shownAt ? Math.max(0, MIN_VISIBLE - (Date.now() - shownAt)) : 0;
      return new Promise(function (res) {
        setTimeout(function () {
          if (shownAt) { b.body.textContent = ""; b.body.classList.remove("pending"); }
          b.el.removeAttribute("aria-busy");
          res();
        }, wait);
      });
    };
  }

  function renderMeter() {
    var parts = [];
    if (state.remaining != null) parts.push(T("usage", { n: state.remaining }));
    if (state.sessionId) parts.push(T("cost", { c: state.costCents }));
    $meter.textContent = parts.join(" · ");
  }

  function renderFoot() {
    $("footText").textContent = T("footRetention", { days: state.retentionDays });
  }

  function setBusy(on) {
    state.busy = on;
    $send.hidden = on; $send.disabled = on;
    $stop.hidden = !on;
    $del.disabled = on;
  }

  // ---- status chip (heartbeat) -------------------------------------------------------
  function setStatus(kind, text) {
    $status.setAttribute("data-state", kind);
    $statusText.textContent = text;
  }

  function pollHealth() {
    fetch(API + "/health").then(function (r) {
      return r.json().then(function (h) { return { ok: r.ok, h: h }; });
    }).then(function (res) {
      state.lastHealthOk = Date.now();
      state.killed = !!res.h.killed;
      if (!res.ok) setStatus("down", T("stDown"));
      else if (res.h.killed) setStatus("killed", T("stKilled"));
      else if (res.h.components && res.h.components.anomalies_runtime !== "🟢") setStatus("warn", T("stRuntime"));
      else setStatus("live", T("stLive"));
    }).catch(function () {
      if (Date.now() - state.lastHealthOk > STALE_AFTER && state.lastHealthOk) {
        setStatus("stale", T("stStale", { t: new Date(state.lastHealthOk).toLocaleTimeString() }));
      } else {
        setStatus("down", T("stDown"));
      }
    });
  }

  // ---- sessions, history, URL state ------------------------------------------------------
  function setUrlSession(id) {
    var u = new URL(location.href);
    if (id) u.searchParams.set("s", id); else u.searchParams.delete("s");
    history.replaceState(null, "", u.toString());
  }

  function useSession(id) {
    state.sessionId = id;
    $del.hidden = !id;
    setUrlSession(id);
    renderMeter();
  }

  function ensureSession() {
    if (state.sessionId) return Promise.resolve(state.sessionId);
    return call("POST", "/v1/chat/sessions", {}).then(function (b) {
      useSession(b.session_id);
      if (!state.entryTracked) { // first real entry, now that a session exists
        state.entryTracked = true;
        track("workbench_entry", { module: "chat", utm_source: "workbench" });
      }
      return b.session_id;
    });
  }

  function refreshHistory() {
    call("GET", "/v1/chat/sessions?limit=20").then(function (b) {
      $histList.textContent = "";
      if (!b.sessions.length) {
        var li = document.createElement("li"); li.className = "muted"; li.textContent = T("historyEmpty");
        $histList.appendChild(li); return;
      }
      b.sessions.forEach(function (s) {
        var li = document.createElement("li"), a = document.createElement("a");
        var u = new URL(location.href); u.searchParams.set("s", s.id);
        a.href = u.toString();
        a.textContent = (s.title || T("untitled")) + " · " + new Date(s.created_at).toLocaleDateString();
        if (s.id === state.sessionId) a.setAttribute("aria-current", "true");
        li.appendChild(a); $histList.appendChild(li);
      });
    }).catch(function () { /* history is optional */ });
  }

  function openSession(id) {
    return call("GET", "/v1/chat/sessions/" + encodeURIComponent(id)).then(function (s) {
      $msgs.textContent = "";
      useSession(s.id);
      s.messages.forEach(function (m) {
        var b = bubble(m.role === "user" ? "user" : "assistant", m.content);
        if (m.role === "assistant") {
          if (m.status === "interrupted") note(b, T("stopped"), "warn");
          else if (m.status === "error") note(b, T("errAgent"), "bad");
          if (m.content) addCopy(b);
        }
      });
      return call("GET", "/v1/chat/sessions/" + encodeURIComponent(id) + "/cost");
    }).then(function (c) { state.costCents = c.cost_cents; renderMeter(); })
      .catch(function (err) {
        if (err instanceof ApiError && err.status === 404) { useSession(null); return; }
        bubble("assistant", errorText(err));
      });
  }

  function newChat() {
    if (state.busy) return;
    useSession(null);
    $msgs.textContent = "";
    state.costCents = 0;
    if ($welcome) $welcome.classList.remove("hidden");
    renderMeter();
    $input.focus();
  }

  var delArmed = null;
  function deleteChat() {
    if (!state.sessionId || state.busy) return;
    if (!delArmed) { // first action arms, second independent action deletes
      $del.textContent = T("delConfirm");
      delArmed = setTimeout(function () { delArmed = null; $del.textContent = T("del"); }, 5000);
      return;
    }
    clearTimeout(delArmed); delArmed = null; $del.textContent = T("del");
    call("DELETE", "/v1/chat/sessions/" + encodeURIComponent(state.sessionId)).then(function () {
      newChat();
      bubble("assistant", T("deleted"));
      refreshHistory();
    }).catch(function (err) { bubble("assistant", errorText(err)); });
  }

  // ---- events + CTA ----------------------------------------------------------------------
  function track(type, detail) {
    call("POST", "/v1/events", { type: type, session_id: state.sessionId, detail: detail || {} })
      .catch(function () { /* telemetry never blocks the user */ });
  }

  function loadCtas() {
    if (state.ctaLoaded) return;
    state.ctaLoaded = true;
    call("GET", "/v1/cta/funnel?lang=" + I.lang).then(function (data) {
      if (!data || !data.ctas) return;
      $cta.textContent = "";
      $cta.hidden = false;
      data.ctas.forEach(function (cta) {
        var a = document.createElement("a");
        a.className = "cta"; a.href = cta.url; a.target = "_blank"; a.rel = "noopener";
        a.textContent = cta.title + " →";
        var small = document.createElement("small");
        small.textContent = cta.blurb + T("free");
        a.appendChild(small);
        a.addEventListener("click", function () {
          track("cta_click", { target: cta.url, utm_campaign: cta.campaign });
        });
        $cta.appendChild(a);
      });
    }).catch(function () { state.ctaLoaded = false; });
  }

  // ---- streaming -----------------------------------------------------------------------------
  function streamReply(messageId, b, clear) {
    state.controller = new AbortController();
    var url = "/v1/chat/sessions/" + encodeURIComponent(state.sessionId) + "/stream?message_id=" + encodeURIComponent(messageId);
    var cleared = false, gotText = false, finalStatus = null;
    function onToken(text) {
      var p = cleared ? Promise.resolve() : clear().then(function () { cleared = true; });
      return p.then(function () { b.body.textContent += text; gotText = true; $msgs.scrollTop = $msgs.scrollHeight; });
    }
    return call("GET", url, undefined, { signal: state.controller.signal, raw: true }).then(function (r) {
      var reader = r.body.getReader(), decoder = new TextDecoder(), buf = "", chain = Promise.resolve();
      function handle(msg) {
        if (msg.type === "token") chain = chain.then(function () { return onToken(msg.text); });
        else if (msg.type === "error") chain = chain.then(function () { note(b, errorText(new ApiError(0, msg.code)), "bad"); });
        else if (msg.type === "notice" && msg.code === "reply_truncated") chain = chain.then(function () { note(b, T("truncated"), "warn"); });
        else if (msg.type === "done") {
          finalStatus = msg.status;
          if (typeof msg.session_cost_cents === "number") state.costCents = msg.session_cost_cents;
          if (typeof msg.remaining_today === "number") state.remaining = msg.remaining_today;
        }
      }
      function pump() {
        return reader.read().then(function (res) {
          if (res.done) return chain;
          buf += decoder.decode(res.value, { stream: true });
          var parts = buf.split("\n\n");
          buf = parts.pop();
          parts.forEach(function (chunk) {
            chunk.split("\n").forEach(function (line) {
              if (line.indexOf("data:") !== 0) return;
              try { handle(JSON.parse(line.slice(5).trim())); } catch (e) { /* skip malformed */ }
            });
          });
          return pump();
        });
      }
      return pump();
    }).then(function () {
      return (cleared ? Promise.resolve() : clear()).then(function () {
        if (finalStatus === "interrupted") note(b, T("stopped"), "warn");
        if (gotText) addCopy(b);
        renderMeter();
      });
    }, function (err) {
      return (cleared ? Promise.resolve() : clear()).then(function () {
        if (err && err.name === "AbortError") { note(b, T("stopped"), "warn"); if (gotText) addCopy(b); return; }
        note(b, errorText(err), "bad");
      });
    }).then(function () { state.controller = null; });
  }

  function send(text, userBubble, idemKey) {
    if (state.busy) return;
    setBusy(true);
    // One key per message, reused on retry, so a retry after a lost response
    // can never post the same message twice.
    var key = idemKey || "m-" + Date.now() + "-" + Math.random().toString(36).slice(2);
    var ub = userBubble || bubble("user", text);
    var pendingNote = note(ub, T("sending"), "muted");
    ensureSession().then(function () {
      return call("POST", "/v1/chat/sessions/" + encodeURIComponent(state.sessionId) + "/messages",
        { content: text, stream: true, idempotency_key: key });
    }).then(function (data) {
      pendingNote.remove();
      if (typeof data.remaining_today === "number") state.remaining = data.remaining_today;
      var ab = bubble("assistant", "");
      var clear = thinking(ab);
      return streamReply(data.message_id, ab, clear);
    }).catch(function (err) {
      // Not accepted by the server: say so on the message itself and offer a retry.
      pendingNote.textContent = T("notSent") + " · " + errorText(err);
      pendingNote.className = "note bad";
      var retry = document.createElement("button");
      retry.type = "button"; retry.className = "linkish"; retry.textContent = T("retry");
      retry.addEventListener("click", function () { pendingNote.remove(); retry.remove(); send(text, ub, key); });
      ub.meta.appendChild(retry);
    }).then(function () {
      setBusy(false);
      refreshHistory();
      $input.focus();
    });
  }

  function stop() {
    if (state.controller) state.controller.abort();
  }

  // ---- keyboard: palette + shortcut sheet (one registry) ---------------------------------------
  var actions = {
    palette: function () { openPalette(); },
    focus: function () { $input.focus(); },
    help: function () { openHelp(); },
    stop: function () { stop(); },
    "new": function () { newChat(); },
    lang: function () { I.setLang(I.lang === "en" ? "zh" : "en"); },
    "delete": function () { deleteChat(); }
  };

  function openHelp() {
    var dl = $("helpList");
    dl.textContent = "";
    SC.SHORTCUTS.forEach(function (s) {
      if (!s.keys) return;
      var dt = document.createElement("dt"), dd = document.createElement("dd");
      var kbd = document.createElement("kbd"); kbd.textContent = SC.display(s.keys, isMac);
      dt.appendChild(kbd); dd.textContent = T(s.label);
      dl.appendChild(dt); dl.appendChild(dd);
    });
    $("helpDialog").showModal();
  }

  function renderPalette(filter) {
    var ul = $("paletteList"), f = (filter || "").toLowerCase();
    ul.textContent = "";
    var items = SC.SHORTCUTS.filter(function (s) {
      if (s.id === "palette" || s.id === "focus") return false;
      var zh = I.table[s.label] ? I.table[s.label].zh : "", en = I.table[s.label] ? I.table[s.label].en : "";
      return !f || zh.toLowerCase().indexOf(f) >= 0 || en.toLowerCase().indexOf(f) >= 0 || s.id.indexOf(f) >= 0;
    });
    if (!items.length) {
      var li0 = document.createElement("li"); li0.className = "muted"; li0.textContent = T("noMatch"); ul.appendChild(li0);
    }
    items.forEach(function (s, i) {
      var li = document.createElement("li"), btn = document.createElement("button");
      li.setAttribute("role", "option");
      btn.type = "button"; btn.className = "palette-item";
      btn.textContent = T(s.label);
      if (s.keys) { var k = document.createElement("kbd"); k.textContent = SC.display(s.keys, isMac); btn.appendChild(k); }
      btn.addEventListener("click", function () { $("paletteDialog").close(); actions[s.id](); });
      if (i === 0) li.setAttribute("aria-selected", "true");
      li.appendChild(btn); ul.appendChild(li);
    });
  }

  function openPalette() {
    var d = $("paletteDialog"), inp = $("paletteInput");
    inp.value = ""; renderPalette("");
    d.showModal(); inp.focus();
  }

  $("paletteInput").addEventListener("input", function (e) { renderPalette(e.target.value); });
  $("paletteInput").addEventListener("keydown", function (e) {
    if (e.isComposing || e.keyCode === 229) return;
    if (e.key === "Enter") {
      var first = document.querySelector("#paletteList .palette-item");
      if (first) { e.preventDefault(); first.click(); }
    }
  });

  var chord = null, chordTimer = null;
  document.addEventListener("keydown", function (e) {
    if (document.querySelector("dialog[open]") && e.key !== "Escape") return;
    var id = SC.match(e, { isMac: isMac, pending: chord });
    if (chord) { chord = null; clearTimeout(chordTimer); }
    if (id) {
      if (id === "stop" && !state.busy) return; // let Esc close dialogs normally
      e.preventDefault();
      actions[id]();
      return;
    }
    var start = SC.startsChord(e);
    if (start) { chord = start; chordTimer = setTimeout(function () { chord = null; }, 1200); }
  });

  // ---- wiring -------------------------------------------------------------------------------
  I.apply(document);
  var lt = $("langToggle");
  lt.textContent = I.lang === "en" ? "中文" : "EN";
  lt.setAttribute("aria-label", T("langSwitch"));
  lt.addEventListener("click", function () { I.setLang(I.lang === "en" ? "zh" : "en"); });

  document.querySelectorAll(".sug").forEach(function (b) {
    b.addEventListener("click", function () { $input.value = b.textContent; $input.focus(); });
  });
  $form.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = $input.value.trim();
    if (!text || state.busy) return;
    $input.value = "";
    send(text);
  });
  $stop.addEventListener("click", stop);
  $("newChat").addEventListener("click", newChat);
  $del.addEventListener("click", deleteChat);
  $("helpBtn").addEventListener("click", openHelp);
  $histBox.addEventListener("toggle", function () { if ($histBox.open) refreshHistory(); });

  renderFoot();
  pollHealth();
  setInterval(pollHealth, HEALTH_EVERY);
  setInterval(function () {
    if (state.lastHealthOk && Date.now() - state.lastHealthOk > STALE_AFTER) {
      setStatus("stale", T("stStale", { t: new Date(state.lastHealthOk).toLocaleTimeString() }));
    }
  }, 5000);
  window.addEventListener("offline", function () { setStatus("down", T("stDown")); });
  window.addEventListener("online", pollHealth);

  var startup = state.token ? Promise.resolve() : mint();
  startup.then(function () {
    loadCtas();
    return call("GET", "/v1/usage");
  }).then(function (u) {
    state.remaining = u.remaining; state.retentionDays = u.retention_days || state.retentionDays;
    renderFoot(); renderMeter();
    var sid = new URLSearchParams(location.search).get("s");
    if (sid) return openSession(sid);
  }).catch(function (err) {
    $meter.textContent = errorText(err);
  });
})();
