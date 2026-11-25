const gamesEl = document.getElementById("games");
const pastGamesEl = document.getElementById("pastGames");
const statsListsEl = document.getElementById("statsLists");
// Expanded players on the stats screen. Lives in memory so refreshes keep them open,
// and starts empty so the screen always opens fully minimized.
const statsOpen = new Set();
const homeViewEl = document.getElementById("homeView");
const matchDayViewEl = document.getElementById("matchDayView");
const appTabsEl = document.getElementById("appTabs");
const toastEl = document.getElementById("toast");
const adminBtn = document.getElementById("adminBtn");
const adminDialog = document.getElementById("adminDialog");
const adminForm = document.getElementById("adminForm");
const adminCancel = document.getElementById("adminCancel");
const adminPassword = document.getElementById("adminPassword");

let state = { games: [], past_games: [], is_admin: false, stats: { games: 0, players: [] } };

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

function fieldCost(game) {
  const cost = game && game.field_cost != null ? Number(game.field_cost) : 60;
  return Number.isFinite(cost) ? cost : 60;
}

function shareText(share, game) {
  const cost = fieldCost(game);
  if (share == null) return `אין עדיין שחקנים — עלות המגרש ${cost} ₪`;
  const nice = Number.isInteger(share) ? String(share) : share.toFixed(2);
  return `${nice} ₪ לכל שחקן`;
}

function costSplit(game) {
  const cost = fieldCost(game);
  if (!game.count) return `אין נרשמים עדיין · ${cost} ₪ על המגרש`;
  const nice = Number.isInteger(game.share) ? String(game.share) : game.share.toFixed(2);
  return `${cost} ₪ ÷ ${game.count} = ${nice} ₪ לכל שחקן`;
}

function formatGameClock(game, extraHours = 0) {
  if (!game || !game.game_at) return extraHours ? "21:00" : "20:00";
  const start = new Date(game.game_at);
  if (Number.isNaN(start.getTime())) return extraHours ? "21:00" : "20:00";
  const d = new Date(start.getTime() + extraHours * 60 * 60 * 1000);
  return d.toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit", hour12: false });
}

function wazeHref(address) {
  const q = encodeURIComponent(address);
  return `https://waze.com/ul?q=${q}&navigate=yes`;
}

const LAZUZ_URL = "https://www.lazuz.co.il/";

function lazuzBookLink(game) {
  if (!game.is_open) return "";
  return `
    <a class="lazuz-link" href="${LAZUZ_URL}" target="_blank" rel="noopener noreferrer">
      הזמן מגרש בלזוז
    </a>
  `;
}

function renderGameHead(game, statusClass) {
  const waze = wazeButton(game);
  const lazuz = lazuzBookLink(game);
  const hasVenue = Boolean(game.location || waze);
  return `
    <div class="game-head">
      <div class="game-head-copy">
        <h3>${esc(game.label_he)}</h3>
        <p class="meta">${esc(game.game_at_he)}</p>
      </div>
      <div class="game-status-col">
        <span class="status ${statusClass}">${esc(game.status_he)}</span>
        ${hasVenue ? "" : lazuz}
      </div>
    </div>
    ${hasVenue ? `
    <div class="game-place">
      ${game.location ? `<p class="place-name">${esc(game.location)}</p>` : ""}
      <div class="game-place-actions">
        ${waze}
        ${lazuz}
      </div>
    </div>` : ""}
  `;
}

