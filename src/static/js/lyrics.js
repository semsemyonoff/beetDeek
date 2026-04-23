/* ---- Lyrics helpers ---- */
const _lyricsStore = {};
let _lyricsStoreId = 0;

function _storeLyrics(text) {
    const key = "_lyr_" + ++_lyricsStoreId;
    _lyricsStore[key] = text;
    return key;
}

function formatLyricsHtml(text) {
    if (!text) return '<span style="color:#555">No lyrics</span>';
    const lines = text.split("\n");
    return lines
        .map((line) => {
            const m = line.match(
                /^(\[\d{2}:\d{2}\.\d{2,3}\])\s*(.*)$/,
            );
            if (m) {
                return `<span class="lrc-timestamp">${esc(m[1])}</span>${esc(m[2])}`;
            }
            return esc(line);
        })
        .join("\n");
}

function lyricsPreviewText(text, maxLines) {
    if (!text) return "";
    return text
        .split("\n")
        .slice(0, maxLines || 6)
        .join("\n");
}

function openLyricsPopup(title, bodyHtml) {
    document.querySelector(".lyrics-popup")?.remove();
    const popup = document.createElement("div");
    popup.className = "lyrics-popup";
    popup.onclick = (e) => {
        if (e.target === popup) popup.remove();
    };
    popup.innerHTML = `
    <div class="lyrics-popup-content">
      <div class="lyrics-popup-header">
        <h3>${title}</h3>
        <button class="lyrics-popup-close" onclick="this.closest('.lyrics-popup').remove()">&times;</button>
      </div>
      <div class="lyrics-popup-body">${bodyHtml}</div>
    </div>
  `;
    document.body.appendChild(popup);
    const handler = (e) => {
        if (e.key === "Escape") {
            popup.remove();
            document.removeEventListener("keydown", handler);
        }
    };
    document.addEventListener("keydown", handler);
}

function showFullLyrics(storeKey, title) {
    const text = _lyricsStore[storeKey] || "";
    openLyricsPopup(
        esc(title),
        `<div class="lyrics-text">${formatLyricsHtml(text)}</div>`,
    );
}

/* ---- Track lyrics inline panel ---- */
async function toggleTrackLyrics(albumId, trackId) {
    const row = $(`#lyrics-${trackId}`);
    if (row.style.display !== "none") {
        row.style.display = "none";
        return;
    }
    row.style.display = "";
    const panel = $(`#lyrics-panel-${trackId}`);
    panel.innerHTML = '<span class="spinner"></span> Loading…';
    try {
        const r = await fetch(
            `/api/album/${albumId}/track/${trackId}/lyrics`,
        );
        const d = await r.json();
        if (d.error) {
            panel.innerHTML = `<span class="error">${esc(d.error)}</span>`;
            return;
        }
        _renderLyricsPanel(panel, albumId, trackId, d);
    } catch (e) {
        panel.innerHTML = `<span class="error">${esc(e.message)}</span>`;
    }
}

function _renderLyricsPanel(panel, albumId, trackId, d) {
    let html =
        '<div style="display:flex;gap:0.5rem;align-items:center;margin-bottom:0.6rem;flex-wrap:wrap">';
    if (d.has_lyrics) {
        if (d.source === "lrc_file") {
            html += `<span class="lrc-badge">External .lrc file</span>`;
            html += `<button class="btn btn-sm btn-lyrics" onclick="embedLrcLyrics(${albumId}, ${trackId})">Embed into file</button>`;
        } else {
            html += `<span class="lyrics-source-badge">Embedded</span>`;
        }
    }
    html += `<button class="btn btn-sm" onclick="openLyricsEditor(${albumId}, ${trackId})">Edit</button>`;
    html += `<button class="btn btn-sm" onclick="fetchTrackLyrics(${albumId}, ${trackId}, this)">Search online</button>`;
    html += "</div>";

    if (d.has_lyrics) {
        const storeKey = _storeLyrics(d.lyrics);
        html += `<div class="lyrics-preview-inline" onclick="showFullLyrics('${storeKey}', 'Lyrics')">${formatLyricsHtml(lyricsPreviewText(d.lyrics, 8))}</div>`;
    } else {
        html +=
            '<span style="color:#555;font-size:0.8rem">No lyrics</span>';
    }

    panel.innerHTML = html;
}

