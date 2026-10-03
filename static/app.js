const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
// Every value put into innerHTML goes through esc(), even ones the server
// already restricts (theme and app names): the restriction is the server's
// invariant, not something this code should depend on. Coverage details
// carry exception text such as "<urlopen error ...>".
const esc = v => String(v).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c]);
const tiles = $$('.theme-btn');
tiles.forEach((b, i) => b.dataset.idx = i);
// One grid per section (custom-dark, ..., community, official, all); a tile's
// data-section names the grid it belongs to when sorted by section.
const grids = Object.fromEntries($$('.grid[data-grid]').map(g => [g.dataset.grid, g]));
const state = {q: '', near: '', showHidden: false, grad: false, readable: false, fresh: false,
               fav: false, hc: false, family: '', sort: 'section', preview: '', view: 'designed'};

// --- light/dark pairs ---------------------------------------------------------
// A theme with a generated twin (nord -> nord-light) is one tile on screen:
// both tiles are in the page, side by side, and only the chosen form shows.
// The choice is the tile's own sun/moon switch if touched, else the sidebar's
// "show every theme as". The live theme always shows in its live form.
const byName = Object.fromEntries(tiles.map(b => [b.dataset.theme, b]));
for (const b of tiles) if (b.dataset.twinOf && byName[b.dataset.twinOf]) b.dataset.hidden = byName[b.dataset.twinOf].dataset.hidden;
let pick = {};                                  // original name -> 'orig' | 'twin'
const originalOf = b => (b.dataset.twinOf && byName[b.dataset.twinOf]) || b;
function activeForm(orig) {
  const twin = byName[orig.dataset.twin];
  if (!twin) return orig;
  const p = pick[orig.dataset.theme];
  if (p) return p === 'twin' ? twin : orig;
  return state.view !== 'designed' && orig.dataset.mode !== state.view && twin.dataset.mode === state.view
    ? twin : orig;
}
const isShownForm = b => activeForm(originalOf(b)) === b;
// Hidden is a property of the theme, kept on its lead tile; the twin follows.
const isHiddenTheme = b => originalOf(b).dataset.hidden === '1';

// --- colour distance (OKLab), for "closest to a colour" and similar themes ---
const lin = c => { c /= 255; return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
function oklab(hex) {
  const r = lin(parseInt(hex.slice(1, 3), 16)), g = lin(parseInt(hex.slice(3, 5), 16)), b = lin(parseInt(hex.slice(5, 7), 16));
  const l = Math.cbrt(0.4122214708*r + 0.5363325363*g + 0.0514459929*b);
  const m = Math.cbrt(0.2119034982*r + 0.6806995451*g + 0.1073969566*b);
  const s = Math.cbrt(0.0883024619*r + 0.2817188376*g + 0.6299787005*b);
  return [0.2104542553*l + 0.7936177850*m - 0.0040720468*s, 1.9779984951*l - 2.4285922050*m + 0.4505937099*s,
          0.0259040371*l + 0.7827717662*m - 0.8086757660*s];
}
const labOf = b => b._lab || (b._lab = (b.dataset.colors || '').split(' ').filter(Boolean).map(oklab));
const dLab = (p, q) => Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]);
// How close a theme comes to one colour: its nearest swatch colour.
function nearness(b) {
  const target = oklab(state.near), labs = labOf(b);
  return labs.length ? Math.min(...labs.map(x => dLab(x, target))) : Infinity;
}
// How alike two themes look (lower = more alike). Two measures, added:
// role by role (page to page, button to button...), and as colour sets
// (each colour to its nearest in the other theme, both ways). Role by role
// alone missed a family that shifts its shades by one (Nordfox's panel IS
// Nord's page); sets alone lost same-family variants. Page and panels weigh
// most, then button, link, text. Checked across all 200 themes.
const ROLE_WEIGHT = [3, 2, 1.5, 1, 1], WSUM = 8.5;
function likeness(a, b) {
  const p = labOf(a), q = labOf(b);
  if (p.length !== 5 || q.length !== 5) return Infinity;
  const role = p.reduce((sum, x, i) => sum + ROLE_WEIGHT[i] * dLab(x, q[i]), 0);
  const near = (from, to) => from.reduce((sum, x, i) => sum + ROLE_WEIGHT[i] * Math.min(...to.map(y => dLab(x, y))), 0);
  return (role + near(p, q) + near(q, p)) / WSUM;
}
function seedPick() {
  pick = {};
  const live = tiles.find(b => b.classList.contains('active'));
  if (live && live.dataset.twinOf) pick[live.dataset.twinOf] = 'twin';
}
function flipForm(btn, form) {
  const orig = originalOf(btn), twin = byName[orig.dataset.twin];
  const target = [orig, twin].find(b => b && b.dataset.mode === form);
  if (!target || target === btn) return;
  const hadFocus = btn === document.activeElement;     // before refresh() hides it
  pick[orig.dataset.theme] = target === orig ? 'orig' : 'twin';
  refresh();
  if (hadFocus) target.focus({preventScroll: true});
}
const FAM_ORDER = ['red','orange','yellow','green','cyan','blue','purple','pink','neutral'];

// Per-viewer convenience only: remember filters and sort across reloads.
try { Object.assign(state, JSON.parse(localStorage.getItem('picker-state') || '{}')); } catch (e) {}
function save() { try { localStorage.setItem('picker-state', JSON.stringify(state)); } catch (e) {} }

function matches(b) {
  const d = b.dataset;
  return isShownForm(b)
      && (state.showHidden || !isHiddenTheme(b))
      && (!state.q || d.theme.toLowerCase().includes(state.q))
      && (!state.grad || d.gradient === '1')
      && (!state.readable || d.contrast === 'ok')
      && (!state.fresh || d.new === '1')
      && (!state.fav || d.fav === '1')
      && (!state.hc || d.hc === '1')
      && (!state.family || d.family === state.family);
}

const SORTS = {
  name:   (a, b) => a.dataset.theme.localeCompare(b.dataset.theme),
  light:  (a, b) => b.dataset.lum - a.dataset.lum,
  dark:   (a, b) => a.dataset.lum - b.dataset.lum,
  hue:    (a, b) => (FAM_ORDER.indexOf(a.dataset.family) - FAM_ORDER.indexOf(b.dataset.family))
                    || (a.dataset.hue - b.dataset.hue),
  // ISO text sorts by time: full UTC timestamps order same-day additions;
  // an older day-only value sorts before any timestamp of that day.
  near:   (a, b) => nearness(a) - nearness(b),
  newest: (a, b) => (b.dataset.added || '').localeCompare(a.dataset.added || '')
                    || a.dataset.theme.localeCompare(b.dataset.theme),
};

// A picked colour overrides the sort: closest first, in one list.
const sortKey = () => state.near ? 'near' : state.sort;
function layout() {
  // "section" keeps official / community / custom; any other sort pools every
  // theme into one grid, because sorting 110 themes by brightness is only
  // useful if it is one list.
  const key = sortKey();
  const sorted = key === 'section'
    ? [...tiles].sort((a, b) => a.dataset.idx - b.dataset.idx)
    : [...tiles].sort(SORTS[key]);
  for (const b of sorted) (key === 'section' ? grids[b.dataset.section] : grids.all).appendChild(b);
}

function refresh() {
  let shown = 0;
  for (const b of tiles) { b.hidden = !matches(b); if (!b.hidden) shown++; }
  for (const sec of $$('.sect')) {
    const n = sec.querySelectorAll('.theme-btn:not([hidden])').length;
    sec.querySelector('.sect-count').textContent = n ? `${n}` : '';
    const inMode = (sec.dataset.sect === 'all') === (sortKey() !== 'section');
    sec.hidden = !inMode || !sec.querySelector('.theme-btn:not([hidden])');
  }
  // Counted over the form each pair is showing: one tile per theme.
  const forms = tiles.filter(isShownForm), total = forms.length;
  const hiddenN = tiles.filter(b => !b.dataset.twinOf && b.dataset.hidden === '1').length;
  // Every theme should have a light/dark twin; say so only when some don't.
  const single = forms.filter(b => !b.dataset.twin && !b.dataset.twinOf).length;
  const grads = forms.filter(b => b.dataset.gradient === '1').length;
  const low = forms.filter(b => b.dataset.contrast === 'low').length;
  const hc = forms.filter(b => b.dataset.hc === '1').length;
  $('#count').textContent = shown === total
    ? `${total} themes${single ? ` (${single} without a light/dark twin)` : ''} · ${grads} gradient · ${hc} high contrast · ${low} low contrast`
      + (hiddenN && !state.showHidden ? ` · ${hiddenN} hidden` : '')
    : `${shown} of ${total}`;
  $$('#view [data-view]').forEach(v => v.classList.toggle('on', v.dataset.view === state.view));
  $$('.fam').forEach(f => f.classList.toggle('on', f.dataset.family === state.family));
  const active = [state.q, state.near, state.grad, state.readable, state.fresh, state.fav, state.hc, state.family]
    .filter(Boolean).length;
  $('#filters-toggle').textContent = active ? `Filters (${active})` : 'Filters';
  updateSurprise();
  save();
}

// --- toolbar wiring -------------------------------------------------------
const ctl = {q: $('#filter'), grad: $('#only-gradient'),
             readable: $('#only-readable'), fresh: $('#only-new'), fav: $('#only-fav'), hc: $('#only-hc'),
             sort: $('#sort'), preview: $('#preview')};
ctl.q.value = state.q; ctl.sort.value = state.sort;
ctl.preview.value = state.preview || '';
ctl.grad.checked = state.grad; ctl.readable.checked = state.readable;
ctl.fresh.checked = state.fresh; ctl.fav.checked = state.fav; ctl.hc.checked = state.hc;
ctl.q.addEventListener('input', () => { state.q = ctl.q.value.trim().toLowerCase(); refresh(); });
ctl.sort.addEventListener('change', () => { state.sort = ctl.sort.value; layout(); refresh(); });
ctl.preview.addEventListener('change', () => { state.preview = ctl.preview.value; applyPreview(); save(); });
ctl.showHidden = $('#show-hidden'); ctl.showHidden.checked = state.showHidden;
ctl.showHidden.addEventListener('change', () => { state.showHidden = ctl.showHidden.checked; refresh(); });
const nearIn = $('#near');
function setNear(hex) {
  state.near = hex;
  $('#near-value').textContent = hex || 'off';
  $('#near-clear').hidden = !hex;
  if (hex) nearIn.value = hex;
  layout(); refresh();
}
nearIn.addEventListener('input', () => setNear(nearIn.value));
if (state.near) { $('#near-value').textContent = state.near; $('#near-clear').hidden = false; nearIn.value = state.near; }
$('#near-clear').addEventListener('click', () => setNear(''));
for (const k of ['grad', 'readable', 'fresh', 'fav', 'hc'])
  ctl[k].addEventListener('change', () => { state[k] = ctl[k].checked; refresh(); });
$$('.fam').forEach(f => f.addEventListener('click', () => {
  state.family = state.family === f.dataset.family ? '' : f.dataset.family; refresh();
}));
$('#fam-any').addEventListener('click', () => { state.family = ''; refresh(); });
$('#surprise').addEventListener('click', surprise);
// The header and live strip stay at the top while the page scrolls. Their
// height varies (the strip wraps), so the sticky sidebar and scroll-into-view
// read it from --topbar-h rather than a fixed number.
new ResizeObserver(([e]) => document.documentElement.style.setProperty(
  '--topbar-h', `${Math.ceil(e.target.getBoundingClientRect().height)}px`)).observe($('#topbar'));
