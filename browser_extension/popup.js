// Default state shape. customPages is an array of { url, permission, added_at }.
const DEFAULTS = {
    autoCollect:  true,
    customPages:  [],
    queue:        [],
};

const STATUS_CLEAR_MS = 3500;
let statusTimer = null;


// Shows a short message at the bottom of the popup. Clears after a few seconds.
function setStatus(msg) {
    const el = document.getElementById("status");
    el.textContent = msg;
    el.classList.toggle("active", !!msg);

    if (statusTimer) clearTimeout(statusTimer);
    if (msg) {
        statusTimer = setTimeout(() => {
            el.textContent = "";
            el.classList.remove("active");
        }, STATUS_CLEAR_MS);
    }
}


// Normalize a user-provided URL to "origin + pathname" lowercase.
function normalizePageUrl(urlString) {
    const url = new URL(urlString);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    return (url.origin + url.pathname).toLowerCase();
}


// Chrome permission pattern for a given normalized page.
function toMatchPattern(normalizedPage) {
    return normalizedPage + "*";
}


// Render the list of saved custom pages with remove buttons.
function renderPageList(customPages) {
    const list = document.getElementById("pageList");
    list.innerHTML = "";

    if (!customPages || customPages.length === 0) {
        const empty = document.createElement("div");
        empty.className = "empty-state";
        empty.textContent = "No custom pages added";
        list.appendChild(empty);
        return;
    }

    for (const entry of customPages) {
        const row = document.createElement("div");
        row.className = "page-item";

        const urlEl = document.createElement("div");
        urlEl.className = "page-url";
        urlEl.textContent = entry.url;
        urlEl.title = entry.url;

        const removeBtn = document.createElement("button");
        removeBtn.className = "remove-btn";
        removeBtn.textContent = "\u00d7";
        removeBtn.title = "Remove";
        removeBtn.addEventListener("click", () => removePage(entry.url));

        row.appendChild(urlEl);
        row.appendChild(removeBtn);
        list.appendChild(row);
    }
}


// Load state from chrome.storage and refresh the UI.
async function loadUI() {
    const data = await chrome.storage.local.get(DEFAULTS);
    document.getElementById("autoCollect").checked = !!data.autoCollect;
    renderPageList(data.customPages || []);
}


// Save a new custom page (after requesting host permission).
async function addPage() {
    const raw = document.getElementById("customUrl").value.trim();
    if (!raw) {
        setStatus("Enter a URL first");
        return;
    }

    let normalized;
    try {
        normalized = normalizePageUrl(raw);
    } catch {
        setStatus("Invalid URL");
        return;
    }
    if (!normalized) {
        setStatus("URL must be http or https");
        return;
    }

    const data = await chrome.storage.local.get(DEFAULTS);
    const customPages = data.customPages || [];

    if (customPages.some(p => p.url === normalized)) {
        setStatus("Already added");
        return;
    }

    const pattern = toMatchPattern(normalized);
    const granted = await chrome.permissions.request({ origins: [pattern] });
    if (!granted) {
        setStatus("Permission denied");
        return;
    }

    customPages.push({
        url: normalized,
        permission: pattern,
        added_at: new Date().toISOString(),
    });

    await chrome.storage.local.set({ customPages });
    document.getElementById("customUrl").value = "";
    setStatus("Page added");
    await loadUI();
}


// Remove a custom page by URL and revoke its permission.
async function removePage(url) {
    const data = await chrome.storage.local.get(DEFAULTS);
    const customPages = data.customPages || [];
    const entry = customPages.find(p => p.url === url);

    if (entry?.permission) {
        try {
            await chrome.permissions.remove({ origins: [entry.permission] });
        } catch {}
    }

    const updated = customPages.filter(p => p.url !== url);
    await chrome.storage.local.set({ customPages: updated });
    setStatus("Page removed");
    await loadUI();
}


// Wire up the auto-collect toggle.
document.getElementById("autoCollect").addEventListener("change", async (e) => {
    await chrome.storage.local.set({ autoCollect: e.target.checked });
    setStatus(e.target.checked ? "Auto collect on" : "Auto collect off");
});


// Fill the input with the current tab URL.
document.getElementById("useCurrent").addEventListener("click", async () => {
    try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        const normalized = normalizePageUrl(tab?.url || "");
        if (!normalized) {
            setStatus("Current tab is not a web page");
            return;
        }
        document.getElementById("customUrl").value = normalized;
    } catch (e) {
        setStatus("Could not read current tab");
    }
});


document.getElementById("addPage").addEventListener("click", addPage);

// Allow Enter in the URL input to trigger Add Page.
document.getElementById("customUrl").addEventListener("keydown", (e) => {
    if (e.key === "Enter") addPage();
});


loadUI();
