const gamesEl = document.getElementById("games");
const statsListsEl = document.getElementById("statsLists");
const toastEl = document.getElementById("toast");
const adminBtn = document.getElementById("adminBtn");
const adminDialog = document.getElementById("adminDialog");
const adminForm = document.getElementById("adminForm");
const adminCancel = document.getElementById("adminCancel");
const adminPassword = document.getElementById("adminPassword");

let state = { games: [], is_admin: false, stats: { games: 0, players: [] } };

function showToast(message) {
  if (!message) return;
  toastEl.hidden = false;
  toastEl.textContent = message;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => {
    toastEl.hidden = true;
  }, 2800);
}

async function api(url, body) {
  const options = body
    ? {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }
    : {};
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({ ok: false, message: "שגיאת שרת" }));
  if (!res.ok && !data.message) data.message = "פעולה נכשלה";
  return data;
}

function esc(text) {
  const d = document.createElement("div");
  d.textContent = text ?? "";
  return d.innerHTML;
}

function shareText(share) {
  if (share == null) return "אין עדיין שחקנים — עלות המגרש 60 ₪";
  const nice = Number.isInteger(share) ? String(share) : share.toFixed(2);
  return `${nice} ₪ לכל שחקן`;
}

function costSplit(game) {
  if (!game.count) return "אין נרשמים עדיין · 60 ₪ על המגרש";
  const nice = Number.isInteger(game.share) ? String(game.share) : game.share.toFixed(2);
  return `60 ₪ ÷ ${game.count} = ${nice} ₪ לכל שחקן`;
}

function renderPlayerRow(player, index, { waitlist = false, admin = false, game = null } = {}) {
  const actions = [];
  if (!waitlist && game && player.is_me) {
    const pay = bitPayButton(game, player);
    if (pay) actions.push(pay);
    if (!player.paid) {
      actions.push(`<button class="me-paid-btn" data-me-paid="${player.id}" type="button">סימנתי ששילמתי</button>`);
    }
  }
  if (admin) {
    if (!waitlist) {
      actions.push(`
        <label class="paid-check">
          <input type="checkbox" data-paid="${player.id}" ${player.paid ? "checked" : ""} />
          שולם
        </label>
      `);
    }
    actions.push(`<button class="tiny-btn danger" data-remove="${player.id}" type="button">הסרה</button>`);
  }
  return `
    <li>
      <div class="row-main">
        <span class="num">${index + 1}</span>
        <span class="name">${esc(player.name)}</span>
      </div>
      <div class="row-actions">${actions.join("")}</div>
    </li>
  `;
}

function formatShare(share) {
  if (share == null) return null;
  return Number.isInteger(share) ? String(share) : share.toFixed(2);
}

function formatBitPhone(digits) {
  if (!digits) return "";
  if (digits.length === 10 && digits.startsWith("05")) {
    return `${digits.slice(0, 3)}-${digits.slice(3)}`;
  }
  return digits;
}

function bitAppHref() {
  const ua = navigator.userAgent || "";
  const path = "www.bitpay.co.il/app/bitcom-info";
  if (/android/i.test(ua)) {
    return `intent://${path}#Intent;scheme=bit;package=com.bnhp.payments.paymentsapp;S.browser_fallback_url=https://play.google.com/store/apps/details?id=com.bnhp.payments.paymentsapp;end`;
  }
  if (/iphone|ipad|ipod/i.test(ua)) {
    return `paymentsBIT://${path}`;
  }
  return "https://www.bitpay.co.il/he";
}

function bitPayButton(game, player) {
  if (!player.is_me) return "";
  if (player.paid) return "";
  if (game.booker_id && game.booker_id === player.id) return "";
  const amount = formatShare(game.share);
  if (amount == null) return "";
  const label = `שלם בביט · ${amount} ₪`;
  return `<a class="bit-pay" data-bit-pay data-amount="${esc(amount)}" href="${esc(bitAppHref())}">${esc(label)}</a>`;
}

function onBitPayClick(link) {
  const amount = link.dataset.amount || "";
  const phone = formatBitPhone(state.bit_phone || "");
  const text = phone
    ? `${amount} ₪ בביט למספר ${phone} · טניסמייט`
    : `${amount} ₪ בביט למזמין המגרש · טניסמייט`;
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).catch(() => {});
  }
  showToast(phone
    ? `נפתחת ביט · שלמו ${amount} ₪ למספר ${phone}`
    : `נפתחת ביט · שלמו ${amount} ₪ למזמין המגרש`);
}