// Phones: the sidebar folds behind a "Filters" button (CSS hides it below
// 900px unless .open), so the tiles are the first thing on screen.
$('#filters-toggle').addEventListener('click', () => {
  const open = $('#filters').classList.toggle('open');
  $('#filters-toggle').setAttribute('aria-expanded', String(open));
});
$$('#view [data-view]').forEach(v => v.addEventListener('click', () => {
  state.view = v.dataset.view; seedPick(); refresh();
}));

// --- applying -------------------------------------------------------------
async function applyTheme(theme) {
  const btn = tiles.find(b => b.dataset.theme === theme);
  if (btn && btn.dataset.busy) return;
  if (btn) btn.dataset.busy = '1';
  const prev = $('.current b').textContent;
  const msg = $('#msg');
  try {
    const res = await fetch('/set-theme', {
      method: 'POST',
      headers: {'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'},
      body: 'theme=' + encodeURIComponent(theme)
    });
    const data = await res.json();
    msg.textContent = data.message; msg.hidden = false;
    if (data.ok) markApplied(prev, data.theme, data.css);
  } catch (e) {
    msg.textContent = 'Request failed: ' + e; msg.hidden = false;
  } finally {
    if (btn) delete btn.dataset.busy;
  }
}

// Re-dress the page for a theme that is now live, however it got applied.
function markApplied(prev, theme, css) {
  tiles.forEach(b => b.classList.toggle('active', b.dataset.theme === theme));
  $('.current b').textContent = theme;
  $('.current').title = theme;
  const now = byName[theme];
  if (now) {
    if (now.dataset.twinOf) pick[now.dataset.twinOf] = 'twin';
    else if (now.dataset.twin) pick[theme] = 'orig';
    const sw = now.querySelector('.swatch');
    $('#live-swatch').replaceChildren(...(sw ? [sw.cloneNode(true)] : []));
    refresh();
  }
  const link = $('#theme-css'); if (link) link.href = css;
  pushRecent(prev, theme);
  clearTimeout(window.__covT); window.__covT = setTimeout(runCoverage, 3500);
}

function pushRecent(prev, now) {
  const box = $('#history');
  const chips = [...box.querySelectorAll('.chip')].map(c => c.dataset.theme)
                  .filter(t => t !== now && t !== prev);
  if (prev && prev !== now && prev !== 'unknown') chips.unshift(prev);
  setUndo(chips[0]);
  box.innerHTML = chips.slice(0, 6).map(t =>
    `<button type="button" class="chip" data-theme="${esc(t)}">${esc(t)}</button>`).join('')
    || '<span class="none">none yet</span>';
}
// Undo re-applies the theme that was live before the last change; undoing
// twice swaps back, like a two-step history.
function setUndo(t) {
  const u = $('#undo');
  u.hidden = !t;
  if (!t) return;
  u.dataset.theme = t; u.title = `Back to ${t} (U)`; u.querySelector('span').textContent = t;
}
$('#undo').addEventListener('click', () => { if ($('#undo').dataset.theme) applyTheme($('#undo').dataset.theme); });
$('#history').addEventListener('click', ev => {
  const c = ev.target.closest('.chip'); if (c) applyTheme(c.dataset.theme);
});

// A folded section's tiles stay laid out in some browsers (Chrome keeps a
// closed <details>' content rendered-but-hidden), so offsetParent alone
// would let the arrow keys and "Surprise me" land on a tile you can't see.
function visibleTiles() {
  return $$('.theme-btn').filter(b => !b.hidden && b.offsetParent && !b.closest('details.sect:not([open])'));
}

// "Surprise me" picks from what the filters show, never the live theme. Worked
// out from the filters and folded sections, not from layout like
// visibleTiles(): the button sits in the live strip on every tab, and on any
// tab but Themes no tile has an offsetParent, so it used to do nothing there.
function surprisePool() {
  return tiles.filter(b => !b.hidden && !isHiddenTheme(b) && !b.closest('.sect[hidden], details.sect:not([open])'));
}
const surpriseCandidates = () => surprisePool().filter(b => !b.classList.contains('active'));

// The count is on the button so it's plain that the filters apply to it. It
// counts every theme shown, the live one included, so it matches the count
// above the grid; the live one is just never the pick.
function updateSurprise() {
  const n = surprisePool().length, btn = $('#surprise');
  btn.textContent = `Surprise me · ${n}`;
  btn.disabled = !surpriseCandidates().some(b => b.dataset.rating !== '-1');
  btn.title = btn.disabled ? 'No other theme matches the filters'
    : `Apply a random theme from the ${n} shown, never the live one (R)`;
}

// A random tile: liked themes three times as likely, disliked ones never --
// the same rule as the server's state.pick().
function weightedPick(pool) {
  pool = pool.filter(b => b.dataset.rating !== '-1');
  const w = pool.map(b => b.dataset.rating === '1' ? 3 : 1), total = w.reduce((s, x) => s + x, 0);
  let r = Math.random() * total;
  for (let i = 0; i < pool.length; i++) { r -= w[i]; if (r < 0) return pool[i]; }
  return pool[pool.length - 1];
}
function surprise() {
  const b = weightedPick(surpriseCandidates());
  if (!b) return;
  if (b.offsetParent) {
    b.scrollIntoView({block: 'center', behavior: 'smooth'});
    b.focus({preventScroll: true});
  }
  applyTheme(b.dataset.theme);
}

$('#picker').addEventListener('click', ev => {
  const btn = ev.target.closest('.theme-btn');
  if (!btn) return;
  ev.preventDefault();
  const form = ev.target.closest('[data-form]');
  if (form) flipForm(btn, form.dataset.form);
  else if (ev.target.closest('.star')) toggleFav(btn);
  else if (ev.target.closest('.peek')) openLightbox(btn);
  else applyTheme(btn.dataset.theme);
});

// --- lightbox ---------------------------------------------------------------
const lb = $('#lightbox'), lbBody = $('#lb-body'), lbCmp = $('#lb-compare');
let lbTile = null, lbApps = [], lbIndex = -1;
const shotsOf = t => { const b = tiles.find(x => x.dataset.theme === t);
                       return b ? (b.dataset.shots || '').split(' ').filter(Boolean) : []; };
function openLightbox(btn) {
  lbTile = btn;
  $('#lb-title').textContent = btn.dataset.theme;
  const bits = [];
  if (btn.dataset.mode) bits.push(btn.dataset.mode);
  if (btn.dataset.gradient === '1') bits.push('gradient');
  // A UTC timestamp shows as the viewer's own calendar day.
  const added = btn.dataset.added || '';
  if (added) bits.push('added ' + (added.includes('T') ? new Date(added).toLocaleDateString() : added));
  $('#lb-meta').textContent = bits.join(' · ');
  $('#lb-hide').textContent = isHiddenTheme(btn) ? 'Unhide' : 'Hide';
  showRating(btn);
  $('#lb-readable').hidden = !btn.dataset.warn;            // only for low-contrast themes
  // The five themes that look most like this one (in the forms on show).
  const near = tiles.filter(b => isShownForm(b) && originalOf(b) !== originalOf(btn))
    .map(b => [likeness(btn, b), b]).filter(x => x[0] < Infinity).sort((x, y) => x[0] - y[0]).slice(0, 5);
  const sim = $('#lb-similar');
  sim.innerHTML = near.length ? 'Looks like: ' + near.map(([, b]) =>
    `<button type="button" class="chip" data-similar="${esc(b.dataset.theme)}">${esc(b.dataset.theme)}</button>`).join(' ') : '';
  sim.hidden = !near.length;
  const warn = $('#lb-warn');
  warn.textContent = btn.dataset.warn ? 'Contrast: ' + btn.dataset.warn : '';
  warn.hidden = !btn.dataset.warn;
  // Every other theme with screenshots; the choice sticks across themes so
  // several can be compared against one reference in a row.
  const keep = lbCmp.value;
  const others = tiles.filter(b => b !== btn && b.dataset.shots).map(b => b.dataset.theme).sort();
  lbCmp.innerHTML = '<option value="">Compare with...</option>'
    + others.map(t => `<option value="${esc(t)}">${esc(t)}</option>`).join('');
  lbCmp.value = others.includes(keep) ? keep : '';
  lbCmp.hidden = !btn.dataset.shots || !others.length;
  setApps();
  showGrid();
  lb.hidden = false;
  $('#lb-close').focus();
}
// In compare mode only apps shot in BOTH themes are shown.
function setApps() {
  const mine = shotsOf(lbTile.dataset.theme), other = lbCmp.value ? shotsOf(lbCmp.value) : null;
  lbApps = other ? mine.filter(a => other.includes(a)) : mine;
}
const shotImg = (a, t, kind, cls = '') => `<img ${cls} loading="lazy" alt="${esc(a)} in ${esc(t)}"
  src="/shots/${kind}/${encodeURIComponent(a)}_${encodeURIComponent(t)}.${kind === 'thumb' ? 'jpg' : 'png'}">`;
function showGrid() {
  lbIndex = -1;
  const T = lbTile.dataset.theme, C = lbCmp.value, t = esc(T), c = esc(C);
  if (!lbApps.length) {
    lbBody.innerHTML = c ? `<p class="lb-empty">${t} and ${c} have no app screenshots in common.</p>`
      : '<p class="lb-empty">No screenshots of this theme yet. They come from the screenshot '
        + 'capture, an optional extra (see DEPLOY.md).</p>';
    return;
  }
  lbBody.innerHTML = C
    ? '<div class="lb-grid pairs">' + lbApps.map((a, i) =>
        `<figure data-i="${i}"><figcaption class="pair-app"><b>${esc(a)}</b></figcaption><div class="pair-imgs">
          <figure>${shotImg(a, T, 'thumb')}<figcaption>${t}</figcaption></figure>
          <figure>${shotImg(a, C, 'thumb')}<figcaption>${c}</figcaption></figure></div></figure>`).join('') + '</div>'
    : '<div class="lb-grid">' + lbApps.map((a, i) =>
        `<figure data-i="${i}">${shotImg(a, T, 'thumb')}<figcaption>${esc(a)}</figcaption></figure>`).join('') + '</div>';
}
function showFull(i) {
  lbIndex = (i + lbApps.length) % lbApps.length;
  const a = lbApps[lbIndex], t = lbTile.dataset.theme, c = lbCmp.value;
  lbBody.innerHTML = `<div class="lb-nav"><button type="button" data-go="grid">&larr; All apps</button>
    <span>${esc(a)} <small>(${lbIndex + 1} of ${lbApps.length} · arrow keys)</small></span></div>`
    + (c ? `<div class="lb-sbs"><figure>${shotImg(a, t, 'full', 'class="lb-full"')}<figcaption>${esc(t)}</figcaption></figure>
            <figure>${shotImg(a, c, 'full', 'class="lb-full"')}<figcaption>${esc(c)}</figcaption></figure></div>`
         : shotImg(a, t, 'full', 'class="lb-full"'));
}
lbCmp.addEventListener('change', () => {
  const app = lbIndex >= 0 ? lbApps[lbIndex] : null;
  setApps();
  const j = app ? lbApps.indexOf(app) : -1;
  j >= 0 ? showFull(j) : showGrid();
});
function closeLightbox() { lb.hidden = true; if (lbTile) lbTile.focus({preventScroll: true}); }
lbBody.addEventListener('click', ev => {
  const f = ev.target.closest('figure[data-i]'); if (f) return showFull(+f.dataset.i);
  if (ev.target.closest('[data-go="grid"]')) showGrid();
});
$('#lb-close').addEventListener('click', closeLightbox);
$('#lb-hide').addEventListener('click', () => { if (lbTile) toggleHide(lbTile); });
$('#lb-similar').addEventListener('click', ev => {
  const c = ev.target.closest('[data-similar]');
  if (c && byName[c.dataset.similar]) openLightbox(byName[c.dataset.similar]);
});
$('#lb-apply').addEventListener('click', () => { applyTheme(lbTile.dataset.theme); closeLightbox(); });
// A link that opens the picker dressed in this theme without applying it.
$('#lb-share').addEventListener('click', async () => {
  const url = `${location.origin}/?preview=${encodeURIComponent(lbTile.dataset.theme)}#themes`;
  const btn = $('#lb-share');
  try {
    await navigator.clipboard.writeText(url);
    btn.textContent = 'Copied';
  } catch (e) {                                  // no clipboard access: show the link instead
    const msg = $('#msg'); msg.textContent = `Link: ${url}`; msg.hidden = false;
    btn.textContent = 'See link above';
  }
  setTimeout(() => { btn.textContent = 'Copy link'; }, 1600);
});

