/* ---- Genre ---- */
async function fetchGenrePreview(albumId) {
    const btn = $("#genre-btn");
    const area = $("#genre-area");
    btn.disabled = true;
    btn.innerHTML =
        '<span class="spinner"></span>Querying Last.fm…';

    try {
        const r = await fetch(`/api/album/${albumId}/genre`, {
            method: "POST",
        });
        const d = await r.json();
        btn.textContent = "Fetch Genre";
        btn.disabled = false;

        if (d.error) {
            area.innerHTML = `<div class="error">${esc(d.error)}</div>`;
            return;
        }

        if (!d.new_genre) {
            area.innerHTML =
                '<div class="identify-form" style="padding:0.8rem">No genre found on Last.fm</div>';
            return;
        }

        const changed = d.old_genre !== d.new_genre;
        area.innerHTML = `
      <div class="identify-form">
        <table class="diff-table">
          <thead><tr><th>Field</th><th>Current</th><th>New</th></tr></thead>
          <tbody>
            <tr>
              <td>genre</td>
              <td class="${changed ? "diff-changed" : "diff-same"}">${esc(d.old_genre) || '<em style="color:#555">empty</em>'}</td>
              <td class="${changed ? "diff-changed" : "diff-same"}">${esc(d.new_genre)}</td>
            </tr>
          </tbody>
        </table>
        <div style="margin-top:0.8rem;display:flex;gap:0.5rem">
          <button class="btn btn-accent" onclick="confirmGenre(${albumId})">Confirm & Write</button>
          <button class="btn" onclick="$('#genre-area').innerHTML=''">Cancel</button>
        </div>
      </div>
    `;
    } catch (e) {
        btn.textContent = "Fetch Genre";
        btn.disabled = false;
        area.innerHTML = `<div class="error">${esc(e.message)}</div>`;
    }
}

async function confirmGenre(albumId) {
    const area = $("#genre-area");
    area.querySelector(".btn-accent").disabled = true;
    area.querySelector(".btn-accent").innerHTML =
        '<span class="spinner"></span>Writing…';

    try {
        const r = await fetch(
            `/api/album/${albumId}/genre/confirm`,
            { method: "POST" },
        );
        const d = await r.json();
        if (d.error) {
            area.innerHTML = `<div class="error">${esc(d.error)}</div>`;
            return;
        }
        area.innerHTML = `<div style="color:#4ecca3;padding:0.8rem">✓ Genre set to: ${esc(d.genre)}</div>`;
        setTimeout(() => loadAlbum(albumId), 1500);
    } catch (e) {
        area.innerHTML = `<div class="error">${esc(e.message)}</div>`;
    }
}

function openGenreEditor(albumId, currentGenre) {
    const area = $("#genre-area");
    area.innerHTML = `
      <div class="identify-form">
        <label>Genre</label>
        <input type="text" id="genre-input" value="${esc(currentGenre)}" placeholder="e.g. Electronic, Synthpop">
        <div style="margin-top:0.5rem;display:flex;gap:0.5rem">
          <button class="btn btn-accent" id="genre-save-btn" onclick="saveGenre(${albumId})">Save</button>
          <button class="btn" onclick="$('#genre-area').innerHTML=''">Cancel</button>
        </div>
      </div>`;
    const input = $("#genre-input");
    input.focus();
    input.selectionStart = input.value.length;
}

async function saveGenre(albumId) {
    const area = $("#genre-area");
    const genre = $("#genre-input").value.trim();
    if (!genre) return;
    const btn = $("#genre-save-btn");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>Saving…';
    try {
        const r = await fetch(`/api/album/${albumId}/genre/save`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ genre }),
        });
        const d = await r.json();
        if (d.error) {
            area.innerHTML = `<div class="error">${esc(d.error)}</div>`;
            return;
        }
        area.innerHTML = `<div style="color:#4ecca3;padding:0.8rem">✓ Genre set to: ${esc(d.genre)}</div>`;
        setTimeout(() => loadAlbum(albumId), 1500);
    } catch (e) {
        area.innerHTML = `<div class="error">${esc(e.message)}</div>`;
    }
}
