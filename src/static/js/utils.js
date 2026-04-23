/* ---- Utils ---- */
const $ = (s) => document.querySelector(s);

function esc(s) {
    if (s === null || s === undefined) return "";
    const d = document.createElement("div");
    d.textContent = String(s);
    return d.innerHTML;
}

function highlight(text, q) {
    if (!q) return esc(text);
    const escaped = esc(text);
    const qEsc = esc(q);
    const re = new RegExp(
        "(" + qEsc.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")",
        "gi",
    );
    return escaped.replace(
        re,
        '<span style="color:#e94560;font-weight:600">$1</span>',
    );
}