// /?preview=<theme>: the banner's "Apply it" is a plain form (works without
// JavaScript); here it applies in place and drops the preview from the URL.
const previewForm = $('#preview-banner');
if (previewForm) previewForm.addEventListener('submit', async ev => {
  ev.preventDefault();
  const theme = previewForm.querySelector('button[name=theme]').value;
  await applyTheme(theme);
  // Only once it is really live: on a failure the page still wears the
  // previewed theme, and the banner is what says it isn't applied.
  if ($('.current b').textContent !== theme) return;
  previewForm.remove();
  history.replaceState(null, '', '/' + location.hash);
});
lb.addEventListener('click', ev => { if (ev.target === lb) closeLightbox(); });

// --- keyboard -------------------------------------------------------------
function moveVertical(cur, dir) {
  const r = cur.getBoundingClientRect(), cx = r.left + r.width / 2;
  let best = null, score = Infinity;
  for (const b of visibleTiles()) {
    const q = b.getBoundingClientRect(), dy = (q.top - r.top) * dir;
    if (dy <= 5) continue;
    const s = dy * 1000 + Math.abs(q.left + q.width / 2 - cx);   // nearest row, then column
    if (s < score) { score = s; best = b; }
  }
  return best;
}
document.addEventListener('keydown', ev => {
  if (!lb.hidden) {
    if (ev.target === lbCmp && ev.key !== 'Escape') return;      // arrows belong to the menu
    if (ev.key === 'Escape') { ev.preventDefault(); lbIndex >= 0 ? showGrid() : closeLightbox(); }
    else if (lbIndex >= 0 && ev.key === 'ArrowRight') showFull(lbIndex + 1);
    else if (lbIndex >= 0 && ev.key === 'ArrowLeft') showFull(lbIndex - 1);
    return;
  }
  const typing = ev.target.matches('input, select, textarea');
  if (ev.key === 'Escape' && ev.target === ctl.q) {
    ctl.q.value = ''; state.q = ''; refresh(); ctl.q.blur(); return;
  }
  if (typing || ev.ctrlKey || ev.metaKey || ev.altKey) return;
  if ((ev.key === 'u' || ev.key === 'U') && !$('#undo').hidden) { $('#undo').click(); return; }
  if (currentTab !== 'themes') return;             // the rest act on the theme grid
  const cur = document.activeElement && document.activeElement.classList.contains('theme-btn')
              ? document.activeElement : null;
  if (ev.key === '/') { ev.preventDefault(); ctl.q.focus(); ctl.q.select(); return; }
  if (ev.key === 'r' || ev.key === 'R') { surprise(); return; }
  if ((ev.key === 'l' || ev.key === 'L') && cur) { flipForm(cur, cur.dataset.mode === 'light' ? 'dark' : 'light'); return; }
  if ((ev.key === 'p' || ev.key === 'P') && cur) { openLightbox(cur); return; }
  if ((ev.key === 'f' || ev.key === 'F') && cur) { toggleFav(cur); return; }
  if ((ev.key === 'h' || ev.key === 'H') && cur) { toggleHide(cur); return; }
  if (!ev.key.startsWith('Arrow')) return;
  ev.preventDefault();
  const list = visibleTiles();
  if (!list.length) return;
  let next;
  if (!cur) next = list.find(b => b.classList.contains('active')) || list[0];
  else if (ev.key === 'ArrowRight') next = list[list.indexOf(cur) + 1];
  else if (ev.key === 'ArrowLeft') next = list[list.indexOf(cur) - 1];
  else next = moveVertical(cur, ev.key === 'ArrowDown' ? 1 : -1);
  if (next) { next.focus({preventScroll: true}); next.scrollIntoView({block: 'nearest'}); }
});

// --- favourites ---------------------------------------------------------------
async function postJSON(url, body) {
  const res = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'},
                                body: JSON.stringify(body)});
  return res.json();
}
async function toggleHide(btn) {
  const orig = originalOf(btn), on = orig.dataset.hidden !== '1';
  const data = await postJSON('/api/hide', {theme: orig.dataset.theme, on});
  if (!data.ok) return;
  for (const b of [orig, byName[orig.dataset.twin]]) if (b) b.dataset.hidden = on ? '1' : '0';
  if (lbTile && originalOf(lbTile) === orig) $('#lb-hide').textContent = on ? 'Unhide' : 'Hide';
  refresh();
}
function showRating(btn) {
  $('#lb-like').setAttribute('aria-pressed', String(btn.dataset.rating === '1'));
  $('#lb-dislike').setAttribute('aria-pressed', String(btn.dataset.rating === '-1'));
}
async function rate(btn, value) {
  const rating = btn.dataset.rating === String(value) ? 0 : value;       // pressing it again clears it
  const data = await postJSON('/api/rate', {theme: btn.dataset.theme, rating});
  if (!data.ok) return;
  btn.dataset.rating = String(rating);
  if (lbTile === btn) showRating(btn);
  updateSurprise();
}
$('#lb-like').addEventListener('click', () => { if (lbTile) rate(lbTile, 1); });
$('#lb-dislike').addEventListener('click', () => { if (lbTile) rate(lbTile, -1); });
async function toggleFav(btn) {
  const on = btn.dataset.fav !== '1';
  const data = await postJSON('/api/favourite', {theme: btn.dataset.theme, on});
  if (!data.ok) return;
  btn.dataset.fav = on ? '1' : '0';
  const star = btn.querySelector('.star');
  star.classList.toggle('on', on); star.innerHTML = on ? '&#9733;' : '&#9734;';
  refresh();
}

// --- preview mode: swatches, or one app's real screenshot per tile ------------
function applyPreview() {
  document.body.classList.toggle('shots', !!state.preview);
  for (const b of tiles) {
    const old = b.querySelector('.tile-shot'); if (old) old.remove();
    const sw = b.querySelector('.swatch');
    const has = state.preview && (b.dataset.shots || '').split(' ').includes(state.preview);
    if (has) {
      const img = document.createElement('img');
      img.className = 'tile-shot'; img.loading = 'lazy'; img.alt = '';
      img.src = `/shots/thumb/${state.preview}_${encodeURIComponent(b.dataset.theme)}.jpg`;
      b.insertBefore(img, sw);
    }
    if (sw) sw.hidden = !!has;
  }
}

// --- apps: per-app pins and coverage ------------------------------------------
for (const sel of $$('.pin')) {
  sel.value = sel.dataset.current || '';
  sel.addEventListener('change', async () => {
    const data = await postJSON('/api/override', {app: sel.dataset.app, theme: sel.value});
    const msg = $('#msg'); msg.textContent = data.message; msg.hidden = false;
    if (!data.ok) sel.value = sel.dataset.current || '';
    else { sel.dataset.current = sel.value; setTimeout(runCoverage, 3500); }
    sel.closest('.app-card').classList.toggle('pinned', !!sel.value);
    updateAppsView();
  });
  sel.closest('.app-card').classList.toggle('pinned', !!sel.value);
}

// The apps list shows what needs attention -- pinned apps and apps not
// getting their theme -- and folds the rest ("quiet") behind one button.
// Without a coverage result, or without JavaScript, every app shows.
let showAllApps = false;
function updateAppsView() {
  const cards = $$('.app-card'), grid = $('#app-grid'), row = $('#apps-toggle-row'), btn = $('#apps-toggle');
  const quiet = cards.filter(c => c.classList.contains('quiet') && !c.classList.contains('pinned')).length;
  grid.classList.toggle('only-notable', !showAllApps && quiet > 0);
  row.hidden = quiet === 0;
  btn.textContent = showAllApps ? 'Show only pinned and failing apps'
    : `Show all ${cards.length} apps (${quiet} following the live theme, all fine)`;
  btn.setAttribute('aria-expanded', String(showAllApps));
}
$('#apps-toggle').addEventListener('click', () => { showAllApps = !showAllApps; updateAppsView(); });
async function runCoverage() {
  const sum = $('#cov-summary'), pill = $('#cov-pill');
  sum.textContent = 'Checking which apps received the theme...';
  pill.textContent = 'Coverage \u2026'; pill.className = 'cov-pill';
  let data;
  try { data = await (await fetch('/api/coverage')).json(); }
  catch (e) { sum.textContent = 'Coverage check failed: ' + e; pill.textContent = 'Coverage ?'; return; }
  const bad = data.results.filter(r => r.state !== 'ok');
  pill.textContent = `Coverage ${data.ok} / ${data.total}`;
  pill.className = 'cov-pill ' + (bad.length ? 'bad' : 'good');
  sum.innerHTML = bad.length
    ? `Coverage: <span class="bad">${esc(data.ok)} of ${esc(data.total)} apps</span> got their theme. `
      + 'Not themed: ' + bad.map(r => `<b>${esc(r.app)}</b> (${esc(r.detail || r.state)})`).join(', ')
      + ' &middot; <a href="#" id="cov-open">details</a>'
    : `Coverage: <span class="good">all ${esc(data.total)} apps</span> are showing their theme.`;
  const open = $('#cov-open');
  if (open) open.addEventListener('click', e => { e.preventDefault(); location.hash = '#apps'; });
  for (const r of data.results) {
    const cell = document.querySelector(`.cov[data-app="${CSS.escape(r.app)}"]`);
    if (!cell) continue;
    cell.closest('.app-card').classList.toggle('quiet', r.state === 'ok' && !r.pinned);
    cell.innerHTML = r.state === 'ok'
      ? `<span class="ok">ok</span> ${esc(r.expected)}${r.pinned ? ' (pinned)' : ''}`
      : `<span class="bad">${esc(r.state)}</span> ${esc(r.detail)}`;
  }
  updateAppsView();
}
$('#cov-run').addEventListener('click', runCoverage);

