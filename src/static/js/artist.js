/* ---- Artist page ---- */
let _artistCache = {};

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
    $("#app").innerHTML = html;
}
