const gamesEl = document.getElementById("games");
const fieldListsEl = document.getElementById("fieldLists");
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

function renderPlayerRow(player, index, { waitlist = false, admin = false } = {}) {
  const actions = [];
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
    if (!game.count) return "";
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

function renderSquad(game) {
  const canJoin = game.is_open || state.is_admin;
  const squad = ensureSquad(game);
  const arrived = squad.filter((p) => p.status === "arrived").map((p) => p.name);
  const missed = squad.filter((p) => p.status === "out").map((p) => p.name);
  const waiting = squad.filter((p) => p.status === "waitlist").map((p) => p.name);
  return `
    <div class="squad">
      <h4>מי מגיע</h4>
      <ul class="name-checks">
        ${squad.map((player) => {
          const checked = player.status !== "out";
          const canToggle = canJoin && (!checked || state.is_admin);
          return `
            <li class="name-check ${player.status}">
              <button type="button" class="name-check-btn"
                data-toggle-name="${esc(player.name)}"
                data-slot="${game.slot}"
                data-id="${player.id || ""}"
                data-checked="${checked ? "1" : "0"}"
                aria-pressed="${checked ? "true" : "false"}"
                ${canToggle ? "" : "disabled"}>
                <span class="box" aria-hidden="true">${checked ? "✓" : ""}</span>
                <span class="check-name">${esc(player.name)}</span>
                <span class="check-status">${statusLabel(player.status)}</span>
              </button>
            </li>
          `;
        }).join("")}
      </ul>
      <div class="arrival-summary">
        <p><strong>הגיעו:</strong> ${arrived.length ? arrived.map(esc).join(" · ") : "אין עדיין"}</p>
        <p><strong>לא הגיעו:</strong> ${missed.length ? missed.map(esc).join(" · ") : "כולם הגיעו"}</p>
        ${waiting.length ? `<p><strong>המתנה:</strong> ${waiting.map(esc).join(" · ")}</p>` : ""}
      </div>
    </div>
  `;
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
  const statusClass = game.is_open ? "open" : game.is_past ? "past" : "closed";
  const filled = (game.count / game.max_players) * 100;
  const emptySlots = Math.max(game.max_players - game.count, 0);
  const rosterHtml = game.roster.map((p, i) => renderPlayerRow(p, i, { admin: state.is_admin })).join("")
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
      ${renderSquad(game)}
      ${renderTeams(game)}
      ${renderHistory(game)}
      ${state.is_admin ? `<div class="admin-tools"><button class="tiny-btn danger" data-clear="${game.slot}" type="button">ניקוי רשימה</button></div>` : ""}
    </article>
  `;
}

function renderField(games) {
  fieldListsEl.innerHTML = games.map((game) => {
    if (!game.roster.length) {
      return `
        <div class="field-game">
          <h3>${esc(game.label_he)}</h3>
          <p class="share">אין נרשמים עדיין · 60 ₪ על המגרש</p>
        </div>
      `;
    }
    const options = [`<option value="">בחרו מי יזמין את המגרש</option>`]
      .concat(game.roster.map((p) => `
        <option value="${p.id}" ${game.booker_id === p.id ? "selected" : ""}>${esc(p.name)}</option>
      `))
      .join("");
    return `
      <div class="field-game">
        <h3>${esc(game.label_he)}</h3>
        <p class="share">${costSplit(game)}</p>
        <label class="booker-label">מי יזמין את המגרש</label>
        <select data-booker="${game.slot}">${options}</select>
        ${game.booker_name ? `<p class="booker-picked">המזמין: <strong>${esc(game.booker_name)}</strong></p>` : `<p class="booker-picked muted">עדיין לא נבחר מזמין</p>`}
        <ul class="pay-list">
          ${game.roster.map((p) => `
            <li class="${p.paid ? "paid" : ""} ${game.booker_id === p.id ? "booker" : ""}">
              <span>${esc(p.name)}${game.booker_id === p.id ? ' <span class="booker-tag">מזמין</span>' : ""}</span>
              <span>${shareText(game.share)}${p.paid ? ' <span class="paid-tag">שולם</span>' : ""}</span>
            </li>
          `).join("")}
        </ul>
      </div>
    `;
  }).join("");
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
  if (state.is_match_day) return true;
  const local = location.hostname === "127.0.0.1" || location.hostname === "localhost";
  return local && new URLSearchParams(location.search).get("match_day") === "1";
}

function formatCountdown(ms) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function matchGameMs() {
  if (state.match_game_at) return Date.parse(state.match_game_at);
  if (isMatchDay()) {
    const d = new Date();
    d.setHours(20, 0, 0, 0);
    return d.getTime();
  }
  return 0;
}

function tickCountdown() {
  const banner = document.getElementById("matchBanner");
  const el = document.getElementById("matchCountdown");
  if (!banner || !el) return;
  if (!isMatchDay()) {
    banner.hidden = true;
    return;
  }
  banner.hidden = false;
  const left = matchGameMs() - Date.now();
  el.textContent = left <= 0 ? "המשחק התחיל" : `מתחילים בעוד ${formatCountdown(left)}`;
}

function renderMatchBanner() {
  tickCountdown();
}

function render() {
  adminBtn.textContent = state.is_admin ? "יציאה ממנהל" : "מנהל";
  renderMatchBanner();
  const notifyBtn = document.getElementById("notifyBtn");
  if (notifyBtn) {
    notifyBtn.hidden = !("Notification" in window);
    notifyBtn.textContent = localStorage.getItem("tm-notify") === "1"
      ? "תזכורות תשלום פעילות"
      : "הפעלת תזכורת תשלום";
  }
  const warn = state.is_admin && state.persistent === false
    ? `<p class="persist-warn">כדי שהרשימות לא יימחקו בעדכון ב-Render, חברו מסד PostgreSQL והגדירו DATABASE_URL.</p>`
    : "";
  gamesEl.innerHTML = warn + state.games.map(renderGame).join("");
  renderField(state.games);
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
  const toggle = e.target.closest("[data-toggle-name]");
  if (toggle) {
    if (toggle.disabled) return;
    const checked = toggle.dataset.checked === "1";
    toggle.disabled = true;
    if (!checked) {
      const data = await api("/api/join", { slot: toggle.dataset.slot, name: toggle.dataset.toggleName });
      applyState(data);
      return;
    }
    if (!state.is_admin) {
      showToast("רק המנהל יכול להסיר שחקנים");
      applyState(state);
      return;
    }
    const data = await api("/api/admin/remove", { id: Number(toggle.dataset.id) });
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

fieldListsEl.addEventListener("change", async (e) => {
  const select = e.target.closest("[data-booker]");
  if (!select) return;
  const playerId = select.value ? Number(select.value) : null;
  const data = await api("/api/booker", { slot: select.dataset.booker, player_id: playerId });
  applyState(data);
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
  let collapsed = false;
  try {
    collapsed = localStorage.getItem(HERO_COLLAPSE_KEY) === "1";
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

const notifyBtn = document.getElementById("notifyBtn");
if (notifyBtn) notifyBtn.addEventListener("click", registerPush);

initHeroToggle();

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
}
if (localStorage.getItem("tm-notify") === "1" && "Notification" in window && Notification.permission === "granted") {
  navigator.serviceWorker.ready.then((reg) => scheduleLocalReminders(reg)).catch(() => {});
}

refresh();
setInterval(refresh, 30000);
setInterval(tickCountdown, 1000);