// --- theme editor -----------------------------------------------------------
// Petio's spinner is a white SVG recoloured by a CSS filter chain. This is the
// same SPSA solver tools/css_filter_solver.py implements (Barrett Sonntag's
// algorithm), run in the browser so the picker container needs no numpy.
class FColor {
  constructor(r, g, b) { this.set(r, g, b); }
  set(r, g, b) { this.r = this.c(r); this.g = this.c(g); this.b = this.c(b); }
  c(v) { return v > 255 ? 255 : v < 0 ? 0 : v; }
  mul(m) { const r = this.c(this.r*m[0]+this.g*m[1]+this.b*m[2]), g = this.c(this.r*m[3]+this.g*m[4]+this.b*m[5]),
                 b = this.c(this.r*m[6]+this.g*m[7]+this.b*m[8]); this.r = r; this.g = g; this.b = b; }
  hueRotate(a) { a = a / 180 * Math.PI; const s = Math.sin(a), c = Math.cos(a);
    this.mul([0.213+c*0.787-s*0.213, 0.715-c*0.715-s*0.715, 0.072-c*0.072+s*0.928,
              0.213-c*0.213+s*0.143, 0.715+c*0.285+s*0.140, 0.072-c*0.072-s*0.283,
              0.213-c*0.213-s*0.787, 0.715-c*0.715+s*0.715, 0.072+c*0.928+s*0.072]); }
  sepia(v) { this.mul([0.393+0.607*(1-v), 0.769-0.769*(1-v), 0.189-0.189*(1-v), 0.349-0.349*(1-v),
    0.686+0.314*(1-v), 0.168-0.168*(1-v), 0.272-0.272*(1-v), 0.534-0.534*(1-v), 0.131+0.869*(1-v)]); }
  saturate(v) { this.mul([0.213+0.787*v, 0.715-0.715*v, 0.072-0.072*v, 0.213-0.213*v, 0.715+0.285*v,
    0.072-0.072*v, 0.213-0.213*v, 0.715-0.715*v, 0.072+0.928*v]); }
  linear(sl, ic = 0) { this.r = this.c(this.r*sl+ic*255); this.g = this.c(this.g*sl+ic*255); this.b = this.c(this.b*sl+ic*255); }
  invert(v) { this.r = this.c((v+this.r/255*(1-2*v))*255); this.g = this.c((v+this.g/255*(1-2*v))*255);
              this.b = this.c((v+this.b/255*(1-2*v))*255); }
  hsl() { const r = this.r/255, g = this.g/255, b = this.b/255, mx = Math.max(r,g,b), mn = Math.min(r,g,b);
    let h = 0, s = 0; const l = (mx+mn)/2;
    if (mx !== mn) { const d = mx-mn; s = l > 0.5 ? d/(2-mx-mn) : d/(mx+mn);
      h = mx === r ? (g-b)/d+(g<b?6:0) : mx === g ? (b-r)/d+2 : (r-g)/d+4; h /= 6; }
    return {h: h*100, s: s*100, l: l*100}; }
}
function solveFilter(hex) {
  const t = new FColor(parseInt(hex.slice(1,3),16), parseInt(hex.slice(3,5),16), parseInt(hex.slice(5,7),16));
  const th = t.hsl(), col = new FColor(0, 0, 0);
  const loss = f => { col.set(255,255,255); col.invert(f[0]/100); col.sepia(f[1]/100); col.saturate(f[2]/100);
    col.hueRotate(f[3]*3.6); col.linear(f[4]/100); col.linear(f[5]/100, -(0.5*f[5]/100)+0.5); const h = col.hsl();
    return Math.abs(col.r-t.r)+Math.abs(col.g-t.g)+Math.abs(col.b-t.b)+Math.abs(h.h-th.h)+Math.abs(h.s-th.s)+Math.abs(h.l-th.l); };
  const fix = (v, i) => { const mx = i === 2 ? 7500 : (i === 4 || i === 5) ? 200 : 100;
    if (i === 3) { if (v > mx) v %= mx; else if (v < 0) v = mx + v % mx; } else v = Math.min(mx, Math.max(0, v)); return v; };
  const spsa = (A, a, c, vals, iters) => { let best = null, bestL = Infinity; const d = [], hi = [], lo = [];
    for (let k = 0; k < iters; k++) { const ck = c / Math.pow(k+1, 1/6);
      for (let i = 0; i < 6; i++) { d[i] = Math.random() > 0.5 ? 1 : -1; hi[i] = vals[i]+ck*d[i]; lo[i] = vals[i]-ck*d[i]; }
      const ld = loss(hi) - loss(lo);
      for (let i = 0; i < 6; i++) vals[i] = fix(vals[i] - a[i]/(A+k+1) * ld/(2*ck)*d[i], i);
      const l = loss(vals); if (l < bestL) { best = vals.slice(); bestL = l; } }
    return {values: best, loss: bestL}; };
  let best = {loss: Infinity};
  for (let run = 0; run < 4 && best.loss > 1; run++) {
    let wide = {loss: Infinity};
    for (let i = 0; wide.loss > 25 && i < 3; i++) {
      const r = spsa(5, [60,180,18000,600,1.2,1.2], 15, [50,20,3750,50,100,100], 1000);
      if (r.loss < wide.loss) wide = r; }
    const A1 = wide.loss + 1;
    const narrow = spsa(wide.loss, [0.25*A1,0.25*A1,A1,0.25*A1,0.2*A1,0.2*A1], 2, wide.values, 500);
    if (narrow.loss < best.loss) best = narrow;
  }
  const f = best.values, r = (i, m = 1) => Math.round(f[i]*m);
  return `invert(${r(0)}%) sepia(${r(1)}%) saturate(${r(2)}%) hue-rotate(${r(3,3.6)}deg) brightness(${r(4)}%) contrast(${r(5)}%)`;
}

const edInputs = $$('.ed [data-f]');
function edGet() {
  const f = {};
  for (const el of edInputs) if (el.classList.contains('hex')) f[el.dataset.f] = el.value.trim().toLowerCase();
  return f;
}
function edSet(vals) {
  for (const el of edInputs) if (vals[el.dataset.f]) el.value = vals[el.dataset.f];
  if (vals.page_bg2) { $('#ed-gradient').checked = true; $('#ed-bg2').value = vals.page_bg2; }
  else $('#ed-gradient').checked = false;
  edUpdate();
}
function hexLum(h) {
  const lin = c => { c /= 255; return c <= 0.04045 ? c/12.92 : Math.pow((c+0.055)/1.055, 2.4); };
  return 0.2126*lin(parseInt(h.slice(1,3),16)) + 0.7152*lin(parseInt(h.slice(3,5),16)) + 0.0722*lin(parseInt(h.slice(5,7),16));
}
function hexCon(a, b) { const x = hexLum(a), y = hexLum(b); return (Math.max(x,y)+0.05)/(Math.min(x,y)+0.05); }
const isHex = v => /^#[0-9a-f]{6}$/.test(v);

// --- contrast fix: nearest colour that passes, same hue and saturation ------
function hexToHsl(h) {
  const r = parseInt(h.slice(1,3),16)/255, g = parseInt(h.slice(3,5),16)/255, b = parseInt(h.slice(5,7),16)/255;
  const mx = Math.max(r,g,b), mn = Math.min(r,g,b), l = (mx+mn)/2;
  let hue = 0, s = 0;
  if (mx !== mn) {
    const d = mx-mn; s = l > 0.5 ? d/(2-mx-mn) : d/(mx+mn);
    hue = mx === r ? (g-b)/d+(g<b?6:0) : mx === g ? (b-r)/d+2 : (r-g)/d+4; hue /= 6;
  }
  return [hue, s, l];
}
function hslToHex(h, s, l) {
  const f = n => { const k = (n + h*12) % 12, a = s * Math.min(l, 1-l);
    return Math.round(255 * (l - a * Math.max(-1, Math.min(k-3, 9-k, 1)))).toString(16).padStart(2, '0'); };
  return '#' + f(0) + f(8) + f(4);
}
// Move only the lightness, away from the background, by the least that
// reaches `min`; try the other direction if that one runs out of room. The
// colour keeps its hue, so the theme still looks like itself.
function fixContrast(fg, bg, min) {
  const [h, s, l0] = hexToHsl(fg);
  const lighter = hexLum(fg) >= hexLum(bg);
  for (const up of [lighter, !lighter]) {
    const end = up ? 1 : 0;
    if (hexCon(hslToHex(h, s, end), bg) < min) continue;
    let lo = l0, hi = end;                      // lo fails, hi passes
    for (let i = 0; i < 30; i++) {
      const mid = (lo + hi) / 2;
      if (hexCon(hslToHex(h, s, mid), bg) >= min) hi = mid; else lo = mid;
    }
    return hslToHex(h, s, hi);
  }
  return null;
}
function edUpdate() {
  const f = edGet(), pv = $('#ed-preview');
  const grad = $('#ed-gradient').checked;
  pv.style.setProperty('--pv-page', grad && isHex(f.page_bg)
    ? `linear-gradient(${$('#ed-angle').value}deg, ${f.page_bg}, ${$('#ed-bg2').value})` : f.page_bg);
  const map = {panel_bg: '--pv-panel', text: '--pv-text', text_hover: '--pv-text-hover', muted: '--pv-muted',
    link: '--pv-link', link_hover: '--pv-link-hover', button: '--pv-button', button_hover: '--pv-button-hover',
    button_text: '--pv-button-text', queue: '--pv-queue'};
  for (const [k, v] of Object.entries(map)) if (isHex(f[k])) pv.style.setProperty(v, f[k]);
  const rows = [['Body text on panel', 'text', 'panel_bg', 4.5], ['Muted text on panel', 'muted', 'panel_bg', 3],
                ['Button label on button', 'button_text', 'button', 3], ['Link on panel', 'link', 'panel_bg', 3]];
  $('#ed-contrast').innerHTML = rows.map(([lab, a, b, min]) => {
    if (!isHex(f[a]) || !isHex(f[b])) return '';
    const c = hexCon(f[a], f[b]);
    const fix = c >= min ? null : fixContrast(f[a], f[b], min);
    return `<li><span class="${c >= min ? 'ok' : 'bad'}">${c.toFixed(1)}:1</span> ${lab} (want ${min}:1)`
      + (fix ? ` <button type="button" class="ed-fix" data-f="${a}" data-v="${fix}" title="Same hue, lightness adjusted">`
               + `<i style="background:${fix}"></i>Use ${fix}</button>` : '') + '</li>';
  }).join('');
  if (typeof updateTwin === 'function') updateTwin();
}
for (const el of edInputs) {
  el.addEventListener('input', () => {
    const twin = $$(`.ed [data-f="${el.dataset.f}"]`).find(x => x !== el);
    const v = el.value.trim().toLowerCase();
    if (twin && isHex(v)) twin.value = v;
    edUpdate();
  });
}
for (const id of ['#ed-gradient', '#ed-bg2', '#ed-angle']) $(id).addEventListener('input', edUpdate);
$('#ed-contrast').addEventListener('click', ev => {
  const b = ev.target.closest('.ed-fix'); if (!b) return;
  for (const el of $$(`.ed [data-f="${b.dataset.f}"]`)) el.value = b.dataset.v;
  edUpdate();
});
// --- a theme from an image -----------------------------------------------------
// Everything happens in the browser: the image is drawn small onto a canvas,
// its colours clustered (k-means, seeded by luminance so the same image always
// gives the same theme), and the clusters mapped onto the editor's fields.
// Surfaces come from the image's big areas, accents from its most vivid ones,
// and every text colour then goes through fixContrast, so the result starts
// out readable. Nothing is uploaded; saving works exactly as for any edit.
const rgbHex = c => '#' + c.map(v => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, '0')).join('');
function clusters(px, k = 6) {
  const lum = p => 0.2126*p[0] + 0.7152*p[1] + 0.0722*p[2];
  const sorted = [...px].sort((a, b) => lum(a) - lum(b));
  let cs = Array.from({length: k}, (_, i) => sorted[Math.floor((i + 0.5) * sorted.length / k)].slice());
  let assign = new Array(px.length).fill(0);
  for (let it = 0; it < 12; it++) {
    for (let i = 0; i < px.length; i++) {
      let best = 0, bd = Infinity;
      for (let j = 0; j < k; j++) {
        const d = (px[i][0]-cs[j][0])**2 + (px[i][1]-cs[j][1])**2 + (px[i][2]-cs[j][2])**2;
        if (d < bd) { bd = d; best = j; }
      }
      assign[i] = best;
    }
    const sum = cs.map(() => [0, 0, 0, 0]);
    px.forEach((p, i) => { const s = sum[assign[i]]; s[0] += p[0]; s[1] += p[1]; s[2] += p[2]; s[3]++; });
    cs = cs.map((c, j) => sum[j][3] ? [sum[j][0]/sum[j][3], sum[j][1]/sum[j][3], sum[j][2]/sum[j][3]] : c);
  }
  const n = cs.map(() => 0); assign.forEach(a => n[a]++);
  return cs.map((c, j) => ({hex: rgbHex(c), share: n[j] / px.length})).filter(c => c.share > 0);
}
function themeFromPixels(px) {
  const cl = clusters(px).map(c => { const [h, s, l] = hexToHsl(c.hex); return {...c, h, s, l}; });
  const avgL = cl.reduce((a, c) => a + c.l * c.share, 0);
  const dark = avgL < 0.5;
  const bySize = [...cl].sort((a, b) => b.share - a.share);
  const byVivid = [...cl].sort((a, b) => (b.s * Math.sqrt(b.share)) - (a.s * Math.sqrt(a.share)));
  const surf = (c, l) => hslToHex(c.h, Math.min(c.s, dark ? 0.45 : 0.3), l);
  const base = bySize[0], second = bySize.find(c => Math.abs(c.h - base.h) > 0.04 && c.share > 0.12) || null;
  const page = surf(base, dark ? Math.min(base.l, 0.12) : Math.max(base.l, 0.94));
  const panel = surf(base, dark ? Math.min(base.l, 0.12) + 0.06 : 0.985);
  // A colourless image has no real hue (grey reads as hue 0 = red): fall back
  // to a calm blue rather than invent a colour it doesn't have.
  const grey = {h: 0.6, s: 0.5, share: 1};
  const acc = byVivid[0].s >= 0.12 ? byVivid[0] : grey;
  const acc2 = byVivid.find(c => c.s >= 0.12 && Math.abs(c.h - acc.h) > 0.08) || acc;
  const button = hslToHex(acc.h, Math.max(acc.s, 0.45), dark ? 0.6 : 0.45);
  const [bh, bs, bl] = hexToHsl(button);
  const buttonText = hexCon('#ffffff', button) >= hexCon('#11141b', button) ? '#ffffff' : '#11141b';
  const link = fixContrast(hslToHex(acc2.h, Math.max(acc2.s, 0.5), dark ? 0.72 : 0.38), panel, 4.5) || buttonText;
  const [lh, ls, ll] = hexToHsl(link);
  const text = fixContrast(hslToHex(base.h, 0.12, dark ? 0.9 : 0.15), panel, 7) || (dark ? '#ffffff' : '#000000');
  const muted = fixContrast(hslToHex(base.h, 0.1, dark ? 0.62 : 0.42), panel, 4.5) || text;
  // The *arr queue colour must not be orange/yellow (it would read as an
  // error): a green-to-blue colour from the image if there is one, else teal.
  const q = cl.filter(c => c.h >= 0.25 && c.h <= 0.7 && c.s > 0.25).sort((a, b) => b.s - a.s)[0];
  const queue = q ? hslToHex(q.h, Math.max(q.s, 0.5), 0.45) : '#1fa88f';
  const out = {page_bg: page, panel_bg: panel, button, button_hover: hslToHex(bh, bs, Math.min(bl + 0.08, 0.9)),
    button_text: buttonText, link, link_hover: hslToHex(lh, ls, dark ? Math.min(ll + 0.08, 0.95) : Math.max(ll - 0.08, 0.05)),
    text, text_hover: dark ? '#ffffff' : '#000000', muted, queue};
  if (second) out.page_bg2 = surf(second, dark ? Math.min(second.l, 0.16) : Math.max(second.l, 0.9));
  return out;
}
$('#ed-image').addEventListener('change', async () => {
  const file = $('#ed-image').files[0], st = $('#ed-image-status');
  if (!file) return;
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    await new Promise((ok, fail) => { img.onload = ok; img.onerror = () => fail(new Error('not an image this browser can read')); img.src = url; });
    const w = 96, h = Math.max(1, Math.round(96 * img.naturalHeight / img.naturalWidth));
    const cv = document.createElement('canvas'); cv.width = w; cv.height = h;
    const ctx = cv.getContext('2d'); ctx.drawImage(img, 0, 0, w, h);
    const d = ctx.getImageData(0, 0, w, h).data, px = [];
    for (let i = 0; i < d.length; i += 4) if (d[i+3] > 200) px.push([d[i], d[i+1], d[i+2]]);
    if (px.length < 16) throw new Error('the image has too few opaque pixels');
    edSet(themeFromPixels(px));
    if (!$('#ed-name').value) {
      const slug = file.name.replace(/\.[^.]*$/, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40);
      if (slug.length >= 2) { $('#ed-name').value = slug; $('#ed-title').value = slug.replace(/-/g, ' ').slice(0, 40); }
    }
    st.textContent = `Colours taken from ${file.name}. Adjust anything, then save.`;
  } catch (e) {
    st.textContent = 'Could not read that image: ' + e.message;
  } finally {
    URL.revokeObjectURL(url);
  }
});

