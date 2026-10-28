/* vertciti chat — UI copy table (zh/en). Clean-room original.
   Language: ?lang=en|zh deep link first, then the saved choice, else zh.
   Every key has both languages; a missing key shows the key, never blank. */
(function (root) {
  "use strict";
  var D = {
    docTitle: { zh: "vertciti 智能助手", en: "vertciti Assistant" },
    title: { zh: "智能助手", en: "Assistant" },
    skip: { zh: "跳到输入框", en: "Skip to message box" },
    welcomeEyebrow: { zh: "免费 · 无需注册", en: "FREE · NO SIGNUP" },
    welcome: { zh: "问点什么，vertciti 直接回答。", en: "Ask anything — vertciti answers directly." },
    sug1: { zh: "帮我比较三家 LLM API 的价格", en: "Compare pricing of three LLM APIs" },
    sug2: { zh: "把这段话翻译成地道英文", en: "Translate this into natural English" },
    sug3: { zh: "解释什么是 cap rate", en: "Explain what a cap rate is" },
    ph: { zh: "问点什么…（免费，无需注册）", en: "Ask anything… (free, no signup)" },
    inputLabel: { zh: "你的消息", en: "Your message" },
    send: { zh: "发送", en: "Send" },
    stop: { zh: "停止", en: "Stop" },
    newChat: { zh: "新对话", en: "New chat" },
    history: { zh: "历史对话", en: "Past chats" },
    historyEmpty: { zh: "还没有保存的对话", en: "No saved chats yet" },
    untitled: { zh: "新的对话", en: "New chat" },
    del: { zh: "删除本对话", en: "Delete this chat" },
    delConfirm: { zh: "再点一次确认删除", en: "Click again to delete" },
    deleted: { zh: "本对话已删除。", en: "This chat was deleted." },
    you: { zh: "你", en: "You" },
    asst: { zh: "vertciti 智能助手", en: "vertciti Assistant" },
    free: { zh: "（免费）", en: " (free)" },
    thinking: { zh: "正在思考…", en: "Thinking…" },
    sending: { zh: "发送中…", en: "Sending…" },
    notSent: { zh: "未发送", en: "Not sent" },
    retry: { zh: "重试", en: "Retry" },
    copy: { zh: "复制", en: "Copy" },
    copied: { zh: "已复制", en: "Copied" },
    stopped: { zh: "已停止，以上是已收到的部分。", en: "Stopped. The part above is what arrived." },
    truncated: { zh: "回复过长，已截断。", en: "The reply was too long and was cut." },
    footRetention: {
      zh: "免费体验 · 对话保存 {days} 天后自动删除，也可随时删除本对话",
      en: "Free preview · chats are deleted automatically after {days} days, or whenever you choose",
    },
    usage: { zh: "今日剩余 {n} 条", en: "{n} messages left today" },
    cost: { zh: "本对话成本 {c} 分", en: "This chat cost {c}¢" },
    // status chip
    stLive: { zh: "在线 · dev 过渡态", en: "Online · dev preview" },
    stRuntime: { zh: "智能体运行时未连接", en: "Agent runtime not connected" },
    stKilled: { zh: "已停止服务", en: "Service stopped" },
    stDown: { zh: "服务不可达", en: "Service unreachable" },
    stStale: { zh: "状态过期 · 上次 {t}", en: "Status stale · last {t}" },
    stChecking: { zh: "检查中…", en: "Checking…" },
    // errors (by server code)
    errUnreachable: { zh: "连不上服务。请检查网络后重试。", en: "Can't reach the service. Check your connection and retry." },
    errKilled: { zh: "服务已被运营方暂停，暂时不能对话。", en: "The operator has paused the service. Chat is unavailable for now." },
    errAgent: { zh: "智能体运行时暂不可用，没有生成任何回复。请稍后重试。", en: "The agent runtime is unavailable; no reply was generated. Please retry later." },
    errQuota: { zh: "今天的免费额度用完了，明天（UTC）再来。", en: "Today's free messages are used up. Come back tomorrow (UTC)." },
    errRate: { zh: "发得太快了，请 {s} 秒后再试。", en: "Too fast. Try again in {s} seconds." },
    errDeadline: { zh: "回复用时过长，已停止。", en: "The reply took too long and was stopped." },
    errGeneric: { zh: "出错了（{code}）。请重试。", en: "Something went wrong ({code}). Please retry." },
    errPage: { zh: "页面出错了，请刷新。", en: "The page hit an error. Please reload." },
    // shortcuts
    shortcuts: { zh: "快捷键", en: "Keyboard shortcuts" },
    palette: { zh: "指令面板", en: "Command palette" },
    palettePh: { zh: "输入指令…", en: "Type a command…" },
    close: { zh: "关闭", en: "Close" },
    langSwitch: { zh: "切换到 English", en: "切换到中文" },
    scFocus: { zh: "聚焦输入框", en: "Focus the message box" },
    scPalette: { zh: "打开指令面板", en: "Open command palette" },
    scHelp: { zh: "显示快捷键", en: "Show keyboard shortcuts" },
    scStop: { zh: "停止生成 / 关闭面板", en: "Stop reply / close dialog" },
    scNew: { zh: "新对话", en: "New chat" },
    scLang: { zh: "切换语言", en: "Switch language" },
    scDelete: { zh: "删除本对话（需再确认）", en: "Delete this chat (asks again)" },
    noMatch: { zh: "没有匹配的指令", en: "No matching command" }
  };

  var lang = null;
  try {
    var q = new URLSearchParams(root.location ? root.location.search : "").get("lang");
    if (q === "en" || q === "zh") { lang = q; root.localStorage.setItem("vc_lang", q); }
    else { lang = root.localStorage.getItem("vc_lang"); }
  } catch (e) { /* storage blocked: fall back to default */ }
  lang = lang === "en" ? "en" : "zh";

  function T(key, vars) {
    var entry = D[key];
    var s = entry ? (entry[lang] || entry.zh) : key;
    if (vars) {
      Object.keys(vars).forEach(function (k) { s = s.split("{" + k + "}").join(String(vars[k])); });
    }
    return s;
  }

  function setLang(next) {
    try { root.localStorage.setItem("vc_lang", next); } catch (e) { /* ignore */ }
    var u = new URL(root.location.href);
    u.searchParams.set("lang", next);
    root.location.href = u.toString();
  }

  function apply(doc) {
    doc.documentElement.lang = lang === "en" ? "en" : "zh-CN";
    doc.title = T("docTitle");
    doc.querySelectorAll("[data-i18n]").forEach(function (el) { el.textContent = T(el.getAttribute("data-i18n")); });
    doc.querySelectorAll("[data-i18n-ph]").forEach(function (el) { el.placeholder = T(el.getAttribute("data-i18n-ph")); });
    doc.querySelectorAll("[data-i18n-label]").forEach(function (el) {
      el.setAttribute("aria-label", T(el.getAttribute("data-i18n-label")));
    });
  }

  var api = { T: T, lang: lang, setLang: setLang, apply: apply, table: D };
  root.VC_I18N = api;
  root.T = T;
  root.VC_LANG = lang;
  if (typeof module !== "undefined" && module.exports) { module.exports = api; }
})(typeof window !== "undefined" ? window : globalThis);
