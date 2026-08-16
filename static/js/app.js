/* Behaviour for the Car Rental System UI.
   Everything is delegated or bound here rather than written as inline
   attributes, so the pages carry no inline script and a strict
   Content-Security-Policy stays possible. */

(function () {
  "use strict";

  /* ---- theme -------------------------------------------------------- */
  var root = document.documentElement;

  function applyTheme(theme) {
    root.setAttribute("data-theme", theme);
    document.querySelectorAll("[data-theme-toggle]").forEach(function (btn) {
      var dark = theme === "dark";
      btn.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
      btn.querySelectorAll("[data-theme-icon]").forEach(function (icon) {
        icon.hidden = icon.getAttribute("data-theme-icon") !== (dark ? "sun" : "moon");
      });
    });
  }

  function storedTheme() {
    try {
      var saved = localStorage.getItem("theme");
      if (saved === "dark" || saved === "light") return saved;
      // Honour the pre-redesign key so an existing preference is not lost.
      if (localStorage.getItem("darkMode") === "true") return "dark";
    } catch (e) { /* private mode */ }
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  applyTheme(storedTheme());

  document.addEventListener("click", function (event) {
    var toggle = event.target.closest("[data-theme-toggle]");
    if (!toggle) return;
    var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    applyTheme(next);
    try { localStorage.setItem("theme", next); } catch (e) { /* ignore */ }
  });

  /* ---- password reveal ---------------------------------------------- */
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-reveal]");
    if (!button) return;
    var input = document.getElementById(button.getAttribute("data-reveal"));
    if (!input) return;
    var hidden = input.type === "password";
    input.type = hidden ? "text" : "password";
    button.setAttribute("aria-label", hidden ? "Hide password" : "Show password");
    button.querySelectorAll("[data-reveal-icon]").forEach(function (icon) {
      icon.hidden = icon.getAttribute("data-reveal-icon") !== (hidden ? "off" : "on");
    });
  });

  /* ---- caps lock ----------------------------------------------------- */
  function capsCheck(event) {
    var input = event.target;
    if (input.type !== "password" && !input.dataset.wasPassword) return;
    var hint = input.closest(".field") && input.closest(".field").querySelector("[data-caps]");
    if (!hint) return;
    var on = typeof event.getModifierState === "function" && event.getModifierState("CapsLock");
    hint.classList.toggle("show", !!on);
  }
  ["keydown", "keyup"].forEach(function (type) {
    document.addEventListener(type, function (event) {
      if (event.target.matches("input")) capsCheck(event);
    });
  });
  document.addEventListener("focusout", function (event) {
    var hint = event.target.closest(".field") && event.target.closest(".field").querySelector("[data-caps]");
    if (hint) hint.classList.remove("show");
  });

  /* ---- price input: digits and a single decimal point ---------------- */
  document.addEventListener("input", function (event) {
    var input = event.target;
    if (!input.matches("[data-money]")) return;
    var cleaned = input.value.replace(/[^\d.]/g, "");
    var firstDot = cleaned.indexOf(".");
    if (firstDot !== -1) {
      cleaned = cleaned.slice(0, firstDot + 1) + cleaned.slice(firstDot + 1).replace(/\./g, "");
    }
    if (cleaned !== input.value) input.value = cleaned;
  });

  /* ---- destructive confirmation -------------------------------------- */
  document.addEventListener("submit", function (event) {
    var form = event.target;
    var message = form.getAttribute("data-confirm");
    if (message && !window.confirm(message)) {
      event.preventDefault();
      return;
    }
    // Guard against a double submit creating two rentals.
    var submit = form.querySelector('button[type="submit"], input[type="submit"]');
    if (submit && !form.hasAttribute("data-no-busy")) {
      window.setTimeout(function () { submit.classList.add("is-busy"); }, 0);
    }
  });

  /* ---- flash dismissal ----------------------------------------------- */
  document.addEventListener("click", function (event) {
    var close = event.target.closest("[data-flash-close]");
    if (close) close.closest(".flash").remove();
  });

  /* ---- mobile rail ---------------------------------------------------- */
  document.addEventListener("click", function (event) {
    var toggle = event.target.closest("[data-rail-toggle]");
    if (!toggle) return;
    var rail = document.querySelector(".rail");
    var open = rail.classList.toggle("open");
    toggle.setAttribute("aria-expanded", String(open));
  });
})();
