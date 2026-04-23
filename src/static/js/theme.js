/* ---- Theme ---- */
// mode: 'auto' | 'dark' | 'light'
let _themeMode = localStorage.getItem("theme") || "auto";

function applyTheme() {
    let effective;
    if (_themeMode === "auto") {
        effective = window.matchMedia(
            "(prefers-color-scheme: light)",
        ).matches
            ? "light"
            : "dark";
    } else {
        effective = _themeMode;
    }
    document.documentElement.setAttribute("data-theme", effective);
    const icons = {
        auto: "\u25D0",
        light: "\u2600",
        dark: "\u263E",
    };
    const btn = document.getElementById("theme-toggle");
    if (btn) btn.textContent = icons[_themeMode];
}

function cycleTheme() {
    const order = ["auto", "light", "dark"];
    _themeMode = order[(order.indexOf(_themeMode) + 1) % 3];
    localStorage.setItem("theme", _themeMode);
    applyTheme();
}

window
    .matchMedia("(prefers-color-scheme: light)")
    .addEventListener("change", () => {
        if (_themeMode === "auto") applyTheme();
    });

applyTheme();
