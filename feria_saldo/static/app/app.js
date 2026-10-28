(() => {
    'use strict';

    const API = '/feria/api/v1';
    const INFLIGHT_KEY = 'feria_inflight';
    const CASH_KEY = 'feria_cash_inflight';
    const SCREEN_IDLE_MS = 60 * 1000;
    const TRANSIENT = ['customer', 'amount', 'consulta', 'result', 'cash', 'cash_count', 'cash_keep', 'cash_confirm'];
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
        contact: null,
        by: null, // how the customer was identified: {code} or {contact_id}
        orders: [],
        cash: null, // what the drawer should hold, from the server
        counted: '', // cash counted by the person
        kept: '', // cash left for the next day
        amount: '',
        taps: [], // coins and notes tapped for a recarga, in euros
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
            pill.querySelector('b').textContent = S.online ? 'ONLINE' : 'SIN CONEXIÓN';
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
        Object.assign(S, { action: null, query: '', contact: null, by: null, orders: [], cash: null, counted: '', kept: '', amount: '', taps: [], message: '', result: null, busy: false });
        go('home');
    }

    // ---------- views ----------
    const TITLES = { COBRAR: 'Cobrar', RECARGAR: 'Recargar', CONSULTA: 'Saldo y pedidos' };
    const ASSETS = '/feria_saldo/static/app';

    // Line icons, one visual family (24x24, drawn with the current text colour)
    const ICON = {
        card: '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M3 10h18M7 15h4"/>',
        plus: '<circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/>',
        receipt: '<path d="M6 3h12v18l-3-2-3 2-3-2-3 2z"/><path d="M9 8h6M9 12h6"/>',
        wallet: '<path d="M4 8a2 2 0 0 1 2-2h11v3"/><rect x="3" y="8" width="18" height="12" rx="3"/><circle cx="16.5" cy="14" r="1.2" fill="currentColor"/>',
        cash: '<rect x="2.5" y="6" width="19" height="12" rx="2.5"/><circle cx="12" cy="12" r="2.8"/><path d="M6 9.5v.01M18 14.5v.01"/>',
        back: '<path d="M15 5l-7 7 7 7"/>',
        backspace: '<path d="M21 6H9l-6 6 6 6h12a1 1 0 0 0 1-1V7a1 1 0 0 0-1-1z"/><path d="M12 9.500l5 5m0-5l-5 5"/>',
        up: '<path d="M12 19V5m0 0l-6 6m6-6l6 6"/>',
        down: '<path d="M12 5v14m0 0l-6-6m6 6l6-6"/>',
        check: '<path d="M5 12.500l4.500 4.500L19 7.500"/>',
        alert: '<circle cx="12" cy="12" r="9"/><path d="M12 7.500V13M12 16.500v.01"/>',
        undo: '<path d="M9 14L4 9l5-5"/><path d="M4 9h9a6 6 0 0 1 0 12h-3"/>',
        trash: '<path d="M4 7h16M10 3h4M6 7l1 13h10l1-13M10 11v6M14 11v6"/>',
        band: '<rect x="2.500" y="8" width="19" height="8" rx="4"/><rect x="9" y="10" width="6" height="4" rx="1.200"/>',
        contactless: '<path d="M8.500 8.500a5 5 0 0 1 0 7"/><path d="M12 6a8.500 8.500 0 0 1 0 12"/><path d="M15.500 3.500a12 12 0 0 1 0 17"/>',
    };
    const icon = (name) => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${ICON[name]}</svg>`;
    const initials = (name) => String(name || '?').split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('');

    const bar = (back = true, title = TITLES[S.action] || '') => `
        <header class="bar">
            <div class="bar-left">
                ${back
        ? `<button class="iconbtn" data-act="home" aria-label="Volver al inicio">${icon('back')}<span>Inicio</span></button>`
        : `<span class="mark">${icon('card')}</span><span class="brand">TpvPlus</span>`}
            </div>
            <div class="bar-title">${esc(title)}</div>
            <div class="right">
                <span id="pill" class="pill ${S.online ? '' : 'off'}"><i></i><b>${S.online ? 'ONLINE' : 'SIN CONEXIÓN'}</b></span>
            </div>
        </header>`;

    const keypad = (fill = false) => `<div class="pad${fill ? ' fill' : ''}">${[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => `<button class="key" data-act="key" data-k="${n}">${n}</button>`).join('')}
        <button class="key muted" data-act="key" data-k=".">,</button><button class="key" data-act="key" data-k="0">0</button>
        <button class="key muted" data-act="back" aria-label="Borrar">${icon('backspace')}</button></div>`;

    const shownAmount = () => (S.amount ? S.amount.replace('.', ',') : '0');
    const when = (iso) => new Date(iso).toLocaleString('es-ES', { dateStyle: 'short', timeStyle: 'short' });
    const errLine = () => (S.message ? `<p class="sub err">${esc(S.message)}</p>` : '');

    const views = {
        home() {
            return `${bar(false)}<div class="home">
                <button class="big tile" data-act="start" data-a="COBRAR">
                    <span class="tile-icon">${icon('card')}</span>
                    <span class="tile-text"><b>Cobrar</b><small>Descontar del saldo del cliente</small></span>
                </button>
                <button class="big tile" data-act="start" data-a="RECARGAR">
                    <span class="tile-icon">${icon('plus')}</span>
                    <span class="tile-text"><b>Recargar</b><small>Añadir saldo a la pulsera</small></span>
                </button>
                <button class="big tile" data-act="start" data-a="CONSULTA">
                    <span class="tile-icon">${icon('wallet')}</span>
                    <span class="tile-text"><b>Ver saldo y pedidos</b><small>Consultar el saldo y el historial del cliente</small></span>
                </button>
                <button class="big tile" data-act="cash" data-needs-online>
                    <span class="tile-icon">${icon('cash')}</span>
                    <span class="tile-text"><b>Caja</b><small>Contar y cerrar la caja del dia</small></span>
                </button>
            </div>`;
        },

        customer() {
            return `${bar()}<div class="screen scan">
                <p class="eyebrow">¿Qué cliente?</p>
                <div class="radar" aria-hidden="true">
                    <span class="ring r1"></span><span class="ring r2"></span><span class="ring r3"></span>
                    <span class="core"><svg class="icon" viewBox="0 0 24 24">${ICON.contactless}</svg></span>
                </div>
                <h1 class="scan-title">Acerca la pulsera o tarjeta RFID al lector</h1>
                <p class="sub">El cliente se identifica solo en cuanto se lee</p>
                <div class="chips"><span class="chip">${icon('band')}Pulsera</span><span class="chip">${icon('card')}Tarjeta</span></div>
                ${errLine()}</div>`;
        },

        consulta() {
            const kinds = { COBRAR: 'Cobro', RECARGAR: 'Recarga', ANULACION: 'Anulación', AJUSTE: 'Ajuste' };
            const how = { cash: 'efectivo', card: 'tarjeta' };
            const rows = S.orders.map((m) => {
                const negative = Number(m.signed_amount) < 0;
                const kind = (kinds[m.type] || m.type) + (m.payment_method ? ` · ${how[m.payment_method] || m.payment_method}` : '');
                return `<div class="item op"><span class="op-icon ${negative ? 'neg' : 'pos'}">${icon(negative ? 'down' : 'up')}</span>
                    <span class="op-main"><b>${esc(kind)}</b><small>${esc(when(m.received_at))}</small></span>
                    <span class="op-amount"><b class="${negative ? 'neg' : 'pos'}">${negative ? '−' : '+'}${money(String(m.amount))}</b><small>Saldo ${money(m.balance_after)}</small></span></div>`;
            }).join('');
            return `${bar()}${customerBanner(S.contact)}<div class="screen">
                <h2 class="section">Pedidos</h2>
                <div class="list">${rows || '<p class="empty">Todavía no hay operaciones</p>'}</div>
                <button class="btn" data-act="home">Volver</button></div>`;
        },

        amount() {
            return S.action === 'RECARGAR' ? views.recarga() : views.cobrar();
        },

        cobrar() {
            const c = S.contact;
            return `${bar()}${customerBanner(c)}<div class="screen fill">
                <div class="amount-card cobrar total"><small>Importe a cobrar</small>
                    <div class="amount cobrar">${esc(shownAmount())} ${esc(S.currency)}</div></div>
                ${errLine()}
                ${keypad(true)}
                <div class="row"><button class="btn ghost" data-act="home">Cancelar</button>
                    <button class="btn brand" data-act="confirm" data-needs-online ${c.blocked ? 'disabled' : ''}>COBRAR</button></div></div>`;
        },

        // Recarga: the customer hands over coins and notes, so the person taps them (no keypad).
        recarga() {
            const c = S.contact;
            const total = S.taps.reduce((sum, v) => sum + v, 0);
            const counts = {};
            S.taps.forEach((v) => { counts[v] = (counts[v] || 0) + 1; });
            const cnt = (v) => (counts[v] ? `<i class="cnt">${counts[v]}</i>` : '');
            const den = (v) => `<button class="denom${counts[v] ? ' on' : ''}" data-act="denom" data-v="${v}" aria-label="${v} euro${v > 1 ? 's' : ''}"><b>${v}</b><span>€</span>${cnt(v)}</button>`;
            const summary = Object.keys(counts).map(Number).sort((x, y) => y - x).map((v) => `<span class="mini">${counts[v]} × ${v} €</span>`).join('');
            const disabled = !total || c.blocked ? 'disabled' : '';
            return `${bar()}${customerBanner(c)}<div class="screen fill">
                <div class="amount-card recargar total">
                    <div class="amount-head"><small>Importe a recargar</small>
                        <span class="tools"><button class="tool" data-act="denom-undo" aria-label="Quitar el último" ${total ? '' : 'disabled'}>${icon('undo')}</button>
                        <button class="tool" data-act="denom-clear" aria-label="Borrar todo" ${total ? '' : 'disabled'}>${icon('trash')}</button></span></div>
                    <div class="amount recargar">${money(total.toFixed(2))}</div>
                    <div class="minis">${summary || '<span class="hint">Toca las monedas y los billetes que entrega el cliente</span>'}</div></div>
                ${errLine()}
                <div class="denoms">${[1, 2, 5, 10, 20, 50, 100, 200].map(den).join('')}</div>
                <div class="row">
                    <button class="btn pay" data-act="confirm" data-pay="cash" data-needs-online ${disabled}>${icon('cash')}<span class="pay-t">Efectivo</span></button>
                    <button class="btn pay" data-act="confirm" data-pay="card" data-needs-online ${disabled}>${icon('card')}<span class="pay-t">Tarjeta</span></button>
                </div></div>`;
        },

        cash() {
            const c = S.cash;
            const since = c.period_start ? when(c.period_start) : 'el principio';
            return `${bar(true, 'Caja')}<div class="screen">
                <div class="balance-card"><small>Efectivo que debe haber en caja</small><div class="balance">${money(c.expected)}</div></div>
                <div class="card list">
                    <div class="item"><span>Fondo (lo que se dejó)</span><b>${money(c.opening_float)}</b></div>
                    <div class="item"><span>+ Recargas en efectivo</span><b>${money(c.recharges)}</b></div>
                    <div class="item"><span>− Devoluciones</span><b>${money(c.refunds)}</b></div>
                </div>
                <p class="sub">Desde ${esc(since)} · ${c.movements_count} operaciones<br>Ventas (cobros): <b>${money(c.sales)}</b><br>Recargas con tarjeta (no entran en caja): <b>${money(c.card_recharges)}</b></p>
                <div class="row"><button class="btn" data-act="cash-count">Contar caja</button>
                    <button class="btn wine" data-act="cash-count">Cerrar caja</button></div></div>`;
        },

        cash_count() {
            const diff = S.amount === '' ? null : toCents(S.amount) - toCents(S.cash.expected);
            const verdict = diff === null ? '&nbsp;' : diff === 0 ? 'La caja cuadra' : diff > 0 ? `Sobran ${money(fromCents(diff))}` : `Faltan ${money(fromCents(diff))}`;
            return `${bar(true, 'Contar caja')}<div class="screen">
                <p class="sub">Cuenta el dinero y escribe el total · Debe haber <b>${money(S.cash.expected)}</b></p>
                <div class="amount-card"><small>Total contado</small><div class="amount">${esc(shownAmount())} ${esc(S.currency)}</div></div>
                <p class="sub ${diff ? 'err' : ''}">${verdict}</p>
                ${errLine()}
                ${keypad()}
                <div class="row"><button class="btn" data-act="cash-save-count" data-needs-online>Guardar recuento</button>
                    <button class="btn wine" data-act="cash-to-keep">Cerrar caja</button></div></div>`;
        },

        cash_keep() {
            const kept = S.amount === '' ? 0 : toCents(S.amount);
            return `${bar(true, 'Cerrar caja')}<div class="screen">
                <p class="sub">Has contado <b>${money(S.counted)}</b> · ¿Cuánto dejas para mañana?</p>
                <div class="amount-card recargar"><small>Dejas en caja</small><div class="amount recargar">${esc(shownAmount())} ${esc(S.currency)}</div></div>
                <p class="sub">Retiras: <b>${money(fromCents(toCents(S.counted) - kept))}</b></p>
                ${errLine()}
                <div class="row"><button class="btn ghost" data-act="cash-keep-zero">No dejar nada</button>
                    <button class="btn ghost" data-act="cash-keep-all">Dejar todo</button></div>
                ${keypad()}
                <button class="btn wine" data-act="cash-review">Continuar</button></div>`;
        },

        cash_confirm() {
            const c = S.cash;
            const diff = toCents(S.counted) - toCents(c.expected);
            const verdict = diff === 0 ? 'Cuadra' : `${diff > 0 ? 'Sobran' : 'Faltan'} ${money(fromCents(diff))}`;
            return `${bar(true, 'Confirmar cierre')}<div class="screen">
                <div class="card list">
                    <div class="item"><span>Debía haber</span><b>${money(c.expected)}</b></div>
                    <div class="item"><span>Contado</span><b>${money(S.counted)}</b></div>
                    <div class="item"><span>Diferencia</span><b class="${diff ? 'err' : ''}">${verdict}</b></div>
                    <div class="item"><span>Dejas para mañana</span><b>${money(S.kept)}</b></div>
                    <div class="item"><span>Retiras</span><b>${money(fromCents(toCents(S.counted) - toCents(S.kept)))}</b></div>
                </div>
                <p class="sub">Al cerrar, la caja de mañana empieza con ${money(S.kept)}.</p>
                <div class="row"><button class="btn ghost" data-act="home">Cancelar</button>
                    <button class="btn wine" data-act="cash-confirm" data-needs-online>CERRAR CAJA</button></div></div>`;
        },

        sending() {
            return `${bar(false, 'Procesando')}<div class="screen done">
                <div class="done-card wait"><div class="spin"></div><h1 class="done-title">Procesando…</h1><p class="sub">No retire la pulsera</p></div></div>`;
        },

        pending() {
            return `${bar(false, 'Pendiente')}<div class="screen done">
                <div class="done-card wait"><div class="spin"></div><h1 class="done-title">PENDIENTE DE CONFIRMAR</h1>
                    <p class="sub">No se sabe si la operación se ha registrado. Espere, se resolverá sola.</p>
                    <p id="elapsed" class="sub"></p></div></div>`;
        },

        result() {
            const r = S.result;
            const body = r.sale
                ? `<div class="done-name">${esc(r.sale.name)}</div>
                    <div class="done-amount ${r.sale.negative ? 'neg' : 'pos'}" data-cents="${toCents(r.sale.raw)}" data-sign="${r.sale.negative ? '−' : '+'}">${esc(r.sale.amount)}</div>
                    <div class="done-sub">${r.sale.how ? `${esc(r.sale.how)} · ` : ''}Saldo ${esc(r.sale.balance)}</div>`
                : r.lines.map((l) => `<div class="done-line">${esc(l)}</div>`).join('');
            const confetti = r.ok ? '<i></i>'.repeat(16) : '';  // positions and colours live in the CSS (no inline styles: CSP)
            const mark = r.ok
                ? '<svg class="mark-svg" viewBox="0 0 52 52" aria-hidden="true"><circle class="mark-ring" cx="26" cy="26" r="23"/><path class="mark-tick" d="M15 27l8 8 15-17"/></svg>'
                : icon('alert');
            return `${bar(false, r.ok ? 'Listo' : 'No realizado')}<div class="screen done">
                <div class="done-card ${r.ok ? 'ok' : 'bad'}">
                    <span class="done-stage"><span class="burst">${confetti}</span><span class="pulse"></span><span class="pulse p2"></span>
                        <span class="done-badge">${mark}</span></span>
                    <h1 class="done-title">${esc(r.title)}</h1>
                    ${body}
                </div>
                <button class="btn brand" data-act="home">Nueva operación</button></div>`;
        },
    };

    // Banner under the header while a customer is identified: the name and the balance, same size.
    function customerBanner(c) {
        return `<section class="customer-bar">
            <span class="avatar">${esc(initials(c.contact.name))}</span>
            <div class="who"><div class="name">${esc(c.contact.name)}</div>${c.blocked ? '<span class="tag">BLOQUEADA</span>' : ''}</div>
            <div class="saldo">${money(c.balance)}</div></section>`;
    }

    function render() {
        $app.innerHTML = views[S.view]();
        paintStatus();
        if (S.view === 'result') { countUp(); }
    }

    // The amount of a finished operation counts up from zero (skipped if the system asks for less motion).
    function countUp() {
        const el = document.querySelector('.done-amount[data-cents]');
        if (!el || window.matchMedia('(prefers-reduced-motion: reduce)').matches) { return; }
        const target = Number(el.dataset.cents);
        const sign = el.dataset.sign;
        const final = el.textContent;
        const start = performance.now();
        const duration = 800;
        const tick = (now) => {
            const t = Math.min(1, (now - start) / duration);
            const eased = 1 - (1 - t) ** 3;
            el.textContent = t < 1 ? `${sign}${money(fromCents(Math.round(target * eased)))}` : final;
            if (t < 1 && el.isConnected) { requestAnimationFrame(tick); } else { el.textContent = final; }
        };
        requestAnimationFrame(tick);
    }

    // ---------- finding the customer ----------
    async function showCustomer(path, by) {
        const { status, data } = await api('GET', path);
        if (status !== 200) { return { status, data }; }
        S.contact = data;
        S.by = by;
        if (data.currency) { S.currency = currencySymbol(data.currency); }
        if (S.action === 'CONSULTA') {
            // "pedidos" are the operations stored by this module (cobros and recargas), newest first
            const history = await api('GET', `/movements?contact_id=${data.contact.id}&limit=30`);
            S.orders = history.data.movements || [];
            go('consulta');
        } else {
            go('amount');
        }
        return { status, data };
    }

    // A card / wristband was read: its code identifies the customer.
    async function find() {
        const text = S.query.trim();
        if (!text || S.busy) { return; }
        S.busy = true; S.message = '';
        try {
            const found = await showCustomer(`/contacts/lookup?code=${encodeURIComponent(text)}`, { code: text });
            if (found.status === 200) { S.busy = false; return; }
            S.message = found.data.error_code === 'CODE_UNKNOWN' ? 'Pulsera o tarjeta no reconocida' : (found.data.message || 'Error');
            feedback(false);
        } catch {
            S.message = 'Sin conexión: vuelva a acercar la pulsera';
        }
        S.busy = false;
        render();
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

    // The recarga amount is the sum of the coins and notes tapped (whole euros).
    function syncTaps() {
        const total = S.taps.reduce((sum, v) => sum + v, 0);
        S.amount = total ? String(total) : '';
        S.message = '';
        render();
    }

    const amountValid = () => /^\d+(\.\d{1,2})?$/.test(S.amount) && Number(S.amount) > 0;

    function pad2(text) {
        const [whole, frac = ''] = text.split('.');
        return `${whole}.${frac.padEnd(2, '0')}`;
    }

    async function confirm(pay) {
        if (!amountValid()) { S.message = 'Escribe un importe'; return render(); }
        if (S.action === 'RECARGAR' && !['cash', 'card'].includes(pay)) { S.message = 'Elige efectivo o tarjeta'; return render(); }
        const amount = pad2(S.amount);
        if (S.action === 'COBRAR' && Number(amount) > Number(S.contact.balance)) {
            S.message = `Saldo insuficiente (${money(S.contact.balance)})`;
            feedback(false);
            return render();
        }
        const op = {
            uuid: uuid4(),
            contactName: S.contact.contact.name,
            body: { type: S.action, amount, created_at_device: new Date().toISOString(), ...S.by, ...(S.action === 'RECARGAR' ? { payment_method: pay } : {}) },
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
        const how = { cash: 'en efectivo', card: 'con tarjeta' }[op.body.payment_method] || '';
        S.result = {
            ok: true,
            title: cobrar ? 'COBRADO' : 'RECARGADO',
            sale: {
                name: op.contactName,
                amount: `${cobrar ? '−' : '+'}${money(op.body.amount)}`,
                raw: op.body.amount,
                how: how ? how[0].toUpperCase() + how.slice(1) : '',
                balance: money(data.balance_after),
                negative: cobrar,
            },
        };
        feedback(true);
        go('result');
        // after a pending operation the person must acknowledge the outcome, never auto-dismiss it
        if (!wasPending) {
            // only closes THIS result: an older timer must never close the result of a later operation
            const shown = S.result;
            setTimeout(() => { if (S.view === 'result' && S.result === shown) { home(); } }, 7000);
        }
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
    // 1. USB / PDA keyboard-wedge readers (RFID or NFC) "type" the code and press Enter: captured below.
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
        find();
    }
    window.handleNfcScan = onCardRead;

    // Keyboard-wedge readers: a fast burst of characters, normally closed by Enter. There is no text field on
    // purpose (nobody searches by hand), so keystrokes are collected while the customer screen is up.
    let keyBuffer = '';
    let keyTimer = null;
    let lastKeyAt = 0;
    document.addEventListener('keydown', (event) => {
        if (S.view !== 'customer' || S.busy || event.ctrlKey || event.metaKey || event.altKey) { return; }
        clearTimeout(keyTimer);
        if (event.key === 'Enter') {
            const code = keyBuffer;
            keyBuffer = '';
            if (code.length >= 3) { event.preventDefault(); onCardRead(code); }
            return;
        }
        if (event.key.length !== 1) { return; }
        const now = Date.now();
        const fast = keyBuffer === '' || now - lastKeyAt < 100; // a reader sends the characters in a few ms
        keyBuffer = fast ? keyBuffer + event.key : event.key;
        lastKeyAt = now;
        // readers without the Enter suffix: the burst ending is the signal
        keyTimer = setTimeout(() => {
            const code = keyBuffer;
            keyBuffer = '';
            if (code.length >= 6) { onCardRead(code); }
        }, 250);
    });

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
            case 'start': S.action = el.dataset.a; S.query = ''; S.message = ''; S.taps = []; go('customer'); startNfc(); break;
            case 'home': home(); break;
            case 'key': pressKey(el.dataset.k); break;
            case 'denom': S.taps.push(Number(el.dataset.v)); try { navigator.vibrate?.(15); } catch { /* ignore */ } syncTaps(); break;
            case 'denom-undo': S.taps.pop(); syncTaps(); break;
            case 'denom-clear': S.taps = []; syncTaps(); break;
            case 'back': S.amount = S.amount.slice(0, -1); render(); break;
            case 'confirm': confirm(el.dataset.pay); break;
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
