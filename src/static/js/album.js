/* ---- Album detail ---- */
let _albumData = null;

async function loadAlbum(id) {
    $("#app").innerHTML =
        '<div class="loading">Loading album…</div>';
    try {
        const r = await fetch(`/api/album/${id}`);
        if (!r.ok) throw new Error(r.statusText);
        _albumData = await r.json();
        renderAlbum(_albumData);
    } catch (e) {
        $("#app").innerHTML =
            `<div class="error">${esc(e.message)}</div>`;
    }
}

function renderAlbum(a) {
    document.title = `${a.album} — ${a.albumartist} — beetDeck`;
    const coverHtml = a.has_cover
        ? `<img class="cover-art" src="/api/album/${a.id}/cover" alt="Cover" onclick="openLightbox('/api/album/${a.id}/cover')">`
        : `<div class="cover-placeholder">♪</div>`;

    let html = `
    <span class="back-link" onclick="navigate('')">← Library</span>
    <span class="back-link" onclick="navigate('artist/${encodeURIComponent(a.albumartist)}')" style="margin-left:1rem">← ${esc(a.albumartist)}</span>
    <div class="album-header">
      ${coverHtml}
      <div class="album-info">
        <h2>${esc(a.album)} ${a.tagged ? '<span class="check">✓</span>' : ""}</h2>
        <div class="meta"><a href="#artist/${encodeURIComponent(a.albumartist)}">${esc(a.albumartist)}</a>${a.year ? ` · ${a.year}` : ""}</div>
        ${a.genre ? `<div class="meta">${esc(a.genre.replace(/\\?\u2400|\0/g, ", "))}</div>` : ""}
        ${a.label ? `<div class="meta">${esc(a.label)}</div>` : ""}
        ${a.mb_albumid ? `<div class="meta">MB: <a href="https://musicbrainz.org/release/${esc(a.mb_albumid)}" target="_blank" rel="noopener">${esc(a.mb_albumid)}</a></div>` : ""}
        <div class="path">${esc(a.path)}</div>
        <div class="album-actions">
          <div class="action-group">
            <span class="action-group-label">Tags</span>
            <button class="btn btn-sm" onclick="toggleIdentify(${a.id})">Identify</button>
          </div>
          <div class="action-group">
            <span class="action-group-label">Genre</span>
            <button class="btn btn-sm" id="genre-btn" onclick="fetchGenrePreview(${a.id})">Fetch</button>
            <button class="btn btn-sm" onclick="openGenreEditor(${a.id}, '${esc(a.genre ? a.genre.replace(/\\?\u2400|\0/g, ", ").replace(/'/g, "\\'") : "")}')">Edit</button>
          </div>
          <div class="action-group">
            <span class="action-group-label">Cover</span>
            <button class="btn btn-sm" id="cover-fetch-btn" onclick="fetchCover(${a.id})">Fetch</button>
            <label class="upload-label btn-sm" style="padding:0.3rem 0.6rem;font-size:0.75rem">Upload<input type="file" accept="image/*" style="display:none" onchange="uploadCover(${a.id}, this.files[0])"></label>
          </div>
          <div class="action-group">
            <span class="action-group-label">Lyrics</span>
            <button class="btn btn-sm" id="lyrics-btn" onclick="fetchAlbumLyrics(${a.id})">Fetch All</button>
            ${(() => {
                const lrcCount = a.tracks.filter((t) => t.has_lrc).length;
                return lrcCount
                    ? `<button class="btn btn-sm btn-lyrics" id="embed-all-btn" onclick="embedAllLrc(${a.id})">Embed All (${lrcCount})</button>`
                    : "";
            })()}
          </div>
        </div>
      </div>
    </div>
    <div id="genre-area"></div>
    <div id="cover-area"></div>
    <div id="lyrics-area"></div>
    <div id="identify-area"></div>
    <table class="track-table">
      <thead><tr>
        <th>#</th><th>Title</th><th>Artist</th><th style="text-align:right">Duration</th><th></th>
      </tr></thead>
      <tbody>
        ${a.tracks
            .map(
                (t) => `
          <tr>
            <td class="track-num">${t.disc > 1 ? t.disc + "-" : ""}${t.track}</td>
            <td>${esc(t.title)}</td>
            <td style="color:#888">${esc(t.artist)}</td>
            <td class="track-length">${t.length}</td>
            <td>
              <div class="track-actions-cell">
                <span class="track-action-group track-action-group-lyrics">
                  <span class="tag-toggle" onclick="toggleTrackLyrics(${a.id}, ${t.id})">lyrics</span>
                </span>
                <span class="track-action-group track-action-group-tags">
                  <span class="tag-toggle" onclick="toggleTags(${a.id}, ${t.id}, this)">tags</span>
                </span>
              </div>
            </td>
          </tr>
          <tr class="tag-row" id="lyrics-${t.id}" style="display:none">
            <td colspan="5"><div class="tag-panel" id="lyrics-panel-${t.id}">Loading…</div></td>
          </tr>
          <tr class="tag-row" id="tags-${t.id}" style="display:none">
            <td colspan="5"><div class="tag-panel" id="tag-panel-${t.id}">Loading…</div></td>
          </tr>
        `,
            )
            .join("")}
      </tbody>
    </table>
  `;
    $("#app").innerHTML = html;
}

/* ---- Track tags ---- */
async function toggleTags(albumId, trackId, el) {
    const row = $(`#tags-${trackId}`);
    if (row.style.display !== "none") {
        row.style.display = "none";
        return;
    }
    row.style.display = "";
    const panel = $(`#tag-panel-${trackId}`);
    try {
        const r = await fetch(
            `/api/album/${albumId}/track/${trackId}/tags`,
        );
        const tags = await r.json();
        let t = "<table>";
        for (const [k, v] of Object.entries(tags)) {
            t += `<tr><td class="tag-key">${esc(k)}</td><td class="tag-val">${esc(v)}</td></tr>`;
        }
        t += "</table>";
        panel.innerHTML = t;
    } catch (e) {
        panel.innerHTML = `<span class="error">${esc(e.message)}</span>`;
    }
}
