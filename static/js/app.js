/* Behaviour for the Car Rental System UI.
   Everything is delegated or bound here rather than written as inline
   attributes, so the pages carry no inline script and a strict
   Content-Security-Policy stays possible. */

(function () {
  "use strict";

  /* ---- theme -------------------------------------------------------- */
  var root = document.documentElement;
  var themeAnimTimer = null;

  function prefersReducedMotion() {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function applyTheme(theme, animate) {
    // The transition class is added only for the duration of the switch. Left
    // on, it would animate the first paint and make hovers feel sluggish.
    if (animate && !prefersReducedMotion()) {
      root.classList.add("theme-anim");
      window.clearTimeout(themeAnimTimer);
      themeAnimTimer = window.setTimeout(function () {
        root.classList.remove("theme-anim");
      }, 420);
    }
    root.setAttribute("data-theme", theme);
    // Icon visibility is CSS's job now; only the label needs updating here.
    document.querySelectorAll("[data-theme-toggle]").forEach(function (btn) {
      btn.setAttribute(
        "aria-label",
        theme === "dark" ? "Switch to light theme" : "Switch to dark theme"
      );
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

  applyTheme(storedTheme(), false); // no animation on first paint

  document.addEventListener("click", function (event) {
    var toggle = event.target.closest("[data-theme-toggle]");
    if (!toggle) return;
    var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    applyTheme(next, true);
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

  /* ---- submit guards --------------------------------------------------- */
  document.addEventListener("submit", function (event) {
    var form = event.target;

    // Catch missing dates here rather than letting the server bounce the whole
    // page back. The server still validates; this only saves the round trip.
    var firstMissing = null;
    form.querySelectorAll("[data-datetime]").forEach(function (group) {
      var hidden = group.querySelector("[data-dt-value]");
      var display = group.querySelector("[data-dt-display]");
      var time = group.querySelector("[data-dt-time]");
      var slot = group.querySelector("[data-dt-error]");
      var empty = !hidden.value;

      display.classList.toggle("is-invalid", empty);
      if (time) time.classList.toggle("is-invalid", empty);
      if (slot) {
        if (empty) {
          var name = (group.querySelector("label") || {}).textContent || "date";
          slot.textContent = "Choose a " + name.trim().toLowerCase() + " date and time.";
          slot.hidden = false;
        } else {
          slot.hidden = true;
        }
      }
      if (empty && !firstMissing) firstMissing = display;
    });
    if (firstMissing) {
      event.preventDefault();
      firstMissing.scrollIntoView({ block: "center", behavior: "smooth" });
      firstMissing.focus({ preventScroll: true });
      return;
    }

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

  /* ---- number stepper ------------------------------------------------ */
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-step]");
    if (!button) return;
    var input = document.getElementById(button.getAttribute("data-step-for"));
    if (!input) return;
    var step = parseFloat(button.getAttribute("data-step")) || 1;
    var min = input.min === "" ? -Infinity : parseFloat(input.min);
    var max = input.max === "" ? Infinity : parseFloat(input.max);
    var current = parseFloat(input.value);
    if (isNaN(current)) current = min === -Infinity ? 0 : min;
    var next = Math.min(max, Math.max(min, Math.round((current + step) * 100) / 100));
    input.value = next.toFixed(2);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });

  /* ---- date and time --------------------------------------------------- */
  var DOW = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];
  var MONTHS = ["January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December"];

  function pad(n) { return String(n).padStart(2, "0"); }
  function toISO(d) { return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); }
  function fromISO(s) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || "");
    return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null;
  }
  // Display is always day/month/year, independent of the browser locale --
  // a native date input cannot be forced away from the host's format.
  function toDisplay(d) { return pad(d.getDate()) + "/" + pad(d.getMonth() + 1) + "/" + d.getFullYear(); }
  function midnight(d) { return new Date(d.getFullYear(), d.getMonth(), d.getDate()); }

  // Times are stored as 24-hour "HH:MM" -- that is what the server field
  // parses -- and shown as 12-hour with AM/PM.
  function to12h(hhmm) {
    var bits = hhmm.split(":");
    var h = Number(bits[0]);
    var suffix = h >= 12 ? "PM" : "AM";
    var shown = h % 12 === 0 ? 12 : h % 12;
    return shown + ":" + bits[1] + " " + suffix;
  }
  function roundUpToSlot(date) {
    var d = new Date(date);
    d.setSeconds(0, 0);
    var m = d.getMinutes();
    if (m === 0 || m === 30) return d;
    d.setMinutes(m < 30 ? 30 : 60);
    return d;
  }
  var TIME_SLOTS = (function () {
    var out = [];
    for (var i = 0; i < 48; i++) {
      out.push(pad(Math.floor(i / 2)) + ":" + (i % 2 ? "30" : "00"));
    }
    return out;
  })();
  var QUICK_TIMES = [
    ["Morning", "08:00"],
    ["Midday", "12:00"],
    ["Afternoon", "14:00"],
    ["Evening", "18:00"],
  ];

  function initDateTime(root) {
    var hidden = root.querySelector("[data-dt-value]");
    var display = root.querySelector("[data-dt-display]");
    var time = root.querySelector("[data-dt-time]");
    var cal = root.querySelector("[data-dt-cal]");
    var allowPast = root.hasAttribute("data-dt-allow-past");
    var selected = null;
    var view = midnight(new Date());

    var menu = root.querySelector("[data-dt-timemenu]");
    var label = root.querySelector("[data-dt-time-label]");

    var parts = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(hidden.value || "");
    if (parts) {
      selected = fromISO(parts[1]);
      setTime(parts[2]);
      if (selected) { display.value = toDisplay(selected); view = new Date(selected); }
    }

    function setTime(hhmm) {
      time.dataset.value = hhmm;
      label.textContent = to12h(hhmm);
    }

    function setDate(date) {
      selected = midnight(date);
      display.value = toDisplay(selected);
      view = new Date(selected);
    }

    function sync() {
      hidden.value = selected ? toISO(selected) + "T" + (time.dataset.value || "10:00") : "";
    }

    function render() {
      var first = new Date(view.getFullYear(), view.getMonth(), 1);
      var offset = (first.getDay() + 6) % 7; // weeks start Monday
      var days = new Date(view.getFullYear(), view.getMonth() + 1, 0).getDate();
      var today = midnight(new Date());

      var html = '<div class="cal-head">' +
        '<button type="button" class="cal-nav" data-cal-move="-1" aria-label="Previous month">' +
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"/></svg></button>' +
        '<span class="cal-title">' + MONTHS[view.getMonth()] + " " + view.getFullYear() + "</span>" +
        '<button type="button" class="cal-nav" data-cal-move="1" aria-label="Next month">' +
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg></button>' +
        '</div><div class="cal-grid">';
      html += DOW.map(function (d) { return '<div class="cal-dow">' + d + "</div>"; }).join("");
      for (var b = 0; b < offset; b++) html += '<button type="button" class="cal-day is-blank" tabindex="-1"></button>';
      for (var day = 1; day <= days; day++) {
        var date = new Date(view.getFullYear(), view.getMonth(), day);
        var cls = "cal-day";
        if (+date === +today) cls += " is-today";
        if (selected && +date === +selected) cls += " is-selected";
        var disabled = !allowPast && date < today ? " disabled" : "";
        html += '<button type="button" class="' + cls + '" data-cal-pick="' + toISO(date) + '"' + disabled + ">" + day + "</button>";
      }
      html += '</div><div class="cal-foot">' +
        '<button type="button" class="cal-link" data-cal-today>Today</button>' +
        '<button type="button" class="cal-link" data-cal-close>Close</button></div>';
      cal.innerHTML = html;
    }

    function open() { render(); cal.hidden = false; display.setAttribute("aria-expanded", "true"); }
    function close() { cal.hidden = true; display.setAttribute("aria-expanded", "false"); }

    display.addEventListener("click", function () { cal.hidden ? open() : close(); });
    display.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); }
      if (event.key === "Escape") close();
    });

    function renderMenu() {
      var current = time.dataset.value;
      var html = '<div class="timemenu-quick">';
      if (time.hasAttribute("data-dt-now")) {
        html += '<button type="button" data-quick-now class="wide">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2L4.5 13.5H11l-1 8.5 8.5-11.5H12z"/></svg>' +
          "Now</button>";
      }
      QUICK_TIMES.forEach(function (q) {
        html += '<button type="button" data-quick-time="' + q[1] + '">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.4V12l3 1.8"/></svg>' +
          q[0] + "</button>";
      });
      html += '</div><div class="timemenu-list" role="presentation">';
      TIME_SLOTS.forEach(function (slot) {
        html += '<button type="button" class="timemenu-item" role="option" data-slot="' + slot +
          '" aria-selected="' + (slot === current) + '">' + to12h(slot) +
          '<svg class="tick" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6.5 9.5 17 4 11.5"/></svg></button>';
      });
      menu.innerHTML = html + "</div>";
    }

    function openMenu() {
      renderMenu();
      menu.hidden = false;
      time.setAttribute("aria-expanded", "true");
      var chosen = menu.querySelector('[aria-selected="true"]');
      if (chosen) chosen.scrollIntoView({ block: "center" });
    }
    function closeMenu() {
      menu.hidden = true;
      time.setAttribute("aria-expanded", "false");
    }

    time.addEventListener("click", function () {
      menu.hidden ? openMenu() : closeMenu();
    });

    menu.addEventListener("click", function (event) {
      var slot = event.target.closest("[data-slot]");
      if (slot) {
        setTime(slot.getAttribute("data-slot"));
        if (!selected) setDate(new Date());
        sync(); closeMenu(); time.focus();
        return;
      }
      if (event.target.closest("[data-quick-now]")) {
        var soon = roundUpToSlot(new Date());
        setDate(soon);
        setTime(pad(soon.getHours()) + ":" + pad(soon.getMinutes()));
        sync(); closeMenu(); time.focus();
        return;
      }
      var preset = event.target.closest("[data-quick-time]");
      if (!preset) return;
      var hhmm = preset.getAttribute("data-quick-time");
      setTime(hhmm);
      if (!selected) {
        // No date chosen yet: use today, or tomorrow if that slot has gone.
        var when = midnight(new Date());
        when.setHours(Number(hhmm.slice(0, 2)), Number(hhmm.slice(3)), 0, 0);
        if (!allowPast && when <= new Date()) when.setDate(when.getDate() + 1);
        setDate(when);
      }
      sync(); closeMenu(); time.focus();
    });

    document.addEventListener("click", function (event) {
      if (!menu.hidden && !root.contains(event.target)) closeMenu();
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !menu.hidden) { closeMenu(); time.focus(); }
    });

    cal.addEventListener("click", function (event) {
      var move = event.target.closest("[data-cal-move]");
      if (move) { view = new Date(view.getFullYear(), view.getMonth() + Number(move.getAttribute("data-cal-move")), 1); render(); return; }
      if (event.target.closest("[data-cal-close]")) { close(); return; }
      if (event.target.closest("[data-cal-today]")) { view = midnight(new Date()); render(); return; }
      var pick = event.target.closest("[data-cal-pick]");
      if (!pick || pick.disabled) return;
      selected = fromISO(pick.getAttribute("data-cal-pick"));
      display.value = toDisplay(selected);
      if (!time.value) time.value = "10:00";
      sync();
      close();
      display.focus();
    });

    document.addEventListener("click", function (event) {
      if (!cal.hidden && !root.contains(event.target)) close();
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !cal.hidden) close();
    });

    sync();
  }

  document.querySelectorAll("[data-datetime]").forEach(initDateTime);
})();
