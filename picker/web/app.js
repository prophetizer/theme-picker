const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
// Every value put into innerHTML goes through esc(), even ones the server
// already restricts (theme and app names): the restriction is the server's
// invariant, not something this code should depend on. Coverage details
// carry exception text such as "<urlopen error ...>".
const esc = v => String(v).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c]);
const tiles = $$('.theme-btn');
tiles.forEach((b, i) => b.dataset.idx = i);
const grids = {official: $('#grid-official'), community: $('#grid-community'),
               custom: $('#grid-custom'), all: $('#grid-all')};
const state = {q: '', mode: '', grad: false, readable: false, fresh: false,
               fav: false, hc: false, family: '', sort: 'section', preview: '', view: 'designed'};

// --- light/dark pairs ---------------------------------------------------------
// A theme with a generated twin (nord -> nord-light) is one tile on screen:
// both tiles are in the page, side by side, and only the chosen form shows.
// The choice is the tile's own sun/moon switch if touched, else the sidebar's
// "show every theme as". The live theme always shows in its live form.
const byName = Object.fromEntries(tiles.map(b => [b.dataset.theme, b]));
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
      && (!state.q || d.theme.toLowerCase().includes(state.q))
      && (!state.mode || d.mode === state.mode)
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
  newest: (a, b) => (b.dataset.added || '').localeCompare(a.dataset.added || '')
                    || a.dataset.theme.localeCompare(b.dataset.theme),
};

function layout() {
  // "section" keeps official / community / custom; any other sort pools every
  // theme into one grid, because sorting 110 themes by brightness is only
  // useful if it is one list.
  const sorted = state.sort === 'section'
    ? [...tiles].sort((a, b) => a.dataset.idx - b.dataset.idx)
    : [...tiles].sort(SORTS[state.sort]);
  for (const b of sorted) (state.sort === 'section' ? grids[b.dataset.section] : grids.all).appendChild(b);
}

function refresh() {
  let shown = 0;
  for (const b of tiles) { b.hidden = !matches(b); if (!b.hidden) shown++; }
  for (const sec of $$('.sect')) {
    const n = sec.querySelectorAll('.theme-btn:not([hidden])').length;
    sec.querySelector('.sect-count').textContent = n ? `${n}` : '';
    const inMode = (sec.dataset.sect === 'all') === (state.sort !== 'section');
    sec.hidden = !inMode || !sec.querySelector('.theme-btn:not([hidden])');
  }
  // Counted over the form each pair is showing: one tile per theme.
  const forms = tiles.filter(isShownForm), total = forms.length;
  const twins = tiles.filter(b => b.dataset.twin).length;
  const grads = forms.filter(b => b.dataset.gradient === '1').length;
  const low = forms.filter(b => b.dataset.contrast === 'low').length;
  const hc = forms.filter(b => b.dataset.hc === '1').length;
  $('#count').textContent = shown === total
    ? `${total} themes (${twins} with a light/dark twin) · ${grads} gradient · ${hc} high contrast · ${low} low contrast`
    : `${shown} of ${total}`;
  $$('#view [data-view]').forEach(v => v.classList.toggle('on', v.dataset.view === state.view));
  $$('.fam').forEach(f => f.classList.toggle('on', f.dataset.family === state.family));
  updateSurprise();
  save();
}

// --- toolbar wiring -------------------------------------------------------
const ctl = {q: $('#filter'), mode: $('#mode'), grad: $('#only-gradient'),
             readable: $('#only-readable'), fresh: $('#only-new'), fav: $('#only-fav'), hc: $('#only-hc'),
             sort: $('#sort'), preview: $('#preview')};
ctl.q.value = state.q; ctl.mode.value = state.mode; ctl.sort.value = state.sort;
ctl.preview.value = state.preview || '';
ctl.grad.checked = state.grad; ctl.readable.checked = state.readable;
ctl.fresh.checked = state.fresh; ctl.fav.checked = state.fav; ctl.hc.checked = state.hc;
ctl.q.addEventListener('input', () => { state.q = ctl.q.value.trim().toLowerCase(); refresh(); });
ctl.mode.addEventListener('change', () => { state.mode = ctl.mode.value; refresh(); });
ctl.sort.addEventListener('change', () => { state.sort = ctl.sort.value; layout(); refresh(); });
ctl.preview.addEventListener('change', () => { state.preview = ctl.preview.value; applyPreview(); save(); });
for (const k of ['grad', 'readable', 'fresh', 'fav', 'hc'])
  ctl[k].addEventListener('change', () => { state[k] = ctl[k].checked; refresh(); });
$$('.fam').forEach(f => f.addEventListener('click', () => {
  state.family = state.family === f.dataset.family ? '' : f.dataset.family; refresh();
}));
$('#fam-any').addEventListener('click', () => { state.family = ''; refresh(); });
$('#surprise').addEventListener('click', surprise);
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

// "Surprise me" picks from what the filters show, minus the live theme. Worked
// out from the filters and folded sections, not from layout like
// visibleTiles(): the button sits in the live strip on every tab, and on any
// tab but Themes no tile has an offsetParent, so it used to do nothing there.
function surprisePool() {
  return tiles.filter(b => !b.hidden && !b.classList.contains('active')
                           && !b.closest('.sect[hidden], details.sect:not([open])'));
}

// The count is on the button so it's plain that the filters apply to it.
function updateSurprise() {
  const n = surprisePool().length, btn = $('#surprise');
  btn.textContent = `Surprise me · ${n}`;
  btn.disabled = !n;
  btn.title = n ? `Apply a random theme from the ${n} shown (R)` : 'No other theme matches the filters';
}

function surprise() {
  const pool = surprisePool();
  if (!pool.length) return;
  const b = pool[Math.floor(Math.random() * pool.length)];
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
  if (btn.dataset.added) bits.push('added ' + btn.dataset.added);
  $('#lb-meta').textContent = bits.join(' · ');
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
      : '<p class="lb-empty">No screenshots of this theme yet. They come from '
        + '<code>theme-switcher/capture-theme-screenshots.sh</code>.</p>';
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
$('#lb-apply').addEventListener('click', () => { applyTheme(lbTile.dataset.theme); closeLightbox(); });
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
  });
}
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
    cell.innerHTML = r.state === 'ok'
      ? `<span class="ok">ok</span> ${esc(r.expected)}${r.pinned ? ' (pinned)' : ''}`
      : `<span class="bad">${esc(r.state)}</span> ${esc(r.detail)}`;
  }
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
  return `on · now ${s.slot} (${s[s.slot]}) · next: ${s.next_theme} at ${s.next_at}`;
}
$('#sch-save').addEventListener('click', async () => {
  const st = $('#sch-status');
  st.textContent = 'Saving...';
  const data = await postJSON('/api/schedule', {
    enabled: $('#sch-enabled').checked, day: $('#sch-day').value, night: $('#sch-night').value,
    day_at: $('#sch-day-at').value, night_at: $('#sch-night-at').value});
  st.textContent = data.message;
  if (!data.ok) return;
  $('#sch-state').textContent = schSummary(data.schedule);
  if (data.theme !== data.previous) markApplied(data.previous, data.theme, data.css);
});

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
