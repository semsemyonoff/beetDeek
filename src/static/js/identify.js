/* ---- Identify ---- */
let _identifyShown = false;
let _identifyPoll = null;
let _selectedCandidate = null;

function toggleIdentify(albumId) {
    const area = $("#identify-area");
    if (_identifyShown) {
        area.innerHTML = "";
        _identifyShown = false;
        return;
    }
    _identifyShown = true;
    _selectedCandidate = null;
    area.innerHTML = `
    <div class="identify-form">
      <div class="form-row">
        <div>
          <label>Artist (optional)</label>
          <input id="id-artist" placeholder="Override artist search">
        </div>
        <div>
          <label>Album (optional)</label>
          <input id="id-album" placeholder="Override album search">
        </div>
      </div>
      <label>MusicBrainz Release ID (optional)</label>
      <input id="id-mbid" placeholder="e.g. 12345678-1234-1234-1234-123456789abc">
      <button class="btn btn-accent" onclick="startIdentify(${albumId})">Search</button>
    </div>
    <div id="identify-results"></div>
  `;
}

async function startIdentify(albumId) {
    const results = $("#identify-results");
    results.innerHTML =
        '<div class="loading"><span class="spinner"></span> Searching sources…</div>';

    const body = {
        artist: $("#id-artist").value.trim(),
        album: $("#id-album").value.trim(),
        search_id: $("#id-mbid").value.trim(),
    };

    try {
        const r = await fetch(`/api/album/${albumId}/identify`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        await r.json();
        _identifyPoll = setInterval(
            () => pollIdentify(albumId),
            2000,
        );
    } catch (e) {
        results.innerHTML = `<div class="error">${esc(e.message)}</div>`;
    }
}

async function pollIdentify(albumId) {
    try {
        const r = await fetch(
            `/api/album/${albumId}/identify/status`,
        );
        const d = await r.json();
        if (d.status === "running") return;
        clearInterval(_identifyPoll);
        if (d.status === "error") {
            $("#identify-results").innerHTML =
                `<div class="error">${esc(d.error)}</div>`;
            return;
        }
        renderCandidates(albumId, d.candidates || []);
    } catch {
        clearInterval(_identifyPoll);
    }
}

function distClass(d) {
    if (d <= 0.1) return "dist-good";
    if (d <= 0.3) return "dist-ok";
    return "dist-bad";
}

function renderCandidates(albumId, candidates) {
    if (!candidates.length) {
        $("#identify-results").innerHTML =
            '<div class="loading">No matches found</div>';
        return;
    }
    _selectedCandidate = null;
    let html = '<div class="candidates">';
    html += candidates
        .map(
            (c) => `
    <div class="candidate" id="cand-${c.index}" onclick="selectCandidate(${c.index})">
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
    html += `<button class="btn btn-accent" id="apply-btn" onclick="applyMatch(${albumId})" disabled>Apply Selected</button>`;
    html += '</div><div id="diff-area"></div>';
    $("#identify-results").innerHTML = html;
}

function selectCandidate(idx) {
    document
        .querySelectorAll(".candidate")
        .forEach((el) => el.classList.remove("selected"));
    const el = $(`#cand-${idx}`);
    if (el) el.classList.add("selected");
    _selectedCandidate = idx;
    const btn = $("#apply-btn");
    if (btn) btn.disabled = false;
}

async function applyMatch(albumId) {
    if (_selectedCandidate === null) return;
    const diffArea = $("#diff-area");
    diffArea.innerHTML =
        '<div class="loading"><span class="spinner"></span> Computing diff…</div>';

    try {
        const r = await fetch(`/api/album/${albumId}/apply`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                candidate_index: _selectedCandidate,
            }),
        });
        const diff = await r.json();
        if (diff.error) {
            diffArea.innerHTML = `<div class="error">${esc(diff.error)}</div>`;
            return;
        }
        renderDiff(albumId, diff);
    } catch (e) {
        diffArea.innerHTML = `<div class="error">${esc(e.message)}</div>`;
    }
}

function renderDiff(albumId, diff) {
    let html = '<div class="diff-section"><h3>Album Changes</h3>';
    html +=
        '<table class="diff-table"><thead><tr><th>Field</th><th>Current</th><th>New</th></tr></thead><tbody>';
    for (const [field, vals] of Object.entries(diff.album)) {
        const changed = String(vals.old) !== String(vals.new);
        const cls = changed ? "diff-changed" : "diff-same";
        html += `<tr>
      <td>${esc(field)}</td>
      <td class="${cls}">${esc(vals.old)}</td>
      <td class="${cls}">${esc(vals.new)}</td>
    </tr>`;
    }
    html += "</tbody></table></div>";

    html += '<div class="diff-section"><h3>Track Changes</h3>';
    html +=
        '<table class="diff-table"><thead><tr><th>#</th><th>Field</th><th>Current</th><th>New</th></tr></thead><tbody>';
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
    html += `<button class="btn btn-accent" onclick="confirmMatch(${albumId}, ${diff.candidate_index})">Confirm & Write Tags</button>`;

    $("#diff-area").innerHTML = html;
}

async function confirmMatch(albumId, candidateIndex) {
    const diffArea = $("#diff-area");
    try {
        const r = await fetch(`/api/album/${albumId}/confirm`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                candidate_index: candidateIndex,
            }),
        });
        const d = await r.json();
        if (d.error) {
            diffArea.innerHTML += `<div class="error">${esc(d.error)}</div>`;
            return;
        }
        diffArea.innerHTML =
            '<div style="color:#4ecca3;padding:1rem;text-align:center">✓ Tags written successfully</div>';
        _identifyShown = false;
        setTimeout(() => loadAlbum(albumId), 1000);
    } catch (e) {
        diffArea.innerHTML += `<div class="error">${esc(e.message)}</div>`;
    }
}
