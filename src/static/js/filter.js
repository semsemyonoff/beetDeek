/* ---- Filter ---- */
let _tagFilter = "all"; // 'all' | 'tagged' | 'untagged'

function setFilter(val) {
    _tagFilter = val;
    // re-render current view
    route();
}

function filterBarHtml() {
    const opts = [
        ["all", "All"],
        ["tagged", "Identified"],
        ["untagged", "Not identified"],
    ];
    return `<div class="filter-bar">
    <span class="filter-label">Show:</span>
    ${opts
        .map(
            ([v, l]) =>
                `<button class="filter-btn${_tagFilter === v ? " active" : ""}" onclick="setFilter('${v}')">${l}</button>`,
        )
        .join("")}
    <span class="filter-spacer"></span>
    <button class="filter-btn" id="toggle-all-btn" onclick="toggleAllArtists()">Expand all</button>
  </div>`;
}

function toggleAllArtists() {
    const artists = document.querySelectorAll("#app .artist");
    const anyOpen = [...artists].some((a) =>
        a.classList.contains("open"),
    );
    artists.forEach((a) => a.classList.toggle("open", !anyOpen));
    const btn = document.getElementById("toggle-all-btn");
    if (btn)
        btn.textContent = anyOpen ? "Expand all" : "Collapse all";
}

function filterAlbums(albums) {
    if (_tagFilter === "all") return albums;
    return albums.filter((al) =>
        _tagFilter === "tagged" ? al.tagged : !al.tagged,
    );
}