function renderTeamGrid(teams) {
  return `
    <div class="team-grid">
      ${(teams || []).map((team) => `
        <div class="team-card">
          <strong>${esc(team.label)}</strong>
          <ul>
            ${(team.players || []).map((p) => `<li>${esc(p.name)}</li>`).join("")}
          </ul>
        </div>
      `).join("")}
    </div>
  `;
}

function renderTeams(game) {
  if (!game.teams_ready) {
    return `<p class="draw-note">הגרלת הקבוצות תתבצע אוטומטית ב־${esc(game.draw_at_he)}</p>`;
  }
  if (!game.teams || !game.teams.length) {
    if (!game.count) return `<p class="draw-note">אין מספיק שחקנים להגרלת קבוצות</p>`;
    return `<p class="draw-note">אין מספיק שחקנים להגרלת קבוצות</p>`;
  }
  const hour2 = game.rematch_ready && game.teams2 && game.teams2.length
    ? `<div class="teams">
         <h4>שעה שנייה · 21:00</h4>
         ${renderTeamGrid(game.teams2)}
       </div>`
    : `<p class="draw-note">ב־${esc(game.rematch_at_he || "21:00")} הגרלה מחדש — בלי אותם זוגות</p>`;
  return `
    <div class="teams">
      <h4>שעה ראשונה · 20:00</h4>
      ${renderTeamGrid(game.teams)}
    </div>
    ${hour2}
  `;
}

function foldStorageKey(kind, game) {
  return `tm-${kind}-collapsed-${game.slot}-${game.week_key || ""}`;
}

function isFoldCollapsed(kind, game) {
  try {
    return localStorage.getItem(foldStorageKey(kind, game)) !== "0";
  } catch (e) {
    return true;
  }
}

function renderFold(kind, game, title, subtitle, bodyHtml) {
  const collapsed = isFoldCollapsed(kind, game);
  const key = foldStorageKey(kind, game);
  return `
    <div class="game-fold${collapsed ? " collapsed" : ""}" data-fold="${kind}" data-fold-key="${esc(key)}">
      <button type="button" class="hero-toggle game-fold-toggle" data-fold-toggle aria-expanded="${collapsed ? "false" : "true"}">
        <span class="hero-toggle-copy">
          <span class="kicker">${esc(title)}</span>
          <span class="hero-title">${esc(subtitle)}</span>
        </span>
        <span class="hero-toggle-action">${collapsed ? "הרחב" : "מזער"}</span>
      </button>
      <div class="game-fold-body">${bodyHtml}</div>
    </div>
  `;
}

function renderFieldFold(game) {
  const subtitle = game.booker_name
    ? `${costSplit(game)} · ${game.booker_name}`
    : costSplit(game);
  let body;
  if (!game.roster.length) {
    body = `<p class="share">${costSplit(game)}</p>`;
  } else {
    const select = game.is_ended
      ? ""
      : `
        <label class="booker-label">מי יזמין את המגרש</label>
        <select data-booker="${game.slot}">
          <option value="">בחרו מי יזמין את המגרש</option>
          ${game.roster.map((p) => `
            <option value="${p.id}" ${game.booker_id === p.id ? "selected" : ""}>${esc(p.name)}</option>
          `).join("")}
        </select>
      `;
    body = `
      <p class="share">${costSplit(game)}</p>
      ${select}
      ${game.booker_name
        ? `<p class="booker-picked">המזמין: <strong>${esc(game.booker_name)}</strong></p>`
        : `<p class="booker-picked muted">עדיין לא נבחר מזמין</p>`}
      <ul class="pay-list">
        ${game.roster.map((p) => `
          <li class="${p.paid ? "paid" : ""} ${game.booker_id === p.id ? "booker" : ""}">
            <span>${esc(p.name)}${game.booker_id === p.id ? ' <span class="booker-tag">מזמין</span>' : ""}</span>
            <span class="pay-right">
              ${shareText(game.share)}${p.paid ? ' <span class="paid-tag">שולם</span>' : ""}
              ${p.is_me ? bitPayButton(game, p) : ""}
              ${p.is_me && !p.paid ? `<button class="me-paid-btn" data-me-paid="${p.id}" type="button">סימנתי ששילמתי</button>` : ""}
            </span>
          </li>
        `).join("")}
      </ul>
    `;
  }
  return renderFold("field", game, "מזמין המגרש", subtitle, body);
}

