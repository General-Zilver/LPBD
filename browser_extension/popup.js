// Default values for settings and local queue.
const DEFAULTS = 
    {
        autoCollect:        true,
        customPage:         null,
        customPermission:   null,
        queue:              []   
    };

// Write a short message into the popup status area.
function setStatus(msg)
    {
        document.getElementById("status").textContent = msg;
    }

// Update the number shown in the "Queued count" display.
function updateQueueContent(queue)
    {
        document.getElementById("queueCount").textContent = String(queue.length);
    }

// Normalize a user-provided URL into an "exact page".
function normalizePageUrl(urlString) 
    {
        const url = new URL(urlString);
        // Only allow normal website URLs.
        if (url.protocol !== "http:" && url.protocol !== "https:") return null;
        return (url.origin + url.pathname).toLowerCase();
    }

// Convert our normalized page string into a Chrome permission match pattern.
// The "*" allows any query string or hash.
function toMatchPatternFromNormalizedPage(normalizedPage) 
    {
        return normalizedPage + "*";
    }

// Load settings from chrome.storage, and reflect them into the popup UI.
async function loadUI()
    {
        const data = await chrome.storage.local.get(DEFAULTS);

        document.getElementById("autoCollect").checked = !!data.autoCollect;

        if (data.customPage)
            {
                document.getElementById("customUrl").value = data.customPage;
            }

        updateQueueContent(data.queue || []);
    }

// Handle changes to the auto-collect checkbox.
// This updates chrome.storage so the service worker can use it later.
document.getElementById("autoCollect").addEventListener("change", async (e) => 
    {
        await chrome.storage.local.set({ autoCollect: e.target.checked });
        setStatus(e.target.checked ? "Auto collect enabled." : "Auto collect disabled.");
    });

// Handle "Set custom page" button clicks.
// This asks Chrome for permission to observe the custom page URL.
document.getElementById("setCustom").addEventListener("click", async () =>
    {
        const raw = document.getElementById("customUrl").value.trim();
        if (!raw)
            {
                setStatus("Enter a custom webpage URL first");
                return;   
            }

        let normalized;
            try
                {
                    normalized = normalizePageUrl(raw);
                } 
            catch
                {
                    setStatus("Invalid URL.");
                    return;
                }
            if (!normalized)
                {
                    setStatus("URL must be http or https.");
                    return;   
                }
        const pattern = toMatchPatternFromNormalizedPage(normalized);

        const granted = await chrome.permissions.request({origins: [pattern] });
        if (!granted)
            {
                setStatus("Permission denied for that page.");
                return;   
            }

        await chrome.storage.local.set 
            ({
                customPage: normalized,
                customPermission: pattern
            });

        setStatus ("Custom page set and permission granted.");
        await loadUI();

    });

// Handle "Remove custom page" button clicks.
// This removes the custom page setting and revokes permission if possible.
document.getElementById("clearCustom").addEventListener("click", async () => 
    {
        const data = await chrome.storage.local.get(DEFAULTS);
        const pattern = data.customPermission;

        if (pattern)
            {
                await chrome.permissions.remove({ origins: [pattern] });
            }
        
        await chrome.storage.local.set({ customPage: null, customPermission: null});
        setStatus("Custom page removed.");
        await loadUI();
    });

// Handle "Send queued items now" button clicks.
// This tells the service worker to attempt sending the queue.
document.getElementById("sendNow").addEventListener("click", async () => 
    {
        chrome.runtime.sendMessage({ type: "queue.flush" }, async (resp) => 
            {
                const err = chrome.runtime.lastError?.message;
                if (err)
                    {
                        setStatus(`Could not message service worker: ${err}`);
                        return;
                    }    
                setStatus(resp?.ok ? "Flush requested." : "Flush request failed.");
                await loadUI();
            });
    });

// Handle "Clear local extension data" button clicks.
// This wipes queued items and key settings.
document.getElementById("clearLocal").addEventListener("click", async () => 
    {
        await chrome.storage.local.set(
            {
                queue: [],
                lastSent: {},
                autoCollect: true,
                customPage: null,
                customPermission: null
            });
        setStatus("Cleared extension data.");
        await loadUI();
    });
// Handle "Use Current Page" button
document.getElementById("useCurrent").addEventListener("click", async () => {
    try 
        {
            const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
            const url = tab?.url;
            const normalized = normalizePageUrl(url || "");

            if (!normalized) 
                {
                    setStatus("Current tab is not an http/https page.");
                    return;
                }

            document.getElementById("customUrl").value = normalized;
            setStatus("Loaded current page. Click 'Set custom page' to save.");
        } 
    catch (e) 
        {
            setStatus(`Could not read current tab URL: ${e?.message || e}`);
        }
});


loadUI();