let edSeq = 0;
async function edLoad() {
  // Only the newest request may fill the form: opening the panel auto-loads
  // the live theme, and a quick "Load" of another theme could otherwise be
  // overwritten when the slower first response lands.
  const mine = ++edSeq, t = $('#ed-base').value;
  const vals = await (await fetch('/api/theme-vars?theme=' + encodeURIComponent(t))).json();
  if (mine === edSeq && !vals.error) edSet(vals);
}
$('#ed-load').addEventListener('click', edLoad);
// The editor loads the live theme's colours the first time its tab opens.
$('#ed-save').addEventListener('click', async () => {
  const f = edGet(), st = $('#ed-status');
  if (!isHex(f.button)) { st.textContent = 'Set a button colour first.'; return; }
  st.textContent = 'Computing the spinner filter...';
  await new Promise(r => setTimeout(r, 30));          // let the message paint
  const body = Object.assign({}, f, {name: $('#ed-name').value.trim(), title: $('#ed-title').value.trim(),
    base: $('#ed-base').value, gradient: $('#ed-gradient').checked, page_bg2: $('#ed-bg2').value,
    angle: +$('#ed-angle').value, spinner: solveFilter(f.button)});
  const data = await postJSON('/api/editor/save', body);
  st.textContent = data.message;
  if (!data.ok) return;
  const name = body.name, started = Date.now();
  const poll = async () => {
    const s = await (await fetch('/api/editor/status?name=' + encodeURIComponent(name))).json();
    if (s.state === 'deployed') { st.innerHTML = `Deployed. <a href="/">Reload</a> to see <b>${esc(name)}</b> in the list.`; return; }
    if (s.state === 'failed') { st.textContent = 'Deploy failed: ' + (s.detail || 'see theme-worker log'); return; }
    if (Date.now() - started > 240000) { st.textContent = 'Still queued after 4 minutes -- is the deploy job running?'; return; }
    setTimeout(poll, 4000);
  };
  setTimeout(poll, 4000);
});

// --- day/night schedule -------------------------------------------------------
function schSummary(s) {
  if (!s.enabled) return 'off';
  if (!s.slot) return 'on, but a theme is missing';
  return `on${s.sun ? ' · by the sun' : ''} · now ${s.slot} (${s[s.slot]}) · next: ${s.next_theme} at ${s.next_at}`;
}
function rotateSummary(s) {
  if (!s.rotate_enabled) return 'off';
  const pool = s.rotate_mode === 'list' ? 'your list' : s.rotate_pool === 'favourites' ? 'favourites' : 'all themes';
  return `on · every ${s.rotate_every} hour${s.rotate_every === 1 ? '' : 's'} from ${pool} (${s.rotate_pool_size || 0})`
    + (s.rotate_next ? ` · next ${s.rotate_next}` : '');
}
// After any schedule save: every card's summary and on/off box, since
// turning one schedule on turns the others off.
function showSchedules(s) {
  $('#sch-state').textContent = schSummary(s);
  $('#daily-state').textContent = dailySummary(s);
  $('#rotate-state').textContent = rotateSummary(s);
  $('#sch-enabled').checked = s.enabled;
  $('#daily-enabled').checked = s.daily_enabled;
  $('#rotate-enabled').checked = s.rotate_enabled;
  $('#sch-sun-today').textContent = s.sun_today || '';
}
const sunRows = () => document.querySelectorAll('.sun-row').forEach(r => { r.hidden = !$('#sch-sun').checked; });
$('#sch-sun').addEventListener('change', sunRows);
sunRows();
$('#sch-save').addEventListener('click', async () => {
  const st = $('#sch-status');
  st.textContent = 'Saving...';
  const data = await postJSON('/api/schedule', {
    enabled: $('#sch-enabled').checked, day: $('#sch-day').value, night: $('#sch-night').value,
    day_at: $('#sch-day-at').value, night_at: $('#sch-night-at').value,
    sun: $('#sch-sun').checked, lat: $('#sch-lat').value, lon: $('#sch-lon').value,
    day_offset: $('#sch-day-off').value, night_offset: $('#sch-night-off').value});
  st.textContent = data.message;
  if (!data.ok) return;
  showSchedules(data.schedule);
  if (data.theme !== data.previous) markApplied(data.previous, data.theme, data.css);
});
function dailySummary(s) {
  if (!s.daily_enabled) return 'off';
  const pool = s.daily_pool === 'favourites' ? 'favourites' : 'all themes';
  return `on · from ${pool} (${s.daily_pool_size || 0}) · next pick ${s.daily_next || ''}`;
}
$('#daily-save').addEventListener('click', async () => {
  const st = $('#daily-status');
  st.textContent = 'Saving...';
  const data = await postJSON('/api/daily', {
    enabled: $('#daily-enabled').checked, at: $('#daily-at').value, pool: $('#daily-pool').value});
  st.textContent = data.message;
  if (!data.ok) return;
  showSchedules(data.schedule);
  if (data.theme !== data.previous) markApplied(data.previous, data.theme, data.css);
});
// The playlist: an ordered list built here, sent whole on Save.
const rotateItem = t => {
  const li = document.createElement('li');
  li.dataset.theme = t;
  li.innerHTML = `<span>${esc(t)}</span><button type="button" data-move="up" aria-label="Move ${esc(t)} up">&uarr;</button>`
    + `<button type="button" data-move="down" aria-label="Move ${esc(t)} down">&darr;</button>`
    + `<button type="button" data-move="del" aria-label="Remove ${esc(t)}">&times;</button>`;
  return li;
};
const rotateMode = () => {
  const list = $('#rotate-mode').value === 'list';
  $('#rotate-list-box').hidden = !list;
  $('#rotate-pool').disabled = list;
};
$('#rotate-mode').addEventListener('change', rotateMode);
rotateMode();
$('#rotate-add-btn').addEventListener('click', () => {
  const t = $('#rotate-add').value, ol = $('#rotate-list');
  if (t && ![...ol.children].some(li => li.dataset.theme === t)) ol.appendChild(rotateItem(t));
});
$('#rotate-list').addEventListener('click', ev => {
  const b = ev.target.closest('button[data-move]'); if (!b) return;
  const li = b.closest('li');
  if (b.dataset.move === 'del') li.remove();
  else if (b.dataset.move === 'up' && li.previousElementSibling) li.parentNode.insertBefore(li, li.previousElementSibling);
  else if (b.dataset.move === 'down' && li.nextElementSibling) li.parentNode.insertBefore(li.nextElementSibling, li);
});
$('#rotate-save').addEventListener('click', async () => {
  const st = $('#rotate-status');
  st.textContent = 'Saving...';
  const data = await postJSON('/api/rotate', {
    enabled: $('#rotate-enabled').checked, every: +$('#rotate-every').value, pool: $('#rotate-pool').value,
    mode: $('#rotate-mode').value, list: [...$('#rotate-list').children].map(li => li.dataset.theme)});
  st.textContent = data.message;
  if (!data.ok) return;
  showSchedules(data.schedule);
  if (data.theme !== data.previous) markApplied(data.previous, data.theme, data.css);
});

