/* ---- Artist page ---- */
let _artistCache = {};
let _untaggedItems = [];
let _itemsIdentifyPoll = null;
let _itemsSelectedCandidate = null;

async function loadArtist(name) {
    if (_artistCache[name]) {
        renderArtist(_artistCache[name]);
        return;
    }
    $("#app").innerHTML =
        '<div class="loading">Loading artist…</div>';
    try {
        const r = await fetch(
            `/api/artist?name=${encodeURIComponent(name)}`,
        );
        if (!r.ok) throw new Error(r.statusText);
        _artistCache[name] = await r.json();
        renderArtist(_artistCache[name]);
    } catch (e) {
        $("#app").innerHTML =
            `<div class="error">${esc(e.message)}</div>`;
    }
}

function renderArtist(data) {
    document.title = `${data.artist} — beetDeck`;
    const albums = filterAlbums(data.albums);
    let html = `
    <span class="back-link" onclick="navigate('')">← Library</span>
    <div class="artist-page-header">
      <h2>${esc(data.artist)}</h2>
      <div class="meta">${albums.length} album${albums.length !== 1 ? "s" : ""}</div>
    </div>
    ${filterBarHtml()}
    <div class="album-grid">
      ${albums
          .map(
              (al) => `
        <a class="album-card" href="#album/${al.id}">
          ${
              al.has_cover
                  ? `<img class="album-card-cover" src="/api/album/${al.id}/cover" loading="lazy" alt="">`
                  : '<div class="album-card-nocover">♪</div>'
          }
          <div class="album-card-info">
            <div class="album-card-title" title="${esc(al.album)}">${esc(al.album)}</div>
            <div class="album-card-year">${al.year || ""}</div>
            <div class="album-card-badges">
              ${al.tagged ? '<span class="check">✓</span>' : ""}
            </div>
          </div>
        </a>
      `,
          )
          .join("")}
    </div>`;

    if (data.artist === "Unknown Artist") {
        html += `<div id="untagged-section">
      <h3 style="margin-top:2rem;padding-top:1rem;border-top:1px solid #333">Untagged Files</h3>
      <div id="untagged-list"><div class="loading">Loading…</div></div>
      <div id="items-identify-area"></div>
    </div>`;
    }

    $("#app").innerHTML = html;

    if (data.artist === "Unknown Artist") {
        loadUntaggedItems();
    }
}

async function loadUntaggedItems() {
    try {
        const r = await fetch("/api/items/untagged");
        if (!r.ok) throw new Error(r.statusText);
        _untaggedItems = await r.json();
        renderUntaggedItems();
    } catch (e) {
        const el = $("#untagged-list");
        if (el) el.innerHTML = `<div class="error">${esc(e.message)}</div>`;
    }
}

function renderUntaggedItems() {
    const el = $("#untagged-list");
    if (!el) return;
    if (!_untaggedItems.length) {
        el.innerHTML = '<div class="meta" style="padding:0.5rem 0">No untagged files found.</div>';
        return;
    }

    let html = `
    <div style="margin-bottom:0.5rem;display:flex;gap:0.5rem;align-items:center">
      <button class="btn" onclick="selectAllItems(true)">Select All</button>
      <button class="btn" onclick="selectAllItems(false)">Deselect All</button>
      <button class="btn btn-accent" onclick="startItemsIdentify()">Identify Selected</button>
    </div>
    <div style="overflow-x:auto">
    <table style="width:100%;border-collapse:collapse;font-size:0.85rem">
      <thead>
        <tr style="text-align:left;border-bottom:1px solid #333">
          <th style="padding:0.3rem 0.5rem;width:2rem"></th>
          <th style="padding:0.3rem 0.5rem">Title</th>
          <th style="padding:0.3rem 0.5rem">Artist</th>
          <th style="padding:0.3rem 0.5rem">Album</th>
          <th style="padding:0.3rem 0.5rem;width:6rem"></th>
        </tr>
      </thead>
      <tbody>`;

    for (const item of _untaggedItems) {
        html += `
        <tr data-item-id="${item.id}" style="border-bottom:1px solid #222">
          <td style="padding:0.3rem 0.5rem">
            <input type="checkbox" class="item-select" data-item-id="${item.id}">
          </td>
          <td style="padding:0.3rem 0.5rem">
            <input class="item-field" data-field="title" data-item-id="${item.id}"
                   value="${esc(item.title)}" placeholder="Title"
                   style="background:transparent;border:1px solid #333;color:inherit;padding:0.2rem 0.4rem;width:100%">
          </td>
          <td style="padding:0.3rem 0.5rem">
            <input class="item-field" data-field="artist" data-item-id="${item.id}"
                   value="${esc(item.artist)}" placeholder="Artist"
                   style="background:transparent;border:1px solid #333;color:inherit;padding:0.2rem 0.4rem;width:100%">
          </td>
          <td style="padding:0.3rem 0.5rem">
            <input class="item-field" data-field="album" data-item-id="${item.id}"
                   value="${esc(item.album)}" placeholder="Album"
                   style="background:transparent;border:1px solid #333;color:inherit;padding:0.2rem 0.4rem;width:100%">
          </td>
          <td style="padding:0.3rem 0.5rem">
            <button class="btn" style="font-size:0.75rem;padding:0.2rem 0.6rem"
                    onclick="saveItemMeta(${item.id})">Save</button>
          </td>
        </tr>`;
    }

    html += "</tbody></table></div>";
    el.innerHTML = html;
}

