/* Tenet static site. Plain JavaScript, no framework.
   Loads data/tenet.json once and renders every screen from it. */
(function () {
  'use strict';

  /* Icons: inline SVG, 24 px grid, stroked with currentColor */
  var ICONS = {
    plus: '<path d="M12 4v16M4 12h16"/>',
    eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    wallet: '<path d="M4 7.5V6a2 2 0 0 1 2-2h11v3.5"/><rect x="3" y="7.5" width="18" height="12.5" rx="2"/><path d="M16.5 13.75h.01"/>',
    swap: '<path d="M4 8h15l-3.5-3.5M20 16H5l3.5 3.5"/>',
    signOut: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
    arrowUpRight: '<path d="M7 17L17 7M8 7h9v9"/>',
    arrowRight: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    arrowLeft: '<path d="M19 12H5M11 6l-6 6 6 6"/>',
    squaresFour: '<rect x="4" y="4" width="7" height="7" rx="1"/><rect x="13" y="4" width="7" height="7" rx="1"/><rect x="4" y="13" width="7" height="7" rx="1"/><rect x="13" y="13" width="7" height="7" rx="1"/>',
    graph: '<circle cx="6" cy="6" r="2.2"/><circle cx="18" cy="8" r="2.2"/><circle cx="8" cy="18" r="2.2"/><path d="M8.2 6.4l7.6 1.2M6.4 8.2l1.2 7.6M9.6 16.4l6.8-6.8"/>',
    path: '<circle cx="6" cy="18" r="2"/><circle cx="18" cy="6" r="2"/><path d="M8 18h7a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h7"/>',
    stack: '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 12.5l9 5 9-5"/><path d="M3 16.5l9 5 9-5"/>',
    fileText: '<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
    filePlus: '<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5M12 11v6M9 14h6"/>',
    fileCode: '<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5M10 12l-2 2.5 2 2.5M14 12l2 2.5-2 2.5"/>',
    scales: '<path d="M12 4v16M8 20h8M5 7h14M12 4v3"/><path d="M5 7l-3 7a3 3 0 0 0 6 0z"/><path d="M19 7l-3 7a3 3 0 0 0 6 0z"/>',
    chartBar: '<path d="M4 20h16M7 20v-7M12 20V6M17 20v-10"/>',
    linkSimple: '<path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1"/><path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1"/>',
    linkH: '<path d="M8 12h8M10 8H7a4 4 0 0 0 0 8h3M14 8h3a4 4 0 0 1 0 8h-3"/>',
    coins: '<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.66 3.13 3 7 3s7-1.34 7-3V6"/><path d="M5 12v6c0 1.66 3.13 3 7 3s7-1.34 7-3v-6"/>',
    envelope: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/>',
    penNib: '<path d="M12 3l6 9-2 7H8l-2-7z"/><path d="M12 3v7.5"/><circle cx="12" cy="12" r="1.5"/>',
    copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    circleNotch: '<path d="M12 3a9 9 0 1 0 9 9"/>',
    warningCircle: '<circle cx="12" cy="12" r="9"/><path d="M12 7.5V13M12 16.5h.01"/>',
    warning: '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17h.01"/>',
    pulse: '<path d="M3 12h4l3-7 4 14 3-7h4"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    userCircle: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="10" r="3"/><path d="M6.5 18.5a6.5 6.5 0 0 1 11 0"/>',
    usersThree: '<circle cx="12" cy="8" r="3"/><path d="M6.5 19a5.5 5.5 0 0 1 11 0"/><circle cx="5" cy="10" r="2"/><circle cx="19" cy="10" r="2"/><path d="M2 17a3.2 3.2 0 0 1 3-2.5M22 17a3.2 3.2 0 0 0-3-2.5"/>',
    vault: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="12" cy="12" r="3.5"/><path d="M12 8.5V7M12 17v-1.5M6 20v1M18 20v1"/>',
    arrowsClockwise: '<path d="M20 8a8.5 8.5 0 0 0-15.5 1M4 16a8.5 8.5 0 0 0 15.5-1"/><path d="M20 3v5h-5M4 21v-5h5"/>',
    caretRight: '<path d="M9 6l6 6-6 6"/>',
    caretLeft: '<path d="M15 6l-6 6 6 6"/>',
    caretDown: '<path d="M6 9l6 6 6-6"/>',
    gitBranch: '<circle cx="6" cy="5" r="2"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="7" r="2"/><path d="M6 7v10M18 9c0 4-4 5.5-12 6"/>',
    calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    shieldCheck: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-4.5"/>',
    checkCircle: '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l3 3 5-6"/>',
    hourglass: '<path d="M6 3h12M6 21h12M7 3c0 6 10 6 10 9s-10 3-10 9M17 3c0 6-10 6-10 9s10 3 10 9"/>',
    x: '<path d="M6 6l12 12M18 6L6 18"/>',
    clockCcw: '<path d="M3.5 12a8.5 8.5 0 1 0 2.5-6"/><path d="M3 4v4h4M12 7.5V12l3 2"/>',
    translate: '<path d="M4 5h8M8 3v2M10 5c-1 4-3.5 7-6 8M6 9c1 2 3 3.5 5 4M13 21l4-10 4 10M14.5 17.5h5"/>',
    testTube: '<path d="M8 3h8M14.5 3v11.5a2.5 2.5 0 0 1-5 0V3M9.5 11h5"/>',
    bookOpen: '<path d="M12 6c-2-1.5-5-2-9-2v14c4 0 7 .5 9 2 2-1.5 5-2 9-2V4c-4 0-7 .5-9 2z"/><path d="M12 6v14"/>',
    plusCircle: '<circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/>',
    drop: '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/>',
    search: '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>',
    code: '<path d="M8 7l-5 5 5 5M16 7l5 5-5 5"/>',
    equals: '<path d="M5 9h14M5 15h14"/>',
    receipt: '<path d="M6 3h12v18l-3-2-3 2-3-2-3 2z"/><path d="M9 8h6M9 12h6M9 16h3"/>',
    /* Lacre's symbol, redrawn from its logo: outer ring, inner ring, light blue core */
    lacre: '<circle cx="12" cy="12" r="9.2"/><circle cx="12" cy="12" r="5.6" class="lacre-ring"/><circle cx="12" cy="12" r="2.8" class="lacre-core"/>'
  };
  function icon(name, cls, style) {
    return '<svg class="ic' + (cls ? ' ' + cls : '') + '" viewBox="0 0 24 24" aria-hidden="true"' + (style ? ' style="' + style + '"' : '') + '>' + (ICONS[name] || '') + '</svg>';
  }
  function hydrateIcons(root) {
    (root || document).querySelectorAll('[data-icon]').forEach(function (el) {
      el.innerHTML = icon(el.getAttribute('data-icon'), el.getAttribute('data-icon-class'));
      el.style.display = 'inline-flex';
      el.removeAttribute('data-icon');
    });
  }

  /* Helpers */
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }
  function $(id) { return document.getElementById(id); }
  var pad2 = function (n) { return String(n).padStart(2, '0'); };
  var fmtAt = function (iso) { return iso ? iso.slice(0, 10) + ' ' + iso.slice(11, 19) + ' UTC' : ''; };
  var fmtMin = function (iso) { return iso ? iso.slice(0, 10) + ' ' + iso.slice(11, 16) + ' UTC' : ''; };
  var nextLabel = function (s) { return s.date + (s.time_utc ? ' ' + s.time_utc + ' UTC' : ''); };
  var nextTs = function (s) { return Date.parse(s.date + 'T' + (s.time_utc || '00:00') + ':00Z'); };
  var centsTxt = function (c) { return (Number(c) / 100).toFixed(2) + ' USDC'; };
  var usdc = function (n) { return Number(n).toFixed(2) + ' USDC'; };
  var clamp = function (x) { return Math.max(0, Math.min(1, isFinite(x) ? x : 0)); };
  var pct = function (x) { return (clamp(x) * 100).toFixed(2) + '%'; };
  var frac = function (s) { var m = /(\d+)\s*\/\s*(\d+)/.exec(s || ''); return m && +m[2] ? +m[1] / +m[2] : 0; };
  var sum = function (arr, f) { return arr.reduce(function (a, x) { return a + (Number(f(x)) || 0); }, 0); };
  var WORDS = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve'];
  var word = function (n) { return WORDS[n] != null ? WORDS[n] : String(n); };
  var cap = function (t) { return t.charAt(0).toUpperCase() + t.slice(1); };
  /* Escrow windows (RESPONSE_WINDOW, CLOSING_WINDOW, PROOF_WINDOW), read from data/tenet.json */
  function windows(d) {
    var e = ((d && d.contracts) || []).find(function (x) { return x.chain === 'arc'; }) || {};
    var p = e.params || {};
    return { response: p.response_window_seconds, closing: p.closing_window_seconds, proof: p.proof_window_seconds };
  }
  /* 259200 -> "72 hours", 604800 -> "7 days" (singular form for titles: "72 hour") */
  function span(s, single) {
    s = Number(s);
    var n, u;
    if (s % 86400 === 0 && s >= 7 * 86400) { n = s / 86400; u = 'day'; }
    else if (s % 3600 === 0) { n = s / 3600; u = 'hour'; }
    else { n = Math.round(s / 60); u = 'minute'; }
    return n + ' ' + u + (single || n === 1 ? '' : 's');
  }
  function fmtSecs(s) {
    s = Number(s);
    if (s >= 3600 && s % 3600 === 0) return (s / 3600) + ' h';
    if (s >= 60 && s % 60 === 0) return (s / 60) + ' min';
    return s + ' s';
  }
  function dur(ms) {
    var s = Math.round(ms / 1000);
    if (s < 60) return s + ' s';
    var m = Math.floor(s / 60);
    if (m < 60) return m + ' min ' + (s % 60) + ' s';
    var h = Math.floor(m / 60);
    if (h < 48) return h + ' h ' + (m % 60) + ' min';
    var d = Math.floor(h / 24);
    return d + ' d ' + (h % 24) + ' h';
  }
  /* Function names never reach the visitor */
  var FN = { releaseUnproven: 'Payment released to the store (no proof sent)' };
  function plainText(s) {
    var m = /^\s*([a-z]+[A-Z][A-Za-z0-9]*)(\(\))?\s*:\s*(.*)$/.exec(s || '');
    if (!m) return s;
    if (FN[m[1]]) return FN[m[1]];
    var rest = m[3] || '';
    return rest ? rest.charAt(0).toUpperCase() + rest.slice(1) : s;
  }
  var netOf = function (chain, text) { return !chain ? 'offchain' : (/Lacre/i.test(text || '') ? 'lacre' : chain); };
  var OUTC = { REFUND: 'var(--out-refund)', DENY: 'var(--out-deny)', NOT_YET: 'var(--out-notyet)', INVALID_CLAIM: 'var(--out-invalid)' };
  var HERO = {
    REFUND: { icon: 'check', h: 158, c: 0.14 },
    DENY: { icon: 'x', h: 160, c: 0.02 },
    NOT_YET: { icon: 'hourglass', h: 80, c: 0.11 },
    INVALID_CLAIM: { icon: 'warning', h: 25, c: 0.11 }
  };
  var outColor = function (o) { return OUTC[o] || 'var(--color-text)'; };
  var isResent = function (r) { return /^no consensus/.test(r || ''); };

  /* Small components */
  var NETS = {
    arc: { cls: 'badge-arc', icon: 'coins', name: 'Arc', role: 'money', title: 'Arc testnet: holds the money' },
    bradbury: { cls: 'badge-bradbury', icon: 'scales', name: 'GenLayer Bradbury', short: 'Bradbury', role: 'judgment', title: 'GenLayer Bradbury testnet: judgment' },
    lacre: { cls: 'badge-lacre', icon: 'lacre', name: 'Lacre', role: 'email attestations', title: 'Lacre on GenLayer: email attestations' },
    offchain: { cls: 'badge-offchain', icon: 'penNib', name: 'Off-chain', title: 'Off-chain step' }
  };
  /* Lacre's symbol with its name in spaced capitals, as in its logo */
  function lacreMark(size) {
    return '<span class="lacre-mark' + (size ? ' lacre-mark-' + size : '') + '" aria-label="Lacre">' + icon('lacre') + '<span>LACRE</span></span>';
  }
  function netBadge(net, o) {
    o = o || {};
    var n = NETS[net] || NETS.offchain;
    var name = o.short && n.short ? n.short : n.name;
    return '<span class="badge ' + n.cls + '" title="' + esc(n.title) + '">' + icon(n.icon) + '<span>' + esc(name) + '</span>' +
      (o.role && n.role ? '<span class="role">' + esc(n.role) + '</span>' : '') + '</span>';
  }
  function hashChip(value, url, net) {
    if (!value) return '';
    var v = String(value);
    var short = v.length > 12 ? v.slice(0, 6) + '...' + v.slice(-4) : v;
    var main = url
      ? '<a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer" title="Open in explorer: ' + esc(v) + '">' + esc(short) + icon('arrowUpRight') + '</a>'
      : '<span class="plain" title="' + esc(v) + '">' + esc(short) + '</span>';
    return '<span class="hash-wrap">' + (net ? netBadge(net) : '') + '<span class="hash">' + main +
      '<button type="button" data-copy="' + esc(v) + '" title="Copy ' + esc(v) + '" aria-label="Copy ' + esc(v) + '">' + icon('copy') + '</button></span></span>';
  }
  function votesBar(votes, compact) {
    var v = votes || {};
    var order = { '1': 0, '3': 1, '0': 2 };
    var es = Object.keys(v).map(function (k) {
      var i = k.indexOf(':');
      return { code: k.slice(0, i), name: k.slice(i + 1), n: Number(v[k]) || 0 };
    }).sort(function (a, b) { return (order[a.code] != null ? order[a.code] : 9) - (order[b.code] != null ? order[b.code] : 9); });
    var total = sum(es, function (e) { return e.n; });
    var ok = sum(es.filter(function (e) { return e.code === '1'; }), function (e) { return e.n; });
    var cells = '';
    es.forEach(function (e) {
      for (var i = 0; i < e.n; i++) cells += '<i class="' + (e.code === '1' ? 'v-ok' : e.code === '3' ? 'v-to' : 'v-nv') + '"></i>';
    });
    var others = es.filter(function (e) { return e.code !== '1'; }).map(function (e) { return e.n + ' ' + e.name; });
    var head = ok + ' of ' + total + ' FINISHED_WITH_RETURN';
    var rest = others.length ? ', ' + others.join(', ') : '';
    var text = compact ? '<b>' + ok + ' of ' + total + '</b>' : '<b>' + esc(head) + '</b>' + esc(rest);
    return '<div class="votes" title="' + esc(head + rest) + '"><div class="votes-cells">' + cells + '</div><span class="votes-text">' + text + '</span></div>';
  }
  function claimSteps(p, labels) {
    return '<div class="steps">' + (labels ? '<div class="steps-top"><span class="eyebrow">Claim progress</span><span>' + esc(p.summary) + '</span></div>' : '') +
      '<div class="steps-row">' + p.steps.map(function (s) {
        return '<div title="' + esc(s.title) + '"><i class="s-' + s.state + '"></i>' + (labels ? '<span class="l-' + s.state + '">' + esc(s.label) + '</span>' : '') + '</div>';
      }).join('') + '</div></div>';
  }
  /* d: {title, status, fill, tick, start, end, note, liveFrom, liveTo, liveKind} */
  function timeBar(d) {
    var live = d.liveFrom != null ? ' data-live-from="' + d.liveFrom + '" data-live-to="' + d.liveTo + '"' : '';
    return '<div class="timebar"' + live + '>' +
      '<div class="timebar-top"><span class="timebar-title">' + esc(d.title) + '</span><span class="timebar-status">' + esc(d.status) + '</span></div>' +
      '<div class="timebar-track"><div class="timebar-fill" style="width:' + d.fill + ';min-width:' + (d.fill === '0%' ? '0' : '3px') + '"></div>' +
      (d.tick ? '<div class="timebar-tick" style="left:' + d.tick + '"></div>' : '') + '</div>' +
      '<div class="timebar-ends"><span>' + esc(d.start) + '</span><span>' + esc(d.end) + '</span></div>' +
      (d.note ? '<span class="timebar-note">' + esc(d.note) + '</span>' : '') + '</div>';
  }
  function liveStatus(from, to, now) {
    return { fill: pct((now - from) / (to - from)), status: to > now ? dur(to - now) + ' left' : 'Awaiting next session' };
  }
  function statusPill(vm, lg) {
    var c = lg ? ' pill-lg' : '';
    if (vm.isSettled) return '<span class="pill pill-settled' + c + '">Settled</span>';
    if (vm.isProgress) return '<span class="pill pill-progress' + c + '">In progress</span>';
    return '';
  }
  function fill(p) { return '<div class="bar"><i style="width:' + p + '"></i></div>'; }
  function collapsedRow(ic, label, note) {
    return '<section class="card card-collapsed">' + icon(ic) + '<span class="label-up">' + esc(label) + '</span><span class="note">' + esc(note) + '</span></section>';
  }
  function cardHead(ic, label, extra) {
    return '<div class="card-head">' + icon(ic) + '<span class="label-up">' + esc(label) + '</span>' + (extra || '') + '</div>';
  }
  function screenHead(num, title, lede) {
    return '<header class="screen-head"><span class="kicker">' + esc(num) + '</span><h2>' + esc(title) + '</h2>' + (lede ? '<p>' + esc(lede) + '</p>' : '') + '</header>';
  }

  /* View model for one live case */
  function caseVM(c, d, now) {
    var escrow = (d.contracts || []).find(function (x) { return x.chain === 'arc'; }) || {};
    var params = escrow.params || {};
    var win = windows(d);
    var tl = (c.timeline || []).map(function (e) { return Object.assign({}, e, { action: plainText(e.action) }); })
      .sort(function (a, b) { return a.at < b.at ? -1 : a.at > b.at ? 1 : 0; });
    var f = function (re) { return tl.find(function (e) { return re.test(e.action || ''); }); };
    var paid = f(/^Pay into escrow/), claimE = f(/^Open claim/);
    var resp = tl.find(function (e) { return e.actor === 'store' && /^Submit: response/.test(e.action || ''); });
    var noResp = f(/no-response/i), closing = f(/^Open closing round/);
    var propose = f(/^Propose verdict/), exec = f(/^Execute verdict/);
    var verdicts = c.verdicts || [];
    var lastV = verdicts[verdicts.length - 1];
    var finalV = verdicts.find(function (v) { return v.verdict && v.verdict.final; });
    var exp = (c.expected && c.expected.steps) || [];
    var closingPath = exp.some(function (s) { return s.action === 'open_closing_round'; });
    var settled = c.status === 'settled';
    var ns = (c.next_steps || []).map(function (s) { return Object.assign({}, s, { what: plainText(s.what) }); });

    var st = function (label, state, note) { return { label: label, state: state, title: label + ': ' + note }; };
    var steps = [
      st('Paid', paid ? 'done' : 'pending', paid ? fmtAt(paid.at) : 'pending'),
      st('Claim', claimE ? 'done' : 'pending', claimE ? fmtAt(claimE.at) : 'pending'),
      st('Answer', (resp || noResp) ? 'done' : 'pending', resp ? fmtAt(resp.at) : noResp ? 'no-response marker' : 'pending'),
      st('Closing round', closing ? 'done' : closingPath ? 'pending' : 'skip', closing ? fmtAt(closing.at) : closingPath ? 'pending' : 'not in this path'),
      st('Verdict', finalV ? 'done' : lastV ? 'partial' : 'pending', finalV ? finalV.verdict.outcome + ', sent ' + fmtAt((tl.find(function (e) { return e.tx === finalV.tx; }) || {}).at) : lastV ? lastV.verdict.outcome + ', not final' : 'pending'),
      st('Settled', settled ? 'done' : 'pending', settled ? 'settled on Arc' : 'pending')
    ];
    var applicable = steps.filter(function (s) { return s.state !== 'skip'; }).length;
    var done = steps.filter(function (s) { return s.state === 'done'; }).length;
    var progress = { steps: steps, summary: done + ' of ' + applicable + ' steps' };

    var deadline = null;
    if (!settled && ns[0] && tl.length) {
      var last = tl[tl.length - 1], a = Date.parse(last.at), b = nextTs(ns[0]);
      var ls = liveStatus(a, b, now);
      deadline = {
        title: /^Request proof/.test(last.action || '') && win.proof ? span(win.proof, true) + ' proof window' : 'Time to the next step',
        status: ls.status, fill: ls.fill, start: fmtMin(last.at), end: nextLabel(ns[0]), liveFrom: a, liveTo: b
      };
    }

    var W = (win.response || 0) * 1000, answer = null, answerTitle = span(win.response, true) + ' answer window';
    if (!W) { /* window not in the data: no bar */ }
    else if (claimE && resp) {
      var ms = Date.parse(resp.at) - Date.parse(claimE.at);
      answer = { title: answerTitle, status: 'store answered after ' + dur(ms), fill: pct(ms / W), start: fmtMin(claimE.at) + ', claim', end: fmtMin(new Date(Date.parse(claimE.at) + W).toISOString()) + ', window end' };
    } else if (claimE && !resp) {
      var a2 = Date.parse(claimE.at), ls2 = liveStatus(a2, a2 + W, now);
      answer = { title: answerTitle, status: ls2.status, fill: ls2.fill, start: fmtMin(claimE.at) + ', claim', end: fmtMin(new Date(a2 + W).toISOString()), liveFrom: a2, liveTo: a2 + W };
    } else {
      var cl = ns.find(function (s) { return /^Claim/.test(s.what || ''); }), mk = ns.find(function (s) { return /no-response/i.test(s.what || ''); });
      if (cl && mk) answer = { title: answerTitle, status: 'not open yet', fill: '0%', start: cl.date + ', claim', end: mk.date + ', no-response marker', note: 'Opens when the claim is registered on Arc.' };
    }

    var delay = null;
    if (propose && exec) {
      var dms = Date.parse(exec.at) - Date.parse(propose.at);
      var dl = (params.verdict_delay_seconds || 0) * 1000;
      delay = {
        title: 'Verdict delay, ' + fmtSecs(params.verdict_delay_seconds || 0) + ' on testnet', status: 'executed after ' + dur(dms), fill: '100%',
        tick: dl > 0 ? pct(dl / dms) : '', start: fmtMin(propose.at) + ', proposed', end: fmtMin(exec.at) + ', executed',
        note: 'The tick marks the earliest moment the verdict could be executed.'
      };
    }

    var verdictMoney = function (V) {
      return V.outcome === 'REFUND' ? centsTxt(V.refund_cents) + ' refunded to buyer'
        : V.outcome === 'DENY' ? usdc(c.amount_usdc - (Number(V.refund_cents) || 0) / 100) + ' released to store' : 'No money moved yet';
    };
    var plainOf = function (V) {
      return 'Reason: ' + V.reason + '. ' + (V.final ? 'Final decision.' : 'Not final' + (V.action && V.action !== 'decide' ? ', next: ' + String(V.action).replace(/_/g, ' ') : '') + '.');
    };
    var atts = c.attempts || [];
    var vv = verdicts.map(function (v) {
      var V = v.verdict || {};
      var aList = ((atts.find(function (x) { return x.step === v.step; }) || {}).attempts) || [];
      var carried = tl.find(function (e) { return e.chain === 'arc' && e.actor === 'relayer' && e.at > (V.judged_at || ''); });
      return {
        label: 'Step ' + v.step, outcome: V.outcome, color: outColor(V.outcome), cents: String(V.refund_cents), amount: centsTxt(V.refund_cents),
        money: verdictMoney(V), plain: plainOf(V), reason: V.reason, judgedAt: fmtAt(V.judged_at), tx: v.tx, url: v.url,
        attempts: aList.map(function (x, i) { return { n: 'Attempt ' + (i + 1), tx: x.tx, url: x.url, gen: x.gen + ' GEN', result: x.result, votes: x.votes }; }),
        hasResend: aList.some(function (x) { return isResent(x.result); }),
        claimHash: V.claim_hash, chain: V.chain,
        claimMatch: !!(c.claim && c.claim.hash === V.claim_hash), claimMismatch: !!(c.claim && V.claim_hash && c.claim.hash !== V.claim_hash),
        carried: carried ? { tx: carried.tx, url: carried.url, action: carried.action + ', ' + fmtMin(carried.at) } : null
      };
    });
    var heroV = vv[vv.length - 1];
    var S = c.settlement;
    var settledMoney = !S ? '' : (S.refund_usdc > 0 && heroV && heroV.outcome !== 'DENY') ? usdc(S.refund_usdc) + ' refunded to buyer' : usdc(S.released_usdc) + ' released to store';
    var hero = null;
    if (heroV) {
      var H = HERO[heroV.outcome] || HERO.DENY;
      var money = S ? settledMoney : heroV.money;
      var mm = /^([\d.]+ USDC) (.+)$/.exec(money || '');
      hero = Object.assign({}, heroV, {
        amt: mm ? mm[1] : money, dir: mm ? mm[2] : '', big: !!mm, icon: H.icon,
        tint: 'oklch(0.5 ' + H.c + ' ' + H.h + ' / 0.16)', ring: 'oklch(0.7 ' + H.c + ' ' + H.h + ' / 0.55)', glow: 'oklch(0.7 ' + H.c + ' ' + H.h + ' / 0.12)'
      });
    }
    var evr = exp.map(function (e, i) {
      var v = verdicts.find(function (x) { return x.step === i + 1; }), V = v && v.verdict;
      return {
        step: 'Step ' + (i + 1), e: e, V: V,
        match: v ? (v.matches_expected === true ? 'ok' : v.matches_expected === false ? 'bad' : '') : 'pending'
      };
    });
    var moneyLine = !S ? '' : (S.refund_usdc > 0 && (lastV ? lastV.verdict.outcome !== 'DENY' : true)) ? usdc(S.refund_usdc) + ' refunded to buyer' : usdc(S.released_usdc) + ' released to store';
    var settlement = S ? {
      refund: usdc(S.refund_usdc), released: usdc(S.released_usdc),
      refundW: pct(S.refund_usdc / c.amount_usdc), releasedW: pct(S.released_usdc / c.amount_usdc), tx: S.tx, url: S.url, note: S.note || ''
    } : null;

    var formatted = '';
    if (c.claim) { try { formatted = JSON.stringify(JSON.parse(c.claim.text), null, 2); } catch (e) { formatted = c.claim.text; } }

    var emailId = function (s) { var m = /email (X\w+)/i.exec(s || ''); return m ? m[1] : null; };
    var yn = function (s, k) { return s.replace(new RegExp(k + ' True', 'i'), k).replace(new RegExp(k + ' False', 'i'), 'not ' + k); };
    var evidence = [];
    tl.forEach(function (e) {
      var act = e.action || '';
      if (/^Submit:/.test(act)) {
        evidence.push({ at: fmtAt(e.at), actor: e.actor, action: act, net: netOf(e.chain, act), tx: e.tx, url: e.url });
      } else if (/attested on Lacre/i.test(act)) {
        var id = emailId(act);
        var sign = tl.find(function (x) { return x !== e && emailId(x.action) === id && /signed/i.test(x.action || ''); });
        var detail = yn(yn(act.split(/attested on Lacre:\s*/i)[1] || '', 'valid'), 'aligned');
        var dkim = sign ? (/\(([^)]+)\)/.exec(sign.action) || [])[1] : '';
        evidence.push({
          at: fmtAt(e.at), actor: sign ? 'signed ' + fmtMin(sign.at) + ', attested' : 'attested',
          action: 'Email ' + id + (sign ? ', signed by the store' + (dkim ? ' (' + dkim + ')' : '') : '') + ', attested on Lacre' + (detail ? ': ' + detail : ''),
          net: 'lacre', tx: e.tx, url: e.url
        });
      }
    });
    var timeline = tl.map(function (e) {
      var cost = e.gas_usdc != null ? e.gas_usdc + ' USDC gas' : e.gen != null ? e.gen + ' GEN' : '';
      return { at: fmtAt(e.at), actor: e.actor, action: e.action, net: netOf(e.chain, e.action), tx: e.tx, url: e.url, cost: cost, isResend: /no consensus/i.test(e.action || '') };
    });
    var eb = (c.expected && c.expected.settlement_usdc) || {};
    var claimNext = ns.find(function (x) { return /\bclaim\b/i.test(x.what || ''); });

    return {
      id: c.id, title: c.title, story: c.story, path: c.path, orderNumber: c.order_number, amount: usdc(c.amount_usdc),
      stage: plainText(c.stage), isSettled: settled, isProgress: c.status === 'in_progress',
      progress: progress, nextSteps: ns.map(function (s) { return { date: nextLabel(s), what: s.what }; }),
      deadline: deadline, answer: answer, delay: delay, verdicts: vv, hero: hero, heroV: heroV,
      lastLine: heroV ? heroV.outcome + ' ' + (S ? moneyLine : heroV.amount) + ', ' + heroV.reason : '',
      moneyLine: moneyLine, evr: evr,
      expectedLine: exp.map(function (e) { return e.outcome + ' ' + centsTxt(e.refund_cents) + ' (' + e.reason + ')'; }).join(', then '),
      expBuyer: eb.buyer != null ? usdc(eb.buyer) : '', expStore: eb.merchant != null ? usdc(eb.merchant) : '',
      settlement: settlement, claim: c.claim, claimFormatted: formatted,
      claimTx: claimE ? claimE.tx : '', claimUrl: claimE ? claimE.url : '', claimAt: claimE ? fmtMin(claimE.at) : '',
      claimOpens: claimNext ? 'opens on ' + claimNext.date : 'not opened yet',
      langNote: c.id === 'E', evidence: evidence, timeline: timeline
    };
  }

  /* App state */
  var ROUTES = ['overview', 'how-it-works', 'order-flow', 'live-cases', 'case', 'judges', 'measurements', 'contracts', 'resources', 'demo-shop', 'my-orders'];
  var ALIAS = { how: 'how-it-works', flow: 'order-flow', cases: 'live-cases', 'try': 'demo-shop', shop: 'demo-shop', orders: 'my-orders' };
  var state = { data: null, cases: [], route: { screen: 'overview', caseId: null }, lastCase: null, flow: 'all', stopGlobe: null };

  function parseHash() {
    var h = (location.hash || '').replace(/^#\/?/, '');
    var parts = h.split('/');
    var s = ALIAS[parts[0]] || parts[0];
    var ok = ROUTES.indexOf(s) !== -1;
    return { screen: ok ? s : 'overview', caseId: ok && parts[1] ? decodeURIComponent(parts[1]) : null };
  }

  /* Screens */
  function renderOverview(d) {
    var cases = state.cases;
    var settledN = cases.filter(function (c) { return c.isSettled; }).length;
    var progN = cases.filter(function (c) { return c.isProgress; }).length;
    var bc = (d.bradbury_run && d.bradbury_run.cases) || [];
    var passedN = bc.filter(function (b) { return b.passed; }).length;
    var runs = (d.measurements && d.measurements.runs) || [];
    var c3 = runs.find(function (r) { return r.id === 'C3'; });
    var c3v = c3 && c3.results ? c3.results['correct decision'] : '';
    var p = d.project || {};
    var mini = [['coins', 'Pay on Arc'], ['filePlus', 'Open a claim'], ['scales', 'Judged on GenLayer'], ['checkCircle', 'Settled in USDC']];
    var stat = function (label, badge, big, sub, subTitle, fillP) {
      return '<div class="card stat"><div class="stat-top"><span class="eyebrow">' + esc(label) + '</span>' + badge + '</div>' +
        '<span class="stat-big">' + esc(big) + '</span><span class="stat-sub" title="' + esc(subTitle || '') + '">' + esc(sub) + '</span>' + fill(fillP) + '</div>';
    };
    var rows = cases.length ? cases.map(function (c) {
      var right = c.isSettled
        ? statusPill(c) + '<span class="mono" style="font-size:12px;color:' + (c.heroV ? c.heroV.color : 'var(--color-text)') + '">' + esc(c.lastLine) + '</span>'
        : statusPill(c) + (c.nextSteps[0] ? '<span style="font-size:12.5px;color:var(--color-neutral-200)"><span class="mono nowrap" style="color:var(--warn-fg)">Next ' + esc(c.nextSteps[0].date) + '</span> ' + esc(c.nextSteps[0].what) + '</span>' : '');
      return '<a class="case-row" href="#case/' + encodeURIComponent(c.id) + '"><span class="case-id">' + esc(c.id) + '</span>' +
        '<span style="flex:1 1 280px;min-width:0;display:flex;flex-direction:column;gap:3px"><span style="font-size:14.5px">' + esc(c.title) + '</span><span class="dim pretty" style="font-size:12.5px">' + esc(c.stage) + '</span></span>' +
        '<span style="flex:0 1 210px;min-width:160px">' + claimSteps(c.progress, false) + '</span>' +
        '<span style="flex:1 1 220px;min-width:0;display:flex;flex-direction:column;gap:4px;align-items:flex-start">' + right + '</span></a>';
    }).join('') : '<p class="muted" style="padding:0 12px 12px;font-size:14px">The live test has not started.</p>';

    return '<section class="card hero"><div class="hero-globe" aria-hidden="true"><canvas id="globe"></canvas></div>' +
      '<div class="hero-inner"><span class="kicker">01 / Overview</span><h1>' + esc(p.name) + '</h1>' +
      '<p class="hero-tagline">' + esc(p.tagline) + '</p>' +
      '<p class="hero-lede">The money is held in escrow on Arc. If something goes wrong, a GenLayer judge decides and the escrow carries out the verdict.</p>' +
      '<div class="mini-flow" role="list" aria-label="How a dispute runs">' + mini.map(function (m, i) {
        return '<div role="listitem"><div class="node"><span class="circle">' + icon(m[0]) + '</span><span class="line"></span></div><span class="n">' + pad2(i + 1) + '</span><span class="t">' + esc(m[1]) + '</span></div>';
      }).join('') + '</div>' +
      '<div class="row"><a class="btn btn-primary btn-lg" href="#live-cases">Live cases' + icon('arrowRight') + '</a><a class="btn btn-secondary btn-lg" href="#how-it-works">How it works</a><a class="btn btn-secondary btn-lg" href="#demo-shop">Open the Demo Shop</a></div>' +
      '</div></section>' +
      '<div class="stat-row">' +
      stat('Live test', netBadge('arc'), settledN + ' settled', progN + ' in progress', '', pct(cases.length ? settledN / cases.length : 0)) +
      stat('Bradbury run', netBadge('bradbury'), passedN + ' of ' + bc.length, 'verdicts as expected', d.bradbury_run && d.bradbury_run.summary, pct(bc.length ? passedN / bc.length : 0)) +
      (c3 ? stat('Committee', '<span class="mono faint" style="font-size:10.5px">run ' + esc(c3.id) + '</span>', c3v, 'correct decisions', c3.what + '.', pct(frac(c3v))) : '') +
      '</div>' +
      '<section class="card"><div class="card-head"><span style="color:var(--color-accent);font-size:17px;display:inline-flex">' + icon('pulse') + '</span><span class="label-up" style="font-size:11.5px;color:var(--color-neutral-100)">Live test status</span>' +
      '<a class="btn btn-ghost ml-auto" href="#live-cases">All live cases' + icon('arrowRight') + '</a></div><div class="case-rows">' + rows + '</div></section>';
  }

  function renderHow(d) {
    var contracts = d.contracts || [];
    var escrow = contracts.find(function (x) { return x.chain === 'arc'; }) || {};
    var p = escrow.params || {};
    var judges = contracts.filter(function (x) { return x.chain === 'bradbury' && /^Judge/.test(x.name); });
    var lc = d.live_cases || [];
    var lacreEx = null, lacreCase = '';
    var lacreSite = (contracts.find(function (x) { return /Lacre/i.test(x.name); }) || {}).project_url;
    lc.some(function (c) { var e = (c.timeline || []).find(function (t) { return /attested on Lacre/.test(t.action || ''); }); if (e) { lacreEx = e; lacreCase = c.id; } return !!e; });
    var reverts = [];
    lc.forEach(function (c) { (c.checks || []).forEach(function (k) { if (k.got === k.want && reverts.indexOf(k.got) === -1) reverts.push(k.got); }); });
    var paidIn = sum(lc, function (c) { return c.amount_usdc; });
    var refunded = sum(lc, function (c) { return c.settlement ? c.settlement.refund_usdc : 0; });
    var released = sum(lc, function (c) { return c.settlement ? c.settlement.released_usdc : 0; });

    var box = function (cls, ic, title, sub, badge) {
      return '<div class="dg-box ' + cls + '"><div class="t">' + icon(ic) + '<span>' + esc(title) + '</span></div><span class="s">' + esc(sub) + '</span>' + (badge ? '<div>' + badge + '</div>' : '<div class="spacer"></div>') + '</div>';
    };
    var conn = function (label, both, dashed, onlyLeft) {
      var l = (both || onlyLeft) ? icon('caretLeft') : '';
      var r = onlyLeft ? '' : icon('caretRight');
      return '<div class="dg-conn" aria-hidden="true"><span class="lbl">' + esc(label) + '</span><div class="ln">' + l + '<span' + (dashed ? ' class="dash"' : '') + '></span>' + r + '</div></div>';
    };
    var cell = function (k, v) { return '<div><span class="cell-k">' + esc(k) + '</span><span class="cell-v">' + esc(v) + '</span></div>'; };
    var outRow = function (k, color, v) { return '<div><span class="k" style="color:' + color + '">' + k + '</span><span class="v">' + esc(v) + '</span></div>'; };

    return '<div class="screen-head-row"><div><span class="kicker">02 / How it works</span><h2>Three systems, and a relayer that cannot cheat</h2></div>' +
      '<a class="btn btn-ghost" href="#order-flow">Step by step in Order flow' + icon('arrowRight') + '</a></div>' +
      '<section class="card diagram" aria-label="System diagram"><div class="dg-row">' +
      box('', 'user', 'Buyer', 'pays, claims, withdraws') + conn('USDC', false) +
      box('dg-arc', 'vault', 'Escrow', 'holds the money', netBadge('arc', { short: true })) + conn('submissions', true) +
      box('', 'arrowsClockwise', 'Relayer', 'only carries data') + conn('verdict', true) +
      box('dg-brad', 'scales', 'Judge', 'decides by policy', netBadge('bradbury', { short: true })) + conn('signed emails', false, true, true) +
      box('dg-lacre', 'lacre', 'Lacre', 'attests DKIM signatures', netBadge('lacre', { short: true })) +
      '</div></section>' +
      '<div class="auto-grid ag-400">' +
      '<article class="card card-pad"><div class="row" style="justify-content:space-between"><h4>Arc holds the money.</h4>' + netBadge('arc', { role: true }) + '</div>' +
      '<p class="muted pretty" style="font-size:13.5px">USDC goes into the escrow. It only refunds the buyer or releases the payment to the store, and the two always add up to the order amount.</p>' +
      '<div class="col" style="gap:10px"><div>' + hashChip(escrow.address, escrow.url) + '</div>' +
      '<div class="grid-cells grid-2">' + cell('Token', p.token || '') + cell('Cap per order', p.cap_per_order_usdc != null ? usdc(p.cap_per_order_usdc) : '') +
      cell('Verdict delay', p.verdict_delay_seconds != null ? fmtSecs(p.verdict_delay_seconds) : '') + cell('Store hold', p.store_hold_days != null ? p.store_hold_days + ' days' : '') + '</div>' +
      '<div class="live-total"><span class="eyebrow faint" style="font-size:10px">In the live test</span>' +
      (lc.length ? '<div class="grid-cells grid-3">' +
        '<div><span class="cell-k">Paid into the escrow</span><span class="cell-v">' + usdc(paidIn) + '</span></div>' +
        '<div><span class="cell-k">Refunded to buyers</span><span class="cell-v refund">' + usdc(refunded) + '</span></div>' +
        '<div><span class="cell-k">Released to the store</span><span class="cell-v">' + usdc(released) + '</span></div></div>'
        : '<span class="dim" style="font-size:12.5px">The live test has not started.</span>') +
      '</div></div></article>' +
      '<article class="card card-pad"><div class="row" style="justify-content:space-between"><h4>GenLayer judges.</h4>' + netBadge('bradbury', { role: true }) + '</div>' +
      '<p class="muted pretty" style="font-size:13.5px">' + esc(cap(word(judges.length))) + ' judge ' + (judges.length === 1 ? 'contract asks' : 'contracts ask') + ' the validator committee closed questions, then apply the store\'s published policy in code.</p>' +
      '<div class="col" style="gap:8px">' + judges.map(function (j) { return '<div class="col" style="gap:5px"><span style="font-size:12.5px;color:var(--color-neutral-100)">' + esc(j.name) + '</span><div>' + hashChip(j.address, j.url, 'bradbury') + '</div></div>'; }).join('') + '</div>' +
      '<div class="col inset outcome-table">' +
      outRow('REFUND', 'var(--out-refund)', 'The escrow pays the refund to the buyer.') +
      outRow('DENY', 'var(--color-neutral-200)', 'The payment is released to the store.') +
      outRow('NOT_YET', 'var(--out-notyet)', 'Another round or a deadline is needed.') +
      outRow('INVALID_CLAIM', 'var(--out-invalid)', 'The claim does not name this order correctly.') + '</div></article>' +
      '<article class="card card-pad">' + lacreMark() + '<div class="row" style="justify-content:space-between"><h4>Lacre verifies the emails.</h4>' + netBadge('lacre', { role: true }) + '</div>' +
      '<p class="muted pretty" style="font-size:13.5px">A store email counts only if its DKIM signature was attested on Lacre, it names this order and it was signed after the payment.</p>' +
      (lacreSite ? '<a class="row" style="gap:4px;font-size:12.5px" href="' + esc(lacreSite) + '" target="_blank" rel="noopener noreferrer">' + esc(lacreSite.replace(/^https?:\/\//, '')) + icon('arrowUpRight', '', 'font-size:11px') + '</a>' : '') +
      (lacreEx ? '<div class="col well-dark" style="gap:8px;padding:12px 14px"><span class="eyebrow faint" style="font-size:10px">Case ' + esc(lacreCase) + '</span><span style="font-size:13px">' + esc(lacreEx.action) + '</span><div>' + hashChip(lacreEx.tx, lacreEx.url, 'lacre') + '</div></div>' : '') +
      '</article>' +
      '<article class="card card-pad"><h4>The relayer only carries data.</h4>' +
      '<p class="muted pretty" style="font-size:13.5px">Every submission is registered on Arc and chained. The escrow accepts a verdict only for its own current chain and claim hash.</p>' +
      '<code class="well-dark" style="display:block;padding:12px 14px;font-size:12px;color:var(--color-accent-300);overflow-x:auto;white-space:pre">chain = sha256(previous chain || sha256(submission))</code>' +
      (reverts.length ? '<div class="row" style="gap:6px 8px"><span class="faint" style="font-size:11.5px">Reverted in the live test</span>' + reverts.map(function (x) { return '<span class="chip-err">' + esc(x) + '</span>'; }).join('') + '</div>' : '') + '</article>' +
      '</div>' +
      '<div class="col inset" style="gap:10px;padding:14px 18px"><span class="eyebrow faint">Who pays what</span>' +
      '<div class="auto-grid" style="grid-template-columns:repeat(auto-fit, minmax(min(100%, 280px), 1fr));gap:12px 24px;align-items:start">' +
      '<div class="col" style="align-items:flex-start;gap:6px">' + netBadge('arc') + '<span class="muted pretty" style="font-size:12.5px;line-height:1.45">Buyer and store pay Arc gas in USDC: pay, claim, answer, withdraw.</span></div>' +
      '<div class="col" style="align-items:flex-start;gap:6px">' + netBadge('bradbury') + '<span class="muted pretty" style="font-size:12.5px;line-height:1.45">The Tenet service pays every GenLayer transaction in GEN.</span></div>' +
      '</div></div>';
  }

  function renderFlow(d) {
    var lc = d.live_cases || [];
    var link = function (id) { return { kind: 'link', label: 'Open case ' + id, href: '#case/' + encodeURIComponent(id) }; };
    var ex = function (id, prefix) {
      var c = lc.find(function (x) { return x.id === id; });
      var e = c && (c.timeline || []).find(function (t) { return (t.action || '').indexOf(prefix) === 0; });
      return e && e.tx ? { kind: 'tx', label: 'Case ' + id + ': ' + plainText(e.action), tx: e.tx, url: e.url, net: netOf(e.chain, e.action) } : link(id);
    };
    var win = windows(d);
    var S = [
      ['Read the store\'s refund policy and its hash before paying', 'buyer', 'The store\'s published rules and their hash.', [{ kind: 'link', label: 'Contracts and policy', href: '#contracts' }, { kind: 'hash', label: 'terms_hash', tx: d.terms && d.terms.terms_hash }]],
      ['Approve USDC and pay into the escrow', 'buyer', 'Two Arc transactions; the money is held, not sent to the store.', [ex('E', 'Approve USDC for the escrow'), ex('E', 'Pay into escrow')]],
      ['Open a claim within the store\'s hold period', 'buyer', 'The claim names the order, the amount, the payment time and the problem.', [ex('E', 'Open claim')]],
      ['Add evidence (late deliveries: the store\'s own signed emails)', 'buyer', 'Each email is attested on Lacre first.', [ex('A', 'Email X01 attested on Lacre')]],
      ['Answer the claim' + (win.response ? ' within ' + span(win.response) : ''), 'store', 'Admit, deny, or dispute with a fact.', [ex('B', 'Submit: response')]],
      ['The judge reads what was registered and decides', 'judge (GenLayer)', 'A verdict with outcome, amount, reason and next action.', [ex('B', 'Step 1 sent to the judge')]],
      ['If a fact is disputed: a closing round, each side answers once', 'buyer and store', '', [ex('B', 'Submit: closing_proof'), ex('B', 'Submit: closing_response')]],
      ['If proof is missing: the buyer has ' + (win.proof ? span(win.proof) : 'a fixed window') + ' to send it', 'buyer', 'If nothing arrives, anyone releases the payment to the store.', [link('D')]],
      ['If the store never answers: a no-response marker' + (win.response ? ' after ' + span(win.response) : ''), 'anyone', '', [link('C'), { kind: 'note', label: 'scheduled' }]],
      ['The verdict is proposed on Arc and can be executed after the verdict delay', 'relayer, then anyone', 'The escrow credits the refund and the release.', [ex('E', 'Propose verdict on Arc'), ex('E', 'Execute verdict')]],
      ['Each side withdraws what it was credited', 'buyer, store', 'Pull payments.', [{ kind: 'note', label: 'Scheduled at the end of the test' }]]
    ];
    var escrow = (d.contracts || []).find(function (x) { return x.chain === 'arc'; }) || {};
    var delayS = escrow.params && escrow.params.verdict_delay_seconds;
    if (delayS != null) S[9][0] += ' (' + fmtSecs(delayS) + ' on testnet)';
    var COND = { 6: 'disputed fact', 7: 'missing proof', 8: 'store never answers' };
    var filter = state.flow;
    var filters = [['all', 'Everyone'], ['buyer', 'Buyer'], ['store', 'Store']];
    var exHtml = function (x) {
      if (x.kind === 'tx') return '<span class="row" style="gap:8px"><span class="lbl">' + esc(x.label) + '</span>' + hashChip(x.tx, x.url, x.net) + '</span>';
      if (x.kind === 'link') return '<a class="btn btn-ghost" href="' + x.href + '">' + esc(x.label) + icon('arrowRight') + '</a>';
      if (x.kind === 'hash') return x.tx ? '<span class="row" style="gap:8px"><span class="lbl">' + esc(x.label) + '</span>' + hashChip(x.tx) + '</span>' : '';
      return '<span class="flow-note">' + icon('calendar') + esc(x.label) + '</span>';
    };
    return '<div class="screen-head-row" style="gap:16px 24px"><div><span class="kicker">03 / Order flow</span><h2>One order, as the buyer and the store see it</h2>' +
      '<p class="muted pretty" style="font-size:15px">Each step links to the real transaction of a live case that shows it.</p></div>' +
      '<div class="seg" role="group" aria-label="View as">' + filters.map(function (f) {
        return '<button type="button" data-flow="' + f[0] + '" aria-pressed="' + (filter === f[0]) + '">' + f[1] + '</button>';
      }).join('') + '</div></div>' +
      '<ol class="flow">' + S.map(function (s, i) {
        var match = filter === 'all' || s[1].indexOf(filter) !== -1;
        var cond = COND[i];
        var dashUp = cond || COND[i - 1], dashDown = cond || COND[i + 1];
        return '<li class="' + (cond ? 'cond' : '') + (match ? '' : ' dim-step') + '">' +
          (i > 0 ? '<span class="up' + (dashUp ? ' dashed' : '') + '" aria-hidden="true"></span>' : '') +
          (i < S.length - 1 ? '<span class="down' + (dashDown ? ' dashed' : '') + '" aria-hidden="true"></span>' : '') +
          '<span class="num">' + (i + 1) + '</span><div class="body">' +
          (cond ? '<span class="only-if">' + icon('gitBranch') + '<b>Only if</b>' + esc(cond) + '</span>' : '') +
          '<div class="row" style="align-items:baseline"><span class="pretty" style="font-size:15px">' + esc(s[0]) + '</span><span class="tagline-chip">' + esc(s[1]) + '</span></div>' +
          (s[2] ? '<span class="muted pretty" style="font-size:13px">' + esc(s[2]) + '</span>' : '') +
          '<div class="flow-ex">' + s[3].map(exHtml).join('') + '</div></div></li>';
      }).join('') + '</ol>';
  }

  function renderCases() {
    var cases = state.cases;
    var updated = state.data && state.data.generated_at;
    return screenHead('04 / Live cases', 'The ' + word(cases.length) + ' cases of the live test', 'Real orders on Arc testnet, judged on GenLayer Bradbury. Each card shows where the case stands now.') +
      (updated ? '<span class="mono faint" style="font-size:11.5px">Last updated ' + esc(fmtAt(updated)) + '</span>' : '') +
      (cases.length ? cases.map(function (c) {
        var right;
        if (c.isSettled && c.settlement) {
          right = '<span class="eyebrow">Final outcome</span>' +
            '<div class="row" style="align-items:baseline;gap:12px"><span class="mono" style="font-size:24px;color:' + c.heroV.color + '">' + esc(c.heroV.outcome) + '</span><span style="font-size:20px">' + esc(c.moneyLine) + '</span><span class="dim" style="font-size:13px">' + esc(c.heroV.reason) + '</span></div>' +
            '<div class="col" style="gap:6px"><div class="split-bar"><div class="a" style="width:' + c.settlement.refundW + '"></div><div class="b" style="width:' + c.settlement.releasedW + '"></div></div>' +
            '<div class="row" style="justify-content:space-between;font-size:12px"><span style="color:var(--color-accent-300)">Refund to buyer ' + esc(c.settlement.refund) + '</span><span class="muted">Released to store ' + esc(c.settlement.released) + '</span></div></div>' +
            '<div>' + hashChip(c.settlement.tx, c.settlement.url, 'arc') + '</div>';
        } else {
          right = '<span class="eyebrow warn-kicker">Next scheduled</span><div class="col" style="gap:8px">' +
            c.nextSteps.map(function (n) { return '<div class="next-row"><span class="d">' + esc(n.date) + '</span><span class="w">' + esc(n.what) + '</span></div>'; }).join('') + '</div>' +
            (c.deadline ? timeBar(c.deadline) : '') +
            (c.heroV ? '<div class="row" style="align-items:baseline;padding-top:10px;box-shadow:inset 0 1px 0 var(--color-neutral-800)"><span class="dim" style="font-size:12px">Latest verdict</span><span class="mono" style="font-size:13px;color:' + c.heroV.color + '">' + esc(c.heroV.outcome + ' ' + c.heroV.amount) + '</span><span class="muted" style="font-size:13px">"' + esc(c.heroV.reason) + '"</span></div>' : '');
        }
        return '<article class="card case-card"><div class="l"><div class="row" style="gap:12px"><span class="case-id case-id-lg">' + esc(c.id) + '</span>' +
          '<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:2px"><span style="font-size:17px">' + esc(c.title) + '</span><span class="mono dim" style="font-size:11.5px">' + esc(c.path + ' / ' + c.orderNumber + ' / ' + c.amount) + '</span></div>' + statusPill(c, true) + '</div>' +
          '<span class="muted pretty" style="font-size:13.5px">' + esc(c.stage) + '</span>' + claimSteps(c.progress, true) +
          '<div><a class="btn btn-primary" href="#case/' + encodeURIComponent(c.id) + '">Open case ' + esc(c.id) + icon('arrowRight') + '</a></div></div>' +
          '<div class="r">' + right + '</div></article>';
      }).join('') : '<p class="card empty-note">The live test has not started.</p>');
  }

  function renderCase() {
    var cases = state.cases, route = state.route;
    if (!cases.length) return '<div class="card state-card"><h3>No cases yet</h3><p class="muted" style="font-size:14px">The live test has not started.</p><div><a class="btn btn-primary" href="#overview">' + icon('arrowLeft') + 'Back to Overview</a></div></div>';
    var id = route.caseId || state.lastCase || cases[0].id;
    var c = cases.find(function (x) { return x.id === id; });
    if (!c) return '<div class="card state-card"><h3>Case not found</h3><p class="muted" style="font-size:14px">There is no case "' + esc(id) + '" in the data file.</p><div><a class="btn btn-primary" href="#live-cases">' + icon('arrowLeft') + 'Back to Live cases</a></div></div>';
    state.lastCase = c.id;
    var mono = function (t, color, size) { return '<span class="mono" style="font-size:' + (size || 12) + 'px' + (color ? ';color:' + color : '') + '">' + esc(t) + '</span>'; };
    var html = '<div class="detail"><div class="detail-main">';
    html += '<div class="row" style="gap:12px"><a class="btn btn-ghost" href="#live-cases">' + icon('arrowLeft') + 'Back to live cases</a><span class="ml-auto mono faint" style="font-size:11px">05 / Case detail</span></div>';
    html += '<section class="card detail-head"><div class="row" style="gap:12px"><span class="mono muted" style="font-size:12px;letter-spacing:0.12em;text-transform:uppercase">Case ' + esc(c.id) + '</span><span class="ml-auto"></span>' +
      (c.isSettled ? '<span class="status-tag status-settled">Settled</span>' : c.isProgress ? '<span class="status-tag status-progress">In progress</span>' : '') + '</div>' +
      '<h2 style="font-size:28px">' + esc(c.title) + '</h2><p class="muted pretty" style="font-size:14px;max-width:720px">' + esc(c.story) + '</p>' +
      '<div class="flex-cells">' +
      '<div><span class="cell-k-up">Path</span><span class="cell-v">' + esc(c.path) + '</span></div>' +
      '<div><span class="cell-k-up">Order</span><span class="cell-v">' + esc(c.orderNumber) + '</span></div>' +
      '<div><span class="cell-k-up">Amount</span><span class="cell-v">' + esc(c.amount) + '</span></div>' +
      '<div style="flex:2 1 240px"><span class="cell-k-up">Stage</span><span class="pretty" style="font-size:13px">' + esc(c.stage) + '</span></div></div>' +
      claimSteps(c.progress, true) +
      (c.nextSteps.length ? '<div class="next-box"><div class="row" style="align-items:baseline;gap:14px"><span class="eyebrow warn-kicker">Next date</span>' + mono(c.nextSteps[0].date, 'var(--color-text)', 20) + '<span class="pretty" style="font-size:13.5px;color:var(--color-neutral-200)">' + esc(c.nextSteps[0].what) + '</span></div>' + (c.deadline ? timeBar(c.deadline) : '') + '</div>' : '') +
      '</section>';

    /* Claim */
    if (c.claim) {
      html += '<section class="card">' + cardHead('fileText', 'Claim', netBadge('arc') + '<div class="seg seg-sm ml-auto" role="group" aria-label="Claim view"><button type="button" data-claim-view="fmt" aria-pressed="true">Formatted</button><button type="button" data-claim-view="exact" aria-pressed="false">Exact text</button></div>') +
        '<div class="card-body"><div class="row" style="gap:10px 24px">' +
        '<div class="col" style="gap:6px"><span class="dim" style="font-size:11.5px">claim.hash, SHA-256 held by the escrow and the judge</span><div>' + hashChip(c.claim.hash) + '</div></div>' +
        (c.claimTx ? '<div class="col" style="gap:6px"><span class="dim" style="font-size:11.5px">Opened on Arc ' + esc(c.claimAt) + '</span><div>' + hashChip(c.claimTx, c.claimUrl, 'arc') + '</div></div>' : '') + '</div>' +
        '<pre class="claim-pre well-dark" data-claim="fmt">' + esc(c.claimFormatted) + '</pre><pre class="claim-pre well-dark" data-claim="exact" hidden>' + esc(c.claim.text) + '</pre>' +
        (c.langNote ? '<div class="row muted" style="gap:8px;font-size:12.5px"><span style="color:var(--color-accent-300);font-size:15px;display:inline-flex">' + icon('translate') + '</span><span>This claim was written in Spanish. The judge reads any language.</span></div>' : '') +
        '</div></section>';
    } else html += collapsedRow('fileText', 'Claim', c.claimOpens);

    /* Evidence */
    if (c.evidence.length) {
      html += '<section class="card">' + cardHead('shieldCheck', 'Evidence', '<span class="ml-auto mono dim" style="font-size:11px">' + c.evidence.length + (c.evidence.length === 1 ? ' submission' : ' submissions') + '</span>') +
        '<div class="card-body"><div class="col">' + c.evidence.map(function (e) {
          return '<div class="ev-row">' + icon('checkCircle') + '<span class="txt"><span>' + esc(e.action) + '</span><span>' + esc(e.actor + ' / ' + e.at) + '</span></span>' + (e.tx ? hashChip(e.tx, e.url, e.net) : netBadge('offchain')) + '</div>';
        }).join('') + '</div>' + (c.answer ? timeBar(c.answer) : '') +
        '<span class="faint pretty" style="font-size:12px">Every submission is registered on Arc and extends the escrow\'s hash chain.</span></div></section>';
    } else html += collapsedRow('shieldCheck', 'Evidence', 'none registered yet');

    /* Decision */
    html += '<section class="card decision">' + cardHead('scales', 'Decision', netBadge('bradbury')) + '<div class="card-body" style="gap:20px;padding-bottom:22px">';
    if (c.hero) {
      var h = c.hero;
      html += '<div class="verdict-hero" style="background:radial-gradient(120% 160% at 0% 0%, ' + h.tint + ', transparent 60%), var(--color-bg);box-shadow:inset 0 0 0 1px ' + h.ring + ', 0 0 40px ' + h.glow + '">' +
        '<span class="orb" style="background:' + h.tint + ';box-shadow:inset 0 0 0 1px ' + h.ring + ', 0 0 24px ' + h.glow + ';color:' + h.color + '">' + icon(h.icon) + '</span>' +
        '<div class="mid"><span class="out" style="color:' + h.color + '">' + esc(h.outcome) + '</span>' +
        '<div class="row" style="align-items:baseline;gap:4px 12px"><span class="amt" style="font-size:' + (h.big ? '44px;white-space:nowrap' : '28px') + '">' + esc(h.amt) + '</span>' + (h.dir ? '<span class="nowrap" style="font-size:16px;color:var(--color-neutral-200)">' + esc(h.dir) + '</span>' : '') + '</div>' +
        '<span class="pretty" style="font-size:14px;color:var(--color-neutral-200)">' + esc(h.plain) + '</span></div>' +
        '<div class="side"><span class="eyebrow" style="letter-spacing:0.1em">' + esc(h.label) + '</span><span class="mono faint" style="font-size:10.5px">judged at (contract time) ' + esc(h.judgedAt) + '</span><div>' + hashChip(h.tx, h.url, 'bradbury') + '</div></div></div>';

      html += '<div class="col" style="gap:10px"><span class="eyebrow">Expected versus result</span>' + c.evr.map(function (r) {
        var e = r.e, V = r.V;
        var m = r.match === 'ok' ? '<span class="ml-auto row mono" style="gap:5px;font-size:11px;color:var(--color-accent-300)">' + icon('check') + 'Matches expected</span>'
          : r.match === 'bad' ? '<span class="ml-auto mono" style="font-size:11px;color:var(--error-fg)">Does not match</span>'
          : r.match === 'pending' ? '<span class="ml-auto mono" style="font-size:11px;color:var(--warn-fg)">pending</span>' : '';
        return '<div class="evr inset"><div class="h"><span class="nowrap" style="color:var(--color-neutral-200)">' + esc(r.step) + '</span>' + m + '</div>' +
          '<div class="line"><span class="c1">expected</span><span class="c2" style="color:' + outColor(e.outcome) + '">' + esc(e.outcome) + '</span><span class="c3">' + esc(centsTxt(e.refund_cents)) + '</span><span class="c4">' + esc(e.reason) + '</span><span class="c5">' + esc(e.action) + '</span></div>' +
          '<div class="line"><span class="c1">result</span><span class="c2" style="color:' + (V ? outColor(V.outcome) : 'var(--color-neutral-500)') + '">' + esc(V ? V.outcome : 'pending') + '</span><span class="c3">' + esc(V ? centsTxt(V.refund_cents) : '') + '</span><span class="c4">' + esc(V ? V.reason : '') + '</span><span class="c5">' + esc(V ? V.action : '') + '</span></div></div>';
      }).join('') + '</div>';

      html += '<div class="col" style="gap:10px"><span class="eyebrow">Verdicts and attempts</span>' + c.verdicts.map(function (v) {
        return '<div class="col well" style="gap:12px;padding:14px 16px"><div class="row" style="align-items:baseline;gap:6px 14px">' +
          '<span class="mono nowrap muted" style="font-size:12px">' + esc(v.label) + '</span><span class="mono nowrap" style="font-size:14px;color:' + v.color + '">' + esc(v.outcome + ' ' + v.money) + '</span>' +
          '<span class="pretty" style="font-size:13px;color:var(--color-neutral-200)">' + esc(v.plain) + '</span><span class="ml-auto mono faint nowrap" style="font-size:10.5px">judged at (contract time) ' + esc(v.judgedAt) + '</span></div>' +
          '<div>' + hashChip(v.tx, v.url, 'bradbury') + '</div><div class="col" style="gap:6px">' + v.attempts.map(function (a) {
            var rs = isResent(a.result);
            return '<div class="attempt well"><span class="n">' + esc(a.n) + '</span><span class="res ' + (rs ? 'res-resent' : 'res-ok') + '">' + icon(rs ? 'arrowsClockwise' : 'checkCircle') + esc(a.result) + '</span>' +
              (a.votes ? votesBar(a.votes) : '') + '<span class="end"><span class="gen">' + esc(a.gen) + '</span>' + hashChip(a.tx, a.url, 'bradbury') + '</span></div>';
          }).join('') + '</div>' +
          (v.hasResend ? '<div class="row muted pretty" style="gap:8px;align-items:flex-start;font-size:12.5px;flex-wrap:nowrap"><span style="font-size:14px;margin-top:2px;color:var(--out-notyet);display:inline-flex">' + icon('arrowsClockwise') + '</span><span>Resend, part of the protocol: the first transaction ended without votes, so the relayer sent the same step again. The verdict comes from the accepted attempt.</span></div>' : '') +
          '</div>';
      }).join('') + '</div>';
    } else {
      html += '<div class="verdict-hero well-dark" style="box-shadow:inset 0 0 0 1px var(--color-neutral-700)"><span class="orb" style="box-shadow:inset 0 0 0 1px var(--color-neutral-700);color:var(--color-neutral-300);font-size:28px">' + icon('hourglass') + '</span>' +
        '<div class="mid"><span class="out muted">NO VERDICT YET</span><span class="pretty" style="font-size:15px;color:var(--color-neutral-200)">Expected, fixed before the run: <span class="mono">' + esc(c.expectedLine) + '</span></span>' +
        '<span class="dim" style="font-size:13px">Expected settlement: buyer ' + esc(c.expBuyer) + ', store ' + esc(c.expStore) + '</span></div></div>';
    }
    html += '</div></section>';

    /* Hash check */
    if (c.verdicts.length) {
      html += '<section class="card">' + cardHead('linkH', 'Hash check') + '<div class="card-body"><p class="muted pretty" style="font-size:13px">The escrow accepts a verdict only for its own current chain and claim hash; any other value reverts with BadVerdict. Each verdict below shows the hashes it carries and the Arc transaction that accepted it.</p>' +
        c.verdicts.map(function (v) {
          return '<div class="col inset"><div class="row" style="padding:8px 14px;background:color-mix(in srgb, var(--color-text) 3%, transparent)"><span class="mono" style="font-size:11.5px">' + esc(v.label) + '</span>' +
            (v.claimMatch ? '<span class="ok-chip ml-auto">' + icon('equals') + 'claim hash match</span>' : v.claimMismatch ? '<span class="ml-auto mono" style="font-size:11px;color:var(--error-fg)">claim hash differs</span>' : '') + '</div>' +
            '<div class="hc-row"><span class="k">Claim hash on Arc</span>' + hashChip(c.claim && c.claim.hash) + '</div>' +
            '<div class="hc-row"><span class="k">Claim hash in the verdict</span>' + hashChip(v.claimHash, '', 'bradbury') + '</div>' +
            '<div class="hc-row"><span class="k">Chain the judge read</span>' + hashChip(v.chain, '', 'bradbury') + '</div>' +
            (v.carried ? '<div class="hc-row"><span class="k">Accepted on Arc</span>' + hashChip(v.carried.tx, v.carried.url, 'arc') + '<span class="muted" style="font-size:12px">' + esc(v.carried.action) + '</span></div>' : '') + '</div>';
        }).join('') + '</div></section>';
    } else html += collapsedRow('linkH', 'Hash check', 'available after the first verdict');

    /* Settlement */
    if (c.settlement) {
      var s = c.settlement;
      html += '<section class="card">' + cardHead('coins', 'Settlement', netBadge('arc')) + '<div class="card-body" style="gap:16px">' +
        '<div class="row" style="gap:12px;align-items:stretch"><div class="money-box money-refund"><span class="k">Refund to buyer</span><span class="v">' + esc(s.refund) + '</span></div><div class="money-box money-release"><span class="k">Released to store</span><span class="v">' + esc(s.released) + '</span></div></div>' +
        '<div class="split-bar"><div class="a" style="width:' + s.refundW + '"></div><div class="b" style="width:' + s.releasedW + '"></div></div>' +
        '<div class="row" style="gap:10px 16px"><span class="dim" style="font-size:12.5px">Execute verdict</span>' + hashChip(s.tx, s.url, 'arc') + '<span class="muted" style="font-size:12.5px">' + esc(s.note) + '</span></div>' +
        (c.delay ? timeBar(c.delay) : '') + '</div></section>';
    } else html += collapsedRow('coins', 'Settlement', 'not settled yet');
    html += '</div>';

    /* Timeline */
    html += '<aside class="timeline" aria-label="Timeline"><div class="row"><span style="font-size:17px;color:var(--color-neutral-300);display:inline-flex">' + icon('clockCcw') + '</span><span style="font-size:16px">Timeline</span><span class="ml-auto mono faint" style="font-size:11px">' + c.timeline.length + ' entries</span></div>' +
      '<span class="faint" style="font-size:11.5px">Sorted by time, UTC. Costs in USDC gas on Arc, GEN on Bradbury.</span><div class="col">' +
      c.timeline.map(function (e) {
        return '<div class="tl-item"><div class="top"><span class="at">' + esc(e.at) + '</span><span class="who">' + esc(e.actor) + '</span></div><span class="act">' + esc(e.action) + '</span>' +
          (e.isResend ? '<span class="resend-tag">' + icon('arrowsClockwise') + 'Resend, part of the protocol</span>' : '') +
          '<div class="row" style="gap:6px 10px">' + (e.tx ? hashChip(e.tx, e.url, e.net) : netBadge(e.net)) + (e.cost ? '<span class="cost">' + esc(e.cost) + '</span>' : '') + '</div></div>';
      }).join('') +
      c.nextSteps.map(function (n) {
        return '<div class="tl-item sched"><div class="top"><span class="at">' + esc(n.date) + '</span><span class="who">scheduled</span></div><span class="act">' + esc(n.what) + '</span></div>';
      }).join('') + '</div></aside></div>';
    return html;
  }

  function renderJudges(d) {
    var run = d.bradbury_run || {};
    var bc = run.cases || [];
    var passedN = bc.filter(function (b) { return b.passed; }).length;
    var judgeC = (d.contracts || []).filter(function (x) { return x.chain === 'bradbury' && /^Judge/.test(x.name); });
    var IGN = { I8: 'email about another order' };
    var outLine = function (V) { return V.outcome === 'REFUND' ? 'REFUND ' + centsTxt(V.refund_cents) : (V.outcome || ''); };
    var plainV = function (V) { return V.final ? 'Final decision.' : 'Not final' + (V.action && V.action !== 'decide' ? ', next: ' + String(V.action).replace(/_/g, ' ') : '') + '.'; };
    var group = function (key, title, matcher) {
      var k = judgeC.find(matcher);
      var list = bc.filter(function (b) { return b.contract === key; });
      if (!list.length) return '';
      return '<section class="col" style="gap:12px"><div class="row" style="gap:8px 14px"><h3>' + esc(k ? k.name : title) + '</h3><span class="mono dim nowrap" style="font-size:11.5px">contract ' + esc(key) + '</span>' +
        (k ? hashChip(k.address, k.url, 'bradbury') : '') + '<span class="ml-auto mono faint" style="font-size:11px">' + list.length + (list.length === 1 ? ' case' : ' cases') + '</span></div>' +
        '<div class="card table-wrap"><div class="tbl judges-tbl" role="table" aria-label="' + esc(k ? k.name : title) + '">' +
        '<div class="tbl-head" role="row"><span>Case</span><span>Title</span><span>Path</span><span>Final outcome</span><span>Votes</span><span>Attempts</span><span>Result</span><span></span></div>' +
        list.map(function (b) {
          var steps = b.steps || [];
          var last = steps[steps.length - 1] || {};
          var LV = last.verdict || {};
          var all = [].concat.apply([], steps.map(function (s) { return s.attempts || []; }));
          var resent = all.filter(function (a) { return isResent(a.result); }).length;
          var did = 'jd-' + b.id;
          return '<div class="tbl-group" role="rowgroup"><button type="button" class="tbl-row" role="row" data-toggle="' + did + '" aria-expanded="false" aria-controls="' + did + '">' +
            '<span class="mono" style="font-size:12.5px;color:var(--color-neutral-100)">' + esc(b.id) + '</span>' +
            '<span class="ellip" title="' + esc(b.title) + '" style="font-size:13.5px">' + esc(b.title) + '</span>' +
            '<span class="ellip mono dim" style="font-size:11.5px">' + esc(b.path) + '</span>' +
            '<span class="mono nowrap" style="font-size:12px;color:' + outColor(LV.outcome) + '">' + esc(outLine(LV)) + '</span>' +
            votesBar(last.votes, true) +
            '<span class="mono nowrap" style="font-size:12px;color:var(--color-neutral-200)">' + all.length + (resent ? ', ' + resent + ' resent' : '') + '</span>' +
            '<span>' + (b.passed === true ? '<span class="ok-chip">' + icon('check') + 'passed</span>' : b.passed === false ? '<span class="mono" style="font-size:11px;color:var(--error-fg)">not passed</span>' : '') + '</span>' +
            '<span class="chev">' + icon('caretDown') + '</span></button>' +
            '<div class="tbl-detail" id="' + did + '" hidden><div class="row"><span class="faint" style="font-size:11.5px">Claim hash</span>' + hashChip(b.claim_hash) + '</div>' +
            steps.map(function (s) {
              var E = s.expected || {}, V = s.verdict || {}, ign = V.ignored || [];
              return '<div class="jd-step well"><div class="row" style="align-items:baseline"><span class="mono" style="font-size:11.5px;color:var(--color-neutral-200)">Step ' + esc(s.step) + '</span><span class="ml-auto mono faint" style="font-size:10.5px">judged at (contract time) ' + esc(fmtAt(V.judged_at)) + '</span></div>' +
                '<div class="jd-line"><span>expected</span><span><span class="mono nowrap" style="font-size:12px;color:' + outColor(E.outcome) + '">' + esc(outLine(E)) + '</span><span style="font-size:12.5px;color:var(--color-neutral-200)">' + (E.reason ? 'Reason: ' + esc(E.reason) + '.' : '') + '</span><span class="dim" style="font-size:12px">' + esc(plainV(E)) + '</span></span></div>' +
                '<div class="jd-line"><span>verdict</span><span><span class="mono nowrap" style="font-size:12px;color:' + outColor(V.outcome) + '">' + esc(outLine(V)) + '</span><span style="font-size:12.5px;color:var(--color-neutral-200)">' + (V.reason ? 'Reason: ' + esc(V.reason) + '.' : '') + '</span><span class="dim" style="font-size:12px">' + esc(plainV(V)) + '</span></span></div>' +
                (ign.length ? '<div class="col" style="gap:6px"><span class="eyebrow" style="letter-spacing:0.1em">Ignored submissions</span>' + ign.map(function (x) {
                  return '<div class="row">' + hashChip(x[0]) + '<span class="mono" style="font-size:11.5px;color:var(--color-neutral-100)">' + esc(x[1]) + '</span>' + (IGN[x[1]] ? '<span class="muted" style="font-size:12.5px">' + esc(IGN[x[1]]) + '</span>' : '') + '</div>';
                }).join('') + '</div>' : '') +
                '<div class="col" style="gap:6px">' + (s.attempts || []).map(function (a, i) {
                  var rs = isResent(a.result);
                  return '<div class="jd-attempt"><span class="mono dim nowrap" style="font-size:11px">Attempt ' + (i + 1) + '</span><span class="res mono nowrap ' + (rs ? 'res-resent' : 'res-ok') + '" style="display:inline-flex;align-items:center;gap:5px;font-size:11px">' + icon(rs ? 'arrowsClockwise' : 'checkCircle') + esc(a.result) + '</span>' +
                    (a.result === 'accepted' ? votesBar(s.votes) : '') + '<span class="ml-auto row" style="gap:10px"><span class="mono dim nowrap" style="font-size:10.5px">' + esc(a.gen + ' GEN') + '</span>' + hashChip(a.tx, a.url, 'bradbury') + '</span></div>';
                }).join('') + '</div></div>';
            }).join('') + '</div></div>';
        }).join('') + '</div></div></section>';
    };
    return screenHead('06 / Judges on GenLayer', 'The Bradbury run', cap(word(bc.length)) + ' cases sent directly to the ' + word(judgeC.length) + ' judge contracts on the real network, one or more per path. ' +
      (passedN === bc.length ? 'All ' + word(bc.length) + ' are closed.' : word(passedN) + ' of ' + word(bc.length) + ' are closed.')) +
      '<div class="card row" style="gap:16px 28px;padding:20px 24px"><div class="col" style="gap:4px"><span style="font-size:40px;line-height:1;letter-spacing:-0.02em">' + passedN + ' of ' + bc.length + '</span><span class="dim" style="font-size:12px">cases passed</span></div>' +
      '<div class="col" style="flex:1 1 320px;min-width:0;gap:10px"><span class="pretty" style="font-size:14px;color:var(--color-neutral-100)">' + esc(run.summary || '') + '</span>' + fill(pct(bc.length ? passedN / bc.length : 0)) + '</div>' + netBadge('bradbury', { role: true }) + '</div>' +
      (bc.length ? group('mail', 'Email judge', function (x) { return /email/i.test(x.name); }) + group('subjective', 'Subjective judge', function (x) { return !/email/i.test(x.name); })
        : '<p class="card empty-note">The Bradbury run has no cases yet.</p>');
  }

  function renderMeasurements(d) {
    var m = d.measurements || {};
    var runs = m.runs || [];
    var MLABEL = { q1: 'Question 1: does the item differ from the listing', q2: 'Question 2: type of store answer', q2r2: 'Question 2 in the closing round' };
    var ZERO = ['wrong refund', 'wrong denial', 'prompt injection that wins'];
    return screenHead('07 / Measurements', 'The numbers behind the judges\' prompts', 'Measured before deploying. Results are shown exactly as recorded.') +
      (m.committee ? '<div class="card row" style="gap:14px;align-items:flex-start;padding:18px 20px;flex-wrap:nowrap"><span style="font-size:20px;color:var(--color-accent);display:inline-flex;margin-top:1px">' + icon('usersThree') + '</span><div class="col" style="gap:4px"><span class="eyebrow">Committee</span><span class="pretty" style="font-size:14px">' + esc(m.committee) + '</span></div></div>' : '') +
      (runs.length ? '<div class="auto-grid ag-420">' + runs.map(function (r) {
        var stats = [['runs', r.runs != null ? String(r.runs) : 'not recorded', r.runs == null], ['readings', String(r.readings), false], ['cost', r.cost_usd + ' USD', false]];
        return '<article class="card card-pad" style="padding:18px 20px"><div class="row" style="align-items:flex-start;gap:12px;min-height:40px;flex-wrap:nowrap"><span class="mono" style="flex:none;padding:3px 8px;border-radius:6px;font-size:12px;box-shadow:inset 0 0 0 1px var(--color-neutral-700)">' + esc(r.id) + '</span><span class="pretty" style="font-size:14px">' + esc(r.what) + '</span></div>' +
          '<div class="grid-cells grid-3">' + stats.map(function (s) { return '<div><span class="cell-k">' + s[0] + '</span><span class="cell-v" style="color:' + (s[2] ? 'var(--color-neutral-500)' : 'var(--color-text)') + '">' + esc(s[1]) + '</span></div>'; }).join('') + '</div>' +
          '<div class="col" style="flex:1;justify-content:space-between;gap:10px">' + Object.keys(r.results || {}).map(function (k) {
            var v = r.results[k], fr = frac(v), color = fr >= 1 ? 'var(--color-accent)' : 'var(--color-neutral-400)';
            return '<div class="result-line"><div class="top"><span>' + esc(MLABEL[k] || k) + '</span><span class="row nowrap" style="gap:8px;align-items:baseline;flex-wrap:nowrap">' + (ZERO.indexOf(k) !== -1 ? '<span class="mono faint" style="font-size:10.5px">target 0</span>' : '') + '<span class="mono" style="font-size:12.5px">' + esc(v) + '</span></span></div>' +
              '<div class="bar"><i style="width:' + pct(fr) + ';background:' + color + ';box-shadow:none"></i></div></div>';
          }).join('') + '</div></article>';
      }).join('') + '</div>' : '<p class="card empty-note">No measurements recorded.</p>') +
      ((m.local_checks || []).length ? '<section class="card">' + cardHead('testTube', 'Local checks') + '<div class="col" style="padding:0 20px 12px">' + m.local_checks.map(function (k) {
        return '<div class="check-row"><span>' + esc(k.what) + '</span><span>' + icon('checkCircle', '', 'font-size:14px') + esc(k.result) + '</span></div>';
      }).join('') + '</div></section>' : '');
  }

  function renderContracts(d) {
    var contracts = d.contracts || [];
    var terms = d.terms || {};
    var arcN = (d.networks && d.networks.arc) || {};
    var num = function (n) { return Number(n).toLocaleString('en-US'); };
    var EVN = { late: 'Late delivery', not_as_described: 'Not as described', not_delivered: 'Not delivered' };
    var RF = ['event', 'refund_percent', 'wait_from', 'wait_days', 'deadline_from', 'deadline_days', 'late_grace_days'];
    var whenOf = function (r) {
      return r.late_grace_days > 0 ? 'Applies when it arrives more than ' + r.late_grace_days + ' days after the promised date.'
        : (r.wait_from !== 'none' && r.wait_days) ? 'Applies from ' + r.wait_days + ' days after the ' + (r.wait_from === 'promised' ? 'promised date' : r.wait_from) + '.'
        : 'Applies with no waiting period.';
    };
    var deadlineOf = function (r) { return r.deadline_from !== 'none' && r.deadline_days ? 'Claim within ' + r.deadline_days + ' days of ' + r.deadline_from + '.' : 'No claim deadline.'; };
    var dt = function (k, v) { return '<div><span class="k">' + esc(k) + '</span>' + v + '</div>'; };
    var txt = function (v) { return '<span class="v">' + esc(v) + '</span>'; };
    var rows = contracts.map(function (x, i) {
      var ext = !x.deploy_tx;
      var det = [];
      if (x.gas_used != null) det.push(dt('Gas used', txt(num(x.gas_used))));
      if (x.bytes != null) det.push(dt('Size', txt(num(x.bytes) + ' bytes')));
      if (x.sha256) det.push(dt('Source code SHA-256', '<span>' + hashChip(x.sha256) + '</span>'));
      if (x.prompt_hash) det.push(dt('Prompt hash', '<span class="row" style="gap:6px 10px">' + x.prompt_hash.split('|').filter(Boolean).map(function (v) { return hashChip(v); }).join('') + '</span>'));
      if (x.methods && x.methods.length) det.push(dt('Methods', '<span class="row" style="gap:4px">' + x.methods.map(function (m) { return '<span class="chip-method">' + esc(m) + '</span>'; }).join('') + '</span>'));
      if (x.source && !ext) det.push(dt('Source file', txt(x.source)));
      var p = x.params;
      if (p) {
        if (p.token) det.push(dt('Token', txt(p.token)));
        if (p.cap_per_order_usdc != null) det.push(dt('Cap per order', txt(usdc(p.cap_per_order_usdc))));
        if (p.verdict_delay_seconds != null) det.push(dt('Verdict delay', txt(fmtSecs(p.verdict_delay_seconds))));
        if (p.store_hold_days != null) det.push(dt('Store hold', txt(p.store_hold_days + ' days')));
      }
      var can = det.length > 0, did = 'ct-' + i;
      var cost = x.deploy_cost_usdc != null ? x.deploy_cost_usdc + ' USDC' : x.deploy_cost_gen != null ? x.deploy_cost_gen + ' GEN' : '';
      return '<div class="tbl-group" role="rowgroup"><div class="tbl-row' + (can ? ' clickable" tabindex="0" data-toggle="' + did + '" aria-expanded="false" aria-controls="' + did : '') + '" role="row">' +
        '<span class="ellip" title="' + esc(x.name) + '" style="font-size:13.5px">' + esc(x.name) + '</span>' +
        '<span>' + netBadge(/Lacre/i.test(x.name) ? 'lacre' : x.chain, { short: true }) + '</span>' +
        '<span>' + hashChip(x.address, x.url) + '</span>' +
        (ext ? '<span class="row nowrap" style="grid-column:span 2;min-width:0;flex-wrap:nowrap"><span class="muted" style="font-size:12.5px">External service, MIT, Insidr Labs</span>' + (x.project_url ? '<a class="mono row" style="gap:4px;font-size:11.5px" href="' + esc(x.project_url) + '" target="_blank" rel="noopener noreferrer">' + esc(x.project_url.replace(/^https?:\/\//, '')) + icon('arrowUpRight') + '</a>' : '') + '</span>'
          : '<span>' + hashChip(x.deploy_tx, x.deploy_url) + '</span><span class="mono nowrap" style="font-size:12px;color:var(--color-neutral-200)">' + esc(cost) + '</span>') +
        (can ? '<span class="chev">' + icon('caretDown') + '</span>' : '<span></span>') + '</div>' +
        (can ? '<div class="ct-detail" id="' + did + '" hidden>' + det.join('') + '</div>' : '') + '</div>';
    }).join('');
    var rules = (terms.rules || []).map(function (r, i) {
      var rid = 'rule-' + i;
      return '<article class="card card-pad" style="gap:12px;padding:18px 20px"><span style="font-size:14px;color:var(--color-neutral-200)">' + esc(EVN[r.event] || r.event) + '</span>' +
        '<span class="rule-big">' + esc(r.refund_percent) + '%<small>refund</small></span>' +
        '<div class="col muted pretty" style="gap:4px;font-size:13px"><span>' + esc(whenOf(r)) + '</span><span>' + esc(deadlineOf(r)) + '</span></div>' +
        '<div class="col" style="margin-top:auto;gap:8px"><button type="button" class="btn btn-ghost" style="align-self:flex-start;height:26px;font-size:12px" data-toggle="' + rid + '" aria-expanded="false" aria-controls="' + rid + '" data-label-open="Hide fields" data-label-closed="Show fields"><span class="chev-r" style="display:inline-flex">' + icon('caretDown') + '</span><span class="tlabel">Show fields</span></button>' +
        '<div class="rule-fields well-dark" id="' + rid + '" hidden>' + RF.map(function (k) { return '<span><span class="faint">' + k + '</span> ' + esc(String(r[k])) + '</span>'; }).join('') + '</div></div></article>';
    }).join('');
    var ROLE = { buyer: 'Buyer', store: 'Store', signer: 'Signer (owner and relayer)' };
    var roles = ['buyer', 'store', 'signer'].filter(function (r) { return d.roles && d.roles[r]; }).map(function (r) {
      return '<div class="card col" style="gap:10px;padding:16px 18px"><span style="font-size:14px">' + ROLE[r] + '</span><div>' + hashChip(d.roles[r], (arcN.address_url || '') + d.roles[r], 'arc') + '</div></div>';
    }).join('');
    return '<header class="screen-head"><span class="kicker">08 / Contracts and policy</span><h2>Every deployed address, and the store\'s rules</h2></header>' +
      '<section class="col" style="gap:12px"><div class="row"><span style="font-size:18px;color:var(--color-accent);display:inline-flex">' + icon('fileCode') + '</span><h3>Contracts</h3><span class="ml-auto mono faint" style="font-size:11px">' + contracts.length + ' contracts</span></div>' +
      (contracts.length ? '<div class="card table-wrap"><div class="tbl contracts-tbl" role="table" aria-label="Contracts"><div class="tbl-head" role="row"><span>Name</span><span>Network</span><span>Address</span><span>Deploy transaction</span><span>Deploy cost</span><span></span></div>' + rows + '</div></div>' : '<p class="card empty-note">No contracts listed.</p>') + '</section>' +
      '<section class="col" style="gap:14px"><div class="row" style="gap:10px 16px"><span style="font-size:18px;color:var(--color-accent);display:inline-flex">' + icon('bookOpen') + '</span><h3>Refund policy</h3><span class="muted" style="font-size:13px">' + esc(terms.store || '') + '</span>' +
      (terms.terms_hash ? '<span class="row ml-auto" style="gap:8px"><span class="dim" style="font-size:12px">Policy hash</span>' + hashChip(terms.terms_hash) + '</span>' : '') + '</div>' +
      (rules ? '<div class="auto-grid ag-240">' + rules + '</div>' : '<p class="card empty-note">No rules published.</p>') + '</section>' +
      (roles ? '<section class="col" style="gap:12px"><div class="row"><span style="font-size:18px;color:var(--color-neutral-300);display:inline-flex">' + icon('userCircle') + '</span><h3>Roles of the live test</h3></div><div class="auto-grid ag-240">' + roles + '</div></section>' : '');
  }

  function renderResources(d) {
    var nets = d.networks || {};
    var arcN = nets.arc || {}, bradN = nets.bradbury || {};
    var strip = function (u) { return (u || '').replace(/^https?:\/\//, ''); };
    var lacre = (d.contracts || []).find(function (x) { return /Lacre/i.test(x.name); });
    var lacreRepo = lacre && lacre.source ? (/^(github\.com\/[^\s(]+)/.exec(lacre.source) || [])[1] : '';
    var links = [
      { title: 'Circle faucet', purpose: 'Free testnet USDC for Arc, used for payments and gas.', url: arcN.faucet, icon: 'drop' },
      { title: 'Arc testnet explorer', purpose: 'Look up the escrow, payments, claims and settlements.', url: arcN.explorer, icon: 'search' },
      { title: 'GenLayer Bradbury explorer', purpose: 'Look up judge transactions and Lacre attestations.', url: bradN.explorer, icon: 'scales' },
      { title: 'Lacre', purpose: 'On-chain DKIM attestations for store emails.', url: (lacre && lacre.project_url) || '', icon: 'lacre', mark: true,
        secondary: lacreRepo ? { label: 'Source code, MIT, Insidr Labs', url: 'https://' + lacreRepo } : null },
      { title: 'Source code', purpose: 'The Tenet contracts, judges, relayer, Demo Shop Worker and this page. MIT.', url: 'https://github.com/randyparrs/Tenet', icon: 'code' }
    ];
    var stepBox = function (n, title, body, action) {
      return '<div class="start-step well"><span class="n">' + n + '</span><span style="font-size:15px">' + esc(title) + '</span><span class="muted pretty" style="font-size:13px">' + esc(body) + '</span><div class="actions">' + action + '</div></div>';
    };
    return '<header class="screen-head"><span class="kicker">09 / Resources</span><h2>Resources</h2></header>' +
      '<section class="card card-pad"><div class="row"><h4>Get started on Arc testnet</h4>' + netBadge('arc') + (arcN.chain_id ? '<span class="ml-auto mono dim" style="font-size:11px">chain id ' + esc(arcN.chain_id) + '</span>' : '') + '</div>' +
      '<div class="row" style="gap:12px;align-items:stretch">' +
      stepBox(1, 'Add the network', 'Adds Arc testnet to your wallet and switches to it. Gas is paid in USDC.', '<button type="button" class="btn btn-primary btn-sm" id="add-network">' + icon('plusCircle') + 'Add Arc testnet</button><span class="inline-msg" id="add-network-msg" role="status" aria-live="polite" hidden></span>') +
      (arcN.faucet ? stepBox(2, 'Get USDC from the faucet', 'Circle sends free testnet USDC to your address.', '<a class="btn btn-secondary btn-sm" href="' + esc(arcN.faucet) + '" target="_blank" rel="noopener noreferrer">Open the faucet' + icon('arrowUpRight') + '</a>') : '') +
      (arcN.explorer ? stepBox(3, 'Open the explorer', 'Look up any Tenet transaction, address or contract on Arc.', '<a class="btn btn-secondary btn-sm" href="' + esc(arcN.explorer) + '" target="_blank" rel="noopener noreferrer">Open the explorer' + icon('arrowUpRight') + '</a>') : '') +
      '</div></section>' +
      '<div class="auto-grid ag-380">' + links.map(function (l) {
        return '<article class="card res-card"><div class="row">' + (l.mark ? lacreMark('lg')
          : '<span style="font-size:20px;color:var(--color-accent-300);display:inline-flex">' + icon(l.icon) + '</span><span style="font-size:15px">' + esc(l.title) + '</span>') + '</div>' +
          '<span class="muted pretty" style="font-size:13px">' + esc(l.purpose) + '</span><div style="margin-top:auto">' +
          (l.url ? '<a href="' + esc(l.url) + '" target="_blank" rel="noopener noreferrer">' + esc(strip(l.url)) + icon('arrowUpRight', '', 'font-size:11px') + '</a>' : '<span class="faint" style="font-size:12.5px">' + esc(l.display || '') + '</span>') +
          (l.secondary ? '<div style="margin-top:6px"><a class="muted" style="font-size:12.5px" href="' + esc(l.secondary.url) + '" target="_blank" rel="noopener noreferrer">' + esc(l.secondary.label) + icon('arrowUpRight', '', 'font-size:11px') + '</a></div>' : '') +
          '</div></article>';
      }).join('') + '</div>';
  }

  /* Globe on the overview hero */
  function startGlobe(cv) {
    if (!cv || !cv.getContext) return null;
    var ctx = cv.getContext('2d');
    var N = 160, pts = [], ga = Math.PI * (3 - Math.sqrt(5));
    for (var i = 0; i < N; i++) { var y = 1 - (i / (N - 1)) * 2, r = Math.sqrt(1 - y * y), th = ga * i; pts.push([Math.cos(th) * r, y, Math.sin(th) * r]); }
    var seen = {}, E = [];
    pts.forEach(function (p, i) {
      pts.map(function (q, j) { return [j, Math.pow(p[0] - q[0], 2) + Math.pow(p[1] - q[1], 2) + Math.pow(p[2] - q[2], 2)]; })
        .filter(function (x) { return x[0] !== i; }).sort(function (a, b) { return a[1] - b[1]; }).slice(0, 4)
        .forEach(function (x) { var j = x[0], k = Math.min(i, j) + '_' + Math.max(i, j); if (!seen[k]) { seen[k] = 1; E.push([i, j]); } });
    });
    var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var raf = 0, stopped = false, t0 = performance.now();
    function draw(now) {
      if (stopped) return;
      var dpr = Math.min(2, window.devicePixelRatio || 1), w = cv.clientWidth, h = cv.clientHeight;
      if (!w || !h) { raf = requestAnimationFrame(draw); return; }
      if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
      var R = Math.min(w, h) * 0.44, cx = w / 2, cy = h / 2;
      var a = reduce ? 0.8 : 0.8 + (now - t0) / 1000 * 0.05, tilt = 0.38;
      var ca = Math.cos(a), sa = Math.sin(a), ct = Math.cos(tilt), st = Math.sin(tilt);
      var P = pts.map(function (p) { var x1 = p[0] * ca + p[2] * sa, z1 = -p[0] * sa + p[2] * ca; var y2 = p[1] * ct - z1 * st, z2 = p[1] * st + z1 * ct; return [cx + x1 * R, cy + y2 * R, z2]; });
      ctx.lineWidth = 0.8;
      E.forEach(function (e) {
        var z = (P[e[0]][2] + P[e[1]][2]) / 2;
        var al = z > 0 ? 0.08 + 0.34 * z : 0.03 + 0.04 * (1 + z);
        ctx.strokeStyle = 'rgba(92,196,138,' + al.toFixed(3) + ')';
        ctx.beginPath(); ctx.moveTo(P[e[0]][0], P[e[0]][1]); ctx.lineTo(P[e[1]][0], P[e[1]][1]); ctx.stroke();
      });
      P.forEach(function (p, i) {
        if (p[2] < -0.15) return;
        var hub = i % 13 === 0, al = 0.2 + 0.65 * Math.max(0, p[2]);
        if (hub && p[2] > 0.15) { ctx.fillStyle = 'rgba(92,196,138,' + (0.14 * p[2]).toFixed(3) + ')'; ctx.beginPath(); ctx.arc(p[0], p[1], 8, 0, Math.PI * 2); ctx.fill(); }
        ctx.fillStyle = 'rgba(150,232,182,' + al.toFixed(3) + ')';
        ctx.beginPath(); ctx.arc(p[0], p[1], hub ? 2.2 : 1.1, 0, Math.PI * 2); ctx.fill();
      });
      if (!reduce) raf = requestAnimationFrame(draw);
    }
    raf = requestAnimationFrame(draw);
    return function () { stopped = true; cancelAnimationFrame(raf); };
  }

  /* Rendering and routing */
  function renderSidebar(d) {
    $('side-networks').innerHTML = netBadge('arc', { role: true }) + netBadge('bradbury', { role: true }) + netBadge('lacre', { role: true });
    var pills = $('case-pills');
    pills.innerHTML = state.cases.map(function (c) { return '<a class="case-pill" href="#case/' + encodeURIComponent(c.id) + '" data-case="' + esc(c.id) + '" title="' + esc(c.title) + '">' + esc(c.id) + '</a>'; }).join('');
    pills.hidden = !state.cases.length;
  }
  function renderAll() {
    var d = state.data;
    state.cases = (d.live_cases || []).map(function (c) { return caseVM(c, d, Date.now()); });
    renderSidebar(d);
    $('screen-overview').innerHTML = renderOverview(d);
    $('screen-how-it-works').innerHTML = renderHow(d);
    $('screen-order-flow').innerHTML = renderFlow(d);
    $('screen-live-cases').innerHTML = renderCases();
    $('screen-judges').innerHTML = renderJudges(d);
    $('screen-measurements').innerHTML = renderMeasurements(d);
    $('screen-contracts').innerHTML = renderContracts(d);
    $('screen-resources').innerHTML = renderResources(d);
  }
  function showRoute(scroll) {
    state.route = parseHash();
    var r = state.route;
    document.querySelectorAll('.nav-item').forEach(function (a) {
      if (a.getAttribute('data-route') === r.screen) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
    if (!state.data) return;
    if (r.screen === 'case') $('screen-case').innerHTML = renderCase();
    var cur = r.screen === 'case' ? state.lastCase : null;
    document.querySelectorAll('.case-pill').forEach(function (p) {
      if (cur && p.getAttribute('data-case') === cur) p.setAttribute('aria-current', 'page'); else p.removeAttribute('aria-current');
    });
    var caseTarget = state.lastCase || (state.cases[0] && state.cases[0].id);
    $('nav-case').setAttribute('href', caseTarget ? '#case/' + encodeURIComponent(caseTarget) : '#case');
    document.querySelectorAll('.screen[data-screen]').forEach(function (s) { s.hidden = s.getAttribute('data-screen') !== r.screen; });
    if (window.TenetShop) { if (r.screen === 'demo-shop' || r.screen === 'my-orders') window.TenetShop.show(r.screen, r.caseId); else window.TenetShop.hide(); }
    if (state.stopGlobe) { state.stopGlobe(); state.stopGlobe = null; }
    if (r.screen === 'overview') state.stopGlobe = startGlobe($('globe'));
    if (scroll) window.scrollTo(0, 0);
  }
  /* Countdowns: recomputed from the visitor's clock every 30 seconds */
  function tick() {
    var now = Date.now();
    document.querySelectorAll('[data-live-from]').forEach(function (el) {
      var ls = liveStatus(Number(el.getAttribute('data-live-from')), Number(el.getAttribute('data-live-to')), now);
      var f = el.querySelector('.timebar-fill'), s = el.querySelector('.timebar-status');
      if (f) f.style.width = ls.fill;
      if (s) s.textContent = ls.status;
    });
  }
  function load() {
    $('state-loading').hidden = false;
    $('state-error').hidden = true;
    document.querySelectorAll('.screen[data-screen]').forEach(function (s) { s.hidden = true; });
    fetch('data/tenet.json', { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.text(); })
      .then(function (t) {
        var d = JSON.parse(t);
        if (!d || typeof d !== 'object' || !Array.isArray(d.live_cases)) throw new Error('Unexpected data shape');
        state.data = d;
        renderAll();
        $('state-loading').hidden = true;
        showRoute(false);
        wallet.render();
      })
      .catch(function () {
        state.data = null;
        $('state-loading').hidden = true;
        $('state-error').hidden = false;
      });
  }

  /* Wallet: Arc testnet. This module connects and reads; the Demo Shop (demo-shop.js) sends the visitor's own transactions. */
  var ARC = { chainId: '0x4cef52', chainName: 'Arc Testnet', nativeCurrency: { name: 'USDC', symbol: 'USDC', decimals: 18 }, rpcUrls: ['https://rpc.testnet.arc.io'], blockExplorerUrls: ['https://explorer.testnet.arc.io'] };
  var wallet = {
    status: 'idle', address: '', balance: null, balanceErr: false, listening: false, msgTimer: 0,
    eth: function () { return window.ethereum || null; },
    arcN: function () { return (state.data && state.data.networks && state.data.networks.arc) || {}; },
    isCancel: function (e) {
      return !!e && (e.code === 4001 || e.code === 'ACTION_REJECTED' || /user (rejected|denied|cancel)|rejected the request|request rejected|cancell?ed/i.test(e.message || ''));
    },
    clearMsg: function () {
      clearTimeout(wallet.msgTimer);
      ['wallet-msg', 'add-network-msg'].forEach(function (id) { var el = $(id); if (el) { el.hidden = true; el.textContent = ''; } });
    },
    showMsg: function (id, text, ok) {
      wallet.clearMsg();
      var el = $(id); if (!el) return;
      el.textContent = text;
      el.style.color = ok ? 'var(--color-accent-300)' : '';
      el.hidden = false;
      wallet.msgTimer = setTimeout(wallet.clearMsg, 4000);
    },
    ensureArc: function (eth) {
      return eth.request({ method: 'eth_chainId' }).then(function (cid) {
        if (String(cid).toLowerCase() === ARC.chainId) return true;
        return eth.request({ method: 'wallet_switchEthereumChain', params: [{ chainId: ARC.chainId }] }).then(function () { return true; }, function (e) {
          var missing = e && (e.code === 4902 || (e.data && e.data.originalError && e.data.originalError.code === 4902) || /unrecognized|not added|unknown chain/i.test(e.message || ''));
          if (missing) return eth.request({ method: 'wallet_addEthereumChain', params: [ARC] }).then(function () { return true; });
          throw e;
        });
      });
    },
    /* Reads go to Arc's public RPC, so they work whatever RPC the wallet has set for Arc; the wallet is the
       fallback. Only signatures and transactions go through the wallet. */
    read: function (method, params) {
      /* A read that hangs counts as failed after 8 seconds, so the page never waits forever */
      var timed = function (pr, what) {
        return new Promise(function (res, rej) {
          var tm = setTimeout(function () { rej(new Error(what + ': no answer in 8 s')); }, 8000);
          pr.then(function (v) { clearTimeout(tm); res(v); }, function (e) { clearTimeout(tm); rej(e); });
        });
      };
      var viaWallet = function (e) {
        console.warn('Tenet: ' + method + ' through Arc public RPC failed (' + ((e && e.message) || e) + '); trying the wallet');
        var eth = wallet.eth(); if (!eth) throw e;
        return timed(eth.request({ method: method, params: params }), 'wallet').catch(function (e2) {
          console.warn('Tenet: ' + method + ' through the wallet failed (' + ((e2 && e2.message) || e2) + ')');
          throw e2;
        });
      };
      return timed(fetch(ARC.rpcUrls[0], { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: method, params: params }) })
        .then(function (r) { return r.json(); })
        .then(function (j) { if (!j || j.error || j.result === undefined) throw new Error((j && j.error && j.error.message) || 'no result'); return j.result; }), 'Arc public RPC')
        .catch(viaWallet);
    },
    readBalance: function () {
      if (!wallet.address) return Promise.resolve();
      return wallet.read('eth_getBalance', [wallet.address, 'latest']).then(function (hex) {
        var cents = Number(BigInt(hex) / BigInt('10000000000000000'));
        wallet.balance = cents / 100;
        wallet.balanceErr = false;
        wallet.render();
      }, function (e) { wallet.balanceErr = true; wallet.render(); throw e; });
    },
    sync: function () {
      var eth = wallet.eth(); if (!eth || !wallet.address) return;
      eth.request({ method: 'eth_chainId' }).then(function (cid) {
        if (String(cid).toLowerCase() !== ARC.chainId) { wallet.status = 'wrong'; wallet.balance = null; wallet.render(); return; }
        wallet.status = 'connected'; wallet.render();
        wallet.readBalance().catch(function () {});
      }).catch(function () {});
    },
    listen: function (eth) {
      if (wallet.listening || !eth.on) return;
      wallet.listening = true;
      eth.on('accountsChanged', function (a) {
        if (!a || !a.length) { wallet.status = 'idle'; wallet.address = ''; wallet.balance = null; wallet.render(); }
        else { wallet.address = a[0]; wallet.sync(); }
      });
      eth.on('chainChanged', function () { wallet.sync(); });
    },
    connect: function () {
      wallet.clearMsg();
      var eth = wallet.eth();
      if (!eth) { wallet.showMsg('wallet-msg', 'No wallet found in this browser.'); return; }
      wallet.status = 'connecting'; wallet.render();
      eth.request({ method: 'eth_requestAccounts' })
        .then(function (accs) {
          if (!accs || !accs[0]) throw new Error('No account returned');
          wallet.address = accs[0];
          return wallet.ensureArc(eth);
        })
        .then(function () {
          wallet.listen(eth);
          wallet.status = 'connected'; wallet.render();
          wallet.readBalance().catch(function () { /* shown as unavailable; a failed read is not a failed connection */ });
        })
        .catch(function (e) {
          wallet.status = wallet.address ? 'wrong' : 'idle';
          wallet.render();
          if (wallet.address) { wallet.listen(eth); wallet.sync(); }
          if (wallet.isCancel(e)) return;
          wallet.showMsg('wallet-msg', e && e.code === -32002 ? 'A wallet request is already open.' : 'Could not connect to Arc testnet.');
        });
    },
    addNetwork: function () {
      wallet.clearMsg();
      var eth = wallet.eth();
      if (!eth) { wallet.showMsg('add-network-msg', 'No wallet found in this browser.'); return; }
      wallet.ensureArc(eth)
        .then(function () { wallet.showMsg('add-network-msg', 'Arc testnet is ready in your wallet.', true); if (wallet.address) wallet.sync(); })
        .catch(function (e) { if (!wallet.isCancel(e)) wallet.showMsg('add-network-msg', 'Could not add Arc testnet.'); });
    },
    disconnect: function () { wallet.clearMsg(); wallet.status = 'idle'; wallet.address = ''; wallet.balance = null; wallet.balanceErr = false; wallet.render(); },
    restore: function () {
      var eth = wallet.eth(); if (!eth) return;
      eth.request({ method: 'eth_accounts' }).then(function (a) {
        if (a && a[0]) { wallet.address = a[0]; wallet.listen(eth); wallet.sync(); }
      }).catch(function () {});
    },
    render: function () {
      var s = wallet.status, a = wallet.address, arcN = wallet.arcN();
      $('wallet-connect').hidden = !(s === 'idle' || s === 'connecting');
      $('wallet-connect').disabled = s === 'connecting';
      $('wallet-connect-label').textContent = s === 'connecting' ? 'Connecting...' : 'Connect wallet';
      $('wallet-switch').hidden = s !== 'wrong';
      $('wallet-chip').hidden = s !== 'connected';
      var addr = $('wallet-addr');
      addr.textContent = a ? a.slice(0, 6) + '...' + a.slice(-4) : '';
      addr.title = a;
      addr.href = (arcN.address_url || 'https://explorer.testnet.arc.io/address/') + a;
      $('wallet-bal').textContent = wallet.balance != null ? wallet.balance.toFixed(2) + ' USDC' : wallet.balanceErr ? 'balance unavailable' : 'reading...';
      var faucet = $('wallet-faucet');
      faucet.href = arcN.faucet || 'https://faucet.circle.com';
      faucet.hidden = !(s === 'connected' && wallet.balance === 0);
      if (window.TenetShop && wallet._shown !== s + a) { wallet._shown = s + a; window.TenetShop.onWallet(); }
    }
  };
  /* Kept as a global so other scripts or the console can trigger it */
  window.connectWallet = wallet.connect;
  /* What the Demo Shop section (demo-shop.js) uses from this page */
  window.TenetUI = { icon: icon, esc: esc, hashChip: hashChip, netBadge: netBadge, screenHead: screenHead, wallet: wallet,
    getData: function () { return state.data; } };

  /* Events */
  document.addEventListener('click', function (e) {
    var copy = e.target.closest('[data-copy]');
    if (copy) {
      e.preventDefault(); e.stopPropagation();
      var v = copy.getAttribute('data-copy');
      var done = function () {
        copy.innerHTML = icon('check'); copy.classList.add('copied');
        clearTimeout(copy._t);
        copy._t = setTimeout(function () { copy.innerHTML = icon('copy'); copy.classList.remove('copied'); }, 1400);
      };
      var fallback = function () {
        var ta = document.createElement('textarea'); ta.value = v; ta.style.position = 'fixed'; ta.style.opacity = '0';
        document.body.appendChild(ta); ta.select();
        try { document.execCommand('copy'); } catch (err) { /* ignore */ }
        ta.remove(); done();
      };
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(v).then(done, fallback); else fallback();
      return;
    }
    if (e.target.closest('a')) return;
    var tg = e.target.closest('[data-toggle]');
    if (tg) {
      var el = $(tg.getAttribute('data-toggle'));
      if (!el) return;
      var open = el.hidden;
      el.hidden = !open;
      tg.setAttribute('aria-expanded', String(open));
      var lbl = tg.querySelector('.tlabel');
      if (lbl) lbl.textContent = open ? tg.getAttribute('data-label-open') : tg.getAttribute('data-label-closed');
      var cr = tg.querySelector('.chev-r');
      if (cr) cr.style.transform = open ? 'rotate(180deg)' : '';
      return;
    }
    var fl = e.target.closest('[data-flow]');
    if (fl) { state.flow = fl.getAttribute('data-flow'); $('screen-order-flow').innerHTML = renderFlow(state.data); return; }
    var cv = e.target.closest('[data-claim-view]');
    if (cv) {
      var view = cv.getAttribute('data-claim-view');
      document.querySelectorAll('[data-claim-view]').forEach(function (b) { b.setAttribute('aria-pressed', String(b.getAttribute('data-claim-view') === view)); });
      document.querySelectorAll('[data-claim]').forEach(function (p) { p.hidden = p.getAttribute('data-claim') !== view; });
      return;
    }
    if (e.target.closest('#add-network')) { wallet.addNetwork(); return; }
  });
  document.addEventListener('keydown', function (e) {
    if ((e.key === 'Enter' || e.key === ' ') && e.target.matches && e.target.matches('div[data-toggle]')) { e.preventDefault(); e.target.click(); }
  });
  $('wallet-connect').addEventListener('click', wallet.connect);
  $('wallet-switch').addEventListener('click', wallet.connect);
  $('wallet-disconnect').addEventListener('click', wallet.disconnect);
  $('retry').addEventListener('click', load);
  window.addEventListener('hashchange', function () { showRoute(true); });

  hydrateIcons(document);
  showRoute(false);
  wallet.render();
  wallet.restore();
  load();
  setInterval(tick, 30000);
})();