function renderTeamsFold(game) {
  let subtitle = "הגרלת זוגות";
  if (game.teams_ready && game.teams && game.teams.length) {
    subtitle = game.rematch_ready && game.teams2 && game.teams2.length
      ? "שעה ראשונה ושנייה"
      : "שעה ראשונה · 20:00";
  } else if (!game.teams_ready && game.draw_at_he) {
    subtitle = `ב־${game.draw_at_he}`;
  }
  return renderFold("teams", game, "הגרלת זוגות", subtitle, renderTeams(game));
}

function ensureSquad(game) {
  if (game.squad && game.squad.length) return game.squad;
  const names = state.players || [];
  const byName = {};
  for (const player of game.roster || []) byName[player.name] = { ...player, status: "arrived" };
  for (const player of game.waiting || []) byName[player.name] = { ...player, status: "waitlist" };
  return names.map((name) => {
    const row = byName[name];
    if (row) return { name, status: row.status, id: row.id, paid: row.paid };
    return { name, status: "out", id: null, paid: false };
  });
}

function statusLabel(status) {
  if (status === "arrived") return "הגיע";
  if (status === "waitlist") return "המתנה";
  return "לא הגיע";
}

function renderJoin(game) {
  if (game.is_ended) return "";
  if (!state.user) {
    return game.is_open ? `<p class="muted join-row">התחברו כדי להירשם למשחק</p>` : "";
  }
  const mine = [...(game.roster || []), ...(game.waiting || [])].some((p) => p.is_me);
  if (mine) {
    return `<p class="muted join-row">אתה רשום למשחק</p>`;
  }
  if (state.unpaid) {
    return `<p class="pay-warn join-row">${esc(state.pay_warning || "הלו הלו לא שילמת למשחקת תשלם עכשיו")}</p>`;
  }
  if (game.is_open) {
    return `<div class="join-row"><button class="primary-btn" data-join="${game.slot}" type="button">הרשמה</button></div>`;
  }
  if (state.is_admin) {
    return `<div class="join-row"><button class="primary-btn" data-join="${game.slot}" type="button">הרשמה</button></div>`;
  }
  return "";
}

function renderHistory(game) {
  if (!game.history || !game.history.length) return "";
  return `
    <div class="history">
      <h4>הרשמות קודמות</h4>
      ${game.history.map((h) => `
        <div class="history-card">
          <strong>${esc(h.game_at_he)}</strong>
          <p>${h.roster.length ? h.roster.map((p) => esc(p.name)).join(" · ") : "אין נרשמים"}</p>
          ${h.booker_name ? `<p>מזמין: ${esc(h.booker_name)}</p>` : ""}
          ${h.teams && h.teams.length
            ? `<p>שעה ראשונה: ${h.teams.map((t) => `${esc(t.label)} ${t.players.map((p) => esc(p.name)).join(", ")}`).join(" · ")}</p>`
            : ""}
          ${h.teams2 && h.teams2.length
            ? `<p class="history-team">שעה שנייה: ${h.teams2.map((t) => `${esc(t.label)} ${t.players.map((p) => esc(p.name)).join(", ")}`).join(" · ")}</p>`
            : ""}
        </div>
      `).join("")}
    </div>
  `;
}