function selectAllItems(select) {
    document.querySelectorAll(".item-select").forEach((cb) => {
        cb.checked = select;
    });
}

async function saveItemMeta(itemId) {
    const row = document.querySelector(`tr[data-item-id="${itemId}"]`);
    if (!row) return;
    const fields = row.querySelectorAll(".item-field");
    const body = {};
    fields.forEach((f) => {
        body[f.dataset.field] = f.value.trim();
    });

    try {
        const r = await fetch(`/api/items/${itemId}/metadata`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        const d = await r.json();
        if (d.error) {
            alert(`Save failed: ${d.error}`);
        } else {
            // Flash the row to indicate success
            row.style.background = "#1a3a2a";
            setTimeout(() => { row.style.background = ""; }, 1000);
        }
    } catch (e) {
        alert(`Save failed: ${e.message}`);
    }
}

async function startItemsIdentify() {
    const checked = Array.from(document.querySelectorAll(".item-select:checked"));
    if (!checked.length) {
        alert("Select at least one file to identify.");
        return;
    }
    const itemIds = checked.map((cb) => parseInt(cb.dataset.itemId, 10));

    const area = $("#items-identify-area");
    area.innerHTML = `
    <div class="identify-form" style="margin-top:1rem">
      <div class="form-row">
        <div>
          <label>Artist (optional)</label>
          <input id="items-id-artist" placeholder="Override artist search">
        </div>
        <div>
          <label>Album (optional)</label>
          <input id="items-id-album" placeholder="Override album search">
        </div>
      </div>
      <button class="btn btn-accent" onclick="submitItemsIdentify(${JSON.stringify(itemIds)})">Search</button>
    </div>
    <div id="items-identify-results"></div>`;
}

async function submitItemsIdentify(itemIds) {
    const results = $("#items-identify-results");
    results.innerHTML = '<div class="loading"><span class="spinner"></span> Searching sources…</div>';
    _itemsSelectedCandidate = null;

    const body = {
        item_ids: itemIds,
        search_artist: ($("#items-id-artist") || {}).value || "",
        search_album: ($("#items-id-album") || {}).value || "",
    };

    try {
        const r = await fetch("/api/items/identify", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        const d = await r.json();
        if (d.error) {
            results.innerHTML = `<div class="error">${esc(d.error)}</div>`;
            return;
        }
        const taskId = d.task_id;
        _itemsIdentifyPoll = setInterval(() => pollItemsIdentify(taskId), 2000);
    } catch (e) {
        results.innerHTML = `<div class="error">${esc(e.message)}</div>`;
    }
}

async function pollItemsIdentify(taskId) {
    try {
        const r = await fetch(`/api/items/identify/${taskId}/status`);
        const d = await r.json();
        if (d.status === "running") return;
        clearInterval(_itemsIdentifyPoll);
        if (d.status === "error") {
            $("#items-identify-results").innerHTML = `<div class="error">${esc(d.error)}</div>`;
            return;
        }
        renderItemsCandidates(taskId, d.candidates || []);
    } catch {
        clearInterval(_itemsIdentifyPoll);
    }
}

function distClass(d) {
    if (d <= 0.1) return "dist-good";
    if (d <= 0.3) return "dist-ok";
    return "dist-bad";
}

function renderItemsCandidates(taskId, candidates) {
    if (!candidates.length) {
        $("#items-identify-results").innerHTML = '<div class="loading">No matches found</div>';
        return;
    }
    _itemsSelectedCandidate = null;
    let html = '<div class="candidates">';
    html += candidates
        .map(
            (c) => `
    <div class="candidate" id="items-cand-${c.index}" onclick="selectItemsCandidate(${c.index})">
      <div class="c-title">${esc(c.artist)} — ${esc(c.album)}</div>
      <div class="c-meta">
        <span class="c-dist ${distClass(c.distance)}">${(100 - c.distance * 100).toFixed(1)}%</span>
        ${c.year ? `· ${c.year}` : ""}
        ${c.media ? `· ${esc(c.media)}` : ""}
        · ${c.track_count} tracks
        · ${esc(c.data_source)}
        ${c.label ? `· ${esc(c.label)}` : ""}
        ${c.mb_albumid ? `· <a href="https://musicbrainz.org/release/${esc(c.mb_albumid)}" target="_blank" rel="noopener" style="color:#555" onclick="event.stopPropagation()">${esc(c.mb_albumid)}</a>` : ""}
      </div>
    </div>
  `,
        )
        .join("");
    html += `<button class="btn btn-accent" id="items-apply-btn" onclick="applyItemsMatch('${taskId}')" disabled>Apply Selected</button>`;
    html += '</div><div id="items-diff-area"></div>';
    $("#items-identify-results").innerHTML = html;
}

function selectItemsCandidate(idx) {
    document
        .querySelectorAll(".candidate")
        .forEach((el) => el.classList.remove("selected"));
    const el = $(`#items-cand-${idx}`);
    if (el) el.classList.add("selected");
    _itemsSelectedCandidate = idx;
    const btn = $("#items-apply-btn");
    if (btn) btn.disabled = false;
}

async function applyItemsMatch(taskId) {
    if (_itemsSelectedCandidate === null) return;
    const diffArea = $("#items-diff-area");
    diffArea.innerHTML = '<div class="loading"><span class="spinner"></span> Computing diff…</div>';

    try {
        const r = await fetch(`/api/items/identify/${taskId}/apply`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ candidate_index: _itemsSelectedCandidate }),
        });
        const diff = await r.json();
        if (diff.error) {
            diffArea.innerHTML = `<div class="error">${esc(diff.error)}</div>`;
            return;
        }
        renderItemsDiff(taskId, diff);
    } catch (e) {
        diffArea.innerHTML = `<div class="error">${esc(e.message)}</div>`;
    }
}

