// Background service worker (Manifest V3).
// Responsibilities:
// 1) Watch .edu/.gov navigations (and any custom pages the user adds).
// 2) Throttle sends so we do not spam duplicates.
// 3) Send items to the native host when possible.
// 4) Queue items locally when native host is unavailable, then retry.

const DEFAULTS = {
  autoCollect: true,
  customPages: [],         // [{ url, permission, added_at }]
  queue: [],               // unsent items [{ kind, value, seen_at }]
  lastSent: {},            // throttling map: key -> timestamp
  hostName: "com.lpbd.native.host"
};

const SEND_COOLDOWN_MS = 7 * 24 * 60 * 60 * 1000; // once per week per key
const QUEUE_CAP = 200;

// Helpers: scope checks and normalization.
function isEduOrGov(hostname) {
  const h = hostname.toLowerCase();
  return h.endsWith(".edu") || h.endsWith(".gov");
}

function normalizeDomain(hostname) {
  return hostname.toLowerCase().replace(/^www\./, "");
}

function normalizePage(urlString) {
  try {
    const u = new URL(urlString);
    if (u.protocol !== "http:" && u.protocol !== "https:") return null;
    return (u.origin + u.pathname).toLowerCase();
  } catch {
    return null;
  }
}

// Storage helpers.
async function getState() {
  return await chrome.storage.local.get(DEFAULTS);
}

async function setState(patch) {
  await chrome.storage.local.set(patch);
}

// Migrate the legacy single customPage/customPermission into the customPages array.
async function migrateLegacyCustomPage() {
  const raw = await chrome.storage.local.get(["customPage", "customPermission", "customPages"]);
  if (raw.customPage && (!raw.customPages || raw.customPages.length === 0)) {
    await chrome.storage.local.set({
      customPages: [{
        url: raw.customPage,
        permission: raw.customPermission || (raw.customPage + "*"),
        added_at: new Date().toISOString(),
      }],
    });
  }
  if (raw.customPage || raw.customPermission) {
    await chrome.storage.local.remove(["customPage", "customPermission"]);
  }
}

// Throttle: decide whether to send a key again.
function shouldSend(lastSent, key, now) {
  const prev = lastSent[key];
  if (!prev) return true;
  return (now - prev) > SEND_COOLDOWN_MS;
}

// Queue: append item, enforce cap.
async function enqueueItem(item) {
  const state = await getState();
  const queue = state.queue || [];
  queue.push(item);
  while (queue.length > QUEUE_CAP) queue.shift();
  await setState({ queue });
}

// Native messaging: connect, send one message, wait for response or disconnect.
function connectAndSend(hostName, payload) {
  return new Promise((resolve, reject) => {
    let port;
    try {
      port = chrome.runtime.connectNative(hostName);
    } catch {
      reject(new Error("connectNative failed"));
      return;
    }

    const requestId = crypto.randomUUID();
    const msg = { ...payload, request_id: requestId };

    const onMessage = (resp) => {
      if (resp?.request_id !== requestId) return;
      cleanup();
      resolve(resp);
    };

    const onDisconnect = () => {
      const err = chrome.runtime.lastError?.message || "native host disconnected";
      cleanup();
      reject(new Error(err));
    };

    function cleanup() {
      try { port.onMessage.removeListener(onMessage); } catch {}
      try { port.onDisconnect.removeListener(onDisconnect); } catch {}
      try { port.disconnect(); } catch {}
    }

    port.onMessage.addListener(onMessage);
    port.onDisconnect.addListener(onDisconnect);
    port.postMessage(msg);
  });
}

// Flush: try sending the queued batch. Clear queue on success, keep on failure.
async function flushQueue() {
  const state = await getState();
  const queue = state.queue || [];
  if (queue.length === 0) return true;

  const payload = {
    type: "collector.sync",
    client: { name: "chrome_extension", version: "0.1.0" },
    captured_at: new Date().toISOString(),
    items: queue
  };

  try {
    await connectAndSend(state.hostName, payload);
    await setState({ queue: [] });
    return true;
  } catch {
    return false;
  }
}

// Event: on install/update, migrate, set defaults and start periodic retry.
chrome.runtime.onInstalled.addListener(async () => {
  await migrateLegacyCustomPage();
  const state = await getState();
  await setState(state);
  chrome.alarms.create("retryFlush", { periodInMinutes: 30 });
});

// Event: periodic retry flush.
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === "retryFlush") await flushQueue();
});

// Event: popup may still ask us to flush (kept for internal messaging support).
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type === "queue.flush") {
    flushQueue()
      .then((ok) => sendResponse({ ok }))
      .catch(() => sendResponse({ ok: false }));
    return true;
  }
});

// Event: navigation committed (top frame). Collect allowed items and send or queue.
chrome.webNavigation.onCommitted.addListener(async (details) => {
  if (details.frameId !== 0) return;

  const state = await getState();
  const normalizedPage = normalizePage(details.url);
  if (!normalizedPage) return;

  const u = new URL(details.url);
  const domain = normalizeDomain(u.hostname);

  const now = Date.now();
  const lastSent = state.lastSent || {};
  const itemsToSend = [];

  // Rule: .edu/.gov domain collection (throttled), only when auto-collect is on.
  if (state.autoCollect && isEduOrGov(domain)) {
    const key = `domain:${domain}`;
    if (shouldSend(lastSent, key, now)) {
      itemsToSend.push({ kind: "domain", value: domain, seen_at: new Date().toISOString() });
      lastSent[key] = now;
    }
  }

  // Rule: exact custom page collection for every saved custom page (throttled).
  const customPages = state.customPages || [];
  for (const entry of customPages) {
    if (normalizedPage === entry.url) {
      const key = `page:${entry.url}`;
      if (shouldSend(lastSent, key, now)) {
        itemsToSend.push({ kind: "page", value: entry.url, seen_at: new Date().toISOString() });
        lastSent[key] = now;
      }
    }
  }

  if (itemsToSend.length === 0) return;

  // Save throttling state first so we don't re-fire repeatedly if sending fails.
  await setState({ lastSent });

  try {
    await connectAndSend(state.hostName, {
      type: "collector.sync",
      client: { name: "chrome_extension", version: "0.1.0" },
      captured_at: new Date().toISOString(),
      items: itemsToSend
    });
  } catch {
    for (const item of itemsToSend) await enqueueItem(item);
  }
});