// --- the other-mode twin, live ------------------------------------------------
// The same maths as theme-park-themes' tools/make_variants.py (build()), on the
// editor's flat fields: surfaces flip lightness around the page, keeping hue
// with softened chroma; text is inverted then moved only as far as 7:1 (muted
// 4.5:1) on every panel and page colour; accents keep their colour and move
// only as far as contrast needs; the button label is re-picked. On save, the
// real twin comes from the Python (the host worker, or picker/twins.py).
function fromOklab(L, a, b) {
  L = Math.min(1, Math.max(0, L));
  const raw = (k) => {
    const l = (L + 0.3963377774*a*k + 0.2158037573*b*k) ** 3, m = (L - 0.1055613458*a*k - 0.0638541728*b*k) ** 3,
          s = (L - 0.0894841775*a*k - 1.2914855480*b*k) ** 3;
    return [4.0767416621*l - 3.3077115913*m + 0.2309699292*s, -1.2684380046*l + 2.6097574011*m - 0.3413193965*s,
            -0.0041960863*l - 0.7034186147*m + 1.7076147010*s];
  };
  const inGamut = c => c.every(x => x >= -0.0005 && x <= 1.0005);
  let k = 1;
  if (!inGamut(raw(1))) {                          // reduce chroma, never lightness or hue
    let lo = 0, hi = 1;
    for (let i = 0; i < 24; i++) { const mid = (lo + hi) / 2; if (inGamut(raw(mid))) lo = mid; else hi = mid; }
    k = lo;
  }
  const gam = x => { x = Math.min(1, Math.max(0, x)); return 255 * (x <= 0.0031308 ? 12.92 * x : 1.055 * x ** (1 / 2.4) - 0.055); };
  return rgbHex(raw(k).map(gam));
}
// Lightness moved (in OKLab) only as far as needed for `need`:1 on every bg.
function fixLab(hex, bgs, need, startL) {
  const [L0raw, a, b] = oklab(hex), L0 = startL === undefined ? L0raw : startL;
  const worst = h => Math.min(...bgs.map(g => hexCon(h, g)));
  const cur = fromOklab(L0, a, b);
  if (worst(cur) >= need) return cur;
  const meanBg = bgs.reduce((s, g) => s + hexLum(g), 0) / bgs.length;
  for (const end of (hexLum(cur) >= meanBg ? [1, 0] : [0, 1])) {
    if (worst(fromOklab(end, a, b)) < need) continue;
    let lo = L0, hi = end;
    for (let i = 0; i < 30; i++) { const mid = (lo + hi) / 2; if (worst(fromOklab(mid, a, b)) >= need) hi = mid; else lo = mid; }
    return fromOklab(hi, a, b);
  }
  return null;
}
function twinFields(f, bg2) {
  const page = [f.page_bg].concat(bg2 ? [bg2] : []);
  const L0 = page.reduce((s, h) => s + oklab(h)[0], 0) / page.length;
  const mode = page.reduce((s, h) => s + hexLum(h), 0) / page.length > 0.35 ? 'light' : 'dark';
  const target = mode === 'light' ? 'dark' : 'light';
  const surf = h => {
    const [L, a, b] = oklab(h);
    if (target === 'light') return fromOklab(Math.min(1, Math.max(0.86, 0.965 + 0.5 * (L - L0))), a * 0.6, b * 0.6);
    const k = Math.min(1, 0.08 / Math.max(1e-6, Math.hypot(a, b)));
    return fromOklab(Math.min(0.34, Math.max(0.12, 0.21 + 1.2 * (L - L0))), a * 0.8 * k, b * 0.8 * k);
  };
  const neutral = Math.hypot(...oklab(f.button).slice(1)) < 0.04;
  const btnMove = h => {
    const [L, a, b] = oklab(h), gap = Math.max(0.06, Math.abs(L - L0));
    return target === 'light' ? fromOklab(Math.max(0.55, 0.965 - 0.8 * gap), a * 0.6, b * 0.6)
                              : fromOklab(Math.min(0.5, 0.21 + 1.2 * gap), a * 0.8, b * 0.8);
  };
  const t = {page_bg: surf(f.page_bg), panel_bg: surf(f.panel_bg)};
  if (bg2) t.page_bg2 = surf(bg2);
  const bgs = [t.panel_bg, t.page_bg].concat(t.page_bg2 ? [t.page_bg2] : []);
  for (const [k, need] of [['text', 7], ['text_hover', 7], ['muted', 4.5]])
    t[k] = fixLab(f[k], bgs, need, 1 - oklab(f[k])[0]) || f[k];
  for (const k of ['button', 'button_hover'])
    t[k] = neutral ? btnMove(f[k]) : (fixLab(f[k], bgs, 3) || f[k]);
  for (const [k, need] of [['link', 4.5], ['link_hover', 4.5], ['queue', 3]]) t[k] = fixLab(f[k], bgs, need) || f[k];
  const best = () => hexCon('#ffffff', t.button) >= hexCon('#11141b', t.button) ? '#ffffff' : '#11141b';
  let lab = f.button_text;
  if (hexCon(lab, t.button) < 4.5) {
    const [L, a, b] = oklab(lab), inv = fromOklab(1 - L, a, b);
    lab = hexCon(inv, t.button) >= 4.5 ? inv : best();      // as make_variants: never a half-way colour
  }
  t.button_text = lab;
  return {target, fields: t};
}
const PV_VARS = {panel_bg: '--pv-panel', text: '--pv-text', text_hover: '--pv-text-hover', muted: '--pv-muted',
  link: '--pv-link', link_hover: '--pv-link-hover', button: '--pv-button', button_hover: '--pv-button-hover',
  button_text: '--pv-button-text', queue: '--pv-queue'};
function updateTwin() {
  const f = edGet(), box = $('#ed-twin'), label = $('#ed-twin-label');
  const ready = ['page_bg', 'panel_bg', 'button', 'button_hover', 'button_text', 'link', 'link_hover',
                 'text', 'text_hover', 'muted', 'queue'].every(k => isHex(f[k]));
  box.hidden = label.hidden = !ready;
  if (!ready) return;
  const bg2 = $('#ed-gradient').checked ? $('#ed-bg2').value : '';
  const {target, fields: t} = twinFields(f, bg2);
  box.style.setProperty('--pv-page', t.page_bg2
    ? `linear-gradient(${$('#ed-angle').value}deg, ${t.page_bg}, ${t.page_bg2})` : t.page_bg);
  for (const [k, v] of Object.entries(PV_VARS)) box.style.setProperty(v, t[k]);
  label.textContent = `Its ${target} twin` + ($('#ed-twin-note') ? ' (made automatically when you save)' : '') + ':';
}

