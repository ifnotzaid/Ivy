# Ivy design system

How Ivy looks and behaves. Read this before changing the frontend
(`app/templates/`, `app/static/css/`, `app/static/js/`).

Ivy is a tool people work in for long sessions: translating, reading, reviewing cards.
The interface stays quiet so the language is the loudest thing on screen.

## Brand

- **Name:** Ivy (capitalised in copy; the wordmark is lowercase `ivy`).
- **Colour:** green, because the name is a plant. Green is the one accent.
- **Logo:** `app/static/logo-dark.png` on dark, `logo-light.png` on light; the sprout mark
  `logo-mark-*-128.png` stands in for "Ask Ivy". No glow or shadow on the logo.

## Colour

Tokens live in `:root` (dark, the default) and `body[data-theme="light"]` at the top of
`app/static/css/ivy.css`. `sets.css` repeats the same values. Use tokens, never raw hex.

| Token | Dark | Light | Use |
| --- | --- | --- | --- |
| `--bg` | `#040806` | `#edf4ee` | Page ground |
| `--surface` | `#0a0f0c` | `#f7fbf7` | Inputs, tab tracks |
| `--card` | `#0e1512` | `#f4faf4` | Panels and cards |
| `--card-hover` | `#141d19` | `#edf5ee` | Hovered card |
| `--floating` | `#111a15` | `#f8fcf8` | Menus, tooltips, toasts |
| `--border` | `#1a2420` | `#cfdfd3` | Card and panel edges |
| `--border-lit` | `#243530` | `#b9d0bf` | Control edges, focus-within |
| `--text` | `#e8f0ec` | `#183126` | Body text |
| `--text-2` | `#8fa89a` | `#3d5848` | Secondary text |
| `--text-3` | `#7a9486` | `#5a7563` | Meta, hints, placeholders (still ≥ 4.5:1) |
| `--ivy` | `#4ade80` | `#0f7a43` | The accent: primary action, active state, focus ring |
| `--danger` | `#ef4444` | `#ef4444` | Destructive actions, profanity warning |

**Data colours.** These encode meaning and are used only for that meaning:

- Register: `--formal` cyan (`#22d3ee` dark, `#0e7490` light), `--neutral` slate,
  `--casual` orange. Cool for formal, warm for casual. They appear on the register chips,
  Compare tags and tone bars, and nowhere else: grammatical-case tags, language badges and
  story theme badges are neutral grey so they never look like a register.
- Part of speech: `--noun` blue, `--verb` green, `--adj` amber, `--adv` pink. Only in word
  underlines, the legend and tooltip tags.

**Rules**

- Every text colour reaches 4.5:1 on the surface it sits on. Check new greys before using them.
- Green appears on the action and the active state, not on decoration.
- No gradients, glows or blurred colour blobs. No violet or indigo.
- Surfaces separate by one tone step or a 1px `--border`, not by shadows. Shadows only on
  things that float: menus, tooltips, the toast, modals.

## Type

- **One family: Outfit** (Google Fonts, weights 300–700). No second face.
- Numbers that change or line up (character counts, percentages, progress, scores) use
  `font-variant-numeric: tabular-nums`. The `--mono` token now points at Outfit for this.
- **Sizes:** 12px minimum for any text. Labels 12–13px, body 14–16px, translation text
  20–22px, card titles 16–18px, page title 24–28px.
- **Case:** sentence case everywhere: labels, tags, buttons, headings. No uppercase
  letter-spaced labels.
- Ellipsis is `…`, not `...`, in placeholders and loading text ("Saving…").

## Layout

- Content column: max 1060px, centred, 20px side padding (14px on phones).
- One `<h1>` per page: the logo on the translator page, "Community" on `/sets`.
  Card titles are `<h2>`, sections inside a card `<h3>`.
- Radius: 14px cards (`--r`), 10px controls (`--r-sm`), full pills for chips and tabs.
- **Phone (≤ 720px):** logo and the theme/account buttons share the top row; the five mode
  tabs sit on their own row and scroll sideways inside it (the page never scrolls sideways).
  Panels stack to one column. Mode tabs are at least 40px tall for thumbs.

## Components

- **Mode tabs** (`.mode-tab`): a `<nav>` of buttons. The active one has `.active` and
  `aria-current="page"`. The mode is kept in the URL hash (`/#stories`) so refresh and links work.
- **Register chips** (`.style-chip`): a button group; the selected chip has
  `aria-pressed="true"` and its register colour.
- **Word details** (`.word-span` + `.tooltip`): open on hover, tap, or keyboard focus. A tap
  elsewhere, moving focus away, or Escape closes them. They are nudged to stay on screen.
- **Buttons:** filled green for the one primary action in a view; outlined or text for the rest.
  Every icon-only button has an `aria-label`.
- **Forms:** a visible `<label for>` above every field. Login and sign-up fields carry
  `autocomplete`. Errors show inline under the form with `role="alert"`.
- **Status text** (story status, practice status, translation output) uses `role="status"` or
  `aria-live="polite"` so screen readers announce it.
- **Notifications:** `showToast(message)` on `/sets` instead of `alert()`. Destructive actions
  keep a confirmation that names the object ("Delete this set?").
- **Drawers** (vocabulary, "Ivy explains"): slide in with `transform`; when closed they are
  `visibility: hidden` so keyboard focus can't land on them.

## Interaction

- Keyboard focus shows a 2px `--ivy` ring (`:focus-visible`); inputs show a soft ring and green
  border instead. Never remove focus styles without a replacement.
- Transitions list their properties (never `transition: all`) and animate colour, opacity and
  transform only.
- Micro-interactions live in `app/static/css/motion.css` and `app/static/js/motion.js`, using
  the tokens at the top of `motion.css` (`--ease-out`, `--t-press` 140ms, `--t-hover` 180ms,
  `--t-ui` 240ms, `--t-reveal` 700ms). Each move confirms something: a press gives
  (`scale(0.96)`), the active mode tab is one pill that slides, a new view rises in, a
  translation's words arrive in reading order while the old one stays dimmed until then, tone
  bars glide to their new value and the percentages count, Compare cards arrive one by one,
  a reviewed flashcard leaves before the next comes in, a wrong practice answer shakes once.
  No bounce or overshoot, no loops except loading dots, nothing on hover for touch screens.
- `prefers-reduced-motion: reduce` means gentler, not nothing: things still fade in, but nothing
  travels, scales, turns or shakes (the reduced block at the end of `motion.css`).
- Escape closes menus, modals and panels. It never clears what the user typed.
- Theme choice is stored in `localStorage['ivy-theme']` and applied on both pages.

## Security rule for templates and scripts

Anything that came from a user or from an AI response is passed through `escapeHtml()` before
it goes into `innerHTML`. Public sets are shown to other users, so a missed escape is a
cross-user script injection.
