/* ---- Search ---- */
let _searchTimer = null;
let _lastSearchQuery = "";

function onSearchInput(val) {
    const q = val.trim();
    document.getElementById("search-clear").style.display = q
        ? "block"
        : "none";
    clearTimeout(_searchTimer);
    if (!q) {
        _lastSearchQuery = "";
        // restore current view
        route();
        return;
    }
    _searchTimer = setTimeout(() => doSearch(q), 250);
}

function clearSearch() {
    const input = document.getElementById("search-input");
    input.value = "";
    document.getElementById("search-clear").style.display = "none";
    _lastSearchQuery = "";
    route();
}

async function doSearch(q) {
    if (q === _lastSearchQuery) return;
    _lastSearchQuery = q;
    try {
        const r = await fetch(
            `/api/search?q=${encodeURIComponent(q)}`,
        );
        if (!r.ok) throw new Error(r.statusText);
        const data = await r.json();
        // only render if query hasn't changed while fetching
        if (q !== _lastSearchQuery) return;
        renderSearchResults(data, q);
    } catch (e) {
        $("#app").innerHTML =
            `<div class="error">Search failed: ${esc(e.message)}</div>`;
    }
}

function renderSearchResults(data, q) {
    const total =
        data.artists.length +
        data.albums.length +
        data.tracks.length;
    if (!total) {
        $("#app").innerHTML =
            `<div class="search-no-results">No results for "${esc(q)}"</div>`;
        return;
    }
    let html = '<div class="search-results">';

    if (data.artists.length) {
        html += `<h3>Artists (${data.artists.length})</h3>`;
        data.artists.forEach((name) => {
            html += `<div class="search-item" data-artist="${esc(name)}" onclick="goToArtist(this.dataset.artist)">
        <span class="si-main">${highlight(name, q)}</span>
      </div>`;
        });
    }

    if (data.albums.length) {
        html += `<h3>Albums (${data.albums.length})</h3>`;
        data.albums.forEach((al) => {
            html += `<div class="search-item" onclick="clearSearch(); navigate('album/${al.id}')">
        ${
            al.has_cover
                ? `<img class="album-thumb" src="/api/album/${al.id}/cover" loading="lazy" alt="">`
                : '<div class="album-thumb-empty">♪</div>'
        }
        <span class="si-main">${highlight(al.album, q)}</span>
        <span class="si-sub">${esc(al.albumartist)}${al.year ? " · " + al.year : ""}</span>
      </div>`;
        });
    }

    if (data.tracks.length) {
        html += `<h3>Tracks (${data.tracks.length})</h3>`;
        data.tracks.forEach((t) => {
            html += `<div class="search-item" onclick="clearSearch(); navigate('album/${t.album_id}')">
        <span class="si-main">${highlight(t.title, q)}</span>
        <span class="si-sub">${esc(t.artist)} — ${esc(t.album)}</span>
      </div>`;
        });
    }

    html += "</div>";
    $("#app").innerHTML = html;
}

function goToArtist(name) {
    clearSearch();
    navigate("artist/" + encodeURIComponent(name));
}
