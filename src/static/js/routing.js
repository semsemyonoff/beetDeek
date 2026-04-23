/* ---- Routing ---- */
function navigate(hash) {
    location.hash = hash;
}

window.addEventListener("hashchange", route);

function route() {
    const h = location.hash.slice(1);
    if (h.startsWith("album/")) {
        const id = parseInt(h.split("/")[1]);
        if (id) loadAlbum(id);
    } else if (h.startsWith("artist/")) {
        const name = decodeURIComponent(h.slice(7));
        if (name) loadArtist(name);
    } else {
        loadLibrary();
    }
}