/* ---- Lyrics editor (inline) ---- */
function openLyricsEditor(albumId, trackId) {
    const row = $(`#lyrics-${trackId}`);
    row.style.display = "";
    const panel = $(`#lyrics-panel-${trackId}`);

    // Load current text first
    fetch(`/api/album/${albumId}/track/${trackId}/lyrics`)
        .then((r) => r.json())
        .then((d) => {
            const existing = (d.has_lyrics ? d.lyrics : "") || "";
            panel.innerHTML = `
        <textarea id="lyrics-editor-${trackId}" style="width:100%;min-height:200px;background:#111;color:#e0e0e0;border:1px solid #0f3460;border-radius:6px;padding:0.6rem;font-size:0.8rem;line-height:1.6;font-family:inherit;resize:vertical">${esc(existing)}</textarea>
        <div style="margin-top:0.5rem;display:flex;gap:0.5rem">
          <button class="btn btn-sm btn-accent" onclick="saveLyricsEdit(${albumId}, ${trackId})">Save</button>
          <button class="btn btn-sm" onclick="toggleTrackLyrics(${albumId}, ${trackId})">Cancel</button>
        </div>
      `;
        });
}

async function saveLyricsEdit(albumId, trackId) {
    const textarea = $(`#lyrics-editor-${trackId}`);
    if (!textarea) return;
    const text = textarea.value;
    const panel = $(`#lyrics-panel-${trackId}`);
    const btn = panel.querySelector(".btn-accent");
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span>Saving…';
    }

    try {
        const r = await fetch(
            `/api/album/${albumId}/track/${trackId}/lyrics/save`,
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ lyrics: text }),
            },
        );
        const d = await r.json();
        if (d.error) {
            alert(d.error);
            if (btn) {
                btn.disabled = false;
                btn.textContent = "Save";
            }
            return;
        }
        // Reload the panel
        const r2 = await fetch(
            `/api/album/${albumId}/track/${trackId}/lyrics`,
        );
        const d2 = await r2.json();
        _renderLyricsPanel(panel, albumId, trackId, d2);
    } catch (e) {
        alert(e.message);
        if (btn) {
            btn.disabled = false;
            btn.textContent = "Save";
        }
    }
}

/* ---- Embed all .lrc files in album ---- */
async function embedAllLrc(albumId) {
    const btn = $("#embed-all-btn");
    btn.disabled = true;
    btn.textContent = "Embedding…";
    try {
        const r = await fetch(
            `/api/album/${albumId}/lyrics/embed`,
            { method: "POST" },
        );
        const d = await r.json();
        if (d.error) {
            alert(d.error);
            return;
        }
        const area = $("#lyrics-area");
        if (d.embedded.length) {
            area.innerHTML =
                '<div class="info" style="margin:0.5rem 0">' +
                d.embedded
                    .map((t) => `✓ Embedded: ${esc(t.title)}`)
                    .join("<br>") +
                "</div>";
        } else {
            area.innerHTML =
                '<div class="info" style="margin:0.5rem 0">No .lrc files to embed</div>';
        }
        btn.remove();
    } catch (e) {
        alert(e.message);
    } finally {
        if (btn.parentNode) {
            btn.disabled = false;
            btn.textContent = "Embed All";
        }
    }
}

/* ---- Embed .lrc into file (inline) ---- */
async function embedLrcLyrics(albumId, trackId) {
    const panel = $(`#lyrics-panel-${trackId}`);
    try {
        const r = await fetch(
            `/api/album/${albumId}/track/${trackId}/lyrics/embed`,
            { method: "POST" },
        );
        const d = await r.json();
        if (d.error) {
            alert(d.error);
            return;
        }
        // Reload panel
        const r2 = await fetch(
            `/api/album/${albumId}/track/${trackId}/lyrics`,
        );
        const d2 = await r2.json();
        _renderLyricsPanel(panel, albumId, trackId, d2);
    } catch (e) {
        alert(e.message);
    }
}

