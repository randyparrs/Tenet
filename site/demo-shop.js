/* Tenet Demo Shop and My orders: the demo mode on testnet. The visitor signs only their own transactions
   (approve, pay, claim, submissions, withdraw) from their wallet on Arc testnet; the demo store and the relayer
   run in the demo Worker, whose API is in <meta name="tenet-demo-api">. Nothing here holds keys. */
(function () {
  'use strict';

  var SEL = {
    approve: '095ea7b3', allowance: 'dd62ed3e', pay: '919aeb18', openClaim: 'f0dd1fe5',
    submit: '3d5376fa', withdraw: '51cff8d9', claimable: 'd4570c1c'
  };
  var STORE_KEY = 'tenet-demo-orders';
  var POLL_MS = 15000, SLOW_MS = 60000, CLOCK_MS = 5000;
  var JUDGE_USUAL_S = 120; // send to ACCEPTED on Bradbury: under 1 minute (measured), plus the Worker's 1 minute tick
  var FINAL_USUAL_S = 1800; // decided to final on Bradbury: about 30 minutes (measured 26 to 30 min from the send)
  var PHASES = [['coins', 'Paid'], ['fileText', 'Claim'], ['envelope', 'Store answer'], ['scales', 'Judge'], ['checkCircle', 'Settled']];
  /* The late path has no store answer: the store's own signed emails, attested on Lacre, are the evidence */
  var PHASES_LATE = [['coins', 'Paid'], ['lacre', 'Store emails'], ['fileText', 'Claim'], ['scales', 'Judge'], ['checkCircle', 'Settled']];
  var t = { config: null, error: '', quota: null, views: {}, busy: '', busyArg: '', busyLabel: '', note: null, folds: {},
    timer: 0, clock: 0, claimable: null, screen: '', focus: null, focusAt: 0, flash: 0, flashNext: false, purchased: null, withdrawnAt: 0 };

  function ui() { return window.TenetUI; }
  function esc(s) { return ui().esc(s); }
  function icon(n, c) { return ui().icon(n, c); }
  function api() { var m = document.querySelector('meta[name="tenet-demo-api"]'); return (m && m.content || '').replace(/\/$/, ''); }
  function get(path) { return fetch(api() + path, { cache: 'no-store' }).then(function (r) { return r.json(); }); }
  function post(path, body) {
    return fetch(api() + path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })
      .then(function (r) { return r.json(); });
  }

  /* ABI encoding of the few calls the page makes */
  function word(hex) { return String(hex).replace(/^0x/, '').toLowerCase().padStart(64, '0'); }
  function uint(n) { return BigInt(n).toString(16).padStart(64, '0'); }
  function bytesHex(text) {
    var b = new TextEncoder().encode(text), h = '';
    for (var i = 0; i < b.length; i++) h += b[i].toString(16).padStart(2, '0');
    return { len: b.length, hex: h.padEnd(Math.ceil(b.length / 32) * 64, '0') };
  }
  function withBytes(sel, ref, text) {
    var d = bytesHex(text);
    return '0x' + sel + word(ref) + uint(64) + uint(d.len) + d.hex;
  }

  /* Wallet calls. The button that started a call shows where it is: open in the wallet, then confirming on Arc. */
  function eth() { return ui().wallet.eth(); }
  function me() { return ui().wallet.address; }
  function step(label) { t.busyLabel = label; render(); }
  function sendTx(to, data, label) {
    if (ui().wallet.kind === 'circle') {
      /* Circle wallet: approved in Circle's window, sent by Circle, then the same wait for the receipt */
      return window.TenetCircle.send(to, data, function (where) {
        step(where === 'approve' ? (label || 'Confirm in your wallet').replace(/in your wallet/, 'in the Circle window') : 'Circle is sending it to Arc...');
      }).then(function (hash) { step('Confirming on Arc...'); return waitTx(hash); });
    }
    return ui().wallet.ensureArc(eth()).then(function () {
      step(label || 'Confirm in your wallet');
      return eth().request({ method: 'eth_sendTransaction', params: [{ from: me(), to: to, data: data }] });
    }).then(function (hash) { step('Confirming on Arc...'); return waitTx(hash); });
  }
  function waitTx(hash) {
    var tries = 0;
    return new Promise(function (res, rej) {
      (function poll() {
        ui().wallet.read('eth_getTransactionReceipt', [hash]).then(function (r) {
          if (r && r.status === '0x1') return res(hash);
          if (r && r.status !== '0x1') return rej(new Error('The transaction reverted on Arc.'));
          if (++tries > 90) return rej(new Error('No receipt yet; check the explorer.'));
          setTimeout(poll, 2000);
        }, rej);
      })();
    });
  }
  /* Reads use Arc's public RPC first (app.js wallet.read), so a wallet with a stale Arc RPC still sees its balance and credit */
  function call(to, data) { return ui().wallet.read('eth_call', [{ to: to, data: data }, 'latest']); }
  function readBalance() { try { ui().wallet.readBalance().catch(function () {}); } catch (e) { /* no wallet */ } }

  /* Orders this browser started (with their payment details), plus every order the Worker saw this wallet
     pay: a visitor finds them again from another browser or device. The Worker holds the real state. */
  function saved() { try { return JSON.parse(localStorage.getItem(STORE_KEY) || '[]'); } catch (e) { return []; } }
  function save(list) { try { localStorage.setItem(STORE_KEY, JSON.stringify(list.slice(-30))); } catch (e) { /* storage off */ } }
  function mine() {
    var a = (me() || '').toLowerCase();
    if (!a) return [];
    var local = saved().filter(function (o) { return o.address === a; }), have = {};
    local.forEach(function (o) { have[o.order] = true; });
    var paid = (t.remote && t.remote.address === a ? t.remote.list : []).filter(function (o) { return !have[o.order]; })
      .map(function (o) { return { order: o.order, scenario: o.scenario, address: a, at: (o.paid_at || 0) * 1000 }; });
    return local.concat(paid).sort(function (x, y) { return x.at - y.at; });
  }
  function remember(order, scenario, pay) {
    var list = saved();
    list.push({ order: order, scenario: scenario, address: me().toLowerCase(), at: Date.now(), pay: pay });
    save(list);
  }
  function payOf(order) {
    var o = saved().filter(function (x) { return x.order === order; })[0];
    return o && o.pay;
  }
  function sentKey(order) { return 'tenet-demo-sent-' + order; }
  function sentSet(order) { try { return JSON.parse(localStorage.getItem(sentKey(order)) || '[]'); } catch (e) { return []; } }
  function wasSent(order, what) { return sentSet(order).indexOf(what) !== -1; }
  function markSent(order, what) {
    var s = sentSet(order); s.push(what);
    try { localStorage.setItem(sentKey(order), JSON.stringify(s)); } catch (e) { /* storage off */ }
  }

  /* Loading */
  /* The products come from a static file, so the shop shows even before the Worker is published;
     buying needs the Worker's API. */
  function load() {
    if (!t.shop) {
      fetch('data/demo-shop.json', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (shop) {
        t.shop = shop;
        if (!t.config) render();
      }, function () { /* no static copy: the API alone */ });
    }
    if (!api()) { t.error = 'not-published'; render(); return; }
    get('/api/config').then(function (c) { t.config = c; t.error = ''; refresh(); }, function () { t.error = 'unreachable'; render(); });
  }
  function refresh() {
    var addr = me();
    var paid = addr ? get('/api/orders?buyer=' + addr).then(function (r) {
      if (r && r.orders) t.remote = { address: addr.toLowerCase(), list: r.orders };
    }, function () { /* this browser's own list still shows */ }) : Promise.resolve();
    return paid.then(refreshViews);
  }
  function refreshViews() {
    var jobs = [];
    if (me()) jobs.push(get('/api/quota?address=' + me()).then(function (q) { t.quota = q.error ? null : q; }));
    mine().forEach(function (o) {
      var v = t.views[o.order];
      if (v && v.settled && v._final) return; // a settled order does not change any more
      jobs.push(get('/api/orders/' + o.order).then(function (x) { if (!x.error) { x._final = !!x.settled; t.views[o.order] = x; } }));
    });
    if (me() && t.config) jobs.push(call(t.config.addresses.escrow, '0x' + SEL.claimable + word(me()) + word(t.config.addresses.usdc))
      .then(function (h) { t.claimable = Number(BigInt(h)) / 1e6; }, function () { t.claimable = null; }));
    if (me()) jobs.push(ui().wallet.readBalance().catch(function () { /* shown as unavailable */ }));
    return Promise.all(jobs).then(fromWorker, fromWorker).then(render, render);
  }
  /* Last resort when this browser cannot read Arc at all (an ad blocker, a dead wallet RPC): the Worker reads it */
  function account() { return get('/api/account?address=' + me()).then(function (a) { if (!a || a.error) throw new Error('no account read'); return a; }); }
  function fromWorker() {
    var W = ui().wallet;
    if (!me() || !t.config || (t.claimable != null && W.balance != null)) return;
    return account().then(function (a) {
      if (t.claimable == null) t.claimable = Number(BigInt(a.claimable)) / 1e6;
      if (W.balance == null) { W.balance = Number(BigInt(a.balance_wei) / BigInt('10000000000000000')) / 100; W.balanceErr = false; W.render(); }
    }, function () { /* the page says the reads failed */ });
  }
  function isDone(v) { return !!(v && (v.settled || v.refund)); }
  function inProgress() {
    return mine().filter(function (o) { var v = t.views[o.order]; return v && (v.paid || wasSent(o.order, 'pay')) && !isDone(v); });
  }

  /* Actions */
  function reason(e) {
    if (e && (e.code === 4001 || /reject|denied|cancel/i.test(e.message || ''))) return 'Cancelled in the wallet.';
    return (e && e.message) || 'Something failed.';
  }
  function payFlow(order) {
    var p = payOf(order), A = t.config.addresses;
    if (!p) return Promise.reject(new Error('The payment details of this order are in another browser.'));
    step('Preparing the payment...');
    return call(A.usdc, '0x' + SEL.allowance + word(me()) + word(A.escrow)).catch(function (e) {
      return account().then(function (a) { return '0x' + BigInt(a.allowance).toString(16); }, function () { throw e; });
    }).then(function (h) {
      var need = BigInt(h) < BigInt(p.amount);
      return (need ? sendTx(A.usdc, '0x' + SEL.approve + word(A.escrow) + uint(p.amount), 'Approve in your wallet (1 of 2)') : Promise.resolve())
        .then(function () {
          return sendTx(A.escrow, '0x' + SEL.pay + word(p.ref) + word(p.merchant) + word(p.token) + uint(p.amount) + uint(p.hold) + word(p.terms_hash),
            need ? 'Pay in your wallet (2 of 2)' : 'Pay in your wallet');
        });
    }).then(function () { markSent(order, 'pay'); readBalance(); });
  }
  function act(kind, arg) {
    if (kind === 'fold') { t.folds[arg] = !t.folds[arg]; render(); return; }
    if (kind === 'connect') { ui().wallet.connect(); return; }
    if (kind === 'refresh') { refresh(); return; }
    if (kind === 'goto-withdraw') { t.flashNext = true; location.hash = '#demo-shop'; return; }
    if (kind === 'go-shop') { location.hash = '#demo-shop'; return; }
    if (t.busy) return;
    var A = t.config && t.config.addresses;
    var begin = function (k, a, label) { t.busy = k; t.busyArg = a || ''; t.busyLabel = label; t.note = null; render(); };
    var end = function (key, text, tone, link) { t.busy = ''; t.busyArg = ''; t.note = text ? { key: key, text: text, tone: tone || 'ok', link: link } : null; return refresh(); };
    if (kind === 'start') {
      /* Buy: the Worker opens the order, then the wallet approves and pays in the same click */
      var order = null;
      begin('start', arg, 'Creating the order...');
      post('/api/orders', { scenario: arg }).then(function (o) {
        if (o.error) throw new Error(o.error);
        order = o.order;
        remember(o.order, arg, Object.assign({ ref: o.ref }, o.pay));
        t.views[o.order] = { order: o.order, scenario: arg, paid: false, events: [], steps: [] };
        return payFlow(o.order);
      }).then(function () {
        t.purchased = { id: arg, order: order, at: Date.now() };
        end('order:' + order, 'Order ' + order + ' paid on Arc. The demo store registers it within a minute.');
        setTimeout(function () { location.hash = '#my-orders/' + order; }, 1100);
      }).catch(function (e) {
        if (order) end('start:' + arg, 'Order ' + order + ' was created but not paid. ' + reason(e) + ' You can pay it from My orders.', 'err',
          { href: '#my-orders/' + order, label: 'Open order ' + order });
        else end('start:' + arg, reason(e), 'err');
      });
      return;
    }
    if (kind === 'pay') {
      begin('pay', arg, 'Preparing the payment...');
      payFlow(arg).then(function () { end('order:' + arg, 'Order ' + arg + ' paid on Arc. The demo store registers it within a minute.'); })
        .catch(function (e) { end('order:' + arg, 'Order ' + arg + ': ' + reason(e), 'err'); });
      return;
    }
    if (kind === 'claim') {
      begin('claim', arg, 'Reading the claim...');
      var view;
      get('/api/orders/' + arg).then(function (v) {
        view = v;
        if (!v.next || v.next.action !== 'claim') throw new Error('The claim is not ready.');
        if (wasSent(arg, 'claim')) throw new Error('The claim was already sent; wait for the demo store.');
        return sendTx(A.escrow, withBytes(SEL.openClaim, v.ref, v.next.claim), 'Sign the claim in your wallet');
      }).then(function () {
        markSent(arg, 'claim');
        var subs = (view.next.then || []).filter(function (s) { return !wasSent(arg, s); });
        return subs.reduce(function (pr, s, i) {
          return pr.then(function () {
            return sendTx(A.escrow, withBytes(SEL.submit, view.ref, s), 'Sign email ' + (i + 1) + ' of ' + subs.length + ' in your wallet')
              .then(function () { markSent(arg, s); });
          });
        }, Promise.resolve());
      }).then(function () { end('order:' + arg, 'Order ' + arg + ': claim registered on Arc. The demo store answers next.'); })
        .catch(function (e) { end('order:' + arg, 'Order ' + arg + ': ' + reason(e), 'err'); });
      return;
    }
    if (kind === 'submit') {
      begin('submit', arg, 'Reading what to send...');
      get('/api/orders/' + arg).then(function (v) {
        var subs = ((v.next && v.next.submissions) || []).filter(function (s) { return !wasSent(arg, s); });
        return subs.reduce(function (pr, s, i) {
          return pr.then(function () {
            return sendTx(A.escrow, withBytes(SEL.submit, v.ref, s), subs.length > 1 ? 'Sign ' + (i + 1) + ' of ' + subs.length + ' in your wallet' : 'Sign in your wallet')
              .then(function () { markSent(arg, s); });
          });
        }, Promise.resolve());
      }).then(function () { end('order:' + arg, 'Order ' + arg + ': registered on Arc.'); })
        .catch(function (e) { end('order:' + arg, 'Order ' + arg + ': ' + reason(e), 'err'); });
      return;
    }
    if (kind === 'withdraw') {
      var amount = t.claimable || 0;
      begin('withdraw', '', 'Sign in your wallet');
      sendTx(A.escrow, '0x' + SEL.withdraw + word(A.usdc), 'Sign in your wallet').then(function () {
        t.withdrawnAt = Date.now();
        readBalance();
        end('withdraw', amount.toFixed(2) + ' USDC sent to your wallet.');
      }).catch(function (e) { end('withdraw', reason(e), 'err'); });
      return;
    }
    if (kind === 'forget') { save(saved().filter(function (o) { return o.order !== arg; })); delete t.views[arg]; render(); }
  }

  /* Text helpers */
  function usdc(c) { return (Number(c) / 100).toFixed(2) + ' USDC'; }
  function outcomeText(s) { return s.outcome + (s.outcome === 'REFUND' ? ' ' + usdc(s.refund_cents) : ''); }
  function mins(sec) { return Math.round((sec || 300) / 60) + ' min'; }
  function hhmm(sec) { return new Date(sec * 1000).toISOString().slice(11, 16) + ' UTC'; }
  function clock(sec) { var s = Math.max(0, Math.round(sec)); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); }
  function scenOf(id) {
    var c = t.config || t.shop || {};
    return (c.scenarios || []).filter(function (s) { return s.id === id; })[0] || {};
  }
  function lastEv(v, re) { var l = null; (v.events || []).forEach(function (e) { if (re.test(e.what)) l = e; }); return l; }
  /* One line per Arc transaction: the Worker's own send and the escrow event it reads back share a hash */
  function timeline(v) {
    var seen = {};
    return (v.events || []).filter(function (e) {
      if (!e.tx || e.net !== 'arc') return true;
      if (seen[e.tx]) return false;
      seen[e.tx] = true;
      return true;
    });
  }

  /* Time bars. Countdowns end at a window's close; the judge's bar runs against its usual time. */
  function bar(title, from, to, now, after) {
    var f = Math.max(0, Math.min(1, (now - from) / Math.max(1, to - from)));
    return { title: title, from: from, to: to, after: after || '', fill: Math.round(f * 100) + '%',
      status: to > now ? clock(to - now) + ' left' : after || 'Closed, registering on Arc', start: hhmm(from), end: hhmm(to) };
  }
  function judgeBar(from, now) {
    var el = now - from;
    return { title: 'GenLayer judge', from: from, to: from + JUDGE_USUAL_S, judge: true,
      fill: Math.round(Math.min(0.96, el / JUDGE_USUAL_S) * 100) + '%', status: Math.floor(el / 60) + ' min so far',
      start: 'Sent ' + hhmm(from), end: 'Usually done by ' + hhmm(from + JUDGE_USUAL_S) };
  }
  function timeBar(b) {
    return '<div class="timebar" data-bar-from="' + b.from + '" data-bar-to="' + b.to + '"' + (b.judge ? ' data-bar-judge="1"' : '') +
      (b.after ? ' data-bar-after="' + esc(b.after) + '"' : '') + '>' +
      '<div class="timebar-top"><span class="timebar-title">' + esc(b.title) + '</span><span class="timebar-status">' + esc(b.status) + '</span></div>' +
      '<div class="timebar-track"><div class="timebar-fill" style="width:' + b.fill + ';min-width:3px"></div></div>' +
      '<div class="timebar-ends"><span>' + esc(b.start) + '</span><span>' + esc(b.end) + '</span></div></div>';
  }
  /* Between polls only the bars move */
  function clockTick() {
    var now = Date.now() / 1000;
    document.querySelectorAll('[data-bar-from]').forEach(function (el) {
      var from = Number(el.getAttribute('data-bar-from')), to = Number(el.getAttribute('data-bar-to'));
      var b = el.getAttribute('data-bar-judge') ? judgeBar(from, now) : bar('', from, to, now, el.getAttribute('data-bar-after'));
      var f = el.querySelector('.timebar-fill'), s = el.querySelector('.timebar-status');
      if (f) f.style.width = b.fill;
      if (s) s.textContent = b.status;
    });
  }

  /* Where an order is: the current phase (0 Paid to 4 Settled), one status line, an optional time bar
     and the one next action. An action without a kind is a wait, shown as a disabled button. */
  function phase(o, v, sc, now) {
    var c = t.config || {}, W = c.windows_seconds || {}, amt = usdc(c.amount_cents || 100);
    var steps = v.steps || [], st = steps[steps.length - 1];
    var finals = steps.filter(function (s) { return s.final; }), lastFinal = finals.length ? finals[finals.length - 1].final : null;
    var wait = function (label) { return { label: label }; };
    if (v.settled || v.refund) {
      var back = v.settled ? v.settled.refund / 1e6 : 0, rel = v.settled ? v.settled.released / 1e6 : 0, line, tone = '';
      var proofAsked = !!lastEv(v, /^Proof requested/);
      if (v.refund) line = v.refund.text + '. ' + (v.settled ? back.toFixed(2) + ' USDC back to you.' : 'The refund is on its way.');
      else if (back > 0) { line = 'REFUND ' + back.toFixed(2) + ' USDC refunded to you' + (rel > 0 ? ', ' + rel.toFixed(2) + ' USDC released to the store.' : '.'); tone = 'ok'; }
      else line = (lastFinal && lastFinal.outcome === 'DENY' ? 'DENY, ' + lastFinal.reason + '. ' : proofAsked ? 'No proof was sent in time. ' : '') +
        'Released to the store: ' + rel.toFixed(2) + ' USDC.';
      var action = !v.settled ? wait('Refund on its way')
        : back > 0 ? (t.claimable === 0 ? { label: 'Withdrawn to your wallet', done: true } : { kind: 'goto-withdraw', label: 'Go to withdraw', icon: 'arrowRight' })
          : { kind: 'go-shop', label: 'Back to the Demo Shop', icon: 'arrowRight', quiet: true };
      return { i: 4, done: !!v.settled, line: line, tone: tone, action: action };
    }
    if (!v.paid) {
      if (wasSent(o.order, 'pay')) return { i: 1, line: 'Paid on Arc. The demo store registers the payment within a minute.', action: wait('Open a claim') };
      return { i: 0, line: 'Waiting for your payment of ' + amt + ' into the demo escrow.',
        action: payOf(o.order) ? { kind: 'pay', label: 'Approve and pay ' + amt } : wait('Paid from another browser') };
    }
    var claimE = lastEv(v, /^Claim opened/);
    var late = sc.path === 'late', CL = late ? 2 : 1; // the Claim phase's place on the track
    if (!claimE) {
      if (v.next && v.next.action === 'claim') {
        if (wasSent(o.order, 'claim')) return { i: CL, line: 'Claim sent on Arc. The demo store registers it within a minute.', action: wait('Waiting for the store') };
        var then = v.next.then || [];
        return { i: CL, line: (sc.product ? sc.product.goes_wrong + ' ' : '') + 'Open a claim: the judge reads it with the store\'s answer.' +
          (then.length ? ' The store\'s ' + then.length + ' signed emails go with it as evidence, one transaction each.' : ''),
          action: { kind: 'claim', label: 'Open a claim' }, exact: [v.next.claim].concat(then) };
      }
      return { i: 1, line: (v.next && v.next.text) || 'Paid. The demo store is preparing the order.', action: wait('Open a claim') };
    }
    var unsent = v.next && v.next.action === 'submit' ? (v.next.submissions || []).filter(function (s) { return !wasSent(o.order, s); }) : [];
    if (late && v.next && v.next.action === 'submit') {
      return unsent.length
        ? { i: CL, line: 'The claim is open. Send the store\'s signed emails as evidence, one transaction each.', action: { kind: 'submit', label: 'Send the evidence' }, exact: unsent }
        : { i: CL, line: 'Evidence sent on Arc. The demo store registers it within a minute.', action: wait('Waiting for the store') };
    }
    var answered = lastEv(v, /^(Store answered|Registered: (response|no response))/);
    if (!late && !answered) {
      return { i: 2, line: 'Claim registered on Arc. The demo store has ' + mins(W.response) + ' to answer.',
        bar: bar('Store answer window', claimE.at, claimE.at + (W.response || 300), now), action: wait('Waiting for the store') };
    }
    var proposed = lastEv(v, /^Verdict proposed/);
    if (proposed && lastFinal) {
      var d = c.verdict_delay_seconds || 120;
      return { i: 3, line: 'Final verdict: ' + outcomeText(lastFinal) + '. Proposed on Arc; the escrow carries it out after ' + mins(d) + '.',
        bar: bar('Before the escrow pays', proposed.at, proposed.at + d, now), action: wait('Waiting for the escrow') };
    }
    var co = lastEv(v, /^Registered: closing open/);
    var closingNow = co && lastFinal && lastFinal.action === 'open_closing_round' && (!st || st.final);
    if (closingNow) {
      var cb = bar('Closing round', co.at, co.at + (W.closing || 300), now);
      return unsent.length
        ? { i: 3, line: 'The judge opened a closing round: send your answer once. Each side has ' + mins(W.closing) + '.', bar: cb,
          action: { kind: 'submit', label: 'Send your answer' }, exact: unsent }
        : { i: 3, line: 'Closing round: your answer is in. Waiting for the store\'s answer and the end of the round.', bar: cb, action: wait('Waiting for the store') };
    }
    var pr = lastEv(v, /^Proof requested/);
    if (pr && lastFinal && lastFinal.action === 'request_proof' && (!st || st.final)) {
      return { i: 3, line: 'The judge asked for proof. In this scenario none is sent, so after ' + mins(W.proof) + ' the escrow releases the payment to the store.',
        bar: bar('Proof window', pr.at, pr.at + (W.proof || 300), now), action: wait('No action needed') };
    }
    var pre = steps.length > 1 ? 'Step ' + st.n + ': ' : '';
    if (st && !st.final) {
      if (st.decided) {
        /* Bradbury makes a decided verdict final about 30 minutes after the send (measured 26 to 30 min); the escrow only acts on it then */
        var dec = lastEv(v, new RegExp('^Step ' + st.n + ' decided, finalizing'));
        var settles = st.decided.outcome === 'REFUND' || st.decided.outcome === 'DENY';
        return { i: 3, line: pre + 'Decided, finalizing: ' + outcomeText(st.decided) + '. ' + (settles
          ? 'The payment waits for the final verdict: GenLayer makes it final in about 30 min, then the escrow pays.'
          : 'The next step waits for the final verdict: GenLayer makes it final in about 30 min.'),
          bar: dec ? bar('Until the verdict is final', dec.at, dec.at + FINAL_USUAL_S, now, 'Finalizing, almost there') : null,
          action: wait('Waiting for the judge') };
      }
      var n = st.attempts.length, att = st.attempts[n - 1] || {};
      if (att.no_consensus_at) {
        /* Bradbury closes an attempt without consensus after about 30 minutes; only then is the step sent again */
        var lastTry = n >= (v.max_attempts || 3);
        return { i: 3, line: pre + 'No consensus on the ' + (['first', 'second', 'third'][n - 1] || 'last') + ' attempt. ' + (lastTry
          ? 'It was the last attempt: if the judge cannot finish within ' + Math.round(((c.limits || {}).stall_seconds || 21600) / 3600) + ' hours, the store refunds you in full.'
          : 'Bradbury closes it after about 30 min, then the step is sent again.'),
          bar: lastTry ? null : bar('Until Bradbury closes the attempt', att.no_consensus_at, att.no_consensus_at + 1800, now, 'Closing, then sent again'),
          action: wait('Waiting for the judge') };
      }
      var sent = lastEv(v, new RegExp('^Step ' + st.n + ' sent to the judge, attempt ' + n + '$'));
      return { i: 3, line: pre + 'The judge is deciding, usually 1 to 2 min.' + (n > 1 ? ' Attempt ' + n + ': the previous one got no consensus and was resent.' : ''),
        bar: sent ? judgeBar(sent.at, now) : null, action: wait('Waiting for the judge') };
    }
    if (lastFinal) return { i: 3, line: 'Final verdict: ' + outcomeText(lastFinal) + '. Proposing it on Arc.', action: wait('Waiting for the escrow') };
    return { i: 3, line: late ? 'The evidence is registered. Sending the case to the judge.' : 'The store answered. Sending the case to the judge.', action: wait('Waiting for the judge') };
  }

  /* Buttons: a signing button shows a spinner and where it is; a wait is a disabled button in the same place */
  function button(a, arg, enabled) {
    var mineBusy = t.busy && t.busy === a.kind && t.busyArg === (arg || '');
    if (mineBusy) return '<button type="button" class="btn btn-primary btn-sm is-busy" disabled aria-busy="true">' + icon('circleNotch', 'spin') + esc(t.busyLabel) + '</button>';
    if (a.done) return '<button type="button" class="btn btn-primary btn-sm is-done" disabled>' + icon('check') + esc(a.label) + '</button>';
    if (!a.kind) return '<button type="button" class="btn btn-secondary btn-sm is-wait" disabled>' + icon('hourglass') + esc(a.label) + '</button>';
    return '<button type="button" class="btn ' + (a.quiet ? 'btn-secondary' : 'btn-primary') + ' btn-sm" data-try="' + a.kind + '" data-arg="' + esc(arg || '') + '"' +
      (t.busy || enabled === false ? ' disabled' : '') + '>' + esc(a.label) + (a.icon ? icon(a.icon) : '') + '</button>';
  }
  function note(key) {
    var n = t.note;
    if (!n || n.key !== key) return '';
    return '<span class="try-note ' + n.tone + '" role="status">' + esc(n.text) + (n.link ? ' <a href="' + esc(n.link.href) + '">' + esc(n.link.label) + '</a>' : '') + '</span>';
  }
  function fold(key, label, inner) {
    return '<details class="try-exact"' + (t.folds[key] ? ' open' : '') + '><summary data-try="fold" data-arg="' + esc(key) + '">' + esc(label) + '</summary>' + inner + '</details>';
  }

  /* Product illustrations: line art in the site's stroke style (accent on the dark background) */
  var ART = {
    sweater: '<path d="M60 22c4 6 12 9 20 9s16-3 20-9"/><path d="M60 22l-24 10-14 30 14 6 9-17v46h70V51l9 17 14-6-14-30-24-10"/>' +
      '<path d="M45 99h70M45 93h70" class="soft"/><path d="M36 62l-6 3M124 62l6 3" class="soft"/>' +
      '<path d="M66 44v22M80 40v30M94 44v22" class="soft" stroke-dasharray="2 5"/>',
    phone: '<rect x="56" y="10" width="48" height="92" rx="9"/><rect x="61" y="18" width="38" height="76" rx="4" class="soft"/>' +
      '<path d="M74 14h12"/><rect x="73" y="50" width="14" height="11" rx="2"/><path d="M76 50v-4a4 4 0 0 1 8 0v4"/>' +
      '<circle cx="80" cy="55.5" r="1.2" class="dot"/><path d="M68 74h24M70 80h20" class="soft"/>',
    laptop: '<rect x="38" y="16" width="84" height="56" rx="4"/><rect x="44" y="22" width="72" height="44" rx="2" class="soft"/>' +
      '<path d="M28 80h104l-8 10H36z"/><path d="M72 85h16" class="soft"/>' +
      '<rect x="120" y="92" width="16" height="10" rx="2" stroke-dasharray="3 3"/><path d="M128 92c0-8-6-10-14-10" stroke-dasharray="3 3" class="soft"/>',
    parcel: '<path d="M80 14l46 20v44l-46 22-46-22V34z"/><path d="M34 34l46 20 46-20M80 54v46" class="soft"/>' +
      '<path d="M57 24l46 20v14" /><path d="M52 66l14 6M52 72l10 4.5" class="soft"/>'
  };
  var BADGE = {
    L1: '<circle cx="134" cy="22" r="11"/><path d="M134 15v7l5 3"/>',
    D1: '<path d="M6 92c10-8 20 2 30-6" stroke-dasharray="3 4" class="soft"/><path d="M128 14a7 7 0 1 1 9 7c-2 1-2 3-2 5M135 31h.01"/>',
    D2: '<path d="M6 92c10-8 20 2 30-6" stroke-dasharray="3 4" class="soft"/><path d="M127 18h14M127 24h9" class="soft"/><path d="M124 12l20 18" />'
  };
  function art(s) {
    return '<svg class="try-art-svg" viewBox="0 0 160 110" aria-hidden="true">' + (ART[s.product.art] || ART.parcel) + (BADGE[s.id] || '') + '</svg>';
  }

  function productCard(s, can, lowFunds, faucet) {
    var U = ui(), last = s.steps[s.steps.length - 1], p = s.product;
    var bought = t.purchased && t.purchased.id === s.id && Date.now() - t.purchased.at < 4000;
    return '<article class="card try-product">' +
      '<div class="try-art">' + art(s) + '<span class="pill ' + (s.next_day ? 'pill-progress' : 'pill-settled') + ' try-wait">' + esc(p.wait) + '</span></div>' +
      '<div class="col" style="gap:10px;padding:16px 18px 18px;flex:1">' +
      '<div class="row" style="justify-content:space-between;gap:8px;align-items:baseline"><span style="font-size:15.5px">' + esc(p.name) + '</span><span class="mono" style="font-size:13px">1.00 USDC</span></div>' +
      '<div class="col" style="gap:6px;font-size:13px">' +
      '<div class="try-line"><span class="k">What goes wrong</span><span>' + esc(p.goes_wrong) + '</span></div>' +
      '<div class="try-line"><span class="k">The store</span><span>' + esc(s.store.charAt(0).toUpperCase() + s.store.slice(1)) + '.</span></div>' +
      '<div class="try-line"><span class="k">Expected</span><span class="mono" style="font-size:12px;color:' + (last.outcome === 'REFUND' ? 'var(--out-refund)' : 'var(--out-deny)') + '">' +
        esc(outcomeText(last)) + '</span></div>' +
      '<div class="try-line"><span class="k">You get back</span><span>' + usdc(s.settle.buyer) + (s.settle.store ? ', the store receives ' + usdc(s.settle.store) : '') + '</span></div>' +
      (s.next_day ? '<span class="pretty" style="font-size:12px;color:var(--warn-fg)">The delivery notice is sent tomorrow (UTC); come back to open the claim. <a href="#case/A">Live case A</a> shows the same path.</span>' : '') +
      '</div><div class="row" style="margin-top:auto;gap:10px;padding-top:4px">' +
      button(bought ? { label: 'Purchased', done: true } : { kind: 'start', label: 'Buy' }, s.id, can) +
      (lowFunds ? '<a class="btn btn-ghost" href="' + esc(faucet) + '" target="_blank" rel="noopener noreferrer">Get USDC from the faucet' + U.icon('arrowUpRight') + '</a>' : '') +
      '</div>' + note('start:' + s.id) + '</div></article>';
  }

  function orderCard(o, now) {
    var U = ui(), v = t.views[o.order] || { events: [], steps: [] }, sc = scenOf(o.scenario), p = phase(o, v, sc, now);
    var net = (U.getData() && U.getData().networks) || {};
    var url = function (e) {
      var base = e.net === 'arc' ? net.arc && net.arc.tx_url : net.bradbury && net.bradbury.tx_url;
      return e.tx && base ? base + e.tx : '';
    };
    var pill = v.refund ? '<span class="pill pill-settled">Refunded by the store</span>' : v.settled ? '<span class="pill pill-settled">Settled</span>'
      : p.i === 0 ? '<span class="pill pill-muted">Not paid</span>' : '<span class="pill pill-progress">In progress</span>';
    var focus = t.focus === o.order && Date.now() - t.focusAt < 12000;
    var tl = timeline(v);
    var phases = sc.path === 'late' ? PHASES_LATE : PHASES;
    /* A note next to the button belongs to the step it was written in: it goes once the order moves on */
    var nk = 'order:' + o.order, here = p.i + '|' + p.line;
    if (t.note && t.note.key === nk) { if (t.note.at == null) t.note.at = here; else if (t.note.at !== here) t.note = null; }
    var html = '<article class="card ord' + (focus ? ' ord-focus' : '') + '" id="ord-' + esc(o.order) + '">' +
      '<div class="ord-head"><div class="col" style="gap:5px;min-width:0">' +
      '<span class="ord-no">Order <b>' + esc(o.order) + '</b><button type="button" class="ord-copy" data-copy="' + esc(o.order) + '" title="Copy ' + esc(o.order) + '" aria-label="Copy order number ' + esc(o.order) + '">' + icon('copy') + '</button></span>' +
      '<span class="ord-product">' + esc((sc.product || {}).name || o.scenario) + '<span class="mono dim">1.00 USDC</span></span></div>' +
      '<span class="ml-auto">' + pill + '</span></div>' +
      '<ol class="ord-track" aria-label="Progress of order ' + esc(o.order) + '">' + phases.map(function (ph, i) {
        var cls = i < p.i || (i === p.i && p.done) ? 'done' : i === p.i ? 'cur' : '';
        return '<li class="' + cls + '"' + (cls === 'cur' ? ' aria-current="step"' : '') + '><span class="circle">' + icon(cls === 'done' ? 'check' : ph[0]) + '</span>' +
          '<span class="line"></span><span class="t">' + esc(ph[1]) + '</span></li>';
      }).join('') + '</ol>' +
      '<div class="ord-now"><span class="ord-line' + (p.tone ? ' ' + p.tone : '') + '">' + esc(p.line) + '</span>' + (p.bar ? timeBar(p.bar) : '') + '</div>' +
      (sc.path === 'late' && v.paid ? storeEmails(v, url, now) : '') +
      '<div class="ord-actions">' + button(p.action, o.order) + note('order:' + o.order) + '</div>';
    var folds = (p.exact ? fold('exact:' + o.order, 'View exact text', p.exact.map(function (x) { return '<pre class="claim-pre well-dark">' + esc(x) + '</pre>'; }).join('')) : '') +
      (tl.length ? fold('tl:' + o.order, 'Timeline (' + tl.length + ')', '<div class="col" style="gap:0">' + tl.map(function (e) {
        var when = new Date(e.at * 1000).toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
        return '<div class="tl-item"><div class="top"><span class="at">' + esc(when) + '</span></div><span class="act">' + esc(e.what) + '</span>' +
          (e.tx ? '<div class="row" style="gap:6px">' + U.hashChip(e.tx, url(e), e.net === 'arc' ? 'arc' : e.net === 'lacre' ? 'lacre' : 'bradbury') + '</div>' : '') + '</div>';
      }).join('') + '</div>') : '');
    return html + (folds ? '<div class="ord-folds">' + folds + '</div>' : '') + '</article>';
  }

  /* The late path's store emails: each one signed by the store, then verified by Lacre with a link to its attestation */
  function storeEmails(v, url, now) {
    var U = ui(), mails = v.mails || [];
    var row = function (kind, label) {
      var m = mails.filter(function (x) { return x.kind === kind; })[0];
      var st = !m ? (kind === 'delivered' ? 'sent the day after the payment (UTC)' : 'not signed yet')
        : m.record ? 'signed by the store, verified by Lacre (record ' + m.record + ')'
        : m.tx ? 'signed by the store, verifying on Lacre' : 'signed by the store';
      /* While Lacre's attestation is not final: what is happening and how long it usually takes */
      var sent = m && m.tx && !m.record ? lastEv(v, new RegExp('^Store email sent to Lacre \\(' + (m.label || '') + '\\)')) : null;
      return '<div class="col" style="gap:8px"><div class="row" style="gap:6px 12px;flex-wrap:wrap;align-items:center"><span style="font-size:13px;color:var(--color-neutral-100)">' + esc(label) + '</span>' +
        '<span class="muted" style="font-size:12.5px">' + esc(st) + '</span>' +
        (m && m.tx ? '<span class="ml-auto">' + U.hashChip(m.tx, url({ tx: m.tx, net: 'lacre' }), 'lacre') + '</span>' : '') + '</div>' +
        (sent ? '<span class="muted pretty" style="font-size:12.5px">Lacre checks the store\'s DKIM signature on GenLayer. The record counts once the attestation is final, about 30 min after it is sent.</span>' +
          timeBar(bar('Until the attestation is final', sent.at, sent.at + FINAL_USUAL_S, now, 'Finalizing, almost there')) : '') + '</div>';
    };
    return '<div class="col well" style="gap:8px;padding:12px 14px"><div class="row" style="gap:8px;align-items:center"><span class="eyebrow">Store emails</span>' +
      U.netBadge('lacre', { short: true }) + '</div>' + row('confirmed', 'Order confirmed') + row('delivered', 'Delivered') + '</div>';
  }

  /* Screens */
  function renderShop() {
    var el = document.getElementById('screen-demo-shop');
    var U = ui();
    if (!el || !U) return;
    var c = t.config;
    var head = '<header class="screen-head"><span class="kicker">10 / Demo Shop</span><h2>Buy something. Let it go wrong. Watch GenLayer decide.</h2>' +
      '<p>Every product costs 1.00 testnet USDC, and each one goes wrong in its own way. A GenLayer judge decides and the escrow pays.</p></header>' +
      '<div class="mini-flow" role="list" aria-label="How the demo runs" style="--mf-col:184px">' +
      [['coins', 'Buy'], ['warning', 'Something goes wrong'], ['scales', 'GenLayer decides and the escrow pays']].map(function (m, i) {
        return '<div role="listitem"><div class="node"><span class="circle">' + U.icon(m[0]) + '</span><span class="line"></span></div><span class="n">0' + (i + 1) + '</span><span class="t">' + esc(m[1]) + '</span></div>';
      }).join('') + '</div>' +
      '<p class="muted pretty" style="font-size:12.5px;margin:0">Demo mode on Arc testnet: separate contracts from the live test, windows of 5 minutes instead of days, and the store is a bot. ' +
      'You sign only your own transactions; the texts are fixed and were measured with the judge\'s committee.</p>';
    if (!c) {
      var msg = t.error === 'not-published' ? 'The Demo Shop opens when its Worker is published. These are its products.'
        : t.error === 'unreachable' ? 'The Demo Shop could not be reached. Try again in a minute.' : 'Loading the Demo Shop.';
      el.innerHTML = head + '<p class="card empty-note">' + msg + '</p>' + (t.shop ? '<div class="auto-grid ag-380">' +
        t.shop.scenarios.map(function (s) { return productCard(s, false, false, ''); }).join('') + '</div>' : '');
      return;
    }
    var connected = U.wallet.status === 'connected';
    var q = t.quota, left = q ? Math.max(0, q.per_address - q.address) : 0, dayFull = q && q.total >= q.per_day;
    var can = connected && !c.paused && q && left > 0 && !dayFull && !t.busy;
    var lowFunds = connected && U.wallet.balance != null && U.wallet.balance < 1;
    var faucet = ((U.getData() || {}).networks || {}).arc ? U.getData().networks.arc.faucet : 'https://faucet.circle.com';
    var list = connected ? mine() : [];
    var held = list.reduce(function (a, o) { var v = t.views[o.order]; return a + (v && v.paid && !isDone(v) ? (c.amount_cents || 100) / 100 : 0); }, 0);
    var credit = t.claimable || 0;
    var withdrawBtn = t.busy === 'withdraw' ? button({ kind: 'withdraw' }, '')
      : credit > 0 ? '<button type="button" class="btn btn-primary btn-sm btn-go" data-try="withdraw"' + (t.busy ? ' disabled' : '') + '>Withdraw ' + credit.toFixed(2) + ' USDC</button>'
        : t.withdrawnAt ? button({ label: 'Withdrawn', done: true }) : '<button type="button" class="btn btn-secondary btn-sm" disabled>Withdraw</button>';
    var flash = Date.now() - t.flash < 12000;
    var html = head + (c.paused ? '<p class="card empty-note" style="color:var(--warn-fg)">The Demo Shop is paused. Orders already paid are refunded in full by the store if they cannot finish.</p>' : '');
    html += '<div class="stat-row">' +
      '<div class="card stat"><div class="stat-top"><span class="eyebrow">Your wallet</span>' + U.netBadge('arc') + '</div>' +
      (connected ? '<span class="stat-big" style="font-size:24px">' + (U.wallet.balance != null ? U.wallet.balance.toFixed(2) : U.wallet.balanceErr ? '--' : '...') + ' <span style="font-size:14px">USDC</span></span>' +
        '<span class="stat-sub">' + esc(me().slice(0, 6) + '...' + me().slice(-4)) + (q ? ', ' + q.address + ' of ' + q.per_address + ' orders today' : '') + '</span>'
        : '<span class="stat-sub">Connect a wallet on Arc testnet to shop.</span><div><button type="button" class="btn btn-primary btn-sm" data-try="connect">Connect wallet</button></div>') + '</div>' +
      '<div class="card stat"><div class="stat-top"><span class="eyebrow">Held in the escrow</span></div><span class="stat-big" style="font-size:24px">' + held.toFixed(2) + ' <span style="font-size:14px">USDC</span></span>' +
        '<span class="stat-sub">Your paid orders waiting for a verdict.</span></div>' +
      '<div class="card stat' + (credit > 0 ? ' try-credit' : '') + (flash ? ' try-flash' : '') + '" id="try-credited"><div class="stat-top"><span class="eyebrow">Credited to you</span></div>' +
        '<span class="stat-big" style="font-size:24px">' + (connected && t.claimable == null ? '--' : credit.toFixed(2)) + ' <span style="font-size:14px">USDC</span></span>' +
        '<div class="row" style="gap:10px"><span class="stat-sub">' + (connected && t.claimable == null ? 'Could not read the escrow on Arc; retrying.' : 'Refunds ready to withdraw.') + '</span><span class="ml-auto">' + withdrawBtn + '</span></div>' + note('withdraw') + '</div>' +
      '</div>';
    if (connected && q && (left === 0 || dayFull)) html += '<p class="muted" style="font-size:12.5px;margin:0">' + (dayFull ? 'The Demo Shop reached its orders for today.' : 'You used your ' + q.per_address + ' orders for today.') + ' Come back tomorrow (UTC).</p>';
    if (list.length) {
      var prog = inProgress().length, settled = list.filter(function (o) { return isDone(t.views[o.order]); }).length;
      html += '<a class="card try-orders" href="#my-orders">' + icon('receipt') + '<span>My orders</span><span class="dim">' + prog + ' in progress, ' + settled + ' settled</span>' +
        '<span class="ml-auto row" style="gap:6px">Open' + icon('arrowRight') + '</span></a>';
    }
    html += '<div class="auto-grid ag-380">' + c.scenarios.map(function (s) { return productCard(s, can, lowFunds, faucet); }).join('') + '</div>';
    html += '<p class="faint pretty" style="font-size:12px;margin:0">If the judge cannot finish within ' + Math.round(c.limits.stall_seconds / 3600) + ' hours, the store refunds you in full. Limits: ' +
      c.limits.per_address_per_day + ' orders per address per day, ' + c.limits.per_day + ' in total.</p>';
    el.innerHTML = html;
  }

  function renderOrders() {
    var el = document.getElementById('screen-my-orders');
    var U = ui();
    if (!el || !U) return;
    var c = t.config;
    var html = '<header class="screen-head"><span class="kicker">11 / My orders</span><h2>My orders</h2>' +
      '<p>Your Demo Shop orders: paid on Arc, judged on GenLayer, settled by the escrow. The demo store and the judge keep working while this page is closed.</p></header>';
    if (!c) {
      el.innerHTML = html + '<p class="card empty-note">' + (t.error ? 'The Demo Shop could not be reached. Try again in a minute.' : 'Loading your orders.') + '</p>';
      return;
    }
    if (U.wallet.status !== 'connected') {
      el.innerHTML = html + '<div class="card empty-note col" style="gap:12px"><span>Connect a wallet on Arc testnet to see its orders.</span>' +
        '<div><button type="button" class="btn btn-primary btn-sm" data-try="connect">Connect wallet</button></div></div>';
      return;
    }
    var list = mine().slice().reverse(), now = Date.now() / 1000;
    if (!list.length) {
      el.innerHTML = html + '<p class="card empty-note">No orders yet. <a href="#demo-shop">Buy something in the Demo Shop</a>.</p>';
      return;
    }
    el.innerHTML = html + '<div class="col" style="gap:14px">' + list.map(function (o) { return orderCard(o, now); }).join('') + '</div>' +
      '<p class="faint pretty" style="font-size:12px;margin:0">Every order this wallet paid, from any browser, and the unpaid ones started here. If the judge cannot finish within ' +
      Math.round(c.limits.stall_seconds / 3600) + ' hours, the store refunds you in full.</p>';
  }

  /* The sidebar counter: orders paid and not settled, their numbers on hover */
  function counter() {
    var n = document.getElementById('nav-orders-count');
    if (!n || !ui()) return;
    var ids = ui().wallet.status === 'connected' ? inProgress().map(function (o) { return o.order; }) : [];
    n.hidden = !ids.length;
    n.textContent = String(ids.length);
    n.title = ids.length ? 'In progress: ' + ids.join(', ') : '';
    n.setAttribute('aria-label', ids.length ? ids.length + ' in progress: ' + ids.join(', ') : '');
  }

  function render() {
    if (!ui()) return;
    renderShop();
    renderOrders();
    counter();
  }
  function focusOrder() {
    var x = t.focus && document.getElementById('ord-' + t.focus);
    if (x && x.scrollIntoView) x.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }

  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-try]');
    if (!b) return;
    e.preventDefault();
    act(b.getAttribute('data-try'), b.getAttribute('data-arg'));
  });

  window.TenetShop = {
    /* screen: 'demo-shop' or 'my-orders'; arg: the order to bring into view */
    show: function (screen, arg) {
      t.screen = screen;
      if (screen === 'my-orders' && arg) { t.focus = arg; t.focusAt = Date.now(); }
      if (screen === 'demo-shop' && t.flashNext) { t.flash = Date.now(); t.flashNext = false; }
      load();
      clearInterval(t.timer); t.timer = setInterval(function () { if (t.config) refresh(); }, POLL_MS);
      clearInterval(t.clock); t.clock = setInterval(clockTick, CLOCK_MS);
      if (screen === 'my-orders' && arg) setTimeout(focusOrder, 60);
    },
    /* Off these screens only the sidebar counter needs the orders, at a slower pace */
    hide: function () {
      t.screen = '';
      clearInterval(t.clock); t.clock = 0;
      clearInterval(t.timer); t.timer = setInterval(function () { if (t.config && inProgress().length) refresh(); }, SLOW_MS);
    },
    onWallet: function () {
      t.quota = null;
      if (ui().wallet.status === 'connected') { if (t.config) refresh(); else load(); } else render();
    },
    _state: t, _act: act, _card: orderCard
  };
})();
