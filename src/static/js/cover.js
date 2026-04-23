/* ---- Cover Art ---- */
async function fetchCover(albumId) {
    const btn = $("#cover-fetch-btn");
    const area = $("#cover-area");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>Searching…';

    try {
        const r = await fetch(`/api/album/${albumId}/cover/fetch`, {
            method: "POST",
        });
        const d = await r.json();
        btn.textContent = "Fetch Cover";
        btn.disabled = false;

        if (d.error) {
            area.innerHTML = `<div class="error">${esc(d.error)}</div>`;
            return;
        }

        if (!d.found) {
            area.innerHTML =
                '<div class="identify-form" style="padding:0.8rem">No cover art found</div>';
            return;
        }

        area.innerHTML = `
      <div class="identify-form" style="text-align:center">
        <p style="margin-bottom:0.5rem;color:#888">Found from: ${esc(d.source)}</p>
        <img src="${esc(d.preview_url)}?t=${Date.now()}" style="max-width:300px;max-height:300px;border-radius:8px;cursor:pointer" onclick="openLightbox('${esc(d.preview_url)}?t=${Date.now()}')" alt="Preview">
        <div style="margin-top:0.8rem;display:flex;gap:0.5rem;justify-content:center">
          <button class="btn btn-accent" onclick="confirmCover(${albumId})">Confirm & Save</button>
          <button class="btn" onclick="$('#cover-area').innerHTML=''">Cancel</button>
        </div>
      </div>
    `;
    } catch (e) {
        btn.textContent = "Fetch Cover";
        btn.disabled = false;
        area.innerHTML = `<div class="error">${esc(e.message)}</div>`;
    }
}

async function confirmCover(albumId) {
    const area = $("#cover-area");
    const btn = area.querySelector(".btn-accent");
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span>Saving…';
    }

    try {
        const r = await fetch(
            `/api/album/${albumId}/cover/confirm`,
            { method: "POST" },
        );
        const d = await r.json();
        if (d.error) {
            area.innerHTML = `<div class="error">${esc(d.error)}</div>`;
            return;
        }
        area.innerHTML =
            '<div style="color:#4ecca3;padding:0.8rem;text-align:center">✓ Cover art saved and embedded</div>';
        setTimeout(() => loadAlbum(albumId), 1500);
    } catch (e) {
        area.innerHTML = `<div class="error">${esc(e.message)}</div>`;
    }
}

async function uploadCover(albumId, file) {
    if (!file) return;
    const area = $("#cover-area");
    area.innerHTML =
        '<div class="loading"><span class="spinner"></span> Uploading…</div>';

    try {
        const fd = new FormData();
        fd.append("file", file);
        const r = await fetch(
            `/api/album/${albumId}/cover/upload`,
            { method: "POST", body: fd },
        );
        const d = await r.json();
        if (d.error) {
            area.innerHTML = `<div class="error">${esc(d.error)}</div>`;
            return;
        }
        area.innerHTML =
            '<div style="color:#4ecca3;padding:0.8rem;text-align:center">✓ Cover art uploaded and embedded</div>';
        setTimeout(() => loadAlbum(albumId), 1500);
    } catch (e) {
        area.innerHTML = `<div class="error">${esc(e.message)}</div>`;
    }
}

/* ---- Lightbox ---- */
function openLightbox(src) {
    const lb = document.createElement("div");
    lb.className = "lightbox";
    lb.onclick = () => lb.remove();
    lb.innerHTML = `<img src="${esc(src)}" alt="Cover">`;
    document.body.appendChild(lb);
    document.addEventListener("keydown", function handler(e) {
        if (e.key === "Escape") {
            lb.remove();
            document.removeEventListener("keydown", handler);
        }
    });
}
