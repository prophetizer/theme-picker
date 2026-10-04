// Theme Picker demo: the real page and script, with no server behind them.
// Loaded before app.js by the static demo (tools/build_demo.py). Every call
// app.js makes to the picker's API is answered here, in the browser: picking
// a theme re-dresses this page only, favourites and hidden themes live in this
// tab, and nothing is sent anywhere. demo.json holds each theme's stylesheet
// path and a sample coverage result.
(() => {
  const DEMO = JSON.parse(document.getElementById('demo-data').textContent);
  const live = () => document.querySelector('.current b').textContent;
  const favs = new Set(DEMO.favourites), hidden = new Set(), ratings = {}, collections = {};
  const json = (body, status = 200) => new Response(JSON.stringify(body),
    {status, headers: {'Content-Type': 'application/json'}});
  const off = what => json({ok: false, message: `Demo: ${what} is off here. Install Theme Picker to use it.`});
  const realFetch = window.fetch.bind(window);

  window.fetch = async (input, init = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
    const path = url.pathname.replace(/^.*?(\/api\/|\/set-theme)/, '$1');
    const body = init.body ? String(init.body) : '';
    const data = body.startsWith('{') ? JSON.parse(body) : Object.fromEntries(new URLSearchParams(body));

    if (path === '/set-theme') {
      const t = data.theme;
      if (!(t in DEMO.css)) return json({ok: false, message: `Rejected: '${t}' is not a known theme.`}, 400);
      return json({ok: true, theme: t, css: DEMO.css[t],
                   message: `Demo: ${t} is on this page only. Installed, every app would change with it.`});
    }
    if (path === '/api/coverage') {
      const t = live();
      return json(Object.assign({}, DEMO.coverage, {theme: t,
        results: DEMO.coverage.results.map(r => Object.assign({}, r, {expected: r.pinned ? r.expected : t,
          detail: r.state === 'ok' ? '' : r.detail}))}));
    }
    if (path === '/api/theme-vars') return realFetch(`data/vars/${encodeURIComponent(url.searchParams.get('theme'))}.json`);
    if (path === '/api/editor/status') return json({state: 'unknown'});
    if (path === '/api/favourite') {
      data.on ? favs.add(data.theme) : favs.delete(data.theme);
      return json({ok: true, favourites: [...favs].sort()});
    }
    if (path === '/api/hide') {
      data.on ? hidden.add(data.theme) : hidden.delete(data.theme);
      return json({ok: true, hidden: [...hidden].sort()});
    }
    if (path === '/api/rate') {
      const r = +data.rating;
      if (![-1, 0, 1].includes(r) || !(data.theme in DEMO.css)) return json({ok: false}, 400);
      r ? ratings[data.theme] = r : delete ratings[data.theme];
      return json({ok: true, ratings});
    }
    if (path === '/api/digest/preview') return json({enabled: false, ntfy: false, title: 'Theme picker: your week',
      body: 'Installed, this summarises your week on ntfy: theme changes and what was on screen most, '
          + 'themes added, coverage, and themes missing screenshots.'});
    if (path === '/api/collection') {                 // kept in this tab only
      const name = String(data.name || '').trim();
      if (data.action === 'delete') { delete collections[name]; return json({ok: true, message: `Collection '${name}' deleted.`, collections}); }
      if (!/^[A-Za-z0-9][A-Za-z0-9 _-]{0,39}$/.test(name) || !(data.theme in DEMO.css))
        return json({ok: false, message: 'A collection name is 1-40 letters, digits, spaces, - or _.'}, 400);
      const cur = new Set(collections[name] || []);
      data.on ? cur.add(data.theme) : cur.delete(data.theme);
      if (cur.size) collections[name] = [...cur].sort(); else delete collections[name];
      return json({ok: true, message: data.on ? `Added ${data.theme} to ${name}.` : `Took ${data.theme} out of ${name}.`, collections});
    }
    if (path === '/api/override') return off('pinning an app');
    if (path === '/api/group') return off('app groups');
    if (path === '/api/schedule' || path === '/api/daily' || path === '/api/rotate') return off('the schedule');
    if (path === '/api/theme-css') return realFetch(DEMO.css[url.searchParams.get('theme')] || 'missing.css');
    if (path === '/api/editor/save') return off('saving themes');
    return realFetch(input, init);
  };
})();