function renderItemsDiff(taskId, diff) {
    let html = '<div class="diff-section"><h3>New Album</h3>';
    html += '<table class="diff-table"><thead><tr><th>Field</th><th>New Value</th></tr></thead><tbody>';
    for (const [field, vals] of Object.entries(diff.album)) {
        if (!vals.new) continue;
        html += `<tr><td>${esc(field)}</td><td>${esc(vals.new)}</td></tr>`;
    }
    html += "</tbody></table></div>";

    html += '<div class="diff-section"><h3>Track Changes</h3>';
    html += '<table class="diff-table"><thead><tr><th>#</th><th>Field</th><th>Current</th><th>New</th></tr></thead><tbody>';
    for (const t of diff.tracks) {
        for (const field of ["title", "artist"]) {
            const vals = t[field];
            if (!vals) continue;
            const changed = String(vals.old) !== String(vals.new);
            const cls = changed ? "diff-changed" : "diff-same";
            html += `<tr>
        <td>${t.track}</td>
        <td>${esc(field)}</td>
        <td class="${cls}">${esc(vals.old)}</td>
        <td class="${cls}">${esc(vals.new)}</td>
      </tr>`;
        }
    }
    html += "</tbody></table></div>";
    html += `<button class="btn btn-accent" onclick="confirmItemsMatch('${taskId}', ${diff.candidate_index})">Confirm & Create Album</button>`;

    const diffEl = document.getElementById("items-diff-area");
    if (diffEl) diffEl.innerHTML = html;
}

async function confirmItemsMatch(taskId, candidateIndex) {
    const diffArea = $("#items-diff-area");
    try {
        const r = await fetch(`/api/items/identify/${taskId}/confirm`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ candidate_index: candidateIndex }),
        });
        const d = await r.json();
        if (d.error) {
            if (diffArea) diffArea.innerHTML += `<div class="error">${esc(d.error)}</div>`;
            return;
        }
        let msg = `✓ Album created successfully (album #${d.album_id})`;
        if (d.warnings && d.warnings.length) {
            msg += `<br><small style="color:#e9a84c">Warnings: ${d.warnings.map(esc).join("; ")}</small>`;
        }
        if (diffArea) diffArea.innerHTML = `<div style="color:#4ecca3;padding:1rem;text-align:center">${msg}</div>`;
        // Bust caches so library and any artist page re-fetch after navigation.
        // Clear the whole artist cache: the new album's albumartist may differ
        // from "Unknown Artist", and a previously visited artist page would
        // otherwise show stale data without the newly confirmed album.
        _artistCache = {};
        _libraryCache = null;
        // Navigate to new album
        setTimeout(() => navigate(`album/${d.album_id}`), 1200);
    } catch (e) {
        if (diffArea) diffArea.innerHTML += `<div class="error">${esc(e.message)}</div>`;
    }
}
