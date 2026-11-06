# Frontend review (Nov 2026)

Checked against Vercel's Web Interface Guidelines (`.claude/skills/web-design-guidelines`) and the
screenshots in `docs/screenshots/`. Paths are relative to the repo root.

## Status (polish pass, Nov 2026)

Fixed on the `frontend-redesign` branch:

- Section 1: all user content is escaped; Escape no longer clears input.
- Section 2: word details open on tap and keyboard focus and stay on screen; phone header
  puts the mode tabs on their own scrollable row. Touch styles added.
- Section 3: one `h1` per page, heading levels fixed, icon buttons labelled, clickable cards
  keyboard-reachable, labels linked, `autocomplete` on auth fields, `aria-current` on tabs,
  live regions on status text, visible `:focus-visible` rings.
- Section 4: no `transition: all`, `…` everywhere, toasts instead of `alert()`, image sizes,
  `theme-color` and `color-scheme`, mode and Community tab kept in the URL, tabular digits,
  12px minimum text, sentence-case labels, readable grey (`--text-3`), glows removed,
  light theme on `/sets`.
- Section 5: CSS and JS moved to `app/static/css/` and `app/static/js/`.

Not changed: `confirm()` is still used before deleting a set or removing a friend (it is a
real confirmation, just browser-styled). Formal changed from violet to cyan; see `DESIGN.md`.

## Overall

The frontend was two pages (before this pass): `app/templates/index.html` (6,449 lines: ~3,500 CSS, ~250 HTML,
~2,650 JS, all in one file) and `app/templates/sets.html` (817 lines). The dark green look is clean
and consistent, and the core features work. The main problems are:

1. A security bug on the Community page (fix first, regardless of redesign).
2. Word tooltips — Ivy's best feature — only work with a mouse hover.
3. Accessibility and polish basics are missing across the board.
4. Everything lives in one huge file, which makes any redesign slow and risky.

## 1. Must fix

- `app/templates/sets.html:323,347,799` — set name, description and owner name inserted with
  `innerHTML` without escaping. Public sets are shown to other users, so a set named
  `<img src=x onerror=...>` runs code in their browser (stored XSS). Same at `sets.html:415`
  (word, meaning, case) and the friends list around `sets.html:721-737` (display name, email).
  `escapeHtml()` already exists at `sets.html:493` — use it everywhere.
- `app/templates/index.html:6415` — pressing Escape calls `clearInput()`, wiping the user's typed
  text with no undo. Escape should only close things.

## 2. Mobile & touch

- `index.html:5735` — word tooltips open on `mouseover` only. On phones and with a keyboard
  there is no way to see word analysis or save a word. Needs tap/click and focus support.
- `index.html:3372` — on narrow screens the 5 mode tabs, theme toggle and avatar squeeze into
  one row; no compact nav for phones.
- `index.html:3715` — story audio controls are one long row of buttons; on a phone they wrap
  awkwardly (see `karaoke.png`, where "Generate story" / "Save story" already wrap on desktop).
- No `touch-action: manipulation`, no `env(safe-area-inset-*)` anywhere.

## 3. Accessibility

- No `<h1>` on either page; logo `alt="ivy"` only. Section titles use `<div>` (`sets.html:189`,
  `index.html:3721`).
- Icon-only buttons without labels: `index.html:3560` (×), `3585` (×), `3627` (⇄ swap),
  `3641` (✕ clear), `3667`, `sets.html:242,259,272` (×), `sets.html:415` (remove word ×).
- Clickable `<div>`s / `<a>` without `href`, not reachable by keyboard: `sets.html:222`
  (Back to sets), `sets.html:323,347,799` (set cards), `index.html:4804` (saved story cards),
  `index.html:3568,3578` (Sign up / Log in links).
- Labels not linked to inputs (no `for`): `index.html:3564-3575` (auth form),
  `sets.html:244-263`.
- Form inputs missing `autocomplete`/`name`: auth form `index.html:3564-3575`.
- Mode tabs (`index.html:3602`) and Community tabs (`sets.html:180`) have no `role="tab"` /
  `aria-selected`; current tab isn't announced.
- Status messages (translation result, story status, form errors) have no `aria-live`.
- Language selects at `index.html:3626,3628` have no label.
- `outline: none` on focus with only a border colour change: `index.html:495,762,949,1897,
  2547,2732,3130`, `sets.html:95`. Nothing uses `:focus-visible`.

## 4. Polish

- `transition: all` in 20+ places (e.g. `index.html:245,273,317,382,610,760,786,812,928`,
  `sets.html:47`). List the properties instead.
- `...` instead of `…` in placeholders and loading text (`index.html:971,3641,4640,4645,4753,
  4827,6053`, `sets.html:276,359,516,554,631,677`). `sets.html:359` sets a button to just `...`.
- Browser `alert()` / `confirm()` for errors and deletes (`sets.html:380,463,649,763,767,770`).
- Images without `width`/`height` (`index.html:3599,3642,3759,3798`).
- No `<meta name="theme-color">` or `color-scheme` despite a dark default theme.
- Tabs and current mode aren't in the URL — refreshing always returns to Translate, and you
  can't link someone to Stories or a specific set.
- Number columns (tone %, counts) don't use `tabular-nums`.

## 5. Structure (matters for the redesign)

- One 6,449-line template holding all CSS and JS. Splitting into `static/css/` and `static/js/`
  per feature (translate, compare, stories, practice, flashcards) is the first step of any
  redesign.
- `sets.html` duplicates the colour tokens and base styles from `index.html` and drifts from it
  (different nav, buttons, modal styles). It should share one stylesheet.