/* ---- Fetch lyrics for single track (inline) ---- */
async function fetchTrackLyrics(albumId, trackId, btn) {
    const panel = $(`#lyrics-panel-${trackId}`);
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>Searching…';
    try {
        const r = await fetch(
            `/api/album/${albumId}/track/${trackId}/lyrics/fetch`,
            { method: "POST" },
        );
        const d = await r.json();
        if (d.error) {
            alert(d.error);
            btn.disabled = false;
            btn.textContent = "Search online";
            return;
        }
        if (!d.found) {
            btn.textContent = "Search online";
            btn.disabled = false;
            panel.innerHTML +=
                '<div style="color:#e94560;font-size:0.8rem;margin-top:0.5rem">No lyrics found online</div>';
            return;
        }

        // Show diff inline
        const curKey = _storeLyrics(d.current_lyrics || "");
        const newKey = _storeLyrics(d.new_lyrics);

        let currentCol = "";
        if (d.current_lyrics) {
            const srcBadge =
                d.current_source === "lrc_file"
                    ? '<span class="lrc-badge">External .lrc</span> '
                    : '<span class="lyrics-source-badge">Embedded</span> ';
            currentCol = `<div class="lyrics-diff-col">
        <h4>Current ${srcBadge}</h4>
        <div class="lyrics-preview-inline" onclick="showFullLyrics('${curKey}', 'Current')">${formatLyricsHtml(lyricsPreviewText(d.current_lyrics, 6))}</div>
      </div>`;
        } else {
            currentCol = `<div class="lyrics-diff-col"><h4>Current</h4><span style="color:#555">No lyrics</span></div>`;
        }

        const newBadge = d.new_synced
            ? ' <span class="lyrics-source-badge">synced</span>'
            : "";
        const newCol = `<div class="lyrics-diff-col">
      <h4>New (${esc(d.new_backend)})${newBadge}</h4>
      <div class="lyrics-preview-inline" onclick="showFullLyrics('${newKey}', 'New')">${formatLyricsHtml(lyricsPreviewText(d.new_lyrics, 6))}</div>
    </div>`;

        panel.innerHTML = `
      <div class="lyrics-diff">${currentCol}${newCol}</div>
      <div style="margin-top:0.6rem;display:flex;gap:0.5rem">
        <button class="btn btn-sm btn-accent" onclick="confirmTrackLyrics(${albumId}, ${trackId})">Confirm & Write</button>
        <button class="btn btn-sm" onclick="reloadLyricsPanel(${albumId}, ${trackId})">Cancel</button>
      </div>
    `;
    } catch (e) {
        btn.textContent = "Search online";
        btn.disabled = false;
        alert(e.message);
    }
}

async function confirmTrackLyrics(albumId, trackId) {
    const panel = $(`#lyrics-panel-${trackId}`);
    const btn = panel.querySelector(".btn-accent");
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span>Writing…';
    }
    try {
        const r = await fetch(
            `/api/album/${albumId}/track/${trackId}/lyrics/confirm`,
            { method: "POST" },
        );
        const d = await r.json();
        if (d.error) {
            alert(d.error);
            if (btn) {
                btn.disabled = false;
                btn.textContent = "Confirm & Write";
            }
            return;
        }
        // Reload panel
        const r2 = await fetch(
            `/api/album/${albumId}/track/${trackId}/lyrics`,
        );
        const d2 = await r2.json();
        _renderLyricsPanel(panel, albumId, trackId, d2);
    } catch (e) {
        alert(e.message);
        if (btn) {
            btn.disabled = false;
            btn.textContent = "Confirm & Write";
        }
    }
}

async function reloadLyricsPanel(albumId, trackId) {
    const panel = $(`#lyrics-panel-${trackId}`);
    const r = await fetch(
        `/api/album/${albumId}/track/${trackId}/lyrics`,
    );
    const d = await r.json();
    _renderLyricsPanel(panel, albumId, trackId, d);
}

