/* Inline autocomplete for the quick-add box: typing a trigger character opens a
 * suggestion menu under the input that completes the token at the caret.
 *   #  → existing buckets (names may contain spaces)
 *   @  → watcher emails seen on other tasks
 *   !  → statuses (Backlog / Now / Blocked / Done)
 * Mirrors what parseQuickAdd understands, so picks here parse back out there. */
(function () {
  "use strict";

  const App = window.App;
  const { $, esc, liveBuckets, STATUS, labelOf, getEmailSuggestions } = App;

  const TRIGGERS = "#@!";
  let $menu = null;        // the suggestions dropdown
  let items = [];          // [{ insert, label, meta }]
  let active = -1;         // highlighted index
  let token = null;        // { type, start } of the token being completed

  const input = () => document.getElementById("quick-add-input");
  const isOpen = () => !!$menu && $menu.is(":visible");

  // Find the token under the caret: scan left for a trigger char that starts a
  // word. '#' may span spaces (multi-word bucket names); '@' and '!' may not.
  function tokenAt(value, caret) {
    let crossedSpace = false;
    for (let i = caret - 1; i >= 0; i--) {
      const ch = value[i];
      if (TRIGGERS.includes(ch) && (i === 0 || /\s/.test(value[i - 1]))) {
        if (crossedSpace && ch !== "#") return null;
        return { type: ch, start: i, query: value.slice(i + 1, caret) };
      }
      if (/\s/.test(ch)) {
        crossedSpace = true;
        if (caret - i > 60) return null; // don't reach back forever for a '#'
      }
    }
    return null;
  }

  async function suggestionsFor(type, query) {
    const q = query.toLowerCase();
    if (type === "#") {
      const buckets = (await liveBuckets()).filter((b) => !b.archived);
      return buckets
        .filter((b) => (b.name || "").toLowerCase().includes(q))
        .slice(0, 8)
        .map((b) => ({ insert: `#${b.name} `, label: b.name, meta: "bucket" }));
    }
    if (type === "@") {
      return (getEmailSuggestions() || [])
        .filter((e) => e.includes(q))
        .slice(0, 8)
        .map((e) => ({ insert: `@${e} `, label: e, meta: "watcher" }));
    }
    if (type === "!") {
      return STATUS
        .filter((s) => s.label.toLowerCase().includes(q) || s.value.includes(q))
        .map((s) => ({ insert: `!${s.label.toLowerCase()} `, label: labelOf(s.value), meta: "status" }));
    }
    return [];
  }

  function ensureMenu() {
    if ($menu) return;
    $menu = $('<div class="qa-ac" role="listbox"></div>').hide();
    $(".qa-input").css("position", "relative").append($menu);
    // Pick on click; mousedown so it fires before the input's blur closes us.
    $menu.on("mousedown", ".qa-ac-item", (e) => {
      e.preventDefault();
      choose($(e.currentTarget).data("idx"));
    });
  }

  function render() {
    ensureMenu();
    $menu.html(
      items
        .map(
          (it, i) =>
            `<div class="qa-ac-item${i === active ? " active" : ""}" role="option" data-idx="${i}">` +
            `<span class="qa-ac-label">${esc(it.label)}</span>` +
            `<span class="qa-ac-meta">${esc(it.meta)}</span></div>`
        )
        .join("")
    );
    $menu.show();
  }

  function close() {
    if ($menu) $menu.hide().empty();
    items = [];
    active = -1;
    token = null;
  }

  // Replace the token at the caret with the chosen completion, then close.
  function choose(idx) {
    const el = input();
    if (!el || !token || !items[idx]) return close();
    const v = el.value;
    const before = v.slice(0, token.start);
    const after = v.slice(el.selectionStart ?? v.length);
    const ins = items[idx].insert;
    el.value = before + ins + after;
    const pos = before.length + ins.length;
    el.setSelectionRange(pos, pos);
    el.focus();
    close();
  }

  async function refresh() {
    const el = input();
    if (!el) return close();
    const t = tokenAt(el.value, el.selectionStart ?? el.value.length);
    if (!t) return close();
    const found = await suggestionsFor(t.type, t.query);
    // The caret may have moved while we awaited; re-check it's still on this token.
    const now = tokenAt(el.value, el.selectionStart ?? el.value.length);
    if (!found.length || !now || now.start !== t.start || now.type !== t.type) return close();
    token = t;
    items = found;
    active = 0;
    render();
  }

  // Returns true when it consumed the key (so the input's Enter handler stands down).
  function onKeydown(e) {
    if (!isOpen()) return false;
    switch (e.key) {
      case "ArrowDown":
        active = (active + 1) % items.length;
        render();
        return true;
      case "ArrowUp":
        active = (active - 1 + items.length) % items.length;
        render();
        return true;
      case "Enter":
      case "Tab":
        choose(active);
        return true;
      case "Escape":
        close();
        return true;
    }
    return false;
  }

  function init() {
    const el = input();
    if (!el) return;
    $(el).on("input", refresh);
    $(el).on("click keyup", (e) => {
      // Arrow/enter/etc. are handled in onKeydown; here only reposition on caret moves.
      if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) refresh();
    });
    $(el).on("blur", () => setTimeout(close, 120));
  }

  Object.assign(App, { initQuickAddAutocomplete: init, qaAutocompleteKeydown: onKeydown });
})();
