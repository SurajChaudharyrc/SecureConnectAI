import { api } from "/js/api.js";
import { avatarHue, escapeHtml, initials, requireAuth, setNavActive, toast } from "/js/ui.js";

const PAGE_SIZE = 50;
const GROUP_WINDOW_MS = 5 * 60 * 1000; // collapse consecutive msgs within 5 min
const MAX_LEN = 2000;
const COUNTER_AT = 1900; // show counter when within 100 of the limit

// NOTE: these consts must be declared BEFORE the top-level await below. With
// top-level await, the module pauses at `await requireAuth`, then runs boot()
// — which reads MAX_LEN/COUNTER_AT — before any declarations placed textually
// after the await would initialize, throwing a temporal-dead-zone ReferenceError.
setNavActive();
const user = await requireAuth(api);
if (user) {
  await boot(user);
}

async function boot(user) {
  const myUserId = user.id;
  const groupId = Number(new URLSearchParams(window.location.search).get("group"));

  const els = {
    title: document.getElementById("chat-title"),
    presence: document.getElementById("chat-presence"),
    list: document.getElementById("chat-messages"),
    empty: document.getElementById("chat-empty"),
    typing: document.getElementById("chat-typing"),
    loadOlder: document.getElementById("load-older"),
    composer: document.getElementById("chat-composer"),
    field: document.querySelector(".chat-field"),
    input: document.getElementById("chat-input"),
    send: document.getElementById("chat-send"),
    counter: document.getElementById("chat-counter"),
  };

  if (!Number.isFinite(groupId) || groupId <= 0) {
    els.title.textContent = "Invalid group";
    return;
  }

  // Source of truth: messages sorted ascending by id. We re-render from this on
  // every change — simplest correct approach for chat-sized history, and it
  // makes grouping / day-dividers / edits / deletes trivial to keep consistent.
  const byId = new Map();
  let oldestId = null;
  let hasMore = true;
  let socket = null;
  let reconnectDelay = 1000;
  const typingUsers = new Map(); // user_id -> { username, timer }
  let openMenuId = null;

  // ---------- helpers ----------

  function sortedMessages() {
    return [...byId.values()].sort((a, b) => a.id - b.id);
  }

  function fmtTime(iso) {
    try {
      return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    } catch {
      return "";
    }
  }

  function dayKey(iso) {
    const d = new Date(iso);
    return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
  }

  function dayLabel(iso) {
    const d = new Date(iso);
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const that = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const diffDays = Math.round((today - that) / 86400000);
    if (diffDays === 0) return "Today";
    if (diffDays === 1) return "Yesterday";
    return d.toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });
  }

  function avatar(username) {
    return `<span class="chat-avatar" style="--hue:${avatarHue(username)}" aria-hidden="true">${escapeHtml(initials(username))}</span>`;
  }

  // ---------- rendering ----------

  function render() {
    const messages = sortedMessages();
    els.list.innerHTML = "";
    els.empty.hidden = messages.length > 0;
    els.loadOlder.hidden = !hasMore || messages.length === 0;

    let prevDay = null;
    let prevUserId = null;
    let prevTs = 0;

    for (const m of messages) {
      const dk = dayKey(m.created_at);
      const ts = new Date(m.created_at).getTime();

      if (dk !== prevDay) {
        const sep = document.createElement("li");
        sep.className = "chat-day";
        sep.innerHTML = `<span>${escapeHtml(dayLabel(m.created_at))}</span>`;
        els.list.append(sep);
        prevUserId = null; // a day break always starts a fresh group
      }

      const grouped =
        m.user_id === prevUserId &&
        dk === prevDay &&
        ts - prevTs < GROUP_WINDOW_MS &&
        !m.deleted_at;

      els.list.append(renderMessage(m, grouped));

      prevDay = dk;
      prevUserId = m.deleted_at ? null : m.user_id;
      prevTs = ts;
    }
  }

  function renderMessage(m, grouped) {
    const li = document.createElement("li");
    li.id = `msg-${m.id}`;
    li.className = "chat-msg";
    const mine = m.user_id === myUserId;
    li.classList.toggle("is-mine", mine);
    li.classList.toggle("is-grouped", grouped);

    if (m.deleted_at) {
      li.classList.add("is-deleted");
      li.innerHTML = `<div class="chat-msg-row"><div class="chat-bubble"><span class="chat-msg-deleted">message deleted</span></div></div>`;
      return li;
    }

    const edited = m.edited_at ? ` <span class="chat-msg-edited">(edited)</span>` : "";
    const av = grouped ? `<span class="chat-avatar-spacer" aria-hidden="true"></span>` : avatar(m.username);
    const header = grouped
      ? ""
      : `<div class="chat-msg-meta">
           <span class="chat-msg-author">${escapeHtml(m.username || "unknown")}</span>
           <span class="chat-msg-time">${fmtTime(m.created_at)}</span>
         </div>`;
    const actions = mine
      ? `<div class="chat-actions ${openMenuId === m.id ? "open" : ""}">
           <button class="chat-kebab" data-menu="${m.id}" aria-label="Message actions" title="Actions">⋯</button>
           <div class="chat-menu" role="menu">
             <button class="chat-menu-item" data-edit="${m.id}" role="menuitem">Edit</button>
             <button class="chat-menu-item chat-menu-danger" data-delete="${m.id}" role="menuitem">Delete</button>
           </div>
         </div>`
      : "";

    li.innerHTML = `
      ${av}
      <div class="chat-msg-row">
        ${header}
        <div class="chat-bubble">
          <div class="chat-msg-body" data-body="${m.id}">${escapeHtml(m.body)}${edited}</div>
          ${actions}
        </div>
      </div>`;
    return li;
  }

  function upsert(m) {
    byId.set(m.id, { ...byId.get(m.id), ...m });
  }

  function scrollToBottom() {
    requestAnimationFrame(() => {
      els.list.scrollTop = els.list.scrollHeight;
    });
  }

  // ---------- history ----------

  async function loadHistory({ older = false } = {}) {
    const opts = { limit: PAGE_SIZE };
    if (older && oldestId) opts.before = oldestId;
    const rows = await api.messages(groupId, opts); // newest-first
    if (rows.length) {
      for (const m of rows) upsert(m);
      oldestId = rows[rows.length - 1].id;
    }
    hasMore = rows.length === PAGE_SIZE;

    const beforeHeight = els.list.scrollHeight;
    render();
    if (older) {
      // Keep the viewport anchored where the user was after prepending.
      els.list.scrollTop = els.list.scrollHeight - beforeHeight;
    } else {
      scrollToBottom();
    }
  }

  // ---------- presence & typing ----------

  function setPresence(online) {
    const stack = online
      .slice(0, 3)
      .map((o) => avatar(o.username))
      .join("");
    const label = `${online.length} online`;
    els.presence.innerHTML = `<span class="chat-avatars">${stack}</span><span class="chat-online">${label}</span>`;
  }

  function renderTyping() {
    const names = [...typingUsers.values()].map((t) => t.username);
    if (!names.length) {
      els.typing.innerHTML = "";
      return;
    }
    const who = names.length === 1 ? `${escapeHtml(names[0])} is typing` : `${names.length} people are typing`;
    els.typing.innerHTML = `<span class="chat-typing-dots"><i></i><i></i><i></i></span> ${who}`;
  }

  function handleTyping(frame) {
    if (frame.user_id === myUserId) return;
    const prev = typingUsers.get(frame.user_id);
    if (prev) clearTimeout(prev.timer);
    if (frame.state) {
      const timer = setTimeout(() => {
        typingUsers.delete(frame.user_id);
        renderTyping();
      }, 4000);
      typingUsers.set(frame.user_id, { username: frame.username, timer });
    } else {
      typingUsers.delete(frame.user_id);
    }
    renderTyping();
  }

  // ---------- websocket ----------

  function wsUrl() {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}/api/groups/${groupId}/ws`;
  }

  function connect() {
    socket = new WebSocket(wsUrl());
    socket.addEventListener("open", () => {
      reconnectDelay = 1000;
    });
    socket.addEventListener("message", (ev) => {
      const frame = JSON.parse(ev.data);
      switch (frame.type) {
        case "message": {
          const atBottom = els.list.scrollHeight - els.list.scrollTop - els.list.clientHeight < 80;
          upsert(frame);
          render();
          if (atBottom || frame.user_id === myUserId) scrollToBottom();
          break;
        }
        case "edit":
          if (byId.has(frame.id)) {
            upsert({ id: frame.id, body: frame.body, edited_at: frame.edited_at });
            render();
          }
          break;
        case "delete":
          if (byId.has(frame.id)) {
            upsert({ id: frame.id, deleted_at: frame.deleted_at });
            render();
          }
          break;
        case "presence":
          setPresence(frame.online);
          break;
        case "typing":
          handleTyping(frame);
          break;
        case "error":
          toast(frame.detail || "Message rejected.", { kind: "warn" });
          break;
      }
    });
    socket.addEventListener("close", () => {
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, 15000);
    });
  }

  // ---------- composer ----------

  function autoGrow() {
    els.input.style.height = "auto";
    els.input.style.height = `${Math.min(els.input.scrollHeight, 140)}px`;
  }

  function updateComposerState() {
    const len = els.input.value.trim().length;
    els.send.disabled = len === 0;
    const raw = els.input.value.length;
    if (raw >= COUNTER_AT) {
      els.counter.hidden = false;
      els.counter.textContent = `${raw}/${MAX_LEN}`;
    } else {
      els.counter.hidden = true;
    }
  }

  let typingSent = false;
  let typingStopTimer = null;

  function sendTyping(state) {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "typing", state }));
    }
  }

  els.input.addEventListener("input", () => {
    autoGrow();
    updateComposerState();
    if (!typingSent) {
      typingSent = true;
      sendTyping(true);
    }
    clearTimeout(typingStopTimer);
    typingStopTimer = setTimeout(() => {
      typingSent = false;
      sendTyping(false);
    }, 2000);
  });

  function submitMessage() {
    const body = els.input.value.trim();
    if (!body) return;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "send", body }));
      els.input.value = "";
      autoGrow();
      updateComposerState();
      typingSent = false;
      sendTyping(false);
    }
  }

  els.composer.addEventListener("submit", (e) => {
    e.preventDefault();
    submitMessage();
  });

  els.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submitMessage();
    }
  });

  els.loadOlder.addEventListener("click", () => loadHistory({ older: true }));

  // ---------- message actions (event delegation) ----------

  function closeMenu() {
    if (openMenuId !== null) {
      openMenuId = null;
      render();
    }
  }

  els.list.addEventListener("click", async (e) => {
    const menuId = e.target.getAttribute?.("data-menu");
    const editId = e.target.getAttribute?.("data-edit");
    const delId = e.target.getAttribute?.("data-delete");

    if (menuId) {
      const id = Number(menuId);
      openMenuId = openMenuId === id ? null : id;
      render();
      return;
    }
    if (editId) {
      closeMenu();
      const current = byId.get(Number(editId))?.body ?? "";
      const next = window.prompt("Edit message:", current);
      if (next != null && next.trim()) {
        try {
          const updated = await api.editMessage(groupId, Number(editId), next.trim());
          upsert(updated);
          render();
        } catch (err) {
          toast(err.message, { kind: "err" });
        }
      }
      return;
    }
    if (delId) {
      closeMenu();
      if (window.confirm("Delete this message?")) {
        try {
          await api.deleteMessage(groupId, Number(delId));
          upsert({ id: Number(delId), deleted_at: new Date().toISOString() });
          render();
        } catch (err) {
          toast(err.message, { kind: "err" });
        }
      }
    }
  });

  // Click outside any open menu closes it.
  document.addEventListener("click", (e) => {
    if (openMenuId !== null && !e.target.closest?.(".chat-actions")) closeMenu();
  });

  // ---------- boot ----------

  updateComposerState();
  try {
    await loadHistory();
  } catch (err) {
    if (err.status === 403) {
      els.title.textContent = "You are not a member of this group";
      toast("Join this group from Discover to chat.", { kind: "warn" });
      return;
    }
    toast(err.message, { kind: "err" });
  }
  connect();
}