/* ---- Fetch lyrics for whole album ---- */
async function fetchAlbumLyrics(albumId) {
    const btn = document.getElementById("lyrics-btn");
    const area = document.getElementById("lyrics-area");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>Fetching lyrics…';

    try {
        const r = await fetch(
            `/api/album/${albumId}/lyrics/fetch`,
            { method: "POST" },
        );
        const d = await r.json();
        btn.textContent = "Fetch All";
        btn.disabled = false;

        if (d.error) {
            area.innerHTML = `<div class="error">${esc(d.error)}</div>`;
            return;
        }

        const found = d.tracks.filter((t) => t.found);
        if (!found.length) {
            area.innerHTML =
                '<div class="identify-form" style="padding:0.8rem">No lyrics found for any track</div>';
            return;
        }

        let html =
            '<div class="identify-form"><h3 style="margin-bottom:0.8rem;font-size:0.95rem">Lyrics Results</h3>';

        for (const t of d.tracks) {
            const trackNum =
                (t.disc > 1 ? t.disc + "-" : "") + t.track;
            html += `<div class="lyrics-result-item">`;
            html += `<div class="lyrics-result-header">
        <span class="lyrics-result-title">${esc(trackNum)}. ${esc(t.title)}</span>`;

            if (t.found) {
                const syncBadge = t.new_synced
                    ? ' <span class="lyrics-source-badge">synced</span>'
                    : "";
                html += `<span class="lyrics-result-meta">${esc(t.new_backend)}${syncBadge}</span>`;
            } else {
                html += `<span class="lyrics-result-meta" style="color:#e94560">not found</span>`;
            }
            html += `</div>`;

            if (t.found) {
                const curKey = _storeLyrics(t.current_lyrics || "");
                const newKey = _storeLyrics(t.new_lyrics);
                const safeTitle = esc(t.title).replace(/'/g, "\\'");

                let currentCol = "";
                if (t.current_lyrics) {
                    const srcBadge =
                        t.current_source === "lrc_file"
                            ? '<span class="lrc-badge">External .lrc</span>'
                            : '<span class="lyrics-source-badge">Embedded</span>';
                    currentCol = `<div class="lyrics-diff-col">
            <h4>Current ${srcBadge}</h4>
            <div class="lyrics-preview-inline" onclick="showFullLyrics('${curKey}', 'Current — ${safeTitle}')">${formatLyricsHtml(lyricsPreviewText(t.current_lyrics, 4))}</div>
          </div>`;
                } else {
                    currentCol = `<div class="lyrics-diff-col"><h4>Current</h4><span style="color:#555">none</span></div>`;
                }

                const newCol = `<div class="lyrics-diff-col">
          <h4>New</h4>
          <div class="lyrics-preview-inline" onclick="showFullLyrics('${newKey}', 'New — ${safeTitle}')">${formatLyricsHtml(lyricsPreviewText(t.new_lyrics, 4))}</div>
        </div>`;

                html += `<div class="lyrics-diff">${currentCol}${newCol}</div>`;
                html += `<label style="display:flex;align-items:center;gap:0.4rem;margin-top:0.5rem;font-size:0.8rem;cursor:pointer">
          <input type="checkbox" class="lyrics-track-cb" value="${t.item_id}" checked> Write lyrics for this track
        </label>`;
            }

            html += `</div>`;
        }

        html += `<div style="margin-top:1rem;display:flex;gap:0.5rem">
      <button class="btn btn-accent" onclick="confirmAlbumLyrics(${albumId})">Confirm & Write Selected</button>
      <button class="btn" onclick="document.getElementById('lyrics-area').innerHTML=''">Cancel</button>
    </div></div>`;

        area.innerHTML = html;
    } catch (e) {
        btn.textContent = "Fetch All";
        btn.disabled = false;
        area.innerHTML = `<div class="error">${esc(e.message)}</div>`;
    }
}

async function confirmAlbumLyrics(albumId) {
    const area = document.getElementById("lyrics-area");
    const checkboxes = area.querySelectorAll(
        ".lyrics-track-cb:checked",
    );
    const itemIds = Array.from(checkboxes).map((cb) =>
        parseInt(cb.value),
    );
    if (!itemIds.length) {
        alert("No tracks selected");
        return;
    }

    const btn = area.querySelector(".btn-accent");
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span>Writing…';
    }

    try {
        const r = await fetch(
            `/api/album/${albumId}/lyrics/confirm`,
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ item_ids: itemIds }),
            },
        );
        const d = await r.json();
        if (d.error) {
            area.innerHTML = `<div class="error">${esc(d.error)}</div>`;
            return;
        }
        if (d.failed && d.failed.length > 0) {
            const failedIds = JSON.stringify(d.failed);
            area.innerHTML = `<div class="identify-form" style="padding:0.8rem">
                <div class="error" style="margin-bottom:0.8rem">Lyrics written for ${d.written} track(s), but failed to write audio tags for ${d.failed.length} track(s). Check file permissions and try again.</div>
                <button class="btn btn-accent" onclick="retryFailedLyrics(${albumId}, ${failedIds})">Retry Failed Tracks</button>
            </div>`;
        } else {
            area.innerHTML = `<div style="color:#4ecca3;padding:0.8rem">✓ Lyrics written for ${d.written} track(s)</div>`;
        }
    } catch (e) {
        area.innerHTML = `<div class="error">${esc(e.message)}</div>`;
    }
}

async function retryFailedLyrics(albumId, failedIds) {
    const area = document.getElementById("lyrics-area");
    const btn = area.querySelector(".btn-accent");
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span>Retrying…';
    }

    try {
        const r = await fetch(
            `/api/album/${albumId}/lyrics/confirm`,
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ item_ids: failedIds }),
            },
        );
        const d = await r.json();
        if (d.error) {
            area.innerHTML = `<div class="error">${esc(d.error)}</div>`;
            return;
        }
        if (d.failed && d.failed.length > 0) {
            const newFailedIds = JSON.stringify(d.failed);
            area.innerHTML = `<div class="identify-form" style="padding:0.8rem">
                <div class="error" style="margin-bottom:0.8rem">Lyrics written for ${d.written} track(s), but failed to write audio tags for ${d.failed.length} track(s). Check file permissions and try again.</div>
                <button class="btn btn-accent" onclick="retryFailedLyrics(${albumId}, ${newFailedIds})">Retry Failed Tracks</button>
            </div>`;
        } else {
            area.innerHTML = `<div style="color:#4ecca3;padding:0.8rem">✓ Lyrics written for ${d.written} track(s)</div>`;
        }
    } catch (e) {
        area.innerHTML = `<div class="error">${esc(e.message)}</div>`;
    }
}