function wazeButton(game) {
  const address = (game.nav_address || "").trim();
  if (!address) return "";
  const title = game.location ? `ניווט ב־Waze אל ${game.location}` : "ניווט ב־Waze אל המגרש";
  return `
    <a class="waze-btn" data-waze href="${esc(wazeHref(address))}" target="_blank" rel="noopener noreferrer" aria-label="${esc(title)}" title="${esc(title)}">
      <svg viewBox="0 0 32 32" width="22" height="22" aria-hidden="true">
        <circle cx="16" cy="16" r="15" fill="#33ccff"/>
        <path fill="#0b3d5c" d="M16 6.2c-4.6 0-8.3 3.5-8.3 8.1 0 4.8 6.7 11.5 8.3 11.5s8.3-6.7 8.3-11.5c0-4.6-3.7-8.1-8.3-8.1zm0 11.2a3.1 3.1 0 1 1 0-6.2 3.1 3.1 0 0 1 0 6.2z"/>
      </svg>
    </a>
  `;
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
        ${player.avatar
          ? `<img class="row-avatar" src="${esc(player.avatar)}" alt="" />`
          : `<span class="num">${index + 1}</span>`}
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
         <h4>שעה שנייה · ${esc(formatGameClock(game, 1))}</h4>
         ${renderTeamGrid(game.teams2)}
       </div>`
    : game.count === 5
      ? `<p class="draw-note">בחמישה שחקנים נקבע רק ההרכב הפותח — ההמשך לפי תוצאות המשחק</p>`
      : `<p class="draw-note">ב־${esc(game.rematch_at_he || formatGameClock(game, 1))} הגרלה מחדש — בלי אותם זוגות</p>`;
  return `
    <div class="teams">
      <h4>שעה ראשונה · ${esc(formatGameClock(game))}</h4>
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

const bookerCustomOpen = {};

function bookerUsers() {
  return state.users || [];
}

function bookerKey(game) {
  return `${game.slot}:${game.week_key || ""}`;
}

function bookerSelectValue(game) {
  if (bookerCustomOpen[bookerKey(game)]) return "custom";
  const users = bookerUsers();
  if (game.booker_id) {
    const player = (game.roster || []).find((p) => p.id === game.booker_id);
    if (player && player.user_id) return `user:${player.user_id}`;
  }
  if (game.booker_name) {
    const match = users.find((user) => user.name === game.booker_name);
    if (match) return `user:${match.id}`;
    return "custom";
  }
  return "";
}

function renderBookerPicker(game) {
  if (game.is_ended && !state.is_admin) return "";
  if (!state.user && !state.is_admin) return "";
  const selected = bookerSelectValue(game);
  const showCustom = selected === "custom";
  const custom = showCustom && !game.booker_id ? (game.booker_name || "") : "";
  return `
    <label class="booker-label">מי יזמין את המגרש</label>
    <select data-booker="${esc(game.slot)}" data-week-key="${esc(game.week_key || "")}">
      <option value="">בחרו מי יזמין את המגרש</option>
      ${bookerUsers().map((user) => `
        <option value="user:${user.id}" ${selected === `user:${user.id}` ? "selected" : ""}>${esc(user.name)}</option>
      `).join("")}
      <option value="custom" ${showCustom ? "selected" : ""}>שם אחר</option>
    </select>
    <form class="booker-custom" data-booker-custom="${esc(game.slot)}" data-week-key="${esc(game.week_key || "")}" ${showCustom ? "" : "hidden"}>
      <input type="text" maxlength="80" placeholder="שם המזמין" value="${esc(custom)}" autocomplete="name" />
      <button type="submit" class="tiny-btn">שמירה</button>
    </form>
  `;
}

function renderFieldFold(game) {
  const subtitle = game.booker_name
    ? `${costSplit(game)} · ${game.booker_name}`
    : costSplit(game);
  const picker = renderBookerPicker(game);
  let body;
  if (!game.roster.length) {
    body = `
      <p class="share">${costSplit(game)}</p>
      ${picker}
      ${game.booker_name
        ? `<p class="booker-picked">המזמין: <strong>${esc(game.booker_name)}</strong></p>`
        : `<p class="booker-picked muted">עדיין לא נבחר מזמין</p>`}
    `;
  } else {
    body = `
      <p class="share">${costSplit(game)}</p>
      ${picker}
      ${game.booker_name
        ? `<p class="booker-picked">המזמין: <strong>${esc(game.booker_name)}</strong></p>`
        : `<p class="booker-picked muted">עדיין לא נבחר מזמין</p>`}
      <ul class="pay-list">
        ${game.roster.map((p) => `
          <li class="${p.paid ? "paid" : ""} ${game.booker_id === p.id ? "booker" : ""}">
            <span>${esc(p.name)}${game.booker_id === p.id ? ' <span class="booker-tag">מזמין</span>' : ""}</span>
            <span class="pay-right">
              ${shareText(game.share, game)}${p.paid ? ' <span class="paid-tag">שולם</span>' : ""}
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
      : `שעה ראשונה · ${formatGameClock(game)}`;
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

function myEnrollment(game) {
  if (!game) return null;
  return [...(game.roster || []), ...(game.waiting || [])].find((player) => player.is_me) || null;
}

function renderJoin(game) {
  if (game.is_ended) return "";
  if (!state.user) {
    return game.is_open ? `<p class="muted join-row">התחברו כדי להירשם למשחק</p>` : "";
  }
  const mine = myEnrollment(game);
  if (mine) {
    const note = mine.is_waitlist || (game.waiting || []).some((p) => p.is_me)
      ? "אתה ברשימת ההמתנה"
      : "אתה רשום למשחק";
    const cancel = game.is_open
      ? `<button class="leave-btn danger-btn" data-leave="${game.slot}" type="button">ביטול הרשמה</button>`
      : "";
    return `<div class="join-row"><p class="muted">${note}</p>${cancel}</div>`;
  }
  if (state.unpaid && !state.is_admin) {
    return "";
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

function renderAdminDate(game) {
  if (!state.is_admin) return "";
  const dateVal = game.game_date || (game.game_at || "").slice(0, 10);
  const timeVal = game.game_time || (game.game_at || "").slice(11, 16) || "20:00";
  const location = game.location || "";
  const nav = game.nav_address || "";
  const cost = fieldCost(game);
  const hasOverride = Boolean(
    game.date_override
    || game.time_override
    || location
    || nav
    || (game.field_cost != null && Number(game.field_cost) !== 60)
  );
  const reset = hasOverride
    ? `<button type="button" class="tiny-btn" data-field-reset="${esc(game.slot)}" data-week-key="${esc(game.week_key || "")}">חזרה לברירת מחדל</button>`
    : "";
  return `
    <form class="admin-field" data-game-settings="${esc(game.slot)}" data-week-key="${esc(game.week_key || "")}">
      <p class="admin-field-title">פרטי המגרש</p>
      <label>תאריך המשחק
        <input type="date" name="date" value="${esc(dateVal)}" required />
      </label>
      <label>שעה
        <input type="time" name="time" value="${esc(timeVal)}" required />
      </label>
      <label>מיקום לתצוגה
        <input type="text" name="location" maxlength="120" placeholder="למשל פארק הירקון" value="${esc(location)}" />
      </label>
      <label>כתובת לניווט ב־Waze
        <input type="text" name="nav_address" maxlength="200" placeholder="רחוב, עיר" value="${esc(nav)}" />
      </label>
      <label>מחיר המגרש (₪)
        <input type="number" name="field_cost" min="1" max="999" step="1" value="${esc(String(cost))}" required />
      </label>
      <div class="admin-field-actions">
        <button type="submit" class="tiny-btn">שמירה</button>
        ${reset}
      </div>
    </form>
  `;
}

function renderGame(game) {
  // The court-booker and teams sections only make sense once someone is enrolled.
  const hasPlayers = (game.roster || []).length > 0;
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
    <article class="game-card" data-slot="${game.slot}" data-week-key="${esc(game.week_key || "")}">
      ${renderGameHead(game, statusClass)}
      <p class="muted">${esc(game.status_detail)}</p>
      <div class="list-head">
        <div class="spots"><span>${game.count}/${game.max_players} שחקנים</span><span>${game.spots_left} מקומות פנויים</span></div>
        <button class="refresh-btn" type="button" data-refresh="${game.slot}">רענון</button>
      </div>
      <div class="bar"><span style="width:${filled}%"></span></div>
      <ul class="player-list">${rosterHtml}</ul>
      ${waitingHtml}
      ${renderJoin(game)}
      ${hasPlayers ? renderFieldFold(game) : ""}
      ${hasPlayers ? renderTeamsFold(game) : ""}
      ${renderAdminDate(game)}
      ${state.is_admin && !game.is_ended ? `<div class="admin-tools"><button class="tiny-btn danger" data-clear="${game.slot}" type="button">ניקוי רשימה</button></div>` : ""}
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
      ${players.map((p, index) => renderStatsPlayer(p, index)).join("")}
    </ul>
    ${testBtn}
  `;
}

function hebrewTimes(n) {
  return n === 1 ? "פעם אחת" : `${n} פעמים`;
}

// Leading partner: the player he was drawn with most across all finished games.
// One name, unless several players are tied for the most.
function statsPartnerHtml(partner) {
  if (!partner || !partner.names || !partner.names.length) {
    return `<span class="stats-partner-none">עדיין לא הוגרל עם אף אחד</span>`;
  }
  const names = partner.names.map((name) => `<strong>${esc(name)}</strong>`).join(" · ");
  const eachSuffix = partner.names.length > 1 ? " כל אחד" : "";
  return `
    <span class="stats-partner-names">${names}</span>
    <span class="stats-partner-times">שיחקו איתך ${hebrewTimes(partner.times)}${eachSuffix}</span>
  `;
}

function renderStatsPlayer(p, index) {
  const arrived = p.arrived || 0;
  const missed = p.missed || 0;
  const booked = p.booked || 0;
  const notBooked = p.not_booked != null ? p.not_booked : Math.max((arrived + missed) - booked, 0);
  const open = statsOpen.has(p.name);
  const detailId = `stats-detail-${index}`;
  return `
    <li class="stats-player${open ? " open" : ""}" data-stats-name="${esc(p.name)}">
      <button type="button" class="stats-name-link" data-stats-toggle aria-expanded="${open}" aria-controls="${detailId}">
        <span class="stats-name-text">${esc(p.name)}</span>
        <span class="stats-chevron" aria-hidden="true"></span>
      </button>
      <div class="stats-detail" id="${detailId}"${open ? "" : " hidden"}>
        <div class="stats-tiles">
          <div class="stats-tile tile-arrived">
            <strong>${arrived}</strong>
            <span>פעמים הגיע</span>
          </div>
          <div class="stats-tile tile-missed">
            <strong>${missed}</strong>
            <span>פעמים החמיץ</span>
          </div>
          <div class="stats-tile tile-booked">
            <strong>${booked}</strong>
            <span>הזמין מגרש</span>
          </div>
        </div>
        <div class="stats-partner">
          <span class="stats-partner-label">השותף המוביל</span>
          <span class="stats-partner-value">${statsPartnerHtml(p.top_partner)}</span>
        </div>
        <div class="stats-metric">
          <span class="stats-metric-label">הגעה</span>
          ${stackedBar(arrived, missed, "bar-arrived", "bar-missed")}
          <div class="sparkline" title="היסטוריית הגעה">${sparkDots(p.arrival_history, "on-arrived", "off-missed")}</div>
        </div>
        <div class="stats-metric">
          <span class="stats-metric-label">הזמנת מגרש</span>
          ${stackedBar(booked, notBooked, "bar-booked", "bar-idle")}
          <div class="sparkline" title="היסטוריית הזמנה">${sparkDots(p.booker_history, "on-booked", "off-idle")}</div>
        </div>
      </div>
    </li>`;
}

function upcomingGames() {
  return (state.games || [])
    .filter((game) => !game.is_ended)
    .slice()
    .sort((a, b) => Date.parse(a.game_at) - Date.parse(b.game_at));
}

function nextUpcomingGame() {
  return upcomingGames()[0] || null;
}

function enrollmentIsOpen() {
  if (state.enrollment_open === true) return true;
  return upcomingGames().some((game) => game.is_open);
}

function isMatchDay() {
  if (state.banner_flash === false) return false;
  if (state.banner_flash === true) return true;
  if (state.is_match_day) return true;
  const local = location.hostname === "127.0.0.1" || location.hostname === "localhost";
  return local && new URLSearchParams(location.search).get("match_day") === "1";
}

function isActiveMatchDay() {
  return isMatchDay();
}

let currentTab = null;

function defaultTabId() {
  return isActiveMatchDay() ? "match" : "home";
}

// "יום המשחק" is only reachable on a game day.
function isTabAvailable(tab) {
  return tab !== "match" || isActiveMatchDay();
}

function setTab(tab, { scroll = true } = {}) {
  if (!isTabAvailable(tab)) tab = "home";
  currentTab = tab;
  document.querySelectorAll(".tab-panel").forEach((el) => {
    el.hidden = el.dataset.tab !== tab;
  });
  if (appTabsEl) {
    appTabsEl.querySelectorAll("[data-tab]").forEach((btn) => {
      const on = btn.dataset.tab === tab;
      const available = isTabAvailable(btn.dataset.tab);
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
      btn.disabled = !available;
      btn.title = available ? "" : "זמין רק ביום המשחק";
    });
  }
  try {
    sessionStorage.setItem("tm-tab", tab);
  } catch (e) {}
  if (scroll) window.scrollTo(0, 0);
}

function resetLandingTab() {
  currentTab = null;
  try {
    sessionStorage.removeItem("tm-tab");
  } catch (e) {}
}

function ensureTab() {
  if (!isPlayerLoggedIn()) {
    currentTab = null;
    return;
  }
  if (currentTab) {
    setTab(currentTab, { scroll: false });
    return;
  }
  let saved = null;
  try {
    saved = sessionStorage.getItem("tm-tab");
  } catch (e) {}
  setTab(saved || defaultTabId());
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
  const payWarn = document.getElementById("payWarn");
  const page = document.querySelector(".page");
  if (appScreen) appScreen.hidden = !loggedIn;
  if (banner) banner.hidden = true;
  if (appTabsEl) appTabsEl.hidden = !loggedIn;
  if (payWarn && !loggedIn) payWarn.hidden = true;
  document.body.classList.toggle("login-only", !loggedIn);
  if (page) {
    page.classList.toggle("login-only", !loggedIn);
    page.classList.toggle("has-unpaid-banner", loggedIn && Boolean(state.unpaid && state.pay_warning));
  }
}

function matchCountdownText(game) {
  const start = game && game.game_at ? Date.parse(game.game_at) : nextGameMs();
  if (!start) return "המשחק הבא";
  if (game && game.is_past && !game.is_ended) return "המשחק התחיל";
  const left = start - Date.now();
  if (left <= 0) return "המשחק התחיל";
  return `מתחילים בעוד ${formatCountdown(left)}`;
}

function tickCountdown() {
  const banner = document.getElementById("matchBanner");
  if (banner) banner.hidden = true;
  const el = document.getElementById("matchDayCountdown");
  if (!el) return;
  el.textContent = matchCountdownText(matchDayGame());
}

function formatMoney(amount) {
  if (amount == null) return "0";
  return Number.isInteger(amount) ? String(amount) : amount.toFixed(2);
}

function matchDayGame() {
  const games = state.games || [];
  const live = games.find((game) => game.is_past && !game.is_ended);
  if (live) return live;
  const now = new Date();
  const today = games.find((game) => {
    const start = new Date(game.game_at);
    return start.getFullYear() === now.getFullYear()
      && start.getMonth() === now.getMonth()
      && start.getDate() === now.getDate();
  });
  return today || nextUpcomingGame();
}

function notifyPermission() {
  if (!("Notification" in window)) return "unsupported";
  return Notification.permission;
}

function renderNotifyBlock() {
  const on = Boolean(state.user && state.user.notify_on);
  const perm = notifyPermission();
  const approved = on && perm === "granted";
  const adminBtn = state.is_admin
    ? `<button class="tiny-btn" id="testPushBtn" type="button">בדיקת התראה</button>`
    : "";
  if (approved) {
    return adminBtn ? `<div class="notify-card is-on">${adminBtn}</div>` : "";
  }
  if (on) {
    return `
      <div class="notify-card">
        <p class="notify-title">התראות</p>
        <p class="notify-copy">במכשיר זה צריך לאשר שוב כדי לקבל תזכורות.</p>
        <button id="notifyBtn" class="ghost-btn notify-btn" type="button">הפעלה במכשיר זה</button>
        ${adminBtn}
      </div>
    `;
  }
  return `
    <div class="notify-card">
      <p class="notify-title">התראות</p>
      <p class="notify-copy">הגרלה ב־12:00 ביום משחק, שעה לפני, חמישי 11:00 להזמנת מגרש, ואחרי המשחק תזכורת תשלום.</p>
      <button id="notifyBtn" class="primary-btn notify-btn" type="button">הפעלת התראות</button>
      ${adminBtn}
    </div>
  `;
}

function renderInstallBlock() {
  if (isStandaloneApp() || !canOfferInstall()) return "";
  return `
    <div class="install-card">
      <button type="button" class="ghost-btn install-btn" id="homeInstallBtn">
        <img class="install-btn-icon" src="/static/racket-icon.png" alt="" />
        הוספה למסך הבית
      </button>
      <p id="homeInstallNote" class="install-note" hidden></p>
    </div>
  `;
}

function renderHome() {
  if (!homeViewEl) return;
  const name = state.user ? state.user.name : "";
  const mine = state.my_stats || {};
  const game = matchDayGame() || nextUpcomingGame();
  const enrolled = Boolean(myEnrollment(game));
  const open = enrollmentIsOpen();
  let cta = "";
  if (enrolled) {
    // The match-day tab only exists on game day; otherwise there is nowhere to go.
    if (isActiveMatchDay()) {
      cta = `<button class="primary-btn" data-go-tab="match" type="button">למשחק של היום</button>`;
    }
  } else if (open) {
    cta = `<button class="primary-btn" data-go-tab="enroll" type="button">להרשמה למשחק</button>`;
  }
  const photo = state.user && state.user.avatar;
  const initial = (name || "?").trim().slice(0, 1);
  homeViewEl.innerHTML = `
    <section class="welcome-card">
      <p class="kicker">ראשי</p>
      <div class="profile-row">
        <label class="avatar-upload">
          ${photo
            ? `<img class="avatar-img" src="${esc(photo)}" alt="" />`
            : `<span class="avatar-fallback">${esc(initial)}</span>`}
          <input id="avatarInput" type="file" accept="image/*" />
          <span class="avatar-action">${photo ? "החלפת תמונה" : "הוספת תמונה"}</span>
        </label>
        <div>
          <h2 class="hello-title">
            <img class="hello-app-icon" src="/static/racket-icon.png" alt="" />
            <span>שלום ${esc(name)}</span>
          </h2>
          <p class="muted">${nextUpcomingGame() && nextUpcomingGame().location
            ? `המשחק הבא: ${esc(nextUpcomingGame().game_at_he)} · ${esc(nextUpcomingGame().location)}`
            : "ברוך הבא לטניסמייט. משחקים ביום ראשון ויום רביעי ב־20:00."}</p>
        </div>
      </div>
      <ul class="welcome-stats">
        <li><strong>${mine.arrived || 0}</strong><span>משחקים שהגעת</span></li>
        <li><strong>${mine.missed || 0}</strong><span>משחקים שפספסת</span></li>
        <li><strong>${formatMoney(mine.paid_total)} ₪</strong><span>שולם על טניס</span></li>
        <li><strong>${mine.booked || 0}</strong><span>הזמנות מגרש</span></li>
      </ul>
      <div class="stats-partner welcome-partner">
        <span class="stats-partner-label">השותף המוביל</span>
        <span class="stats-partner-value">${statsPartnerHtml(mine.top_partner)}</span>
      </div>
      ${cta}
      ${renderNotifyBlock()}
      ${renderInstallBlock()}
    </section>
  `;
  const notifyBtn = document.getElementById("notifyBtn");
  if (notifyBtn) notifyBtn.addEventListener("click", registerPush);
  const testPushBtn = document.getElementById("testPushBtn");
  if (testPushBtn) testPushBtn.addEventListener("click", testPush);
  bindInstallButton(
    document.getElementById("homeInstallBtn"),
    document.getElementById("homeInstallNote")
  );
  const avatarInput = document.getElementById("avatarInput");
  if (avatarInput) avatarInput.addEventListener("change", onAvatarPicked);
}

function resizeAvatar(file) {
  return new Promise((resolve, reject) => {
    if (!file || !file.type.startsWith("image/")) {
      reject(new Error("יש לבחור תמונה"));
      return;
    }
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      const size = 192;
      const canvas = document.createElement("canvas");
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext("2d");
      const side = Math.min(img.width, img.height);
      const sx = (img.width - side) / 2;
      const sy = (img.height - side) / 2;
      ctx.drawImage(img, sx, sy, side, side, 0, 0, size, size);
      URL.revokeObjectURL(url);
      resolve(canvas.toDataURL("image/jpeg", 0.72));
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("לא הצלחנו לקרוא את התמונה"));
    };
    img.src = url;
  });
}

async function onAvatarPicked(e) {
  const file = e.target.files && e.target.files[0];
  e.target.value = "";
  if (!file) return;
  try {
    const image = await resizeAvatar(file);
    const data = await api("/api/me/avatar", { image });
    applyState(data);
  } catch (err) {
    showToast(err.message || "העלאת התמונה נכשלה");
  }
}

function renderMatchDay() {
  if (!matchDayViewEl) return;
  const game = matchDayGame();
  if (!game) {
    matchDayViewEl.innerHTML = `<section class="match-day-card"><h2>יום המשחק</h2><p class="muted">אין משחק קרוב להצגה.</p></section>`;
    return;
  }
  const emptySlots = Math.max(game.max_players - game.count, 0);
  const rosterHtml = (game.roster || []).map((p, i) => renderPlayerRow(p, i, { admin: state.is_admin, game })).join("")
    + Array.from({ length: emptySlots }, (_, i) => `
        <li class="empty">
          <div class="row-main">
            <span class="num">${game.count + i + 1}</span>
            <span>מקום פנוי</span>
          </div>
        </li>
      `).join("");
  const waitingHtml = (game.waiting || []).length
    ? `<h4 class="wait-title">רשימת המתנה</h4>
       <ul class="wait-list">${game.waiting.map((p, i) => renderPlayerRow(p, i, { waitlist: true, admin: state.is_admin })).join("")}</ul>`
    : "";
  const hasPlayers = (game.roster || []).length > 0;
  matchDayViewEl.innerHTML = `
    <article class="game-card match-day-card" data-slot="${game.slot}" data-week-key="${esc(game.week_key || "")}">
      <p class="kicker">יום המשחק</p>
      ${renderGameHead(game, game.is_ended ? "ended" : game.is_past ? "past" : "closed")}
      <p id="matchDayCountdown" class="match-day-count">${esc(matchCountdownText(game))}</p>
      ${renderJoin(game)}
      <div class="match-day-block">
        <h4>שחקנים מגיעים</h4>
        <ul class="player-list">${rosterHtml}</ul>
        ${waitingHtml}
      </div>
      ${hasPlayers ? `
      <div class="match-day-block">
        <h4>מזמין המגרש</h4>
        <p class="share">${costSplit(game)}</p>
        ${renderBookerPicker(game)}
        ${game.booker_name
          ? `<p class="booker-picked">המזמין: <strong>${esc(game.booker_name)}</strong></p>`
          : `<p class="booker-picked muted">עדיין לא נבחר מזמין</p>`}
      </div>
      <div class="match-day-block">
        <h4>הגרלת זוגות</h4>
        ${renderTeams(game)}
      </div>` : ""}
      ${renderAdminDate(game)}
    </article>
  `;
}

function renderMatchBanner() {
  tickCountdown();
}

function renderAuth() {
  const loggedOut = document.getElementById("authLoggedOut");
  const loggedIn = document.getElementById("authLoggedIn");
  const hello = document.getElementById("authHello");
  const helloAvatar = document.getElementById("helloAvatar");
  const authCard = document.getElementById("authCard");
  const payWarn = document.getElementById("payWarn");
  if (state.user) {
    if (loggedOut) loggedOut.hidden = true;
    if (loggedIn) loggedIn.hidden = false;
    if (authCard) authCard.hidden = true;
    if (hello) hello.textContent = state.user.name;
    if (helloAvatar) {
      if (state.user.avatar) {
        helloAvatar.hidden = false;
        helloAvatar.src = state.user.avatar;
      } else {
        helloAvatar.hidden = true;
        helloAvatar.removeAttribute("src");
      }
    }
  } else {
    if (loggedOut) loggedOut.hidden = false;
    if (loggedIn) loggedIn.hidden = true;
    if (authCard) authCard.hidden = false;
  }
  if (payWarn) {
    if (state.user && state.unpaid && state.pay_warning) {
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
  if (!isPlayerLoggedIn()) {
    if (homeViewEl) homeViewEl.innerHTML = "";
    if (matchDayViewEl) matchDayViewEl.innerHTML = "";
    if (gamesEl) gamesEl.innerHTML = "";
    if (pastGamesEl) pastGamesEl.innerHTML = "";
    if (statsListsEl) statsListsEl.innerHTML = "";
    return;
  }
  ensureTab();
  renderHome();
  renderMatchDay();
  renderMatchBanner();
  const warn = state.is_admin && state.persistent === false
    ? `<p class="persist-warn">כדי שהרשימות לא יימחקו בעדכון ב-Render, חברו מסד PostgreSQL והגדירו DATABASE_URL.</p>`
    : "";
  const upcoming = state.is_admin ? upcomingGames() : upcomingGames().slice(0, 1);
  const past = state.past_games || (state.games || []).filter((game) => game.is_ended);
  if (gamesEl) gamesEl.innerHTML = warn + (upcoming.length ? upcoming.map(renderGame).join("") : `<p class="muted">אין משחק קרוב להרשמה.</p>`);
  if (pastGamesEl) {
    pastGamesEl.innerHTML = past.length
      ? past.map(renderGame).join("")
      : `<p class="muted">אין משחקים שהסתיימו עדיין.</p>`;
  }
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

async function onGameListClick(e) {
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
  const leaveBtn = e.target.closest("[data-leave]");
  if (leaveBtn) {
    if (!confirm("לבטל את ההרשמה למשחק?")) return;
    leaveBtn.disabled = true;
    const data = await api("/api/leave", { slot: leaveBtn.dataset.leave });
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
  const fieldReset = e.target.closest("[data-field-reset]");
  if (fieldReset) {
    const data = await api("/api/admin/game-settings", {
      slot: fieldReset.dataset.fieldReset,
      week_key: fieldReset.dataset.weekKey || "",
      reset: true,
    });
    applyState(data);
    return;
  }
  const dateReset = e.target.closest("[data-date-reset]");
  if (dateReset) {
    const data = await api("/api/admin/game-date", { slot: dateReset.dataset.dateReset, date: "" });
    applyState(data);
    return;
  }
  const clearBtn = e.target.closest("[data-clear]");
  if (clearBtn) {
    if (!confirm("לנקות את כל הרשימה למשחק הזה?")) return;
    const data = await api("/api/admin/clear", { slot: clearBtn.dataset.clear });
    applyState(data);
  }
}

async function onBookerCustomSubmit(e) {
  const settingsForm = e.target.closest("[data-game-settings]");
  if (settingsForm) {
    e.preventDefault();
    const data = await api("/api/admin/game-settings", {
      slot: settingsForm.dataset.gameSettings,
      week_key: settingsForm.dataset.weekKey || "",
      date: settingsForm.querySelector('[name="date"]')?.value || "",
      time: settingsForm.querySelector('[name="time"]')?.value || "",
      location: settingsForm.querySelector('[name="location"]')?.value || "",
      nav_address: settingsForm.querySelector('[name="nav_address"]')?.value || "",
      field_cost: settingsForm.querySelector('[name="field_cost"]')?.value || "",
    });
    applyState(data);
    return;
  }
  const dateForm = e.target.closest("[data-game-date]");
  if (dateForm) {
    e.preventDefault();
    const input = dateForm.querySelector('input[type="date"]');
    const data = await api("/api/admin/game-date", {
      slot: dateForm.dataset.gameDate,
      date: (input && input.value) || "",
    });
    applyState(data);
    return;
  }
  const form = e.target.closest("[data-booker-custom]");
  if (!form) return;
  e.preventDefault();
  const input = form.querySelector("input");
  const key = `${form.dataset.bookerCustom}:${form.dataset.weekKey || ""}`;
  bookerCustomOpen[key] = true;
  const data = await api("/api/booker", {
    slot: form.dataset.bookerCustom,
    week_key: form.dataset.weekKey || "",
    name: (input && input.value) || "",
  });
  if (data.ok) bookerCustomOpen[key] = false;
  applyState(data);
}

async function onGameListChange(e) {
  const select = e.target.closest("[data-booker]");
  if (select) {
    const slot = select.dataset.booker;
    const weekKey = select.dataset.weekKey || "";
    const key = `${slot}:${weekKey}`;
    if (select.value === "custom") {
      bookerCustomOpen[key] = true;
      render();
      const input = document.querySelector(`[data-booker-custom="${slot}"][data-week-key="${weekKey}"] input`);
      if (input) input.focus();
      return;
    }
    bookerCustomOpen[key] = false;
    const payload = { slot, week_key: weekKey };
    if (select.value.startsWith("user:")) {
      payload.user_id = Number(select.value.slice(5));
    }
    const data = await api("/api/booker", payload);
    applyState(data);
    return;
  }
  const box = e.target.closest("[data-paid]");
  if (!box) return;
  const data = await api("/api/admin/paid", { id: Number(box.dataset.paid), paid: box.checked });
  applyState(data);
}

if (gamesEl) {
  gamesEl.addEventListener("click", onGameListClick);
  gamesEl.addEventListener("change", onGameListChange);
  gamesEl.addEventListener("submit", onBookerCustomSubmit);
}
if (pastGamesEl) {
  pastGamesEl.addEventListener("click", onGameListClick);
  pastGamesEl.addEventListener("change", onGameListChange);
  pastGamesEl.addEventListener("submit", onBookerCustomSubmit);
}

statsListsEl.addEventListener("click", async (e) => {
  const toggle = e.target.closest("[data-stats-toggle]");
  if (toggle) {
    const item = toggle.closest(".stats-player");
    if (!item) return;
    const name = item.dataset.statsName;
    const open = !statsOpen.has(name);
    if (open) statsOpen.add(name);
    else statsOpen.delete(name);
    item.classList.toggle("open", open);
    toggle.setAttribute("aria-expanded", String(open));
    const detail = item.querySelector(".stats-detail");
    if (detail) detail.hidden = !open;
    return;
  }
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
  if (!state.user) {
    showToast("יש להתחבר כדי להפעיל התראות");
    return;
  }
  if (!("serviceWorker" in navigator) || !("Notification" in window)) {
    showToast("הדפדפן לא תומך בהתראות");
    return;
  }
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    showToast("צריך לאשר התראות בהגדרות הדפדפן");
    render();
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
      const data = await api("/api/push/subscribe", { subscription: sub.toJSON() });
      applyState(data);
      if (!data.ok) return;
    } catch (err) {
      console.warn("push subscribe failed", err);
      showToast("ההרשמה להתראות נכשלה");
      return;
    }
  } else {
    showToast("השרת עדיין לא מוכן להתראות");
    return;
  }
  scheduleLocalReminders(registration);
}

async function testPush() {
  const btn = document.getElementById("testPushBtn");
  if (btn) btn.disabled = true;
  const data = await api("/api/admin/test-push", {});
  applyState(data);
  if (!data.pushed && "Notification" in window && Notification.permission === "granted") {
    new Notification(data.title || "בדיקת התראה · טניסמייט", {
      body: data.body || "אם אתה רואה את זה, ההתראות עובדות.",
      dir: "rtl",
      lang: "he",
      tag: "tennismate-test",
    });
  }
  if (btn) btn.disabled = false;
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
      `מתחילים ב־${nextUpcomingGame() ? formatGameClock(nextUpcomingGame()) : "20:00"}. סמנו הגעה אם עוד לא.`,
      "tennismate-hour"
    );
  }, "_hour");
  scheduleAt(state.court_book_at, () => {
    showLocalNote(
      registration,
      "הזמנת מגרש · טניסמייט",
      "יום חמישי 11:00 · הזמינו עכשיו מגרש בלזוז למשחקים הקרובים.",
      "tennismate-court"
    );
  }, "_court");
  scheduleAt(state.draw_at, () => {
    showLocalNote(
      registration,
      "ההגרלה יצאה · טניסמייט",
      "הזוגות מוכנים. פתחו את טניסמייט לראות עם מי אתה משחק.",
      "tennismate-draw"
    );
  }, "_draw");
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
  if (values.email !== "testuser" && !AUTH_EMAIL_RE.test(values.email)) {
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
  if (data.ok && data.user) {
    showAuthError("");
    resetLandingTab();
  }
  applyState(data);
  if (!data.ok && data.message) showAuthError(data.message, { toast: false });
  if (data.ok && data.user) window.scrollTo(0, 0);
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
      resetLandingTab();
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

const PAST_GAMES_COLLAPSE_KEY = "tm-past-collapsed";

function applyPastGamesCollapsed(collapsed) {
  const card = document.getElementById("pastGamesSection");
  const btn = document.getElementById("pastGamesToggle");
  const action = btn && btn.querySelector(".hero-toggle-action");
  if (!card || !btn) return;
  card.classList.toggle("collapsed", collapsed);
  btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
  if (action) action.textContent = collapsed ? "הרחב" : "מזער";
}

function initPastGamesToggle() {
  const btn = document.getElementById("pastGamesToggle");
  if (!btn) return;
  let collapsed = true;
  try {
    collapsed = localStorage.getItem(PAST_GAMES_COLLAPSE_KEY) !== "0";
  } catch (e) {}
  applyPastGamesCollapsed(collapsed);
  btn.addEventListener("click", () => {
    const next = !document.getElementById("pastGamesSection").classList.contains("collapsed");
    applyPastGamesCollapsed(next);
    try {
      localStorage.setItem(PAST_GAMES_COLLAPSE_KEY, next ? "1" : "0");
    } catch (e) {}
  });
}

function scrollToUnpaidGame() {
  const debt = state.unpaid;
  if (!debt) return;
  setTab("past");
  const jump = () => {
    const card = document.querySelector(
      `.game-card[data-slot="${debt.slot}"][data-week-key="${debt.week_key}"]`
    );
    if (!card) return;
    card.scrollIntoView({ behavior: "smooth", block: "start" });
    card.classList.add("highlight-unpaid");
    clearTimeout(scrollToUnpaidGame._t);
    scrollToUnpaidGame._t = setTimeout(() => card.classList.remove("highlight-unpaid"), 2200);
  };
  requestAnimationFrame(() => requestAnimationFrame(jump));
}

function initTabs() {
  if (!appTabsEl) return;
  appTabsEl.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-tab]");
    if (!btn) return;
    setTab(btn.dataset.tab);
  });
}

function isStandaloneApp() {
  return window.matchMedia("(display-mode: standalone)").matches
    || window.matchMedia("(display-mode: fullscreen)").matches
    || Boolean(navigator.standalone);
}

function isPhoneLike() {
  return window.matchMedia("(pointer: coarse)").matches
    || /android|iphone|ipad|ipod/i.test(navigator.userAgent || "");
}

let deferredInstallPrompt = null;

function canOfferInstall() {
  if (isStandaloneApp()) return false;
  return isPhoneLike() || Boolean(deferredInstallPrompt);
}

function setInstallButtonsHidden(hidden) {
  document.querySelectorAll("#installAppBtn, #homeInstallBtn").forEach((btn) => {
    btn.hidden = hidden;
  });
  if (hidden) {
    document.querySelectorAll("#installAppNote, #homeInstallNote").forEach((note) => {
      note.hidden = true;
    });
  }
}

async function promptInstallApp(note) {
  if (deferredInstallPrompt) {
    deferredInstallPrompt.prompt();
    try {
      await deferredInstallPrompt.userChoice;
    } catch (err) {}
    deferredInstallPrompt = null;
    setInstallButtonsHidden(true);
    return;
  }
  if (note) {
    const ios = /iphone|ipad|ipod/i.test(navigator.userAgent || "");
    note.hidden = false;
    note.textContent = ios
      ? "בספארי לחצו על שיתוף (הריבוע עם החץ למעלה) ואז על הוספה למסך הבית."
      : "בתפריט הדפדפן (⋮) בחרו הוספה למסך הבית או התקנת אפליקציה.";
  }
}

function bindInstallButton(btn, note) {
  if (!btn) return;
  if (!canOfferInstall()) {
    btn.hidden = true;
    return;
  }
  btn.hidden = false;
  btn.addEventListener("click", () => promptInstallApp(note));
}

function initInstallApp() {
  if (isStandaloneApp()) {
    setInstallButtonsHidden(true);
    return;
  }
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredInstallPrompt = e;
    setInstallButtonsHidden(false);
  });
  window.addEventListener("appinstalled", () => {
    deferredInstallPrompt = null;
    setInstallButtonsHidden(true);
  });
  bindInstallButton(
    document.getElementById("installAppBtn"),
    document.getElementById("installAppNote")
  );
}

initAuth();
initTabs();
initInstallApp();
const payWarnBtn = document.getElementById("payWarn");
if (payWarnBtn) payWarnBtn.addEventListener("click", scrollToUnpaidGame);
if (homeViewEl) {
  homeViewEl.addEventListener("click", (e) => {
    const go = e.target.closest("[data-go-tab]");
    if (go) setTab(go.dataset.goTab);
  });
}
if (matchDayViewEl) {
  matchDayViewEl.addEventListener("click", onGameListClick);
  matchDayViewEl.addEventListener("change", onGameListChange);
  matchDayViewEl.addEventListener("submit", onBookerCustomSubmit);
}

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
}
if (localStorage.getItem("tm-notify") === "1" && "Notification" in window && Notification.permission === "granted") {
  navigator.serviceWorker.ready.then((reg) => scheduleLocalReminders(reg)).catch(() => {});
}

refresh();
setInterval(refresh, 30000);
setInterval(tickCountdown, 1000);

const PONG_WIN = 3;
let racketClicks = 0;
let pong = null;
let rockyCtx = null;

function pongEls() {
  return {
    overlay: document.getElementById("pongOverlay"),
    canvas: document.getElementById("pongCourt"),
    score: document.getElementById("pongScore"),
    startHint: document.getElementById("pongStartHint"),
    end: document.getElementById("pongEnd"),
    winner: document.getElementById("pongWinner"),
    trophy: document.getElementById("pongTrophy"),
    closeBtn: document.getElementById("pongClose"),
    againBtn: document.getElementById("pongAgain"),
  };
}

function unlockRockyAudio() {
  const AudioCtx = window.AudioContext || window.webkitAudioContext;
  if (!AudioCtx) return null;
  if (!rockyCtx) rockyCtx = new AudioCtx();
  if (rockyCtx.state === "suspended") rockyCtx.resume();
  try {
    const osc = rockyCtx.createOscillator();
    const gain = rockyCtx.createGain();
    gain.gain.value = 0.001;
    osc.connect(gain);
    gain.connect(rockyCtx.destination);
    osc.start();
    osc.stop(rockyCtx.currentTime + 0.04);
  } catch (e) {}
  return rockyCtx;
}

function startRockyTheme() {
  const ctx = unlockRockyAudio();
  if (!ctx) return { stop() {} };
  const master = ctx.createGain();
  master.gain.value = 0.55;
  master.connect(ctx.destination);
  let alive = true;
  const loopLen = 3.36;
  const hits = [
    [0.00, 261.63, 0.20, 0.7],
    [0.28, 261.63, 0.20, 0.7],
    [0.56, 311.13, 0.20, 0.78],
    [0.84, 349.23, 0.20, 0.82],
    [1.12, 392.00, 0.72, 0.9],
    [1.96, 523.25, 0.22, 0.78],
    [2.24, 466.16, 0.20, 0.72],
    [2.52, 392.00, 0.58, 0.8],
  ];
  const thumps = [0, 0.56, 1.12, 1.68, 2.24, 2.80];

  function brass(time, freq, dur, vol) {
    const filter = ctx.createBiquadFilter();
    const gain = ctx.createGain();
    filter.type = "lowpass";
    filter.frequency.setValueAtTime(1200, time);
    filter.Q.value = 0.8;
    filter.frequency.linearRampToValueAtTime(2200, time + Math.min(0.12, dur * 0.4));
    gain.gain.setValueAtTime(0.001, time);
    gain.gain.exponentialRampToValueAtTime(vol, time + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.001, time + dur);
    filter.connect(gain);
    gain.connect(master);
    ["sawtooth", "square"].forEach((type, i) => {
      const osc = ctx.createOscillator();
      osc.type = type;
      osc.frequency.setValueAtTime(freq * (i ? 1.005 : 1), time);
      osc.connect(filter);
      osc.start(time);
      osc.stop(time + dur + 0.03);
    });
  }

  function thump(time) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(90, time);
    osc.frequency.exponentialRampToValueAtTime(42, time + 0.16);
    gain.gain.setValueAtTime(0.001, time);
    gain.gain.exponentialRampToValueAtTime(0.7, time + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.001, time + 0.2);
    osc.connect(gain);
    gain.connect(master);
    osc.start(time);
    osc.stop(time + 0.22);
  }

  function schedule(from) {
    if (!alive) return;
    hits.forEach(([t, f, d, v]) => brass(from + t, f, d, v));
    thumps.forEach((t) => thump(from + t));
    const wait = Math.max(30, (from + loopLen - ctx.currentTime) * 1000 - 40);
    setTimeout(() => {
      if (alive) schedule(from + loopLen);
    }, wait);
  }

  const startAt = ctx.currentTime + 0.02;
  schedule(startAt);
  return {
    stop() {
      alive = false;
      try {
        master.gain.cancelScheduledValues(ctx.currentTime);
        master.gain.setValueAtTime(master.gain.value, ctx.currentTime);
        master.gain.linearRampToValueAtTime(0.001, ctx.currentTime + 0.15);
      } catch (e) {}
    },
  };
}

function newPongState(canvas) {
  const w = canvas.width;
  const h = canvas.height;
  return {
    w,
    h,
    ball: { x: w / 2, y: h / 2, vx: 0, vy: 0 },
    player: { x: w / 2, y: h - 18, w: 72, h: 8 },
    ai: { x: w / 2, y: 14, w: 72, h: 8 },
    you: 0,
    pc: 0,
    over: false,
    waiting: true,
    serveTowardPlayer: true,
    keys: { left: false, right: false },
  };
}

function setPongHint(show) {
  const { startHint } = pongEls();
  if (startHint) startHint.hidden = !show;
}

function holdForServe(game, towardPlayer) {
  game.waiting = true;
  game.serveTowardPlayer = towardPlayer;
  game.ball.x = game.w / 2;
  game.ball.y = game.h / 2;
  game.ball.vx = 0;
  game.ball.vy = 0;
  setPongHint(true);
}

function serveBall(game, towardPlayer) {
  const dir = Math.random() < 0.5 ? -1 : 1;
  game.waiting = false;
  game.ball.x = game.w / 2;
  game.ball.y = game.h / 2;
  game.ball.vx = 3.1 * dir;
  game.ball.vy = towardPlayer ? 3.5 : -3.5;
  setPongHint(false);
}

function startPongRally() {
  if (!pong || pong.over || !pong.waiting) return;
  serveBall(pong, pong.serveTowardPlayer);
}

function hitPaddle(ball, paddle) {
  return (
    ball.x >= paddle.x - paddle.w / 2
    && ball.x <= paddle.x + paddle.w / 2
    && ball.y >= paddle.y - paddle.h / 2 - 6
    && ball.y <= paddle.y + paddle.h / 2 + 6
  );
}

function drawPong(ctx, game) {
  ctx.fillStyle = "#052e16";
  ctx.fillRect(0, 0, game.w, game.h);
  ctx.strokeStyle = "rgba(255,255,255,0.22)";
  ctx.setLineDash([8, 10]);
  ctx.beginPath();
  ctx.moveTo(12, game.h / 2);
  ctx.lineTo(game.w - 12, game.h / 2);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.strokeStyle = "#ecfdf3";
  ctx.lineWidth = 3;
  ctx.strokeRect(6, 6, game.w - 12, game.h - 12);
  ctx.fillStyle = "#f8fafc";
  ctx.fillRect(game.player.x - game.player.w / 2, game.player.y - game.player.h / 2, game.player.w, game.player.h);
  ctx.fillRect(game.ai.x - game.ai.w / 2, game.ai.y - game.ai.h / 2, game.ai.w, game.ai.h);
  ctx.beginPath();
  ctx.arc(game.ball.x, game.ball.y, 6, 0, Math.PI * 2);
  ctx.fill();
}

function updatePongScore() {
  const { score } = pongEls();
  if (!pong || !score) return;
  score.textContent = `אתה ${pong.you} · ${pong.pc} מחשב`;
}

function finishPong() {
  if (!pong) return;
  pong.over = true;
  const won = pong.you >= PONG_WIN;
  const { end, winner, trophy } = pongEls();
  if (winner) winner.textContent = won ? "ניצחת" : "המחשב ניצח";
  if (trophy) {
    trophy.hidden = !won;
    trophy.setAttribute("aria-hidden", won ? "false" : "true");
  }
  if (end) end.hidden = false;
}

function stepPong() {
  if (!pong || pong.over || pong.waiting) return;
  const speed = 6.4;
  if (pong.keys.left) pong.player.x -= speed;
  if (pong.keys.right) pong.player.x += speed;
  pong.player.x = Math.max(pong.player.w / 2 + 8, Math.min(pong.w - pong.player.w / 2 - 8, pong.player.x));

  const follow = pong.ball.x - pong.ai.x;
  pong.ai.x += Math.max(-4.2, Math.min(4.2, follow * 0.09));
  pong.ai.x = Math.max(pong.ai.w / 2 + 8, Math.min(pong.w - pong.ai.w / 2 - 8, pong.ai.x));

  pong.ball.x += pong.ball.vx;
  pong.ball.y += pong.ball.vy;
  if (pong.ball.x < 12 || pong.ball.x > pong.w - 12) pong.ball.vx *= -1;

  if (pong.ball.vy > 0 && hitPaddle(pong.ball, pong.player)) {
    pong.ball.vy = -Math.abs(pong.ball.vy) - 0.15;
    pong.ball.vx += (pong.ball.x - pong.player.x) * 0.12;
    pong.ball.y = pong.player.y - 12;
  } else if (pong.ball.vy < 0 && hitPaddle(pong.ball, pong.ai)) {
    pong.ball.vy = Math.abs(pong.ball.vy) + 0.12;
    pong.ball.vx += (pong.ball.x - pong.ai.x) * 0.1;
    pong.ball.y = pong.ai.y + 12;
  }

  if (pong.ball.y > pong.h) {
    pong.pc += 1;
    updatePongScore();
    if (pong.pc >= PONG_WIN) finishPong();
    else holdForServe(pong, false);
  } else if (pong.ball.y < 0) {
    pong.you += 1;
    updatePongScore();
    if (pong.you >= PONG_WIN) finishPong();
    else holdForServe(pong, true);
  }
}

function loopPong() {
  if (!pong) return;
  const { canvas } = pongEls();
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  stepPong();
  drawPong(ctx, pong);
  pong.raf = requestAnimationFrame(loopPong);
}

function movePongFromPointer(event) {
  if (!pong) return;
  const { canvas } = pongEls();
  const box = canvas.getBoundingClientRect();
  const x = ((event.clientX - box.left) / box.width) * pong.w;
  pong.player.x = Math.max(pong.player.w / 2 + 8, Math.min(pong.w - pong.player.w / 2 - 8, x));
}

function closePong() {
  const { overlay, end } = pongEls();
  if (pong) {
    cancelAnimationFrame(pong.raf);
    if (pong.theme) pong.theme.stop();
  }
  pong = null;
  if (end) end.hidden = true;
  const { trophy } = pongEls();
  if (trophy) {
    trophy.hidden = true;
    trophy.setAttribute("aria-hidden", "true");
  }
  setPongHint(true);
  if (overlay) overlay.hidden = true;
}

function startPongMatch() {
  const { canvas, overlay, end } = pongEls();
  if (!canvas || !overlay) return;
  if (pong && pong.theme) pong.theme.stop();
  cancelAnimationFrame(pong && pong.raf);
  pong = newPongState(canvas);
  pong.theme = startRockyTheme();
  if (end) end.hidden = true;
  overlay.hidden = false;
  setPongHint(true);
  updatePongScore();
  loopPong();
}

function openPong() {
  racketClicks = 0;
  startPongMatch();
}

function onPongKey(e, down) {
  if (!pong) return;
  if (e.key === "ArrowLeft" || e.key === "a" || e.key === "A") pong.keys.left = down;
  if (e.key === "ArrowRight" || e.key === "d" || e.key === "D") pong.keys.right = down;
}

function initPongEgg() {
  const mark = document.getElementById("brandMark");
  const { overlay, canvas, closeBtn, againBtn } = pongEls();
  if (mark) {
    mark.addEventListener("click", () => {
      unlockRockyAudio();
      racketClicks += 1;
      if (racketClicks >= 10) openPong();
    });
  }
  if (closeBtn) closeBtn.addEventListener("click", closePong);
  if (againBtn) {
    againBtn.addEventListener("click", () => {
      unlockRockyAudio();
      startPongMatch();
    });
  }
  if (overlay) {
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) closePong();
    });
  }
  if (canvas) {
    let dragging = false;
    canvas.addEventListener("pointerdown", (e) => {
      startPongRally();
      dragging = true;
      canvas.setPointerCapture(e.pointerId);
      movePongFromPointer(e);
    });
    canvas.addEventListener("pointermove", (e) => {
      if (dragging) movePongFromPointer(e);
    });
    canvas.addEventListener("pointerup", () => { dragging = false; });
    canvas.addEventListener("pointercancel", () => { dragging = false; });
  }
  window.addEventListener("keydown", (e) => onPongKey(e, true));
  window.addEventListener("keyup", (e) => onPongKey(e, false));
}

initPongEgg();
