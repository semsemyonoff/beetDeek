/* ---- Rescan ---- */
let _rescanPoll = null;

function _setScanButtons(disabled, html) {
    for (const id of ["#rescan-quick", "#rescan-full"]) {
        const b = $(id);
        b.disabled = disabled;
        if (html) b.innerHTML = html;
    }
}

async function doRescan(mode) {
    _setScanButtons(true);
    const label = mode === "full" ? "Full" : "Quick";
    const active =
        mode === "full" ? $("#rescan-full") : $("#rescan-quick");
    active.innerHTML = `<span class="spinner"></span>${label}…`;
    try {
        await fetch(`/api/rescan?mode=${mode}`, { method: "POST" });
        _rescanPoll = setInterval(pollRescan, 3000);
    } catch {
        _setScanButtons(false);
        $("#rescan-quick").textContent = "Quick Scan";
        $("#rescan-full").textContent = "Full Scan";
    }
}

async function pollRescan() {
    try {
        const r = await fetch("/api/rescan/status");
        const d = await r.json();
        if (d.status !== "running") {
            clearInterval(_rescanPoll);
            _setScanButtons(false);
            $("#rescan-quick").textContent = "Quick Scan";
            $("#rescan-full").textContent = "Full Scan";
            _libraryCache = null;
            _artistCache = {};
            _showScanResults(d);
            if (!location.hash || location.hash === "#")
                loadLibrary();
        }
    } catch {}
}

function _showScanResults(d) {
    const el = $("#scan-results");
    const added = d.added || [];
    const removed = d.removed || [];
    if (!added.length && !removed.length) {
        el.style.display = "block";
        el.innerHTML = `<div class="scan-banner">
                        Scan complete — no changes
                        <button class="scan-banner-close" onclick="this.parentElement.parentElement.style.display='none'">×</button>
                    </div>`;
        return;
    }
    let summary = "Scan complete — ";
    const parts = [];
    if (added.length)
        parts.push(`<strong>+${added.length}</strong> added`);
    if (removed.length)
        parts.push(`<strong>-${removed.length}</strong> removed`);
    summary += parts.join(", ");

    let details = "";
    if (added.length) {
        details += `<div class="scan-detail-section"><div class="scan-detail-label">Added:</div>`;
        details += added
            .map(
                (t) =>
                    `<div class="scan-detail-item">+ ${esc(t.artist)} — ${esc(t.title)}</div>`,
            )
            .join("");
        details += `</div>`;
    }
    if (removed.length) {
        details += `<div class="scan-detail-section"><div class="scan-detail-label">Removed:</div>`;
        details += removed
            .map(
                (t) =>
                    `<div class="scan-detail-item">- ${esc(t.artist)} — ${esc(t.title)}</div>`,
            )
            .join("");
        details += `</div>`;
    }

    el.style.display = "block";
    el.innerHTML = `<div class="scan-banner">
                    <span class="scan-summary" onclick="this.parentElement.querySelector('.scan-details').classList.toggle('open')" style="cursor:pointer">
                        ${summary} <span style="font-size:0.75rem;opacity:0.6">▼</span>
                    </span>
                    <button class="scan-banner-close" onclick="this.parentElement.parentElement.style.display='none'">×</button>
                    <div class="scan-details">${details}</div>
                </div>`;
}
