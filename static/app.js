const gamesEl = document.getElementById("games");
const fieldListsEl = document.getElementById("fieldLists");
const toastEl = document.getElementById("toast");
const adminBtn = document.getElementById("adminBtn");
const adminDialog = document.getElementById("adminDialog");
const adminForm = document.getElementById("adminForm");
const adminCancel = document.getElementById("adminCancel");
const adminPassword = document.getElementById("adminPassword");

let state = { games: [], is_admin: false };
const draftNames = {};

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

function renderTeams(game) {
  if (!game.teams_ready) {
    return `<p class="draw-note">הגרלת הקבוצות תתבצע אוטומטית ב־${esc(game.draw_at_he)}</p>`;
  }
  if (!game.teams || !game.teams.length) {
    if (!game.count) return "";
    return `<p class="draw-note">אין מספיק שחקנים להגרלת קבוצות</p>`;
  }
  return `
    <div class="teams">
      <h4>הגרלת כוחות</h4>
      <div class="team-grid">
        ${game.teams.map((team) => `
          <div class="team-card">
            <strong>${esc(team.label)}</strong>
            <ul>
              ${team.players.map((p) => `<li>${esc(p.name)}</li>`).join("")}
            </ul>
          </div>
        `).join("")}
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
            ? h.teams.map((t) => `<p class="history-team">${esc(t.label)}: ${t.players.map((p) => esc(p.name)).join(", ")}</p>`).join("")
            : ""}
        </div>
      `).join("")}
    </div>
  `;
}

function renderGame(game) {
  const statusClass = game.is_open ? "open" : game.is_past ? "past" : "closed";
  const filled = (game.count / game.max_players) * 100;
  const canJoin = game.is_open || state.is_admin;
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
    : `<h4 class="wait-title">רשימת המתנה ריקה</h4>`;

  const draft = draftNames[game.slot] || "";

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
      <form class="join-row" data-join="${game.slot}">
        <input name="name" maxlength="80" placeholder="השם המלא" value="${esc(draft)}" ${canJoin ? "" : "disabled"} />
        <button class="primary-btn" type="submit" ${canJoin ? "" : "disabled"}>הצטרף</button>
      </form>
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

function render() {
  adminBtn.textContent = state.is_admin ? "יציאה ממנהל" : "מנהל";
  const warn = state.is_admin && state.persistent === false
    ? `<p class="persist-warn">כדי שהרשימות לא יימחקו בעדכון ב-Render, חברו מסד PostgreSQL והגדירו DATABASE_URL.</p>`
    : "";
  gamesEl.innerHTML = warn + state.games.map(renderGame).join("");
  renderField(state.games);
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

gamesEl.addEventListener("input", (e) => {
  const form = e.target.closest("[data-join]");
  if (form) draftNames[form.dataset.join] = e.target.value;
});

gamesEl.addEventListener("submit", async (e) => {
  const form = e.target.closest("[data-join]");
  if (!form) return;
  e.preventDefault();
  const name = form.querySelector("input").value.trim();
  const data = await api("/api/join", { slot: form.dataset.join, name });
  if (data.ok) draftNames[form.dataset.join] = "";
  applyState(data);
});

gamesEl.addEventListener("click", async (e) => {
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

refresh();
setInterval(refresh, 30000);