// --- import a colour scheme ------------------------------------------------------
// Parsed here, in the browser: base16/base24 YAML, Ghostty, Kitty, Alacritty,
// Xresources, Windows Terminal JSON, iTerm2 .itermcolors, VS Code themes.
// Each becomes one palette ({bg, panel, fg, fgBright, muted, accents, button,
// buttonText, link, name}), and that maps onto the editor's fields the way
// theme-park-themes' tools/port_palette.py does: every text colour moved only
// in lightness until it reads (body 7:1, muted, links and labels 4.5:1).
// #rrggbb, also from #rgb and #rrggbbaa (VS Code themes use both).
const hex6 = v => {
  const m = /#?([0-9a-f]{8}|[0-9a-f]{6}|[0-9a-f]{3})\b/i.exec(String(v || ''));
  if (!m) return null;
  const h = m[1].length === 3 ? [...m[1]].map(c => c + c).join('') : m[1].slice(0, 6);
  return '#' + h.toLowerCase();
};
const ANSI = ['black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white'];
function fromAnsi(name, bg, fg, ansi, extra = {}) {
  const a = i => ansi[i] || ansi[i % 8] || null;
  return Object.assign({name, bg, fg, fgBright: a(15), muted: a(8) || a(7),
    red: a(1), green: a(2), yellow: a(3), blue: a(4), magenta: a(5), cyan: a(6)}, extra);
}
function parseScheme(text) {
  const src = text.trim();
  if (!src) throw new Error('Paste a scheme first.');
  // iTerm2 .itermcolors: a plist of colour dicts with 0-1 float components.
  if (src.includes('<plist') || src.includes('Ansi 0 Color')) {
    const doc = new DOMParser().parseFromString(src, 'application/xml');
    const colours = {};
    const keys = [...doc.querySelectorAll('plist > dict > key')];
    for (const k of keys) {
      const d = k.nextElementSibling; if (!d || d.tagName !== 'dict') continue;
      const comp = {};
      const ck = [...d.children];
      for (let i = 0; i < ck.length - 1; i++) if (ck[i].tagName === 'key') comp[ck[i].textContent] = parseFloat(ck[i + 1].textContent);
      if ('Red Component' in comp) colours[k.textContent] = rgbHex(['Red', 'Green', 'Blue'].map(c => comp[`${c} Component`] * 255));
    }
    const ansi = Array.from({length: 16}, (_, i) => colours[`Ansi ${i} Color`] || null);
    if (!colours['Background Color']) throw new Error('No background colour in that iTerm2 file.');
    return fromAnsi('', colours['Background Color'], colours['Foreground Color'], ansi);
  }
  // JSON: VS Code theme, or a Windows Terminal scheme.
  if (src.startsWith('{') || /^\[\s*[{"]/.test(src)) {       // not a TOML [section]
    const j = JSON.parse(src.replace(/^\s*\/\/.*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '').replace(/,(\s*[}\]])/g, '$1'));
    if (j.colors && typeof j.colors === 'object') {
      const c = Object.fromEntries(Object.entries(j.colors).map(([k, v]) => [k.toLowerCase(), hex6(v)]));
      const term = n => c[`terminal.ansi${n}`];
      const tok = {};
      for (const r of j.tokenColors || []) { const fgc = hex6(r && r.settings && r.settings.foreground); if (fgc) tok[fgc] = (tok[fgc] || 0) + 1; }
      const common = Object.entries(tok).sort((x, y) => y[1] - x[1]).map(x => x[0]);
      const bg = c['editor.background'];
      if (!bg) throw new Error('That VS Code theme has no editor.background.');
      return {name: j.name || '', bg, panel: c['sidebar.background'] || c['editorwidget.background'],
        fg: c['editor.foreground'] || c['foreground'] || common[0], fgBright: term('brightwhite'),
        muted: c['descriptionforeground'] || c['editorlinenumber.foreground'] || term('brightblack'),
        red: term('red') || common[3], green: term('green') || common[2], yellow: term('yellow') || common[4],
        blue: term('blue') || common[1], magenta: term('magenta') || common[5], cyan: term('cyan') || common[6],
        button: c['button.background'], buttonText: c['button.foreground'], link: c['textlink.foreground']};
    }
    if (j.background && (j.black || j.red)) {              // Windows Terminal
      const ansi = [...ANSI.map(n => hex6(j[n])), ...ANSI.map(n => hex6(j['bright' + n[0].toUpperCase() + n.slice(1)]))];
      return fromAnsi(j.name || '', hex6(j.background), hex6(j.foreground), ansi);
    }
    throw new Error('That JSON is neither a VS Code theme nor a Windows Terminal scheme.');
  }
  // base16 / base24 YAML (or the flat "baseXX: hex" form).
  const b = {};
  for (const m of src.matchAll(/\bbase([0-9A-Fa-f]{2})\s*:\s*["']?#?([0-9a-fA-F]{6})/g)) b[m[1].toUpperCase()] = '#' + m[2].toLowerCase();
  if (b['00'] && b['05']) {
    const nm = /^\s*(?:name|scheme)\s*:\s*["']?([^"'\n]+)/m.exec(src);
    return {name: nm ? nm[1].trim() : '', bg: b['00'], panel: b['01'], fg: b['05'], fgBright: b['07'], muted: b['04'],
      red: b['08'], orange: b['09'], yellow: b['0A'], green: b['0B'], cyan: b['0C'], blue: b['0D'], magenta: b['0E']};
  }
  // key/value terminal formats: Ghostty, Kitty, Alacritty TOML, Xresources.
  const kv = {}, ansi = new Array(16).fill(null);
  let section = '';
  for (const raw of src.split('\n')) {
    const line = raw.replace(/[#;].*$/, m => /^#[0-9a-f]{3,6}/i.test(m) ? m : '').trim();
    const sec = /^\[(.+)\]$/.exec(line); if (sec) { section = sec[1].toLowerCase(); continue; }
    let m;
    if ((m = /^palette\s*=\s*(\d+)\s*=\s*(#?[0-9a-f]{6})/i.exec(line))) { ansi[+m[1]] = hex6(m[2]); continue; }
    if ((m = /^\*?\.?color(\d+)\s*[:= ]\s*["']?(#?[0-9a-f]{6})/i.exec(line))) { ansi[+m[1]] = hex6(m[2]); continue; }
    if ((m = /^\*?\.?([a-z_-]+)\s*[:= ]\s*["']?(#?[0-9a-f]{6})/i.exec(line))) {
      const key = m[1].toLowerCase(), v = hex6(m[2]);
      const i = ANSI.indexOf(key);
      if (i >= 0 && /colors\.(normal|bright)/.test(section)) ansi[i + (section.endsWith('bright') ? 8 : 0)] = v;
      else kv[key] = v;
    }
  }
  if (!kv.background) throw new Error("Couldn't find a background colour: is that one of the formats listed above?");
  return fromAnsi('', kv.background, kv.foreground, ansi);
}
// Every colour fixed against every background it sits on.
const fixOn = (h, bgs, need) => (h && fixLab(h, bgs, need)) || null;
function fieldsFromPalette(p) {
  let page = p.bg, panel = p.panel || p.bg;
  if (hexLum(panel) < hexLum(page)) [page, panel] = [panel, page];   // cards lighter than the page
  const bgs = [page, panel];
  const dark = hexLum(page) <= 0.35;
  const fallbackText = dark ? '#eeeeee' : '#222222';
  const text = fixOn(p.fg || fallbackText, bgs, 7) || (dark ? '#ffffff' : '#000000');
  const button = p.button || p.blue || p.cyan || p.green || '#3584e4';
  const hover = p.cyan && p.cyan !== button ? p.cyan : (p.blue || button);
  const cands = [p.buttonText, page, p.fgBright, panel, p.fg].filter(Boolean);
  let label = cands.sort((x, y) => Math.min(hexCon(y, button), hexCon(y, hover)) - Math.min(hexCon(x, button), hexCon(x, hover)))[0];
  if (Math.min(hexCon(label, button), hexCon(label, hover)) < 4.5)
    label = Math.min(hexCon('#ffffff', button), hexCon('#ffffff', hover)) >= Math.min(hexCon('#11141b', button), hexCon('#11141b', hover))
      ? '#ffffff' : '#11141b';
  // Still short on one button (a dark and a light one share no label): that
  // button's lightness moves instead, as port_palette.py's nudge_button does.
  const fitted = h => hexCon(label, h) >= 4.5 ? h : (fixLab(h, [label], 4.5) || h);
  const link = fixOn(p.link || p.cyan || p.blue || button, bgs, 4.5) || text;
  return {page_bg: page, page_bg2: '', panel_bg: panel, button: fitted(button), button_hover: fitted(hover), button_text: label,
    link, link_hover: fixOn(p.magenta || p.blue || link, bgs, 4.5) || link,
    text, text_hover: fixOn(p.fgBright || p.fg || fallbackText, bgs, 7) || text,
    muted: fixOn(p.muted || p.fg || fallbackText, bgs, 4.5) || text,
    queue: p.green || p.cyan || button};
}
const slugify = s => String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40);
$('#ed-import-go').addEventListener('click', () => {
  const st = $('#ed-import-status');
  try {
    const p = parseScheme($('#ed-import-text').value);
    edSet(fieldsFromPalette(p));
    if (p.name) { $('#ed-title').value = p.name.slice(0, 40); $('#ed-name').value = slugify(p.name); }
    st.textContent = `Imported${p.name ? ' ' + p.name : ''}. Check the preview and the contrast list, then Save & deploy.`;
  } catch (e) {
    st.textContent = e.message || String(e);
  }
});

// --- edit a copy, or make a readable copy, from a theme's preview -------------------
// Readable: body text and its hover to 7:1, muted, links and button labels
// to 4.5:1 on the panels and page -- lightness only, the way Organizr
// Contrast was made from Organizr.
// A background with only its lightness moved, as little as possible, until
// fg reads on it at `need`:1 (darker for a dark theme, lighter for a light one).
function moveBg(bg, fg, need, darker) {
  if (hexCon(fg, bg) >= need) return bg;
  const [L0, a, b] = oklab(bg), end = darker ? 0 : 1;
  if (hexCon(fg, fromOklab(end, a, b)) < need) return null;
  let lo = L0, hi = end;
  for (let i = 0; i < 30; i++) { const mid = (lo + hi) / 2; if (hexCon(fg, fromOklab(mid, a, b)) >= need) hi = mid; else lo = mid; }
  return fromOklab(hi, a, b);
}
function makeReadable(f) {
  f = Object.assign({}, f);
  const changed = [];
  // Some themes put text on mid-tone or bright-gradient surfaces where no text
  // colour reaches 7:1, not even white. Then the surfaces move instead: text
  // goes to the far end of its own hue, and page and panels darken (or
  // lighten) just enough for it -- the same idea as the gradient themes' veil.
  const surf = ['page_bg', 'panel_bg'].concat(f.page_bg2 ? ['page_bg2'] : []);
  if (!fixLab(f.text, surf.map(k => f[k]), 7)) {
    const dark = surf.reduce((sum, k) => sum + hexLum(f[k]), 0) / surf.length < 0.35 || hexLum(f.text) > 0.5;
    const [, ta, tb] = oklab(f.text);
    const far = fromOklab(dark ? 0.97 : 0.2, ta, tb);
    for (const k of surf) {
      const v = moveBg(f[k], far, 7.1, dark);
      const what = {page_bg: 'page', panel_bg: 'panels', page_bg2: "the gradient's second colour"}[k];
      if (v && v !== f[k]) { f[k] = v; changed.push(`${what} ${dark ? 'darkened' : 'lightened'}`); }
    }
  }
  const bgs = [f.page_bg, f.panel_bg].concat(f.page_bg2 ? [f.page_bg2] : []);
  const out = Object.assign({}, f);
  for (const [k, need] of [['text', 7], ['text_hover', 7], ['muted', 4.5], ['link', 4.5], ['link_hover', 4.5]]) {
    const v = fixLab(f[k], bgs, need);
    if (v && v !== f[k]) { out[k] = v; changed.push(k.replace('_', ' ')); }
  }
  const lab = fixLab(f.button_text, [f.button, f.button_hover], 4.5);
  if (lab && lab !== f.button_text) { out.button_text = lab; changed.push('button text'); }
  return {fields: out, changed};
}
async function openInEditor(btn, readable) {
  const theme = originalOf(btn).dataset.theme;
  closeLightbox();
  // Switch tabs here, synchronously: a hash change shows the tab a tick
  // later, and the tab's own first-open load then landed after this one and
  // overwrote the readable fix with the theme's original colours.
  $('#ed-base').value = theme;
  history.pushState(null, '', '#editor');
  showTab('editor');
  await edLoad();                                    // the newest load, so it wins
  const title = theme.split('-').map(w => w[0].toUpperCase() + w.slice(1)).join(' ');
  $('#ed-name').value = slugify(`${theme}-${readable ? 'readable' : 'mine'}`);
  $('#ed-title').value = `${title} ${readable ? 'Readable' : '(edited)'}`.slice(0, 40);
  const st = $('#ed-status');
  if (readable) {
    const f = Object.assign(edGet(), {page_bg2: $('#ed-gradient').checked ? $('#ed-bg2').value : ''});
    const r = makeReadable(f);
    edSet(r.fields);
    st.textContent = r.changed.length
      ? `Made readable: ${r.changed.join(', ')} (lightness only). Review, then Save & deploy.`
      : 'Already readable everywhere; nothing to change.';
  } else {
    st.textContent = `Loaded ${theme}. Change what you like, then Save & deploy under the new name.`;
  }
}
$('#lb-edit').addEventListener('click', () => { if (lbTile) openInEditor(lbTile, false); });
$('#lb-readable').addEventListener('click', () => { if (lbTile) openInEditor(lbTile, true); });

// --- collapsible sections: which are folded is remembered per browser ---------
let folded = {};
try { folded = JSON.parse(localStorage.getItem('picker-folded') || '{}'); } catch (e) {}
for (const sec of $$('.sect')) {
  if (folded[sec.dataset.sect]) sec.open = false;
  sec.addEventListener('toggle', () => {
    folded[sec.dataset.sect] = !sec.open;
    try { localStorage.setItem('picker-folded', JSON.stringify(folded)); } catch (e) {}
    updateSurprise();                         // a folded section's themes leave the pool
  });
}

// --- tabs ------------------------------------------------------------------
// Real links (#themes, #apps, ...), so back/forward and bookmarks work. The
// panels' ids are tab-<name>, NOT <name>: a fragment matching an id makes the
// browser jump to it, which scrolled the live strip away on every load of
// /#themes. Without JavaScript every panel simply shows, one after another.
const TABS = ['themes', 'apps', 'schedule', 'editor', 'stats'];
let currentTab = 'themes';
function showTab(name) {
  currentTab = TABS.includes(name) ? name : 'themes';
  for (const p of $$('.tab-panel')) p.hidden = p.dataset.tab !== currentTab;
  for (const a of $$('.tab')) {
    const on = a.dataset.tab === currentTab;
    a.classList.toggle('on', on);
    if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  }
  if (currentTab === 'editor' && !edGet().page_bg) edLoad();
}
window.addEventListener('hashchange', () => { showTab(location.hash.slice(1)); window.scrollTo(0, 0); });
showTab(location.hash.slice(1));

seedPick();
layout();
refresh();
applyPreview();
runCoverage();

// --- export and colour vision (theme preview) ----------------------------------
// Both work from /api/theme-vars: the theme's own role colours (page, panels,
// text, muted, button, link, queue...), the same fields the editor uses.
const varsCache = {};
async function themeVars(t) {
  if (!varsCache[t]) {
    const r = await fetch('/api/theme-vars?theme=' + encodeURIComponent(t));
    varsCache[t] = r.ok ? await r.json() : null;
  }
  return varsCache[t];
}

// Colour-vision deficiency: Machado, Oliveira and Fernandes (2009), severity
// 1.0, on linear RGB -- the same matrices as the page's SVG filters.
const CVD = {
  protan: [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
  deutan: [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]],
  tritan: [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.303900]],
};
const CVD_NAME = {protan: 'protanopia', deutan: 'deuteranopia', tritan: 'tritanopia'};
function simulate(hex, kind) {
  const c = [1, 3, 5].map(i => lin(parseInt(hex.slice(i, i + 2), 16)));
  const m = CVD[kind];
  const gam = x => { x = Math.min(1, Math.max(0, x)); return 255 * (x <= 0.0031308 ? 12.92 * x : 1.055 * x ** (1 / 2.4) - 0.055); };
  return rgbHex(m.map(row => gam(row[0] * c[0] + row[1] * c[1] + row[2] * c[2])));
}
// Pairs that must stay apart: [a, b, what goes wrong if they merge].
const CVD_PAIRS = [['link', 'text', 'links look like body text'],
                   ['button', 'link', 'buttons and links look the same'],
                   ['queue', 'button', 'the queue colour looks like a button'],
                   ['button', 'panel_bg', 'buttons fade into the panels']];
const CVD_ROLES = [['page_bg', 'page'], ['panel_bg', 'panels'], ['text', 'text'], ['muted', 'muted'],
                   ['button', 'button'], ['link', 'link'], ['queue', 'queue']];
function cvdReport(v, kind) {
  const sim = Object.fromEntries(CVD_ROLES.map(([k]) => [k, v[k] ? simulate(v[k], kind) : '']));
  const alike = CVD_PAIRS.filter(([a, b]) => v[a] && v[b] && dLab(oklab(v[a]), oklab(v[b])) >= 0.08
                                  && dLab(oklab(sim[a]), oklab(sim[b])) < 0.05).map(p => p[2]);
  const low = hexCon(sim.text, sim.panel_bg) < 4.5 ? ['body text drops below 4.5:1'] : [];
  return {sim, problems: alike.concat(low)};
}
async function showVision() {
  const kind = $('#lb-vision').value, box = $('#lb-cvd');
  lbBody.classList.remove('cvd-protan', 'cvd-deutan', 'cvd-tritan');
  if (!kind || !lbTile) { box.hidden = true; return; }
  lbBody.classList.add('cvd-' + kind);
  const v = await themeVars(lbTile.dataset.theme);
  if (!v) { box.hidden = true; return; }
  const {sim, problems} = cvdReport(v, kind);
  box.innerHTML = (problems.length
      ? `<span class="alike">With ${CVD_NAME[kind]}: ${esc(problems.join('; '))}.</span>`
      : `With ${CVD_NAME[kind]}, every role stays distinct.`)
    + ' Each pair below is the colour as designed, then as seen.'
    + '<div class="roles">' + CVD_ROLES.filter(([k]) => v[k]).map(([k, label]) =>
        `<span class="role"><i><b style="background:${esc(v[k])}"></b><b style="background:${esc(sim[k])}"></b></i>${esc(label)}</span>`).join('')
    + '</div>';
  box.hidden = false;
}
$('#lb-vision').addEventListener('change', showVision);

// Terminal palettes: the theme's own accents where one sits near an ANSI
// hue (within 30 degrees, with some colour), otherwise one made at that hue
// with the theme's typical accent lightness and chroma. Each is then moved,
// in lightness only, to 3:1 on the background -- the same rule as the
// editor's import, the other way round.
const ANSI_HUES = [['red', 29], ['green', 142], ['yellow', 100], ['blue', 264], ['magenta', 328], ['cyan', 195],
                   ['orange', 55]];                     // orange: base16's base09, not a terminal colour
function ansiPalette(v) {
  const bg = v.page_bg, light = hexLum(bg) > 0.35;
  const accents = ['button', 'button_hover', 'link', 'link_hover', 'queue'].map(k => v[k]).filter(Boolean)
    .map(h => { const [L, a, b] = oklab(h); return {h, L, C: Math.hypot(a, b), hue: (Math.atan2(b, a) * 180 / Math.PI + 360) % 360}; })
    .filter(x => x.C >= 0.04);
  const med = xs => { const s = xs.slice().sort((p, q) => p - q); return s.length ? s[Math.floor(s.length / 2)] : null; };
  const L = med(accents.map(x => x.L)) ?? (light ? 0.5 : 0.72), C = Math.max(0.1, med(accents.map(x => x.C)) ?? 0.12);
  // Each accent fills at most one slot, closest match first, so two ANSI
  // colours never come out the same.
  const hueGap = (x, y) => Math.min(Math.abs(x - y), 360 - Math.abs(x - y));
  const pairs = [];
  ANSI_HUES.forEach(([name, hue]) => accents.forEach((x, i) => pairs.push([hueGap(x.hue, hue), name, i])));
  const own = {}, used = new Set();
  for (const [d, name, i] of pairs.sort((p, q) => p[0] - q[0])) {
    if (d > 30 || own[name] !== undefined || used.has(i)) continue;
    own[name] = i; used.add(i);
  }
  const out = {};
  for (const [name, hue] of ANSI_HUES) {
    const base = own[name] !== undefined ? accents[own[name]].h
      : fromOklab(L, C * Math.cos(hue * Math.PI / 180), C * Math.sin(hue * Math.PI / 180));
    const normal = fixLab(base, [bg], 3) || base;
    const [nL, a, b] = oklab(normal);
    const bright = fixLab(fromOklab(light ? nL - 0.07 : nL + 0.07, a, b), [bg], 3) || normal;
    out[name] = [normal, bright];
  }
  const black = light ? v.text : (v.panel_bg || bg), white = light ? (v.panel_bg || bg) : v.text;
  out.black = [black, light ? v.muted || black : fixLab(v.muted || black, [bg], 3) || black];
  out.white = [white, light ? bg : (v.text_hover || white)];
  return out;
}
function exportScheme(v, name, title, fmt) {
  const p = ansiPalette(v), fg = v.text, bg = v.page_bg, cur = v.button, sel = v.panel_bg || bg;
  const n16 = [0, 1].flatMap(i => ANSI.map(c => p[c][i]));          // color0..15
  const plain = h => h.slice(1);
  const head = `Theme Picker export of the theme.park theme "${title}" (${name})`;
  if (fmt === 'base16') {
    // base02 (selection) sits between the panels and the muted text;
    // base03 (comments) is the muted text too; base0F is the second link.
    const mid = (x, y) => { const p1 = oklab(x), p2 = oklab(y); return fromOklab((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2, (p1[2] + p2[2]) / 2); };
    const muted = v.muted || fg;
    const b = [bg, sel, mid(sel, muted), muted, muted, fg, v.text_hover || fg, v.text_hover || fg,
               p.red[0], p.orange[0], p.yellow[0], p.green[0], p.cyan[0], p.blue[0], p.magenta[0],
               v.link_hover || p.red[1]];
    return [`${name}.yaml`, `# ${head}\nsystem: "base16"\nname: "${title}"\nauthor: "theme-park export"\n`
      + `variant: "${hexLum(bg) > 0.35 ? 'light' : 'dark'}"\npalette:\n`
      + b.map((h, i) => `  base0${i.toString(16).toUpperCase()}: "${h}"`).join('\n') + '\n'];
  }
  if (fmt === 'ghostty') return [name, `# ${head}\nbackground = ${plain(bg)}\nforeground = ${plain(fg)}\ncursor-color = ${plain(cur)}\n`
      + `selection-background = ${plain(sel)}\nselection-foreground = ${plain(fg)}\n`
      + n16.map((h, i) => `palette = ${i}=${h}`).join('\n') + '\n'];
  if (fmt === 'kitty') return [`${name}.conf`, `# ${head}\nbackground ${bg}\nforeground ${fg}\ncursor ${cur}\n`
      + `selection_background ${sel}\nselection_foreground ${fg}\nurl_color ${v.link || fg}\n`
      + n16.map((h, i) => `color${i} ${h}`).join('\n') + '\n'];
  if (fmt === 'alacritty') return [`${name}.toml`, `# ${head}\n[colors.primary]\nbackground = "${bg}"\nforeground = "${fg}"\n\n`
      + `[colors.cursor]\ncursor = "${cur}"\ntext = "${bg}"\n\n[colors.selection]\nbackground = "${sel}"\ntext = "${fg}"\n\n`
      + ['normal', 'bright'].map((k, i) => `[colors.${k}]\n` + ANSI.map(c => `${c} = "${p[c][i]}"`).join('\n')).join('\n\n') + '\n'];
  if (fmt === 'wt') {
    const cap = s => s[0].toUpperCase() + s.slice(1);
    const o = {name: title, background: bg, foreground: fg, cursorColor: cur, selectionBackground: sel};
    ANSI.forEach(c => { o[c === 'magenta' ? 'purple' : c] = p[c][0]; o['bright' + cap(c === 'magenta' ? 'purple' : c)] = p[c][1]; });
    return [`${name}.json`, JSON.stringify(o, null, 2) + '\n'];
  }
  if (fmt === 'xresources') return [`${name}.Xresources`, `! ${head}\n*.background: ${bg}\n*.foreground: ${fg}\n*.cursorColor: ${cur}\n`
      + n16.map((h, i) => `*.color${i}: ${h}`).join('\n') + '\n'];
  return null;
}
function download(filename, text, type = 'text/plain') {
  const url = URL.createObjectURL(new Blob([text], {type}));
  const a = document.createElement('a');
  a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$('#lb-export').addEventListener('change', async ev => {
  const fmt = ev.target.value; ev.target.value = '';
  if (!fmt || !lbTile) return;
  const t = lbTile.dataset.theme;
  if (fmt === 'css') {
    const r = await fetch('/api/theme-css?theme=' + encodeURIComponent(t));
    if (r.ok) download(`${t}.css`, await r.text(), 'text/css');
    return;
  }
  const v = await themeVars(t);
  if (!v) return;
  const out = exportScheme(v, t, t.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase()), fmt);
  if (out) download(out[0], out[1]);
});

// --- app groups (Apps tab) -------------------------------------------------------
// After a group pin: every member's own select and card follow, then the
// coverage check re-runs once Traefik has the new config.
function showPins(pins) {
  for (const sel of $$('.pin')) {
    const v = pins[sel.dataset.app] || '';
    sel.value = v; sel.dataset.current = v;
    sel.closest('.app-card').classList.toggle('pinned', !!v);
  }
  updateAppsView();
}
for (const sel of $$('.group-pin')) {
  sel.addEventListener('change', async () => {
    const data = await postJSON('/api/group', {action: 'pin', name: sel.dataset.group, theme: sel.value});
    const msg = $('#msg'); msg.textContent = data.message; msg.hidden = false;
    if (!data.ok) return;
    showPins(data.pins);
    setTimeout(runCoverage, 3500);
  });
}
$('#grp-save').addEventListener('click', async () => {
  const apps = $$('.grp-app').filter(c => c.checked).map(c => c.value);
  const data = await postJSON('/api/group', {action: 'save', name: $('#grp-name').value.trim(), apps});
  $('#grp-status').textContent = data.message;
  if (data.ok) setTimeout(() => location.assign('/?g=' + Date.now() + '#apps'), 600);
});
for (const b of $$('.group-edit')) {
  b.addEventListener('click', () => {
    const row = b.closest('.group'), members = row.dataset.apps.split(' ');
    $('#grp-name').value = row.dataset.group;
    for (const c of $$('.grp-app')) c.checked = members.includes(c.value);
    $('#grp-name').focus();
  });
}
for (const b of $$('.group-del')) {
  b.addEventListener('click', async () => {
    if (!confirm(`Delete the group "${b.dataset.group}"? Its apps keep their pins.`)) return;
    const data = await postJSON('/api/group', {action: 'delete', name: b.dataset.group});
    if (data.ok) b.closest('.group').remove();
    $('#grp-status').textContent = data.message;
  });
}