function renderGame(game) {
  const statusClass = game.is_ended ? "ended" : game.is_open ? "open" : game.is_past ? "past" : "closed";
  const filled = (game.count / game.max_players) * 100;
  const emptySlots = Math.max(game.max_players - game.count, 0);
  const rosterHtml = game.roster.map((p, i) => renderPlayerRow(p, i, { admin: state.is_admin, game })).join("")
    + Array.from({ length: emptySlots }, (_, i) => `
        <li class="empty">
          <div class="row-main">
            <span class="num">${game.count + i + 1}</span>
            <span>מקום פנוי</span>
          </div>
        </li>
      `).join("");

  const waitingHtml = game.waiting.length
    ? `<h4 class="wait-title">רשימת המתנה</h4>
       <ul class="wait-list">${game.waiting.map((p, i) => renderPlayerRow(p, i, { waitlist: true, admin: state.is_admin })).join("")}</ul>`
    : "";

  return `
    <article class="game-card" data-slot="${game.slot}">
      <div class="game-head">
        <div>
          <h3>${esc(game.label_he)}</h3>
          <p class="meta">${esc(game.game_at_he)}</p>
        </div>
        <span class="status ${statusClass}">${esc(game.status_he)}</span>
      </div>
      <p class="muted">${esc(game.status_detail)}</p>
      <div class="list-head">
        <div class="spots"><span>${game.count}/${game.max_players} שחקנים</span><span>${game.spots_left} מקומות פנויים</span></div>
        <button class="refresh-btn" type="button" data-refresh="${game.slot}">רענון</button>
      </div>
      <div class="bar"><span style="width:${filled}%"></span></div>
      <ul class="player-list">${rosterHtml}</ul>
      ${waitingHtml}
      ${renderJoin(game)}
      ${renderFieldFold(game)}
      ${renderTeamsFold(game)}
      ${renderHistory(game)}
      ${state.is_admin ? `<div class="admin-tools"><button class="tiny-btn danger" data-clear="${game.slot}" type="button">ניקוי רשימה</button></div>` : ""}
    </article>
  `;
}

function sparkDots(history, onClass, offClass) {
  const bits = Array.isArray(history) ? history : [];
  if (!bits.length) {
    return `<span class="spark-empty">אין עדיין</span>`;
  }
  return bits.map((bit) =>
    `<span class="spark-dot ${bit ? onClass : offClass}"></span>`
  ).join("");
}

function stackedBar(onCount, offCount, onClass, offClass) {
  const total = Math.max(0, (onCount || 0) + (offCount || 0));
  if (!total) {
    return `<div class="stats-bar empty" aria-hidden="true"></div>`;
  }
  const onPct = Math.round((onCount / total) * 100);
  return `
    <div class="stats-bar" aria-hidden="true">
      <span class="${onClass}" style="width:${onPct}%"></span>
      <span class="${offClass}" style="width:${100 - onPct}%"></span>
    </div>
  `;
}

function renderStats() {
  const stats = state.stats || { games: 0, players: [] };
  const testBtn = state.is_admin
    ? `<button class="tiny-btn" data-pay-reminder type="button">בדיקת תזכורת תשלום</button>`
    : "";
  const players = stats.players || [];
  const emptyNote = stats.games
    ? ""
    : `<p class="muted">עדיין אין משחקים שהסתיימו. אחרי משחק יופיעו כאן היסטוריית הגעה והזמנת מגרש.</p>`;
  statsListsEl.innerHTML = `
    ${emptyNote}
    <p class="stats-count">${stats.games || 0} משחקים שהסתיימו</p>
    <ul class="stats-list">
      ${players.map((p) => {
        const arrived = p.arrived || 0;
        const missed = p.missed || 0;
        const booked = p.booked || 0;
        const notBooked = p.not_booked != null ? p.not_booked : Math.max((arrived + missed) - booked, 0);
        return `
        <li class="stats-player">
          <span class="stats-name">${esc(p.name)}</span>
          <div class="stats-graphs">
            <div class="stats-metric">
              <span class="stats-metric-label">הגעה</span>
              ${stackedBar(arrived, missed, "bar-arrived", "bar-missed")}
              <span class="stats-metric-nums">
                <span class="arrived-n">${arrived} הגיע</span>
                <span class="missed-n">${missed} לא</span>
              </span>
              <div class="sparkline" title="היסטוריית הגעה">${sparkDots(p.arrival_history, "on-arrived", "off-missed")}</div>
            </div>
            <div class="stats-metric">
              <span class="stats-metric-label">הזמנת מגרש</span>
              ${stackedBar(booked, notBooked, "bar-booked", "bar-idle")}
              <span class="stats-metric-nums">
                <span class="booked-n">${booked} הזמין</span>
              </span>
              <div class="sparkline" title="היסטוריית הזמנה">${sparkDots(p.booker_history, "on-booked", "off-idle")}</div>
            </div>
          </div>
        </li>`;
      }).join("")}
    </ul>
    ${testBtn}
  `;
}

