/* vertciti chat frontend — clean-room original. SSE from day one.
   API key lives in page memory only (never localStorage). */
(function () {
  "use strict";
  var API = (window.CHAT_API_BASE || "http://127.0.0.1:8120").replace(/\/$/, "");
  var apiKey = "";
  var sessionId = null;

  var $msgs = document.getElementById("messages");
  var $input = document.getElementById("input");
  var $form = document.getElementById("composer");
  var $sendBtn = document.getElementById("sendBtn");
  var $ctaRow = document.getElementById("ctaRow");
  var $badge = document.getElementById("honestyBadge");
  var $welcome = document.getElementById("welcome");

  function headers(extra) {
    var h = { "Content-Type": "application/json", "X-API-Key": apiKey };
    for (var k in extra) h[k] = extra[k];
    return h;
  }

  function addMsg(role, text) {
    var div = document.createElement("div");
    div.className = "msg " + role;
    if ($welcome) $welcome.classList.add("hidden");
    var body = document.createElement("div");
    body.textContent = text;
    div.appendChild(body);
    var tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = role === "user" ? T("you") : T("asst");
    div.appendChild(tag);
    $msgs.appendChild(div);
    $msgs.scrollTop = $msgs.scrollHeight;
    return body;
  }

  function track(type, detail) {
    if (!apiKey || !sessionId) return;
    fetch(API + "/v1/events", {
      method: "POST", headers: headers(),
      body: JSON.stringify({ type: type, session_id: sessionId, detail: detail || {} }),
    }).catch(function () {});
  }

  function loadCtas() {
    fetch(API + "/v1/cta/funnel", { headers: headers() })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data || !data.ctas) return;
        $ctaRow.hidden = false;
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
          $ctaRow.appendChild(a);
        });
      }).catch(function () {});
  }

  function ensureSession() {
    if (sessionId) return Promise.resolve(sessionId);
    return fetch(API + "/v1/chat/sessions", { method: "POST", headers: headers(), body: "{}" })
      .then(function (r) {
        if (!r.ok) throw new Error("session failed: " + r.status);
        return r.json();
      })
      .then(function (data) {
        sessionId = data.session_id;
        return sessionId;
      });
  }

  function streamReply(messageId, bubble) {
    // fetch + manual SSE parsing so we can send the API key in headers
    // (EventSource cannot set headers).
    return fetch(API + "/v1/chat/sessions/" + sessionId + "/stream?message_id=" + messageId,
      { headers: { "X-API-Key": apiKey } })
      .then(function (r) {
        if (!r.ok) throw new Error("stream failed: " + r.status);
        var reader = r.body.getReader();
        var decoder = new TextDecoder();
        var buf = "";
        function pump() {
          return reader.read().then(function (res) {
            if (res.done) return;
            buf += decoder.decode(res.value, { stream: true });
            var parts = buf.split("\n\n");
            buf = parts.pop();
            parts.forEach(function (chunk) {
              chunk.split("\n").forEach(function (line) {
                if (line.indexOf("data:") !== 0) return;
                var msg;
                try { msg = JSON.parse(line.slice(5).trim()); } catch (e) { return; }
                if (msg.type === "token") bubble.textContent += msg.text;
                else if (msg.type === "error") bubble.textContent += "\n" + T("errPrefix") + msg.message;
                $msgs.scrollTop = $msgs.scrollHeight;
              });
            });
            return pump();
          });
        }
        return pump();
      });
  }

  $form.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = $input.value.trim();
    if (!text || !apiKey) { alert(T("needKey")); return; }
    $input.value = "";
    $sendBtn.disabled = true;
    addMsg("user", text);
    var bubble = addMsg("assistant", "");
    ensureSession()
      .then(function () {
        return fetch(API + "/v1/chat/sessions/" + sessionId + "/messages", {
          method: "POST", headers: headers(),
          body: JSON.stringify({ content: text, stream: true }),
        });
      })
      .then(function (r) {
        if (!r.ok) throw new Error("send failed: " + r.status);
        return r.json();
      })
      .then(function (data) { return streamReply(data.message_id, bubble); })
      .catch(function (err) { bubble.textContent = T("errPrefix") + err.message; })
      .then(function () { $sendBtn.disabled = false; $input.focus(); });
  });

  document.getElementById("saveKey").addEventListener("click", function () {
    apiKey = document.getElementById("apiKey").value.trim();
    if (!apiKey) return;
    fetch(API + "/health")
      .then(function (r) { return r.json(); })
      .then(function (h) {
        if ($badge) $badge.textContent = (h.honesty || "") + " dev";
        if (h.components && h.components.anomalies_runtime === "🟡") {
          addMsg("assistant", T("notConnected"));
        }
      }).catch(function () {});
    loadCtas();
    track("workbench_entry", { module: "chat", utm_source: "workbench" });
  });
})();
