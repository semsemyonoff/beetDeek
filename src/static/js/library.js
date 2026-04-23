/* ---- Library ---- */
let _libraryCache = null;

async function loadLibrary() {
    if (_libraryCache) {
        renderLibrary(_libraryCache);
        return;
    }
    $("#app").innerHTML =
        '<div class="loading">Loading library…</div>';
    try {
        const r = await fetch("/api/library");
        if (r.status === 503) {
            renderNotInitialized();
            return;
        }
        if (!r.ok) throw new Error(r.statusText);
        _libraryCache = await r.json();
        if (_libraryCache.length === 0) {
            renderEmpty();
            return;
        }
        renderLibrary(_libraryCache);
    } catch (e) {
        $("#app").innerHTML =
            `<div class="error">Failed to load: ${esc(e.message)}</div>`;
    }
}

function renderNotInitialized() {
    $("#app").innerHTML = `
    <div class="empty-state">
      <div class="empty-icon">♪</div>
      <h2>Library not initialized</h2>
      <p>The beets database has not been created yet.<br>Run a full scan to import your music library.</p>
      <button class="btn btn-accent btn-lg" onclick="doRescan('full')">Full Scan</button>
    </div>`;
}

function renderEmpty() {
    $("#app").innerHTML = `
    <div class="empty-state">
      <div class="empty-icon">♪</div>
      <h2>Library is empty</h2>
      <p>No albums found in the database.<br>Run a scan to import your music library.</p>
      <div style="display:flex;gap:0.5rem;justify-content:center">
        <button class="btn btn-accent btn-lg" onclick="doRescan('full')">Full Scan</button>
        <button class="btn btn-lg" onclick="doRescan('quick')">Quick Scan</button>
      </div>
    </div>`;
}

function renderLibrary(artists) {
    document.title = "beetDeck";
    // Apply filter per artist
    const filtered = artists
        .map((a) => ({ ...a, albums: filterAlbums(a.albums) }))
        .filter((a) => a.albums.length > 0);
    const total = filtered.reduce((s, a) => s + a.albums.length, 0);
    let html = filterBarHtml();
    html += `<div class="stats">${filtered.length} artists · ${total} albums</div>`;
    html += filtered
        .map(
            (a) => `
    <div class="artist">
      <div class="artist-header" onclick="this.parentElement.classList.toggle('open')">
        <span class="arrow">▶</span>
        <a class="artist-name" href="#artist/${encodeURIComponent(a.artist)}" onclick="event.stopPropagation()">${esc(a.artist)}</a>
        <span class="album-count">${a.albums.length}</span>
      </div>
      <div class="albums">
        ${a.albums
            .map(
                (al) => `
          <div class="album-row">
            ${
                al.has_cover
                    ? `<img class="album-thumb" src="/api/album/${al.id}/cover" loading="lazy" alt="">`
                    : '<div class="album-thumb-empty">♪</div>'
            }
            ${al.tagged ? '<span class="check">✓</span>' : ""}
            <a class="album-link" href="#album/${al.id}">${esc(al.album)}</a>
            ${al.year ? `<span class="album-year">${al.year}</span>` : ""}
          </div>
        `,
            )
            .join("")}
      </div>
    </div>
  `,
        )
        .join("");
    $("#app").innerHTML = html;
}