function isMatchDay() {
  if (state.banner_flash === false) return false;
  if (state.banner_flash === true) return true;
  if (state.is_match_day) return true;
  const local = location.hostname === "127.0.0.1" || location.hostname === "localhost";
  return local && new URLSearchParams(location.search).get("match_day") === "1";
}

function bannerShouldFlash() {
  if (state.banner_flash === true) return true;
  if (state.banner_flash === false) return false;
  return isMatchDay();
}

function formatCountdown(ms) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function nextGameMs() {
  if (state.next_game_at) return Date.parse(state.next_game_at);
  const games = state.games || [];
  const now = Date.now();
  const upcoming = games
    .map((g) => Date.parse(g.game_at))
    .filter((t) => t > now)
    .sort((a, b) => a - b);
  return upcoming[0] || 0;
}

function matchInProgress() {
  if (!bannerShouldFlash()) return false;
  const start = state.match_game_at
    ? Date.parse(state.match_game_at)
    : (() => {
        const d = new Date();
        d.setHours(20, 0, 0, 0);
        return d.getTime();
      })();
  const end = start + (2 * 60 + 1) * 60 * 1000;
  const now = Date.now();
  return now >= start && now < end;
}

function isPlayerLoggedIn() {
  return Boolean(state.user);
}

function applyScreen() {
  const loggedIn = isPlayerLoggedIn();
  const appScreen = document.getElementById("appScreen");
  const banner = document.getElementById("matchBanner");
  const page = document.querySelector(".page");
  if (appScreen) appScreen.hidden = !loggedIn;
  if (banner) banner.hidden = !loggedIn;
  document.body.classList.toggle("login-only", !loggedIn);
  if (page) page.classList.toggle("login-only", !loggedIn);
}

function tickCountdown() {
  const banner = document.getElementById("matchBanner");
  const el = document.getElementById("matchCountdown");
  const title = document.getElementById("matchBannerTitle");
  if (!banner || !el) return;
  if (!isPlayerLoggedIn()) {
    banner.hidden = true;
    return;
  }
  banner.hidden = false;
  const flash = bannerShouldFlash();
  banner.classList.toggle("match-day", flash);
  if (title) {
    title.textContent = flash
      ? "יום המשחק הגיע"
      : `המשחק הבא · ${state.next_game_at_he || state.next_game_label_he || ""}`.trim();
  }
  if (matchInProgress()) {
    el.textContent = "המשחק התחיל";
    return;
  }
  const at = nextGameMs();
  if (!at) {
    el.textContent = state.next_game_at_he || "";
    return;
  }
  const left = at - Date.now();
  el.textContent = left <= 0
    ? (state.next_game_at_he || "המשחק הבא")
    : `מתחילים בעוד ${formatCountdown(left)}`;
}

function renderMatchBanner() {
  tickCountdown();
}

function renderAuth() {
  const loggedOut = document.getElementById("authLoggedOut");
  const loggedIn = document.getElementById("authLoggedIn");
  const hello = document.getElementById("authHello");
  const payWarn = document.getElementById("payWarn");
  if (state.user) {
    if (loggedOut) loggedOut.hidden = true;
    if (loggedIn) loggedIn.hidden = false;
    if (hello) hello.textContent = state.user.name;
  } else {
    if (loggedOut) loggedOut.hidden = false;
    if (loggedIn) loggedIn.hidden = true;
  }
  if (payWarn) {
    if (state.unpaid && state.pay_warning) {
      payWarn.hidden = false;
      payWarn.textContent = state.pay_warning;
    } else {
      payWarn.hidden = true;
      payWarn.textContent = "";
    }
  }
}

function render() {
  adminBtn.textContent = state.is_admin ? "יציאה ממנהל" : "מנהל";
  renderAuth();
  applyScreen();
  renderMatchBanner();
  const notifyBtn = document.getElementById("notifyBtn");
  if (notifyBtn) {
    notifyBtn.hidden = !("Notification" in window);
    notifyBtn.textContent = localStorage.getItem("tm-notify") === "1"
      ? "תזכורות תשלום פעילות"
      : "הפעלת תזכורת תשלום";
  }
  if (!isPlayerLoggedIn()) {
    if (gamesEl) gamesEl.innerHTML = "";
    if (statsListsEl) statsListsEl.innerHTML = "";
    return;
  }
  const warn = state.is_admin && state.persistent === false
    ? `<p class="persist-warn">כדי שהרשימות לא יימחקו בעדכון ב-Render, חברו מסד PostgreSQL והגדירו DATABASE_URL.</p>`
    : "";
  gamesEl.innerHTML = warn + state.games.map(renderGame).join("");
  renderStats();
}

