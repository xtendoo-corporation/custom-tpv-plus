(() => {
    'use strict';

    const API = '/feria/api/v1';
    const INFLIGHT_KEY = 'feria_inflight';
    const CASH_KEY = 'feria_cash_inflight';
    const SCREEN_IDLE_MS = 60 * 1000;
    const TRANSIENT = ['customer', 'pick', 'amount', 'saldo', 'orders', 'result', 'cash', 'cash_count', 'cash_keep', 'cash_confirm'];
    const $app = document.getElementById('app');
    const $banner = document.getElementById('banner');

    const store = {
        get(key) { try { return localStorage.getItem(key); } catch { return null; } },
        set(key, value) { try { localStorage.setItem(key, value); } catch { /* storage may be blocked */ } },
        del(key) { try { localStorage.removeItem(key); } catch { /* ignore */ } },
    };

    const S = {
        view: 'home',
        online: true,
        currency: '€',
        action: null,
        query: '',
        matches: [],
        contact: null,
        by: null, // how the customer was identified: {code} or {contact_id}
        orders: [],
        cash: null, // what the drawer should hold, from the server
        counted: '', // cash counted by the person
        kept: '', // cash left for the next day
        amount: '',
        message: '',
        result: null,
        waitSince: 0,
        busy: false,
    };

    let lastCard = { value: '', at: 0 }; // last card read on the current screen, to drop double reads

    // ---------- helpers ----------
    const esc = (text) => String(text ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    // "EUR" -> "€", "USD" -> "$"; unknown codes are shown as they are
    function currencySymbol(code) {
        try {
            const parts = new Intl.NumberFormat('es-ES', { style: 'currency', currency: code }).formatToParts(0);
            return parts.find((part) => part.type === 'currency')?.value || code;
        } catch { return code; }
    }
    const money = (value) => `${String(value).replace('.', ',')} ${S.currency}`;
    const toCents = (text) => {
        const [whole, frac = ''] = String(text || '0').split('.');
        return Number(whole || 0) * 100 + Number(frac.padEnd(2, '0').slice(0, 2));
    };
    const fromCents = (cents) => `${Math.floor(Math.abs(cents) / 100)}.${String(Math.abs(cents) % 100).padStart(2, '0')}`;
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const jitter = (ms) => ms * (0.6 + Math.random() * 0.8);

    function uuid4() {
        const b = crypto.getRandomValues(new Uint8Array(16));
        b[6] = (b[6] & 0x0f) | 0x40;
        b[8] = (b[8] & 0x3f) | 0x80;
        const h = [...b].map((x) => x.toString(16).padStart(2, '0')).join('');
        return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
    }

    function feedback(ok) {
        try { navigator.vibrate?.(ok ? 120 : [200, 100, 200]); } catch { /* ignore */ }
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const osc = ctx.createOscillator();
            osc.frequency.value = ok ? 880 : 220;
            osc.connect(ctx.destination);
            osc.start();
            osc.stop(ctx.currentTime + (ok ? 0.18 : 0.5));
        } catch { /* ignore */ }
    }

    class NetError extends Error {}

    async function api(method, path, body, timeout = 8000) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeout);
        try {
            const response = await fetch(API + path, {
                method,
                signal: controller.signal,
                cache: 'no-store',
                headers: { 'Content-Type': 'application/json', 'X-Api-Version': '1' },
                body: body === undefined ? undefined : JSON.stringify(body),
            });
            let data = {};
            try { data = await response.json(); } catch { /* non JSON body, e.g. a proxy error page */ }
            if (response.status >= 500 || (response.status === 404 && !data.error_code && !data.status)) {
                throw new NetError(`HTTP ${response.status}`);
            }
            setOnline(true);
            return { status: response.status, data };
        } catch (error) {
            if (error instanceof NetError || error.name === 'AbortError' || error instanceof TypeError) {
                setOnline(false);
                throw new NetError(String(error.message || error));
            }
            throw error;
        } finally {
            clearTimeout(timer);
        }
    }

    function setOnline(value) {
        if (S.online === value) { return; }
        S.online = value;
        paintStatus();
        // coming back online: redraw so buttons recover their own enabled state
        if (value && ['home', 'customer', 'amount'].includes(S.view)) { render(); }
    }

    function paintStatus() {
        $banner.hidden = S.online;
        const pill = document.getElementById('pill');
        if (pill) {
            pill.textContent = S.online ? 'ONLINE' : 'SIN CONEXIÓN';
            pill.classList.toggle('off', !S.online);
        }
        if (!S.online) {
            document.querySelectorAll('.big, [data-needs-online]').forEach((el) => { el.disabled = true; });
        }
    }

    async function healthLoop() {
        for (;;) {
            try {
                const response = await fetch(`${API}/health`, { cache: 'no-store', signal: AbortSignal.timeout(3000) });
                setOnline(response.ok);
            } catch { setOnline(false); }
            await sleep(S.online ? 5000 : 2000);
        }
    }

    // A stray screen returns to the four buttons.
    let idleTimer = null;
    function touchIdle() {
        clearTimeout(idleTimer);
        idleTimer = setTimeout(() => { if (TRANSIENT.includes(S.view)) { home(); } }, SCREEN_IDLE_MS);
    }
    document.addEventListener('pointerdown', touchIdle);
    document.addEventListener('keydown', touchIdle);

    // ---------- navigation ----------
    function go(view) {
        S.view = view;
        lastCard = { value: '', at: 0 }; // a new screen starts a new reading
        render();
        touchIdle();
    }

    function home() {
        Object.assign(S, { action: null, query: '', matches: [], contact: null, by: null, orders: [], cash: null, counted: '', kept: '', amount: '', message: '', result: null, busy: false });
        go('home');
    }

    // ---------- views ----------
    const TITLES = { COBRAR: 'COBRAR', RECARGAR: 'RECARGAR', PEDIDOS: 'VER PEDIDOS', SALDO: 'VER SALDO' };

    const bar = (back = true, title = TITLES[S.action] || '') => `
        <div class="bar">
            ${back ? '<button class="link" data-act="home">← Inicio</button>' : '<span class="who">FERIA</span>'}
            <span class="who">${esc(title)}</span>
            <span class="right">
                ${back ? '' : '<button class="link cashbtn" data-act="cash" data-needs-online>💰 Caja</button>'}
                <span id="pill" class="pill ${S.online ? '' : 'off'}">${S.online ? 'ONLINE' : 'SIN CONEXIÓN'}</span>
            </span>
        </div>`;

    const keypad = () => `<div class="pad">${[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => `<button class="btn" data-act="key" data-k="${n}">${n}</button>`).join('')}
        <button class="btn" data-act="key" data-k=".">,</button><button class="btn" data-act="key" data-k="0">0</button>
        <button class="btn" data-act="back">⌫</button></div>`;

    const shownAmount = () => (S.amount ? S.amount.replace('.', ',') : '0');
    const when = (iso) => new Date(iso).toLocaleString('es-ES', { dateStyle: 'short', timeStyle: 'short' });

    const views = {
        home() {
            return `${bar(false)}<div class="home">
                <button class="big b-cobrar" data-act="start" data-a="COBRAR"><span class="ico">💳</span>Cobrar<small>Restar saldo</small></button>
                <button class="big b-recargar" data-act="start" data-a="RECARGAR"><span class="ico">➕</span>Recargar<small>Añadir saldo</small></button>
                <button class="big b-pedidos" data-act="start" data-a="PEDIDOS"><span class="ico">🧾</span>Ver pedidos<small>Solo consulta</small></button>
                <button class="big b-saldo" data-act="start" data-a="SALDO"><span class="ico">👁</span>Ver saldo<small>Solo consulta</small></button>
            </div>`;
        },

        customer() {
            return `${bar()}<div class="screen"><h1 class="title">¿Qué cliente?</h1>
                <p class="sub">Acerque la tarjeta o escriba el nombre</p>
                <input id="query" class="field" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="Tarjeta o nombre" value="${esc(S.query)}">
                ${S.message ? `<p class="sub err">${esc(S.message)}</p>` : ''}
                <button class="btn go" data-act="find" data-needs-online ${S.busy ? 'disabled' : ''}>Buscar</button></div>`;
        },

        pick() {
            const rows = S.matches.map((m) => `<button class="btn ghost" data-act="choose" data-id="${m.id}" data-needs-online>${esc(m.name)}</button>`).join('');
            return `${bar()}<div class="screen"><h1 class="title">¿Cuál de ellos?</h1>
                <div class="ops">${rows}</div></div>`;
        },

        saldo() {
            return `${bar()}<div class="screen">${contactCard(S.contact)}
                <div class="balance">${money(S.contact.balance)}</div>
                <button class="btn" data-act="home">Volver</button></div>`;
        },

        orders() {
            const kinds = { COBRAR: 'Cobro', RECARGAR: 'Recarga', ANULACION: 'Anulación', AJUSTE: 'Ajuste' };
            const rows = S.orders.map((m) => {
                const negative = Number(m.signed_amount) < 0;
                const when = new Date(m.received_at).toLocaleString('es-ES', { dateStyle: 'short', timeStyle: 'short' });
                return `<div class="card item"><span><b>${esc(kinds[m.type] || m.type)}</b><br><small>${esc(when)}</small></span>
                    <span class="amt ${negative ? 'neg' : 'pos'}">${negative ? '−' : '+'}${money(String(m.amount))}<br><small>Saldo ${money(m.balance_after)}</small></span></div>`;
            }).join('');
            return `${bar()}<div class="screen">${contactCard(S.contact)}
                <p class="sub">Saldo actual: <b>${money(S.contact.balance)}</b></p>
                <div class="list">${rows || '<p class="empty">Todavía no hay operaciones</p>'}</div>
                <button class="btn" data-act="home">Volver</button></div>`;
        },

        amount() {
            const c = S.contact;
            const cobrar = S.action === 'COBRAR';
            const shown = S.amount ? S.amount.replace('.', ',') : '0';
            return `${bar()}<div class="screen">${contactCard(c)}
                <p class="sub">Saldo actual: <b>${money(c.balance)}</b></p>
                <div class="amount ${cobrar ? 'cobrar' : 'recargar'}">${esc(shown)} ${esc(S.currency)}</div>
                ${S.message ? `<p class="sub err">${esc(S.message)}</p>` : ''}
                ${keypad()}
                <div class="row"><button class="btn ghost" data-act="home">Cancelar</button>
                    <button class="btn ${cobrar ? 'stop' : 'go'}" data-act="confirm" data-needs-online ${c.blocked ? 'disabled' : ''}>${cobrar ? 'COBRAR' : 'RECARGAR'}</button></div></div>`;
        },

        cash() {
            const c = S.cash;
            const since = c.period_start ? when(c.period_start) : 'el principio';
            return `${bar(true, 'CAJA')}<div class="screen">
                <p class="sub">Efectivo que debe haber en caja</p>
                <div class="balance">${money(c.expected)}</div>
                <div class="card list">
                    <div class="item"><span>Fondo (lo que se dejó)</span><b>${money(c.opening_float)}</b></div>
                    <div class="item"><span>+ Recargas cobradas</span><b>${money(c.recharges)}</b></div>
                    <div class="item"><span>− Devoluciones</span><b>${money(c.refunds)}</b></div>
                </div>
                <p class="sub">Desde ${esc(since)} · ${c.movements_count} operaciones<br>Ventas (cobros): <b>${money(c.sales)}</b></p>
                <div class="row"><button class="btn" data-act="cash-count">Contar caja</button>
                    <button class="btn stop" data-act="cash-count">Cerrar caja</button></div></div>`;
        },

        cash_count() {
            const diff = S.amount === '' ? null : toCents(S.amount) - toCents(S.cash.expected);
            const verdict = diff === null ? '&nbsp;' : diff === 0 ? 'La caja cuadra' : diff > 0 ? `Sobran ${money(fromCents(diff))}` : `Faltan ${money(fromCents(diff))}`;
            return `${bar(true, 'CONTAR CAJA')}<div class="screen">
                <p class="sub">Cuenta el dinero y escribe el total · Debe haber <b>${money(S.cash.expected)}</b></p>
                <div class="amount">${esc(shownAmount())} ${esc(S.currency)}</div>
                <p class="sub ${diff ? 'err' : ''}">${verdict}</p>
                ${S.message ? `<p class="sub err">${esc(S.message)}</p>` : ''}
                ${keypad()}
                <div class="row"><button class="btn" data-act="cash-save-count" data-needs-online>Guardar recuento</button>
                    <button class="btn stop" data-act="cash-to-keep">Cerrar caja</button></div></div>`;
        },

        cash_keep() {
            const kept = S.amount === '' ? 0 : toCents(S.amount);
            return `${bar(true, 'CERRAR CAJA')}<div class="screen">
                <p class="sub">Has contado <b>${money(S.counted)}</b> · ¿Cuánto dejas para mañana?</p>
                <div class="amount">${esc(shownAmount())} ${esc(S.currency)}</div>
                <p class="sub">Retiras: <b>${money(fromCents(toCents(S.counted) - kept))}</b></p>
                ${S.message ? `<p class="sub err">${esc(S.message)}</p>` : ''}
                <div class="row"><button class="btn ghost" data-act="cash-keep-zero">No dejar nada</button>
                    <button class="btn ghost" data-act="cash-keep-all">Dejar todo</button></div>
                ${keypad()}
                <button class="btn stop" data-act="cash-review">Continuar</button></div>`;
        },

        cash_confirm() {
            const c = S.cash;
            const diff = toCents(S.counted) - toCents(c.expected);
            const verdict = diff === 0 ? 'Cuadra' : `${diff > 0 ? 'Sobran' : 'Faltan'} ${money(fromCents(diff))}`;
            return `${bar(true, 'CONFIRMAR CIERRE')}<div class="screen">
                <div class="card list">
                    <div class="item"><span>Debía haber</span><b>${money(c.expected)}</b></div>
                    <div class="item"><span>Contado</span><b>${money(S.counted)}</b></div>
                    <div class="item"><span>Diferencia</span><b class="${diff ? 'err' : ''}">${verdict}</b></div>
                    <div class="item"><span>Dejas para mañana</span><b>${money(S.kept)}</b></div>
                    <div class="item"><span>Retiras</span><b>${money(fromCents(toCents(S.counted) - toCents(S.kept)))}</b></div>
                </div>
                <p class="sub">Al cerrar, la caja de mañana empieza con ${money(S.kept)}.</p>
                <div class="row"><button class="btn ghost" data-act="home">Cancelar</button>
                    <button class="btn stop" data-act="cash-confirm" data-needs-online>CERRAR CAJA</button></div></div>`;
        },

        sending() {
            return '<div class="result wait"><div class="spin"></div><h1>Procesando…</h1><p>No retire la tarjeta</p></div>';
        },

        pending() {
            return `<div class="result wait"><div class="spin"></div><h1>PENDIENTE DE CONFIRMAR</h1>
                <p>No se sabe si la operación se ha registrado. Espere, se resolverá sola.</p>
                <p id="elapsed"></p></div>`;
        },

        result() {
            const r = S.result;
            return `<div class="result ${r.ok ? 'ok' : 'bad'}"><h1>${esc(r.title)}</h1>
                ${r.lines.map((l) => `<p>${esc(l)}</p>`).join('')}
                <button class="btn" data-act="home">Nueva operación</button></div>`;
        },
    };

    function contactCard(c) {
        return `<div class="card who-card"><div class="name">${esc(c.contact.name)}</div>
            ${c.blocked ? '<div class="tag">BLOQUEADA</div>' : ''}</div>`;
    }

    function render() {
        $app.innerHTML = views[S.view]();
        paintStatus();
        if (S.view === 'customer') {
            const input = document.getElementById('query');
            input.focus();
            input.addEventListener('keydown', (event) => {
                if (event.key === 'Enter') { event.preventDefault(); S.query = input.value; find(); }
            });
            input.addEventListener('input', () => { S.query = input.value; });
            // a keyboard-wedge reader types into the focused field: keep the focus there
            input.addEventListener('blur', () => { if (S.view === 'customer') { setTimeout(() => input.focus(), 50); } });
        }
    }

    // ---------- finding the customer ----------
    async function showCustomer(path, by) {
        const { status, data } = await api('GET', path);
        if (status !== 200) { return { status, data }; }
        S.contact = data;
        S.by = by;
        if (data.currency) { S.currency = currencySymbol(data.currency); }
        if (S.action === 'PEDIDOS') {
            // "pedidos" are the operations stored by this module (cobros and recargas), newest first
            const history = await api('GET', `/movements?contact_id=${data.contact.id}&limit=30`);
            S.orders = history.data.movements || [];
            go('orders');
        } else {
            go(S.action === 'SALDO' ? 'saldo' : 'amount');
        }
        return { status, data };
    }

    // The field takes a card code (reader or typed) or part of a name.
    async function find() {
        const text = S.query.trim();
        if (!text || S.busy) { return; }
        S.busy = true; S.message = '';
        try {
            const byCard = await showCustomer(`/contacts/lookup?code=${encodeURIComponent(text)}`, { code: text });
            if (byCard.status === 200) { S.busy = false; return; }
            if (byCard.data.error_code === 'CODE_UNKNOWN') {
                const found = await api('GET', `/contacts/search?q=${encodeURIComponent(text)}`);
                S.matches = found.data.contacts || [];
                if (S.matches.length === 1) {
                    S.busy = false;
                    return choose(S.matches[0].id);
                }
                if (S.matches.length > 1) { S.busy = false; return go('pick'); }
                S.message = 'Cliente no encontrado';
            } else {
                S.message = byCard.data.message || 'Error';
            }
            S.query = '';
            feedback(false);
        } catch {
            S.message = 'Sin conexión: inténtelo de nuevo';
        }
        S.busy = false;
        render();
    }

    async function choose(id) {
        try { await showCustomer(`/contacts/lookup?contact_id=${id}`, { contact_id: id }); } catch { S.message = 'Sin conexión: inténtelo de nuevo'; render(); }
    }

    // ---------- amount ----------
    function pressKey(k) {
        let a = S.amount;
        if (k === '.') {
            if (a.includes('.')) { return; }
            a = a === '' ? '0.' : `${a}.`;
        } else {
            if (a.includes('.') && a.split('.')[1].length >= 2) { return; }
            if (a === '0') { a = ''; }
            if (a.replace('.', '').length >= 8) { return; }
            a += k;
        }
        S.amount = a; S.message = '';
        render();
    }

    const amountValid = () => /^\d+(\.\d{1,2})?$/.test(S.amount) && Number(S.amount) > 0;

    function pad2(text) {
        const [whole, frac = ''] = text.split('.');
        return `${whole}.${frac.padEnd(2, '0')}`;
    }

    async function confirm() {
        if (!amountValid()) { S.message = 'Escribe un importe'; return render(); }
        const amount = pad2(S.amount);
        if (S.action === 'COBRAR' && Number(amount) > Number(S.contact.balance)) {
            S.message = `Saldo insuficiente (${money(S.contact.balance)})`;
            feedback(false);
            return render();
        }
        const op = {
            uuid: uuid4(),
            contactName: S.contact.contact.name,
            body: { type: S.action, amount, created_at_device: new Date().toISOString(), ...S.by },
        };
        op.body.uuid = op.uuid;
        // persist BEFORE sending: a reload or power cut must not lose track of this operation
        store.set(INFLIGHT_KEY, JSON.stringify(op));
        await send(op);
    }

    // ---------- delivering the operation ----------
    function finishOk(op, data, wasPending = false) {
        store.del(INFLIGHT_KEY);
        const cobrar = op.body.type === 'COBRAR';
        S.result = {
            ok: true,
            title: cobrar ? 'COBRADO' : 'RECARGADO',
            lines: [op.contactName, `${cobrar ? '−' : '+'}${money(op.body.amount)}`, `Saldo: ${money(data.balance_after)}`],
        };
        feedback(true);
        go('result');
        // after a pending operation the person must acknowledge the outcome, never auto-dismiss it
        if (!wasPending) { setTimeout(() => { if (S.view === 'result' && S.result?.ok) { home(); } }, 7000); }
    }

    function finishBad(data) {
        store.del(INFLIGHT_KEY);
        const texts = {
            INSUFFICIENT_BALANCE: `Saldo insuficiente${data.balance ? ` (${money(data.balance)})` : ''}`,
            CODE_BLOCKED: 'Tarjeta o cliente bloqueado',
            CODE_UNKNOWN: 'Cliente no reconocido',
            LIMIT_EXCEEDED: 'Importe por encima del límite',
            FORBIDDEN: 'Operación no permitida',
            DUPLICATE: 'Operación repetida con datos distintos',
        };
        S.result = { ok: false, title: 'NO REALIZADO', lines: [texts[data.error_code] || data.message || 'Error', 'No se ha registrado nada'] };
        feedback(false);
        go('result');
    }

    // true when the reply is definitive
    function handleReply(op, status, data, wasPending = false) {
        if (status === 200 && data.status === 'confirmed') { finishOk(op, data, wasPending); return true; }
        if (status >= 400 && status < 500 && data.error_code && status !== 429) { finishBad(data); return true; }
        return false;
    }

    // One attempt to deliver the operation. Anything unclear becomes PENDIENTE DE CONFIRMAR.
    async function send(op) {
        go('sending');
        try {
            const { status, data } = await api('POST', '/movements', op.body, 8000);
            return handleReply(op, status, data) || resolvePending(op);
        } catch { return resolvePending(op); }
    }

    // Ask the server what happened to this uuid until it is known. Re-sending the same uuid is
    // safe: the server registers it once and always answers with the same result.
    async function resolvePending(op) {
        S.waitSince = Date.now();
        go('pending');
        const tick = setInterval(() => {
            const el = document.getElementById('elapsed');
            if (el) { el.textContent = `${Math.round((Date.now() - S.waitSince) / 1000)} s`; }
        }, 1000);
        let delay = 1000;
        try {
            for (;;) {
                try {
                    const known = await api('GET', `/movements/${op.uuid}`, undefined, 5000);
                    if (known.status === 200 && known.data.status === 'confirmed') { return finishOk(op, known.data, true); }
                    if (known.status === 404) {
                        const retry = await api('POST', '/movements', op.body, 8000);
                        if (handleReply(op, retry.status, retry.data, true)) { return; }
                    }
                } catch { /* still offline: keep asking */ }
                await sleep(jitter(delay));
                delay = Math.min(delay * 1.5, 5000);
            }
        } finally { clearInterval(tick); }
    }

    // ---------- cash desk ----------
    async function openCash() {
        try {
            const { status, data } = await api('GET', '/cash');
            if (status !== 200) { return; }
            S.cash = data;
            S.currency = currencySymbol(data.currency);
            S.amount = ''; S.counted = ''; S.kept = ''; S.message = '';
            go('cash');
        } catch { /* the banner already says there is no connection */ }
    }

    const cashAmountOk = () => /^\d+(\.\d{1,2})?$/.test(S.amount);

    function cashOperation(kind) {
        const body = { uuid: uuid4(), kind, counted: pad2(S.counted) };
        if (kind === 'close') { body.kept = pad2(S.kept); }
        const op = { uuid: body.uuid, body };
        // persisted before sending, like the charges: a reload must not lose a cierre
        store.set(CASH_KEY, JSON.stringify(op));
        return sendCash(op);
    }

    function finishCash(op, data) {
        store.del(CASH_KEY);
        const closing = data.kind === 'close';
        const diff = toCents(data.difference);
        S.result = {
            ok: true,
            title: closing ? 'CAJA CERRADA' : 'RECUENTO GUARDADO',
            lines: [
                `Debía haber ${money(data.expected)} · Contado ${money(data.counted)}`,
                diff === 0 ? 'La caja cuadra' : `${diff > 0 ? 'Sobran' : 'Faltan'} ${money(fromCents(diff))}`,
                ...(closing ? [`Dejas para mañana: ${money(data.kept)}`, `Retiras: ${money(data.withdrawn)}`] : []),
            ],
        };
        feedback(true);
        go('result'); // no auto-dismiss: the result of a cierre has to be read
    }

    function finishCashBad(data) {
        store.del(CASH_KEY);
        S.result = { ok: false, title: 'NO REALIZADO', lines: [data.message || 'Error', 'No se ha registrado nada'] };
        feedback(false);
        go('result');
    }

    // Re-sending the same uuid is safe: the server stores it once and answers the same.
    async function sendCash(op) {
        go('sending');
        let delay = 1000;
        for (;;) {
            try {
                const { status, data } = await api('POST', '/cash', op.body, 8000);
                if (status === 200) { return finishCash(op, data); }
                if (status >= 400 && status < 500 && data.error_code && status !== 429) { return finishCashBad(data); }
            } catch { /* no connection: keep trying */ }
            if (S.view !== 'pending') { go('pending'); }
            await sleep(jitter(delay));
            delay = Math.min(delay * 1.5, 5000);
        }
    }

    function resumeInflight() {
        const cashRaw = store.get(CASH_KEY);
        if (cashRaw) {
            try { sendCash(JSON.parse(cashRaw)); return true; } catch { store.del(CASH_KEY); }
        }
        const raw = store.get(INFLIGHT_KEY);
        if (!raw) { return false; }
        try {
            resolvePending(JSON.parse(raw));
            return true;
        } catch { store.del(INFLIGHT_KEY); return false; }
    }

    // ---------- card readers ----------
    // 1. USB / PDA keyboard-wedge readers (RFID or NFC) type into the focused field, see render().
    // 2. Web NFC: Chrome on Android, or the NDEFReader polyfill the TPVPlus Android app injects.
    // 3. window.handleNfcScan(id): global entry point the native Android app calls with the tag.
    function onCardRead(raw) {
        const value = String(raw || '').trim();
        // a tag is only meaningful while the app is asking "¿Qué cliente?"
        if (!value || S.view !== 'customer' || S.busy) { return; }
        const now = Date.now();
        if (lastCard.value === value && now - lastCard.at < 2000) { return; }
        lastCard = { value, at: now };
        S.query = value;
        const input = document.getElementById('query');
        if (input) { input.value = value; }
        find();
    }
    window.handleNfcScan = onCardRead;

    let nfcStarted = false;
    async function startNfc() {
        if (nfcStarted || !('NDEFReader' in window)) { return; }
        nfcStarted = true;
        try {
            const reader = new NDEFReader();
            await reader.scan();
            reader.addEventListener('reading', (event) => {
                // a text record carries the identifier when the card was written with one; else use the UID
                let value = '';
                for (const record of event.message?.records || []) {
                    if (record.recordType === 'text') {
                        value = new TextDecoder(record.encoding || 'utf-8').decode(record.data).trim();
                        if (value) { break; }
                    }
                }
                onCardRead(value || event.serialNumber);
            });
        } catch { nfcStarted = false; } // not allowed yet: retried on the next tap
    }
    window.addEventListener('nfc-ready', startNfc);

    // ---------- events ----------
    $app.addEventListener('click', (event) => {
        const el = event.target.closest('[data-act]');
        if (!el || el.disabled) { return; }
        switch (el.dataset.act) {
            case 'start': S.action = el.dataset.a; S.query = ''; S.message = ''; go('customer'); startNfc(); break;
            case 'find': find(); break;
            case 'choose': choose(el.dataset.id); break;
            case 'home': home(); break;
            case 'key': pressKey(el.dataset.k); break;
            case 'back': S.amount = S.amount.slice(0, -1); render(); break;
            case 'confirm': confirm(); break;
            case 'cash': openCash(); break;
            case 'cash-count': S.amount = ''; S.message = ''; go('cash_count'); break;
            case 'cash-save-count':
                if (!cashAmountOk()) { S.message = 'Escribe lo que has contado'; render(); break; }
                S.counted = pad2(S.amount);
                cashOperation('count');
                break;
            case 'cash-to-keep':
                if (!cashAmountOk()) { S.message = 'Escribe lo que has contado'; render(); break; }
                S.counted = pad2(S.amount); S.amount = ''; S.message = '';
                go('cash_keep');
                break;
            case 'cash-keep-zero': S.amount = '0'; S.message = ''; render(); break;
            case 'cash-keep-all': S.amount = S.counted.replace(/\.00$/, ''); S.message = ''; render(); break;
            case 'cash-review':
                if (!cashAmountOk()) { S.message = 'Escribe cuánto dejas o pulsa "No dejar nada"'; render(); break; }
                if (toCents(S.amount) > toCents(S.counted)) { S.message = 'No puedes dejar más de lo contado'; render(); break; }
                S.kept = pad2(S.amount);
                go('cash_confirm');
                break;
            case 'cash-confirm': cashOperation('close'); break;
            default: break;
        }
    });

    // ---------- kiosk ----------
    // Android app back button: go back to the four buttons, never leave an operation half done,
    // and never close the app by accident.
    window.tpvHandleBack = () => {
        if (S.view === 'cash_keep') { S.amount = ''; go('cash_count'); } else if (!['home', 'sending', 'pending'].includes(S.view)) { home(); }
        return true;
    };
    document.addEventListener('contextmenu', (event) => event.preventDefault());
    document.addEventListener('dblclick', (event) => event.preventDefault());
    document.addEventListener('gesturestart', (event) => event.preventDefault());

    async function keepAwake() {
        try { await navigator.wakeLock?.request('screen'); } catch { /* not supported or denied */ }
    }
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') { keepAwake(); } });

    // browsers only allow fullscreen after a tap: do it on the first one
    document.addEventListener('pointerdown', () => {
        if (!document.fullscreenElement) {
            document.documentElement.requestFullscreen?.({ navigationUI: 'hide' }).catch(() => {});
        }
        keepAwake();
    }, { once: true });

    // ---------- start ----------
    healthLoop();
    startNfc();
    api('GET', '/config').then(({ data }) => { if (data.currency) { S.currency = currencySymbol(data.currency); if (S.view === 'home') { render(); } } }).catch(() => {});
    if (!resumeInflight()) { home(); }
})();