function applyState(data) {
  if (data.games) state = data;
  render();
  if (data.message) showToast(data.message);
}

async function refresh() {
  const data = await api("/api/state");
  applyState(data);
}

gamesEl.addEventListener("click", async (e) => {
  const foldBtn = e.target.closest("[data-fold-toggle]");
  if (foldBtn) {
    const wrap = foldBtn.closest(".game-fold");
    if (!wrap) return;
    const next = !wrap.classList.contains("collapsed");
    wrap.classList.toggle("collapsed", next);
    foldBtn.setAttribute("aria-expanded", next ? "false" : "true");
    const action = foldBtn.querySelector(".hero-toggle-action");
    if (action) action.textContent = next ? "הרחב" : "מזער";
    try {
      localStorage.setItem(wrap.dataset.foldKey, next ? "1" : "0");
    } catch (err) {}
    return;
  }
  const bitLink = e.target.closest("[data-bit-pay]");
  if (bitLink) {
    onBitPayClick(bitLink);
    return;
  }
  const joinBtn = e.target.closest("[data-join]");
  if (joinBtn) {
    joinBtn.disabled = true;
    const data = await api("/api/join", { slot: joinBtn.dataset.join });
    applyState(data);
    return;
  }
  const mePaid = e.target.closest("[data-me-paid]");
  if (mePaid) {
    mePaid.disabled = true;
    const data = await api("/api/me/paid", { id: Number(mePaid.dataset.mePaid) });
    applyState(data);
    return;
  }
  const refreshBtn = e.target.closest("[data-refresh]");
  if (refreshBtn) {
    refreshBtn.disabled = true;
    const data = await api("/api/state");
    applyState(data);
    showToast("הרשימה עודכנה");
    return;
  }
  const removeBtn = e.target.closest("[data-remove]");
  if (removeBtn) {
    const data = await api("/api/admin/remove", { id: Number(removeBtn.dataset.remove) });
    applyState(data);
    return;
  }
  const payBtn = e.target.closest("[data-pay-reminder]");
  if (payBtn) {
    payBtn.disabled = true;
    const data = await api("/api/admin/pay-reminder", {});
    applyState(data);
    if (data.sent && data.sent.length && "Notification" in window && Notification.permission === "granted") {
      const first = data.sent[0];
      new Notification(first.title, { body: first.body, dir: "rtl", lang: "he" });
    }
    payBtn.disabled = false;
    return;
  }
  const clearBtn = e.target.closest("[data-clear]");
  if (clearBtn) {
    if (!confirm("לנקות את כל הרשימה למשחק הזה?")) return;
    const data = await api("/api/admin/clear", { slot: clearBtn.dataset.clear });
    applyState(data);
  }
});

gamesEl.addEventListener("change", async (e) => {
  const select = e.target.closest("[data-booker]");
  if (select) {
    const playerId = select.value ? Number(select.value) : null;
    const data = await api("/api/booker", { slot: select.dataset.booker, player_id: playerId });
    applyState(data);
    return;
  }
  const box = e.target.closest("[data-paid]");
  if (!box) return;
  const data = await api("/api/admin/paid", { id: Number(box.dataset.paid), paid: box.checked });
  applyState(data);
});

statsListsEl.addEventListener("click", async (e) => {
  const payBtn = e.target.closest("[data-pay-reminder]");
  if (!payBtn) return;
  payBtn.disabled = true;
  const data = await api("/api/admin/pay-reminder", {});
  applyState(data);
  if (data.sent && data.sent.length && "Notification" in window && Notification.permission === "granted") {
    const first = data.sent[0];
    new Notification(first.title, { body: first.body, dir: "rtl", lang: "he" });
  }
  payBtn.disabled = false;
});

adminBtn.addEventListener("click", async () => {
  if (state.is_admin) {
    const data = await api("/api/admin/logout", {});
    applyState(data);
    return;
  }
  adminPassword.value = "";
  adminDialog.showModal();
  adminPassword.focus();
});

adminCancel.addEventListener("click", () => adminDialog.close());

adminForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = await api("/api/admin/login", { password: adminPassword.value });
  if (data.ok) adminDialog.close();
  applyState(data);
});

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const output = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) output[i] = raw.charCodeAt(i);
  return output;
}

async function registerPush() {
  if (!("serviceWorker" in navigator) || !("Notification" in window)) {
    showToast("הדפדפן לא תומך בהתראות");
    return;
  }
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    showToast("צריך לאשר התראות כדי לקבל תזכורת תשלום");
    return;
  }
  const registration = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
  await navigator.serviceWorker.ready;
  localStorage.setItem("tm-notify", "1");
  if (state.vapid_public_key && registration.pushManager) {
    try {
      const sub = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(state.vapid_public_key),
      });
      await api("/api/push/subscribe", { subscription: sub.toJSON() });
    } catch (err) {
      console.warn("push subscribe failed", err);
    }
  }
  scheduleLocalReminders(registration);
  render();
  showToast("התראות הופעלו: שעה לפני המשחק, ואחרי המשחק תזכורת תשלום.");
}

function showLocalNote(registration, title, body, tag) {
  if (registration && registration.showNotification) {
    registration.showNotification(title, { body, dir: "rtl", lang: "he", tag });
  } else if (Notification.permission === "granted") {
    new Notification(title, { body, dir: "rtl", lang: "he" });
  }
}

function scheduleAt(iso, handler, storeKey) {
  const when = iso ? Date.parse(iso) : 0;
  if (!when) return;
  const delay = when - Date.now();
  if (delay <= 0 || delay > 7 * 24 * 60 * 60 * 1000) return;
  clearTimeout(scheduleAt[storeKey]);
  scheduleAt[storeKey] = setTimeout(handler, delay);
}

function scheduleLocalReminders(registration) {
  scheduleAt(state.pay_reminder_at, async () => {
    const data = await api("/api/cron/pay-reminder", { force: false });
    const pay = (data.pay && data.pay.sent && data.pay.sent[0]) || (data.sent || []).find((s) => !s.kind);
    showLocalNote(
      registration,
      pay ? pay.title : "תזכורת תשלום · טניסמייט",
      pay ? pay.body : "בדקו בטניסמייט כמה לשלם על המגרש.",
      "tennismate-pay"
    );
  }, "_pay");
  scheduleAt(state.hour_before_at, () => {
    showLocalNote(
      registration,
      "המשחק בעוד שעה · טניסמייט",
      "מתחילים ב־20:00. סמנו הגעה אם עוד לא.",
      "tennismate-hour"
    );
  }, "_hour");
}

const HERO_COLLAPSE_KEY = "tm-hero-collapsed";
const AUTH_EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function showAuthError(message, { toast = true } = {}) {
  const el = document.getElementById("authError");
  if (el) {
    el.hidden = !message;
    el.textContent = message || "";
  }
  if (message && toast) showToast(message);
}

function authValues() {
  return {
    email: (document.getElementById("authEmail")?.value || "").trim(),
    password: document.getElementById("authPassword")?.value || "",
    name: (document.getElementById("authName")?.value || "").trim(),
  };
}

function validateAuth({ needPassword = false, needName = false } = {}) {
  const values = authValues();
  if (!values.email) {
    showAuthError("יש להזין אימייל");
    return null;
  }
  if (!AUTH_EMAIL_RE.test(values.email)) {
    showAuthError("אימייל לא תקין");
    return null;
  }
  if (needPassword && !values.password) {
    showAuthError("יש להזין סיסמה");
    return null;
  }
  if (needPassword && values.password.length < 6) {
    showAuthError("הסיסמה חייבת לפחות 6 תווים");
    return null;
  }
  if (needName && !values.name) {
    showAuthError("יש להזין שם");
    return null;
  }
  showAuthError("");
  return values;
}

function applyAuthResult(data) {
  applyState(data);
  if (!data.ok && data.message) showAuthError(data.message, { toast: false });
  if (data.ok && data.user) {
    showAuthError("");
    window.scrollTo(0, 0);
  }
}

function initAuth() {
  const form = document.getElementById("authForm");
  const registerBtn = document.getElementById("authRegisterBtn");
  const resetBtn = document.getElementById("authResetBtn");
  const logoutBtn = document.getElementById("logoutBtn");
  const nameBlock = document.getElementById("authNameBlock");
  const resetNote = document.getElementById("authResetNote");
  const title = document.getElementById("authTitle");
  const loginBtn = document.getElementById("authLoginBtn");
  const nameInput = document.getElementById("authName");
  let registerMode = false;

  function setRegisterMode(on) {
    registerMode = on;
    if (nameBlock) nameBlock.hidden = !on;
    if (title) title.textContent = on ? "הרשמה לשחקנים" : "כניסה לשחקנים";
    if (loginBtn) loginBtn.textContent = on ? "הרשמה" : "כניסה";
    if (registerBtn) registerBtn.textContent = on ? "חזרה לכניסה" : "הרשמה";
    if (on && nameInput) nameInput.focus();
  }

  if (registerBtn) {
    registerBtn.addEventListener("click", () => {
      showAuthError("");
      setRegisterMode(!registerMode);
    });
  }

  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (registerMode) {
        const values = validateAuth({ needPassword: true, needName: true });
        if (!values) return;
        const data = await api("/api/register", values);
        applyAuthResult(data);
        return;
      }
      const values = validateAuth({ needPassword: true });
      if (!values) return;
      const data = await api("/api/login", {
        email: values.email,
        password: values.password,
      });
      applyAuthResult(data);
    });
  }

  if (resetBtn) {
    resetBtn.addEventListener("click", async () => {
      const values = validateAuth();
      if (!values) return;
      const data = await api("/api/reset-password", { email: values.email });
      applyAuthResult(data);
      if (data.ok && data.new_password && resetNote) {
        resetNote.hidden = false;
        resetNote.textContent = `הסיסמה החדשה: ${data.new_password}`;
      }
    });
  }

  if (logoutBtn) {
    logoutBtn.addEventListener("click", async () => {
      const data = await api("/api/logout", {});
      applyState(data);
    });
  }
}

function applyHeroCollapsed(collapsed) {
  const card = document.getElementById("heroCard");
  const btn = document.getElementById("heroToggle");
  const action = btn && btn.querySelector(".hero-toggle-action");
  if (!card || !btn) return;
  card.classList.toggle("collapsed", collapsed);
  btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
  if (action) action.textContent = collapsed ? "הרחב" : "מזער";
}

function initHeroToggle() {
  const btn = document.getElementById("heroToggle");
  if (!btn) return;
  let collapsed = true;
  try {
    collapsed = localStorage.getItem(HERO_COLLAPSE_KEY) !== "0";
  } catch (e) {}
  applyHeroCollapsed(collapsed);
  btn.addEventListener("click", () => {
    const next = !document.getElementById("heroCard").classList.contains("collapsed");
    applyHeroCollapsed(next);
    try {
      localStorage.setItem(HERO_COLLAPSE_KEY, next ? "1" : "0");
    } catch (e) {}
  });
}

const STATS_COLLAPSE_KEY = "tm-stats-collapsed";

function applyStatsCollapsed(collapsed) {
  const card = document.getElementById("statsSection");
  const btn = document.getElementById("statsToggle");
  const action = btn && btn.querySelector(".hero-toggle-action");
  if (!card || !btn) return;
  card.classList.toggle("collapsed", collapsed);
  btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
  if (action) action.textContent = collapsed ? "הרחב" : "מזער";
}

function initStatsToggle() {
  const btn = document.getElementById("statsToggle");
  if (!btn) return;
  let collapsed = true;
  try {
    collapsed = localStorage.getItem(STATS_COLLAPSE_KEY) !== "0";
  } catch (e) {}
  applyStatsCollapsed(collapsed);
  btn.addEventListener("click", () => {
    const next = !document.getElementById("statsSection").classList.contains("collapsed");
    applyStatsCollapsed(next);
    try {
      localStorage.setItem(STATS_COLLAPSE_KEY, next ? "1" : "0");
    } catch (e) {}
  });
}

const notifyBtn = document.getElementById("notifyBtn");
if (notifyBtn) notifyBtn.addEventListener("click", registerPush);

initAuth();
initHeroToggle();
initStatsToggle();

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
}
if (localStorage.getItem("tm-notify") === "1" && "Notification" in window && Notification.permission === "granted") {
  navigator.serviceWorker.ready.then((reg) => scheduleLocalReminders(reg)).catch(() => {});
}

refresh();
setInterval(refresh, 30000);
setInterval(tickCountdown, 1000);
