// Пазар — price comparison frontend (no framework, no build step).
'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const eur = (v) => (v == null ? '—' : `${Number(v).toFixed(2)} €`);
const fmtDate = (iso) => (iso ? new Date(iso + 'T00:00:00').toLocaleDateString('bg-BG', { day: 'numeric', month: 'short' }) : '');
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const BGN_PER_EUR = 1.95583;
// A price as HTML: euro, plus leva in small type when the shopper turned the "лв." toggle on (1.49 € / 2.91 лв.).
const money = (v) => (v == null ? '—'
  : `${eur(v)}${state.bgn ? `<span class="bgn">${(Number(v) * BGN_PER_EUR).toFixed(2)} лв.</span>` : ''}`);
const UNIT_LABEL = { kg: 'кг', l: 'л', pc: 'бр.' };
// Normalised price: per kg / l for weighed packs, per piece for count packs.
function unitOf(it) {
  if (it.unit_price) return { v: it.unit_price, per: it.unit_per || 'kg' };
  if (it.piece_price) return { v: it.piece_price, per: 'pc' };
  return null;
}
const unitText = (u) => (u ? `${u.per === 'pc' ? Number(u.v).toFixed(3).replace(/0$/, '') : Number(u.v).toFixed(2)} €/${UNIT_LABEL[u.per]}` : '');
// Loyalty programmes the shopper can tick under "Моите карти".
const CARD_CHAINS = [['lidl', 'Lidl Plus'], ['kaufland', 'Kaufland Card'], ['billa', 'BILLA Card']];

const store = {
  get(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode */ } },
};

async function api(path, opts) {
  const res = await fetch(`/api/${path}`, opts);
  const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

// --------------------------------------------------------------------------- state

const state = {
  page: 1,
  pages: 1,
  stores: [],
  areas: [],
  dept: '',
  dividerShown: false,
  selectedStores: new Set(store.get('stores', [])),
  area: store.get('area', ''),               // municipality code, '' = whole country
  online: store.get('online', true),          // include online-only chains (delivery)
  basket: store.get('basket', []),            // [{product_id, qty, name, sub}]
  cards: new Set(store.get('cards', [])),     // chains whose loyalty card the shopper has ("Моите карти")
  bgn: store.get('bgn', false),               // also show prices in leva
  maxStores: store.get('maxStores', 2),       // basket: at most this many shops on one trip
  minSavings: store.get('minSavings', 2.5),   // basket: an extra shop must save at least this much (€)
};

const areaName = () => state.areas.find((a) => a.code === state.area)?.name || '';

// Location scope shared by every request.
function scopeParams(p = new URLSearchParams()) {
  if (state.area) p.set('area', state.area);
  if (!state.online) p.set('online', '0');
  if (state.cards.size) p.set('cards', [...state.cards].join(','));   // their card prices count everywhere
  return p;
}

function params(page = 1) {
  const p = new URLSearchParams();
  const q = $('#q').value.trim();
  if (q) p.set('q', q);
  if (state.selectedStores.size) p.set('store', [...state.selectedStores].join(','));
  if ($('#f-disc').checked) p.set('discounts', '1');
  if ($('#f-card').checked) p.set('card', '1');
  if ($('#f-multi').checked) p.set('min_stores', '2');
  if (state.dept) p.set('dept', state.dept);
  p.set('collapse', $('#f-group').value);
  p.set('sort', $('#f-sort').value);
  scopeParams(p);
  p.set('page', String(page));
  p.set('per_page', '24');
  return p;
}

// --------------------------------------------------------------------------- cards

const IMG_FALLBACK = "this.replaceWith(Object.assign(document.createElement('span'),{className:'ph',textContent:'🛒'}))";
const imgHTML = (url) => (url
  ? `<img src="${esc(url)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="${IMG_FALLBACK}">`
  : '<span class="ph">🛒</span>');

// Where this offer can be bought, in one short line.
function whereLine(it) {
  if (it.channel === 'online') return '<span class="where online">🚚 Онлайн доставка</span>';
  if (state.area) {
    const n = it.outlets_total ? it.outlets : it.store_area_outlets;
    const what = it.outlets_total ? 'обекта' : 'магазина на веригата';
    return n ? `<span class="where">📍 ${n === 1 ? '1 обект' : `${n} ${what}`} в ${esc(areaName())}</span>` : '';
  }
  if (it.store_areas && it.store_areas <= 5) return `<span class="where">📍 само в ${esc(it.store_area_names)}</span>`;
  return '';
}

function productCard(it) {
  const deal = it.promo_eur != null && it.promo_eur < it.price_min;
  const shown = deal ? it.promo_eur : it.price_min;
  const old = it.regular && it.regular > shown + 0.004 ? it.regular : null;
  const pct = old ? Math.round((1 - shown / old) * 100) : 0;
  const range = it.outlets > 1 && it.price_max > it.price_min + 0.004
    ? `<span class="unit">до ${eur(it.price_max)} в ${it.outlets} обекта</span>` : '';
  const compare = it.group_stores > 1
    ? `<span class="compare-line">в ${it.group_stores} вериги${it.group_min < shown - 0.004 ? ` · от ${eur(it.group_min)}` : ''}</span>` : '';
  const multi = it.min_quantity > 1 ? ` <span class="unit">при ${it.min_quantity} бр.</span>` : '';
  const u = unitOf(it);
  // EU Omnibus: the "regular" price was not charged in the 30 days before the promo.
  const fake = it.fake_promo ? `<span class="fake" title="Преди промоцията цената е била ${eur(it.prior_price)} (най-ниската за 30 дни): реалното намаление е ${it.real_discount_pct}%, не ${pct}%.">⚠ реално ${it.real_discount_pct > 0 ? `-${it.real_discount_pct}%` : 'без намаление'}</span>` : '';
  const shrink = it.shrink_method ? `<span class="shrink" title="${esc(it.old_name || '')}">📉 ${it.old_size} → ${it.new_size} ${it.shrink_unit === 'ml' ? 'мл' : 'г'} · ${it.unit_change_pct > 0 ? `+${it.unit_change_pct}%` : 'същата цена'} на ${it.shrink_unit === 'ml' ? 'л' : 'кг'}</span>` : '';
  return `
    <article class="card" data-id="${it.id}" tabindex="0" role="button" aria-label="${esc(it.name)}">
      <div class="img">${imgHTML(it.image_url)}</div>
      ${pct >= 3 ? `<span class="badge ${it.fake_promo ? 'suspect' : ''}">-${pct}%</span>` : ''}
      <button class="add" data-add="${it.id}" aria-label="Добави в количката" title="Добави в количката">+</button>
      <div class="body">
        <span class="store">${esc(it.store_name)}</span>
        <span class="name">${esc(it.name)}</span>
        ${compare}
        <div class="prices">
          <span class="price ${deal || pct >= 3 || it.with_card ? 'deal' : ''}">${money(it.with_card ? it.effective : shown)}</span>${multi}
          ${old ? `<span class="old">${eur(old)}</span>` : ''}
          ${it.card_eur != null && !it.with_card ? `<span class="cardprice" title="${esc(it.card_label || 'с карта за лоялност')}">${eur(it.card_eur)} с карта</span>` : ''}
          ${it.with_card ? `<span class="cardprice" title="Цена с вашата карта (Моите карти)">с карта</span>` : ''}
        </div>
        ${u ? `<span class="unitprice">${unitText(u)}</span>` : ''}
        ${fake}${shrink}
        ${it.change_pct ? `<span class="trend ${it.change_pct < 0 ? 'down' : 'up'}">${it.change_pct < 0 ? '↓' : '↑'} ${Math.abs(it.change_pct)}% от ${fmtDate(it.prev_day)}</span>` : ''}
        ${whereLine(it)}
        ${range}
      </div>
    </article>`;
}

// A family (flavours/variants of one product line) or one product sold by several chains:
// the cheapest offer per chain side by side.
function familyCard(it) {
  const f = it.family;
  const many = f.variants > 1;
  const title = many ? `${f.name}${f.size_text ? ` · ${f.size_text}` : ''}` : it.name;
  const best = f.stores[0];
  const disc = Math.max(...f.stores.map((s) => s.disc || 0));
  const shown = f.stores.slice(0, 4);
  // Pack sizes differ inside the family (80 vs 100 g): the price per kg/l tells which offer is really cheapest.
  const sizesVary = (f.size_text || '').includes('–');
  const bestUnit = sizesVary && f.unit_min ? f.unit_min : null;
  const meta = [many ? plural(f.variants, 'вид', 'вида') : '', plural(f.stores.length, 'верига', 'вериги')]
    .filter(Boolean).join(' · ');
  return `
    <article class="card fam" data-family="${f.id}" data-id="${it.id}" tabindex="0" role="button"
             aria-label="${esc(title)}: ${esc(meta)}, от ${eur(best.min)}">
      <div class="img">${imgHTML(it.image_url)}</div>
      ${disc >= 3 ? `<span class="badge">до -${disc}%</span>` : ''}
      ${many ? `<span class="stack" aria-hidden="true">${f.variants}</span>` : `<button class="add" data-add="${it.id}" aria-label="Добави в количката" title="Добави в количката">+</button>`}
      <div class="body">
        <span class="store">${esc(meta)}</span>
        <span class="name">${esc(title)}</span>
        <div class="prices"><span class="from">от</span><span class="price ${disc >= 3 ? 'deal' : ''}">${money(best.min)}</span></div>
        ${bestUnit ? `<span class="unitprice">най-изгодно: ${unitText({ v: bestUnit, per: f.unit_per || 'kg' })}</span>` : ''}
        <ul class="strip">
          ${shown.map((s, i) => `<li class="${i === 0 ? 'best' : ''} ${bestUnit && s.unit_min === bestUnit ? 'bestu' : ''}">
            <span>${s.channel === 'online' ? '🚚 ' : ''}${esc(s.store_name)}${many && s.n > 1 ? ` <i>${s.n}</i>` : ''}</span>
            <b>${money(s.min)}${s.with_card ? ' <i class="c">карта</i>' : ''}${sizesVary && s.unit_min ? `<i class="u">${unitText({ v: s.unit_min, per: f.unit_per || 'kg' })}</i>` : ''}</b></li>`).join('')}
          ${f.stores.length > shown.length ? `<li class="more">+ ${f.stores.length - shown.length} вериги</li>` : ''}
        </ul>
      </div>
    </article>`;
}

// A promotion that starts later (next week's leaflet): when it starts and what it will cost.
function upcomingCard(it) {
  const pct = it.regular && it.regular > it.promo_eur ? Math.round((1 - it.promo_eur / it.regular) * 100) : 0;
  return `
    <article class="card upcoming" data-id="${it.id}" tabindex="0" role="button" aria-label="${esc(it.name)}">
      <div class="img">${imgHTML(it.image_url)}</div>
      ${pct >= 3 ? `<span class="badge">-${pct}%</span>` : ''}
      <div class="body">
        <span class="store">${esc(it.store_name)} · от ${fmtDate(it.valid_from)}${it.valid_to && it.valid_to < '2099' ? ` до ${fmtDate(it.valid_to)}` : ''}</span>
        <span class="name">${esc(it.name)}</span>
        <div class="prices"><span class="price deal">${money(it.promo_eur)}</span>
          ${it.regular ? `<span class="old">${eur(it.regular)}</span>` : ''}
          ${it.requires_loyalty ? '<span class="cardprice">с карта</span>' : ''}
          ${it.min_quantity > 1 ? `<span class="unit">при ${it.min_quantity} бр.</span>` : ''}</div>
        ${it.label ? `<span class="unit">${esc(it.label)}</span>` : ''}
      </div>
    </article>`;
}

const cardHTML = (it) => (it.family ? familyCard(it) : productCard(it));

function renderGrid(el, items, append = false, query = '') {
  let html = '';
  for (const it of items) {
    if (it.off && !state.dividerShown && el.id === 'results') {
      html += `<p class="divider">Други резултати${query ? `, които съдържат „${esc(query)}“` : ''}</p>`;
      state.dividerShown = true;
    }
    html += cardHTML(it);
  }
  if (append) el.insertAdjacentHTML('beforeend', html);
  else el.innerHTML = html || '<p class="empty">Няма намерени продукти.</p>';
}

function renderFacets(facets) {
  const el = $('#facets');
  if (!facets?.length || (facets.length === 1 && !state.dept)) { el.innerHTML = ''; return; }
  el.innerHTML = [`<button type="button" class="facet ${state.dept ? '' : 'on'}" data-dept="">Всички</button>`,
    ...facets.map((f) => `<button type="button" class="facet ${state.dept === f.dept ? 'on' : ''} ${f.primary ? '' : 'minor'}"
      data-dept="${esc(f.dept)}">${esc(f.label)} <span>${f.count}</span></button>`)].join('');
}

// --------------------------------------------------------------------------- search

let searchSeq = 0;
async function search(page = 1) {
  const p = params(page);
  const hasQuery = p.has('q') || p.has('store') || p.has('discounts') || p.has('dept');
  $('#results-sec').hidden = !hasQuery;
  $('#hero').hidden = hasQuery;
  if (!hasQuery) return;
  const seq = ++searchSeq;
  $('#results').classList.add('loading');
  try {
    const data = await api(`search?${p}`);
    if (seq !== searchSeq) return;                    // a newer search superseded this one
    state.page = data.page; state.pages = data.pages;
    if (page === 1) state.dividerShown = false;
    renderGrid($('#results'), data.items, page > 1, p.get('q') || '');
    if (page === 1 && !state.dept) renderFacets(data.facets);
    const where = state.area ? ` · ${areaName()}${state.online ? ' + онлайн' : ''}` : '';
    $('#results-title').textContent = data.barcode ? `Баркод ${data.barcode}` : p.get('q') ? `„${p.get('q')}“` : 'Продукти';
    $('#results-count').textContent = `${data.total.toLocaleString('bg-BG')} резултата${where}`;
    $('#more').hidden = data.page >= data.pages;
    history.replaceState(null, '', `?${p.toString().replace(/&?(page|per_page)=\d+/g, '')}`);
  } catch (e) {
    $('#results').innerHTML = `<p class="empty">Грешка: ${esc(e.message)}</p>`;
  } finally {
    $('#results').classList.remove('loading');
  }
}

let debounce;
function searchSoon() { clearTimeout(debounce); debounce = setTimeout(() => { state.dept = ''; search(1); }, 250); }

// A home-page section that hides itself when its feed is empty.
function feed(path, sec, grid, render = (el, items) => renderGrid(el, items)) {
  api(path).then((d) => {
    $(sec).hidden = !d.items.length;
    if (d.items.length) render($(grid), d.items);
  }).catch(() => { $(sec).hidden = true; });
}

function loadFeeds() {
  const p = scopeParams();
  if ($('#f-multi').checked) p.set('min_stores', '2');
  $('#deals-where').textContent = state.area ? `в ${areaName()}${state.online ? ' + онлайн' : ''}` : '';
  // "Честни намаления": leave out promos whose regular price was inflated before the promo (EU Omnibus check).
  const honest = $('#f-honest')?.checked ? '&honest=1' : '';
  api(`deals?limit=24${honest}&${p}`).then((d) => renderGrid($('#deals'), d.items)).catch(() => {});
  feed(`deals?limit=12&expiring=1${honest}&${p}`, '#expiring-sec', '#expiring');
  feed(`upcoming?limit=12&${p}`, '#upcoming-sec', '#upcoming', (el, items) => { el.innerHTML = items.map(upcomingCard).join(''); });
  feed(`drops?limit=12&${p}`, '#drops-sec', '#drops');                   // needs a week of history
  feed(`shrinkflation?limit=12&${p}`, '#shrink-sec', '#shrink');
}

// --------------------------------------------------------------------------- filters: stores, location

function renderStoreList() {
  const filter = $('#store-filter-text').value.trim().toLowerCase();
  $('#store-list').innerHTML = state.stores
    .filter((s) => !filter || s.name.toLowerCase().includes(filter))
    .map((s) => `<label><input type="checkbox" value="${esc(s.slug)}" ${state.selectedStores.has(s.slug) ? 'checked' : ''}>
      ${esc(s.name)}${s.channel === 'online' ? ' <span class="muted small">онлайн</span>' : ''}
      <span class="n">${s.products.toLocaleString('bg-BG')}</span></label>`).join('');
  const n = state.selectedStores.size;
  $('#store-sel-count').textContent = n ? `(${n})` : '';
}

function renderAreaList() {
  const filter = $('#area-filter-text').value.trim().toLowerCase();
  const items = state.areas.filter((a) => !filter || a.name.toLowerCase().includes(filter)
    || (a.province || '').toLowerCase().includes(filter));
  $('#area-list').innerHTML = [
    !filter ? `<label class="${state.area ? '' : 'on'}"><input type="radio" name="area" value="" ${state.area ? '' : 'checked'}>
      Цялата страна</label>` : '',
    ...items.slice(0, 150).map((a) => `<label class="${state.area === a.code ? 'on' : ''}">
      <input type="radio" name="area" value="${esc(a.code)}" ${state.area === a.code ? 'checked' : ''}>
      ${esc(a.name)}${a.province && !a.name.includes(a.province) ? ` <span class="muted small">обл. ${esc(a.province)}</span>` : ''}
      <span class="n" title="вериги · обекти">${a.stores} вер. · ${a.outlets}</span></label>`),
  ].join('') || '<p class="muted small">Няма такъв град с магазини в данните.</p>';
}

function renderAreaLabel() {
  $('#area-label').textContent = state.area ? areaName() || state.area : 'Цялата страна';
  $('#area-dd summary').classList.toggle('set', !!state.area);
  $('#loc-hint').hidden = !!state.area;
  $('#f-online').checked = state.online;
}

function setArea(code) {
  state.area = code;
  store.set('area', code);
  renderAreaLabel(); renderAreaList();
  $('#area-dd').open = false;
  search(1); loadFeeds();
}

// --------------------------------------------------------------------------- product sheet

function sparkline(history) {
  if (history.length < 2) return '';
  const w = 520, h = 70, pad = 6;
  const vals = history.map((d) => d.min);
  const lo = Math.min(...vals), hi = Math.max(...vals) || 1;
  const x = (i) => pad + (i * (w - 2 * pad)) / (history.length - 1);
  const y = (v) => h - pad - ((v - lo) / ((hi - lo) || 1)) * (h - 2 * pad);
  const pts = history.map((d, i) => `${x(i).toFixed(1)},${y(d.min).toFixed(1)}`).join(' ');
  return `<h4>История на цената</h4>
    <svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" role="img" aria-label="История на цената">
      <polyline points="${pts}" fill="none" stroke="var(--accent)" stroke-width="2"/></svg>
    <div class="note">${fmtDate(history[0].day)} – ${fmtDate(history.at(-1).day)} · мин. ${eur(lo)}, макс. ${eur(hi)}</div>`;
}

function availabilityHTML(d) {
  const av = d.availability;
  if (av.type === 'online') {
    return `<h4>Къде се продава</h4><p class="small">🚚 <b>Онлайн доставка</b> от ${esc(d.store_name)} — веригата няма физически магазини.
      Проверете дали доставят до вашия адрес.</p>`;
  }
  const here = state.area && av.areas.some((a) => a.code === state.area);
  const head = state.area
    ? (here ? `<p class="small ok">✓ Продава се в ${esc(areaName())}.</p>`
      : `<p class="small warn">✕ ${esc(d.store_name)} не ${av.type === 'chain' ? 'има магазини' : 'предлага този продукт'} в ${esc(areaName())}.</p>`) : '';
  const chips = av.areas.slice(0, 18).map((a) => `<span class="place ${a.code === state.area ? 'on' : ''}">${esc(a.name)}
      <i>${a.outlets} ${a.outlets === 1 ? 'обект' : 'обекта'}${a.min != null && av.areas.length > 1 ? ` · от ${eur(a.min)}` : ''}</i></span>`).join('');
  const note = av.type === 'chain'
    ? 'Цена от каталога на веригата — важи за всичките ѝ магазини (наличността може да варира).' : 'Цени по обекти от данните на КЗП.';
  return `<h4>Къде се продава</h4>${head}<div class="places">${chips}${av.areas.length > 18 ? `<span class="muted small">+ още ${av.areas.length - 18}</span>` : ''}</div>
    <div class="note">${note}</div>`;
}

// Only one sheet at a time: opening one from inside the other replaces it instead of stacking two modals.
function closeDialog(sel) {
  const dlg = $(sel);
  if (dlg.open) dlg.close();
}

async function openProduct(id) {
  const dlg = $('#product-dlg');
  closeDialog('#family-dlg');
  $('#product-body').innerHTML = '<div class="sheet-body muted">Зареждане…</div>';
  if (!dlg.open) dlg.showModal();
  let d;
  try { d = await api(`product/${id}?${scopeParams()}`); } catch (e) {
    $('#product-body').innerHTML = `<div class="sheet-body">Грешка: ${esc(e.message)}</div>`; return;
  }
  const activePromos = d.promotions.filter((p) => !p.valid_to || p.valid_to >= new Date().toISOString().slice(0, 10));
  const compareRows = d.compare.map((c, i) => `
    <tr class="clickable ${i === 0 && d.compare.length > 1 && c.available ? 'best' : ''} ${c.available ? '' : 'na'}" data-id="${c.id}">
      <td>${esc(c.store_name)}${c.channel === 'online' ? ' <span class="muted small">🚚 онлайн</span>' : ''}<div class="note">${esc(c.name)}</div></td>
      <td class="num">${money(c.effective)}${c.card_eur != null && !c.with_card ? `<div class="note">${eur(c.card_eur)} с карта</div>` : ''}${unitOf(c) ? `<div class="note">${unitText(unitOf(c))}</div>` : ''}</td>
      <td class="num">${!c.available ? `<span class="note">не и в ${esc(areaName())}</span>`
        : c.channel === 'online' ? 'доставка'
          : c.outlets > 1 ? `${eur(c.price_min)}–${eur(c.price_max)}<div class="note">${c.outlets} обекта</div>` : (c.outlets ? '1 обект' : 'всички магазини')}</td>
      <td class="num note">${c.method === 'gtin' ? 'баркод' : c.method === 'name' ? `${Math.round(c.score * 100)}%` : ''}</td>
    </tr>`).join('');
  const outletsTitle = state.area ? `Обекти на ${esc(d.store_name)} в ${esc(areaName())}` : `Най-евтини обекти на ${esc(d.store_name)}`;
  $('#product-body').innerHTML = `
    <div class="sheet-head"><h2 id="pd-title">${esc(d.store_name)}</h2>
      <button class="icon" data-close aria-label="Затвори">✕</button></div>
    <div class="sheet-body">
      <div class="pd-top">
        ${d.image_url ? `<img src="${esc(d.image_url)}" alt="" referrerpolicy="no-referrer">` : '<div></div>'}
        <div>
          <h3>${esc(d.name)}</h3>
          <div class="prices"><span class="price ${d.promo_eur || d.with_card ? 'deal' : ''}">${money(d.effective)}</span>
            ${d.regular && d.regular > d.effective + 0.004 ? `<span class="old">${eur(d.regular)}</span>` : ''}
            ${d.card_eur != null ? `<span class="cardprice">${eur(d.card_eur)} с карта${d.with_card ? ' (вашата)' : ''}</span>` : ''}</div>
          ${d.prior_price != null && d.promo_eur != null ? `<p class="small ${d.fake_promo ? 'warn' : 'ok'}">${d.fake_promo
            ? `⚠ Обявената редовна цена ${eur(d.regular)} не е прилагана преди промоцията: най-ниската цена за 30 дни е ${eur(d.prior_price)} (обичайна ${eur(d.prior_median)}). Реално намаление: ${d.real_discount_pct}%.`
            : `✓ Намалението е спрямо реална цена: най-ниската за 30 дни преди промоцията е ${eur(d.prior_price)} (реално -${d.real_discount_pct}%).`}</p>` : ''}
          <div class="kv">
            ${d.brand ? `<span>Марка: ${esc(d.brand)}</span>` : ''}
            ${d.unit_text ? `<span>${esc(d.unit_text)}</span>` : ''}
            ${unitOf(d) ? `<span class="unitprice">${unitText(unitOf(d))}</span>` : ''}
            ${d.category_path ? `<span>${esc(d.category_path)}</span>` : ''}
            <span>към ${fmtDate(d.observed_on)}</span>
            ${d.prev_price ? `<span class="trend ${d.change_pct < 0 ? 'down' : d.change_pct > 0 ? 'up' : ''}">${fmtDate(d.prev_day)}: ${eur(d.prev_price)}${d.change_pct ? ` (${d.change_pct > 0 ? '+' : ''}${d.change_pct}%)` : ''}</span>` : ''}
          </div>
          <p><button data-add="${d.id}">+ Добави в количката</button>
            ${d.product_url ? ` <a class="small" href="${esc(d.product_url)}" target="_blank" rel="noopener noreferrer">към магазина ↗</a>` : ''}</p>
          ${d.family_groups > 1 ? `<p><button type="button" class="secondary" data-family="${d.family_id}">
            Всички вкусове и разновидности (${d.family_groups}) →</button></p>` : ''}
        </div>
      </div>
      ${activePromos.length ? `<h4>Промоции</h4><ul class="small">${activePromos.map((p) => `<li>
        <b>${eur(p.promo_eur)}</b>${p.regular_eur ? ` вместо ${eur(p.regular_eur)}` : ''}
        ${p.requires_loyalty ? ' · <span class="cardprice">с карта</span>' : ''}
        ${p.min_quantity > 1 ? ` · при ${p.min_quantity} бр.` : ''}
        ${p.valid_from || p.valid_to ? ` · ${fmtDate(p.valid_from)} – ${fmtDate(p.valid_to)}` : ''}
        ${p.label ? ` · ${esc(p.label)}` : ''}</li>`).join('')}</ul>` : ''}
      ${availabilityHTML(d)}
      <h4>Сравнение между вериги ${d.compare.length > 1 ? `(${d.compare.length})` : ''}</h4>
      ${d.compare.length > 1 ? `<div class="table-scroll"><table>
        <thead><tr><th>Верига</th><th class="num">Цена</th><th class="num">${state.area ? esc(areaName()) : 'Обхват'}</th><th class="num">Съвпадение</th></tr></thead>
        <tbody>${compareRows}</tbody></table></div>
        <div class="note">Съвпаденията са по баркод или по име, грамаж и процент. Проверявайте опаковката.</div>`
        : '<p class="muted small">Не открихме същия продукт в други вериги.</p>'}
      ${d.outlets_list.length > 1 || (state.area && d.outlets_list.length) ? `<h4>${outletsTitle}</h4>
        <div class="table-scroll"><table><tbody>${d.outlets_list.map((o) => `
          <tr><td>${esc(o.outlet)}${!state.area && o.settlement ? `<div class="note">${esc(o.settlement)}</div>` : ''}</td>
          <td class="num">${eur(o.price)}</td></tr>`).join('')}</tbody></table></div>` : ''}
      ${sparkline(d.history)}
    </div>`;
}

// --------------------------------------------------------------------------- family sheet (variants x chains)

async function openFamily(id) {
  const dlg = $('#family-dlg');
  closeDialog('#product-dlg');
  $('#family-body').innerHTML = '<div class="sheet-body muted">Зареждане…</div>';
  if (!dlg.open) dlg.showModal();
  let d;
  try { d = await api(`family/${id}?${scopeParams()}`); } catch (e) {
    $('#family-body').innerHTML = `<div class="sheet-body">Грешка: ${esc(e.message)}</div>`; return;
  }
  const f = d.family;
  const cols = d.stores.filter((s) => s.available);
  const away = d.stores.filter((s) => !s.available);
  const rowsAll = d.variants.filter((r) => cols.some((s) => r.cells[s.slug]?.available));
  const single = f.n_groups <= 1;
  const cell = (r, s) => {
    const c = r.cells[s.slug];
    if (!c || !c.available) return '<td class="num na">—</td>';
    const isBest = r.min != null && Math.abs(c.effective - r.min) < 0.005 && cols.length > 1;
    const u = unitOf(c);
    return `<td class="num cell ${isBest ? 'best' : ''}" data-id="${c.id}" tabindex="0" title="${esc(c.name)}${c.unit_text ? ` · ${esc(c.unit_text)}` : ''}">
      <span class="${c.promo_eur != null || c.with_card ? 'deal' : ''}">${money(c.effective)}</span>
      ${c.discount_pct >= 3 ? `<i class="d">-${c.discount_pct}%${c.fake_promo ? ' ⚠' : ''}</i>` : ''}
      ${c.with_card ? '<i class="c">с вашата карта</i>' : c.card_eur != null ? `<i class="c">${eur(c.card_eur)} карта</i>` : ''}
      ${u ? `<i class="u ${c.best_unit ? 'bu' : ''}">${unitText(u)}</i>` : ''}</td>`;
  };
  const body = (filter) => rowsAll
    .filter((r) => !filter || `${r.label} ${r.name}`.toLowerCase().includes(filter))
    .map((r) => `<tr><th scope="row" class="vlabel" title="${esc(r.name)}">${r.label ? esc(r.label)
      : single ? esc(r.name) : `<span class="muted">основен вариант</span>`}</th>${cols.map((s) => cell(r, s)).join('')}</tr>`)
    .join('') || `<tr><td colspan="${cols.length + 1}" class="muted small">Няма вариант с това име.</td></tr>`;
  const where = state.area ? ` в ${esc(areaName())}${state.online ? ' + онлайн доставка' : ''}` : '';
  $('#family-body').innerHTML = `
    <div class="sheet-head"><h2 id="fm-title">${esc(f.n_groups > 1 ? f.name : rowsAll[0]?.name || f.name)}${f.size_text ? ` <span class="muted">· ${esc(f.size_text)}</span>` : ''}</h2>
      <button class="icon" data-close aria-label="Затвори">✕</button></div>
    <div class="sheet-body">
      <p class="muted small">${plural(rowsAll.length, 'вариант', 'варианта')} в ${plural(cols.length, 'верига', 'вериги')}${where}.
        Най-ниската цена за всеки вариант е маркирана, а най-ниската цена за ${UNIT_LABEL[f.unit_per] || 'кг'} — в зелено. Натиснете цена за подробности.</p>
      ${f.best_unit_price ? `<p class="small"><b>Най-изгодно на ${UNIT_LABEL[f.unit_per] || 'кг'}:</b> <span class="unitprice">${unitText({ v: f.best_unit_price, per: f.unit_per || 'kg' })}</span></p>` : ''}
      ${rowsAll.length > 10 ? '<input type="search" class="vfilter" id="vfilter" placeholder="Филтрирай вкус / вариант…" aria-label="Филтрирай варианти">' : ''}
      ${cols.length ? `<div class="table-scroll matrix-wrap"><table class="matrix">
        <thead><tr><th scope="col">Вариант</th>${cols.map((s) => `<th scope="col" class="num">
          ${s.channel === 'online' ? '🚚 ' : ''}${esc(s.name)}<div class="note">от ${eur(s.min)}${s.min_unit ? ` · ${unitText({ v: s.min_unit, per: f.unit_per || 'kg' })}` : ''}</div></th>`).join('')}</tr></thead>
        <tbody id="matrix-body">${body('')}</tbody></table></div>`
        : `<p class="warn small">Нито една верига не предлага тези продукти${where}.</p>`}
      ${away.length ? `<p class="note">Не се предлагат в ${esc(areaName() || 'избрания град')}: ${away.slice(0, 4).map((s) => `${esc(s.name)}${s.area_names ? ` (${esc(s.area_names)})` : ''}`).join(', ')}${away.length > 4 ? ` и още ${away.length - 4} вериги` : ''}.</p>` : ''}
      <div class="note">Вариантите са групирани по марка, вид продукт и сходен грамаж. Един ред = един вкус/разновидност, сравнен между вериги.</div>
    </div>`;
  $('#vfilter')?.addEventListener('input', (e) => {
    $('#matrix-body').innerHTML = body(e.target.value.trim().toLowerCase());
  });
}

// --------------------------------------------------------------------------- basket

function saveBasket() {
  store.set('basket', state.basket);
  $('#basket-count').textContent = state.basket.reduce((n, l) => n + l.qty, 0);
}

function addToBasket(id) {
  // Update the basket before any await, so a double tap adds qty 2 instead of two lines.
  const line = state.basket.find((l) => l.product_id === id);
  if (line) line.qty += 1;
  else state.basket.push({ product_id: id, qty: 1, name: '' });
  saveBasket();
  const btn = $('#basket-open');
  btn.animate([{ transform: 'scale(1.15)' }, { transform: 'scale(1)' }], { duration: 250 });
  if (!line) {
    api(`product/${id}`).then((d) => {                // name is cosmetic; fill it in when it arrives
      const l = state.basket.find((x) => x.product_id === id);
      if (l && !l.name) { l.name = d.name; saveBasket(); }
    }).catch(() => {});
  }
}

function basketBody() {
  return {
    items: state.basket.map(({ product_id, qty, sub }) => ({ product_id, qty, ...(sub ? { allow_family_substitute: 1 } : {}) })),
    area: state.area, online: state.online ? 1 : 0, cards: [...state.cards],
    max_stores: state.maxStores, min_savings_per_store: state.minSavings,
  };
}

// The recommended trip: at most state.maxStores shops, an extra one only when it saves at least state.minSavings.
function planHTML(plan, r) {
  if (!plan) return '';
  const byStore = {};
  for (const x of plan.items) (byStore[x.store] ||= { name: x.store_name, channel: x.channel, items: [], total: 0 }).items.push(x);
  for (const s of Object.values(byStore)) s.total = s.items.reduce((t, x) => t + x.total, 0);
  const saved = plan.savings_vs_one_store > 0.004 ? ` · спестявате ${money(plan.savings_vs_one_store)} спрямо 1 магазин` : '';
  const missing = plan.missing.length ? `<div class="note warn">Без ${plural(plan.missing.length, 'продукт', 'продукта')} — няма ги в избраните вериги.</div>` : '';
  return `<div class="plan winner">
    <h5><span>Препоръчан маршрут: ${Object.values(byStore).map((s) => esc(s.name)).join(' + ')}</span><span>${money(plan.total)}</span></h5>
    <div class="note">${plural(plan.trips, 'магазин', 'магазина')}${saved}. Нов магазин се добавя само ако спестява поне ${eur(r.min_savings_per_store)}.</div>
    ${Object.values(byStore).map((s) => `<h6>${esc(s.name)}${s.channel === 'online' ? ' · онлайн' : ''} <span class="muted">${eur(s.total)}</span></h6>
      <table><tbody>${s.items.map((x) => `<tr><td>${esc(x.name)}${x.substitute ? ' <span class="sub">заместител</span>' : ''}${x.with_card ? ' <span class="cardprice">карта</span>' : ''}</td>
        <td class="num">${x.qty} × ${money(x.unit)}</td><td class="num">${money(x.total)}</td></tr>`).join('')}</tbody></table>`).join('')}
    ${missing}</div>`;
}

async function renderBasket() {
  const body = $('#basket-body');
  if (!state.basket.length) {
    body.innerHTML = `<div class="empty">Количката е празна.<br>Добави продукти с бутона „+“
      или <button class="link" data-open-list>постави списък</button>.</div>`;
    return;
  }
  const lines = state.basket.map((l, i) => `
    <div class="bk-line" data-line="${l.product_id}"><span>${esc(l.name || `#${l.product_id}`)}
      <label class="note sub-toggle"><input type="checkbox" data-sub="${i}" ${l.sub ? 'checked' : ''}> приемам друг вкус/разфасовка</label></span>
      <span class="qty"><button data-q="${i}" data-d="-1" aria-label="По-малко">−</button><b>${l.qty}</b>
      <button data-q="${i}" data-d="1" aria-label="Повече">+</button></span>
      <button class="icon" data-rm="${i}" aria-label="Премахни">✕</button></div>`).join('');
  const where = state.area ? `<p class="muted small">📍 ${esc(areaName())}${state.online ? ' + онлайн доставка' : ''}</p>` : '';
  const cards = state.cards.size ? `<p class="muted small">💳 Моите карти: ${[...state.cards].map((c) => esc(CARD_CHAINS.find((x) => x[0] === c)?.[1] || c)).join(', ')}</p>` : '';
  body.innerHTML = `<div class="sheet-body">${where}${cards}${lines}
    <div class="bk-settings small">
      <label>До <select id="bk-max">${[1, 2, 3].map((n) => `<option value="${n}" ${n === state.maxStores ? 'selected' : ''}>${plural(n, 'магазин', 'магазина')}</option>`).join('')}</select></label>
      <label>нов магазин само при спестяване ≥ <input id="bk-min" type="number" min="0" step="0.5" value="${state.minSavings}"> €</label>
    </div>
    <div id="plans" class="muted small">Изчисляване…</div>
    <p><button class="link" data-open-list>Умен списък</button> · <button class="link" id="bk-clear">Изчисти количката</button></p></div>`;
  try {
    const r = await api('basket', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(basketBody()) });
    for (const id of r.unavailable) {
      document.querySelector(`.bk-line[data-line="${id}"] span`)?.insertAdjacentHTML('beforeend',
        `<div class="note warn">не се продава в ${esc(areaName() || 'избрания град')}</div>`);
    }
    const best = r.single_store[0];
    const split = `<div class="plan">
      <h5><span>Най-евтино без ограничение (${plural(r.split.stores.length, 'верига', 'вериги')})</span><span>${money(r.split.total)}</span></h5>
      <table><tbody>${r.split.items.map((x) => `<tr><td>${esc(x.name)}<div class="note">${esc(x.store_name)}${x.channel === 'online' ? ' · онлайн' : ''}${x.substitute ? ' · заместител' : ''}</div></td>
        <td class="num">${x.qty} × ${money(x.unit)}</td><td class="num">${money(x.total)}</td></tr>`).join('')}</tbody></table></div>`;
    const single = r.single_store.length ? `<div class="plan">
      <h5><span>Всичко от една верига</span></h5>
      <table><tbody>${r.single_store.slice(0, 6).map((s, i) => `<tr class="${i === 0 ? 'best' : ''}">
        <td>${esc(s.store_name)}${s.channel === 'online' ? ' <span class="note">онлайн</span>' : ''}${s.substitutes ? ` <span class="note">${plural(s.substitutes, 'заместител', 'заместителя')}</span>` : ''}</td><td class="num">${money(s.total)}</td></tr>`).join('')}</tbody></table></div>`
      : `<div class="plan"><h5>Нито една верига няма всичко</h5><table><tbody>${r.partial_stores.slice(0, 5).map((s) => `
        <tr><td>${esc(s.store_name)}</td><td class="num">${s.items}/${r.lines.length - r.unavailable.length} продукта</td>
        <td class="num">${money(s.total)}</td></tr>`).join('')}</tbody></table></div>`;
    $('#plans').innerHTML = `${planHTML(r.plan, r)}${single}${best && r.split.total >= best.total - 0.01 ? '' : split}
      <div class="note">${state.cards.size ? 'Цените с вашите карти за лоялност са включени.' : 'Цените с карта за лоялност не са включени — добавете картите си в „Моите карти“.'}
        Мултипак цените се ползват само при достатъчно количество.</div>`;
  } catch (e) {
    $('#plans').textContent = `Грешка: ${e.message}`;
  }
}

// --------------------------------------------------------------------------- smart shopping list ("Умен списък")
// One product per line: 'прясно мляко 2л', 'яйца 10бр', '3 x кисело мляко'. A leading/trailing 'N x' is the quantity;
// a size in the line (2 л, 400 г) picks the pack of that size among the matches.
// (JS's \b does not see Cyrillic letters as word characters, hence the explicit lookahead.)
const SIZE_RE = /(\d+(?:[.,]\d+)?)\s*(кг|kg|гр|г|gr|g|мл|ml|л|l)\.?(?![а-яa-z])/i;
function parseListLine(line) {
  let text = line.replace(/^\s*(?:[•*\-–]+|\d+[.)])\s*/, '').trim();       // bullets, '1.' / '1)' numbering
  let qty = 1;
  const lead = text.match(/^(\d{1,2})\s*(?:[xх×*]\s*|бр\.?\s+|\s+)(.+)$/i);   // '3 x мляко', '3 бр. яйца', '2 банани'
  const tail = text.match(/^(.+?)\s*[xх×*]\s*(\d{1,2})$/i);                   // 'мляко x3'
  if (lead && !SIZE_RE.test(`${lead[1]}${lead[2].slice(0, 3)}`) && !SIZE_RE.test(`${lead[1]} ${lead[2].slice(0, 3)}`)) {
    qty = Number(lead[1]); text = lead[2];
  } else if (tail) {
    qty = Number(tail[2]); text = tail[1];
  }
  const sz = text.match(SIZE_RE);
  let grams = null;
  if (sz) {
    const n = Number(sz[1].replace(',', '.'));
    grams = /^(кг|kg|л|l)$/i.test(sz[2]) ? n * 1000 : n;
  }
  const pc = text.match(/(\d+)\s*бр\.?(?![а-я])/i);
  // The search runs on the words; the size and piece count only rank the matches ('2л' is not a name token).
  const query = text.replace(SIZE_RE, ' ').replace(/(\d+)\s*бр\.?(?![а-я])/i, ' ').replace(/\s+/g, ' ').trim() || text;
  return { text: text.trim(), query, qty: Math.max(1, Math.min(99, qty)), grams, pieces: pc ? Number(pc[1]) : null };
}

async function resolveListLine(line) {
  const want = parseListLine(line);
  const p = scopeParams(new URLSearchParams({ q: want.query, collapse: 'group', per_page: '24', sort: 'relevance' }));
  const d = await api(`search?${p}`);
  const on = d.items.filter((it) => !it.off);
  const pool = on.length ? on : d.items;
  // With a size (2 л) or count (10 бр.) in the line, a pack of that size beats a better-ranked other size.
  const fits = (it) => (want.grams ? it.size_g && Math.abs(it.size_g - want.grams) <= want.grams * 0.15
    : want.pieces ? it.pieces === want.pieces : false);
  const sized = pool.filter(fits);
  const picks = [...sized, ...pool.filter((it) => !sized.includes(it))].slice(0, 6);
  return { ...want, line, picks };
}

async function runSmartList() {
  const lines = $('#list-text').value.split('\n').map((l) => l.trim()).filter(Boolean).slice(0, 40);
  store.set('listDraft', $('#list-text').value);
  if (!lines.length) return;
  $('#list-results').innerHTML = '<p class="muted small">Търсене…</p>';
  const res = await Promise.all(lines.map((l) => resolveListLine(l).catch(() => ({ line: l, picks: [], qty: 1 }))));
  $('#list-results').innerHTML = `<table class="list-table"><tbody>${res.map((r, i) => `<tr>
      <td><input type="checkbox" data-li="${i}" ${r.picks.length ? 'checked' : 'disabled'} aria-label="Добави"></td>
      <td><div class="note">${esc(r.line)}</div>${r.picks.length ? `<select data-pick="${i}">${r.picks.map((it) =>
        `<option value="${it.id}">${esc(it.name)} · ${esc(it.store_name)} · ${eur(it.effective)}</option>`).join('')}</select>`
        : '<span class="warn small">няма намерен продукт</span>'}</td>
      <td class="num"><input type="number" min="1" max="99" value="${r.qty}" data-lq="${i}" aria-label="Количество"></td></tr>`).join('')}</tbody></table>
    <p class="small"><label><input type="checkbox" id="list-sub" checked> приемам друг вкус/разфасовка, ако веригата няма точния продукт</label></p>
    <p><button id="list-add">Добави в количката</button></p>`;
  $('#list-add').addEventListener('click', () => {
    const sub = $('#list-sub').checked;
    res.forEach((r, i) => {
      if (!r.picks.length || !$(`[data-li="${i}"]`).checked) return;
      const id = Number($(`[data-pick="${i}"]`).value);
      const qty = Math.max(1, Number($(`[data-lq="${i}"]`).value) || 1);
      const it = r.picks.find((x) => x.id === id);
      const line = state.basket.find((l) => l.product_id === id);
      if (line) line.qty += qty;
      else state.basket.push({ product_id: id, qty, name: it?.name || '', sub });
    });
    saveBasket();
    closeDialog('#list-dlg');
    $('#basket-dlg').showModal(); renderBasket();
  });
}

function openSmartList() {
  closeDialog('#basket-dlg');
  $('#list-text').value = store.get('listDraft', '');
  $('#list-results').innerHTML = '';
  $('#list-dlg').showModal();
  $('#list-text').focus();
}

// --------------------------------------------------------------------------- barcode scanner (in-store)
// The browser's own BarcodeDetector (Chrome/Edge on Android, Safari 17+ on some devices): no library needed.
let scanStream = null;
function stopScan() {
  scanStream?.getTracks().forEach((t) => t.stop());
  scanStream = null;
}

async function openScanner() {
  const dlg = $('#scan-dlg');
  $('#scan-msg').textContent = 'Насочете камерата към баркода (EAN-13 / EAN-8).';
  dlg.showModal();
  try {
    scanStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false });
  } catch (e) {
    $('#scan-msg').textContent = `Няма достъп до камерата: ${e.message}`;
    return;
  }
  const video = $('#scan-video');
  video.srcObject = scanStream;
  await video.play().catch(() => {});
  const detector = new BarcodeDetector({ formats: ['ean_13', 'ean_8'] });
  const tick = async () => {
    if (!scanStream || !dlg.open) return;
    try {
      const codes = await detector.detect(video);
      if (codes.length) {
        stopScan(); dlg.close();
        $('#q').value = codes[0].rawValue;
        state.dept = ''; search(1);
        return;
      }
    } catch { /* frame not ready */ }
    setTimeout(tick, 250);
  };
  tick();
}

// --------------------------------------------------------------------------- "Моите карти", BGN toggle

function renderCardsList() {
  $('#cards-list').innerHTML = CARD_CHAINS.map(([slug, name]) => `<label>
    <input type="checkbox" value="${esc(slug)}" ${state.cards.has(slug) ? 'checked' : ''}> ${esc(name)}</label>`).join('');
  $('#cards-count').textContent = state.cards.size ? `(${state.cards.size})` : '';
  $('#cards-dd summary').classList.toggle('set', state.cards.size > 0);
}

function renderBgn() {
  const b = $('#bgn-toggle');
  b.setAttribute('aria-pressed', String(state.bgn));
  b.classList.toggle('on', state.bgn);
}

// --------------------------------------------------------------------------- wiring

async function init() {
  saveBasket();
  const url = new URLSearchParams(location.search);
  if (url.get('q')) $('#q').value = url.get('q');
  if (url.get('discounts')) $('#f-disc').checked = true;
  if (url.get('card')) $('#f-card').checked = true;
  if (Number(url.get('min_stores')) >= 2) $('#f-multi').checked = true;
  if (url.get('store')) {
    state.selectedStores = new Set(url.get('store').split(',').filter(Boolean));
    store.set('stores', [...state.selectedStores]);
  }
  if ([...$('#f-sort').options].some((o) => o.value === url.get('sort'))) $('#f-sort').value = url.get('sort');
  if (['family', 'group', 'none'].includes(url.get('collapse'))) $('#f-group').value = url.get('collapse');
  if (url.get('dept')) state.dept = url.get('dept');
  if (url.has('area')) { state.area = url.get('area'); store.set('area', state.area); }
  if (url.get('online') === '0') state.online = false;

  api('stats').then((s) => {
    $('#s-stores').textContent = s.stores;
    $('#s-outlets').textContent = s.outlets.toLocaleString('bg-BG');
    $('#s-products').textContent = s.products.toLocaleString('bg-BG');
    $('#s-compared').textContent = s.compared.toLocaleString('bg-BG');
    $('#s-updated').textContent = fmtDate(s.last_updated);
  }).catch(() => {});
  api('stores').then((d) => { state.stores = d.stores; renderStoreList(); }).catch(() => {});
  try {
    const a = await api('areas');
    state.areas = a.areas;
    $('#online-names').textContent = a.online_stores.length ? `(${a.online_stores.map((s) => s.name).join(', ')})` : '';
    if (state.area && !state.areas.some((x) => x.code === state.area)) { state.area = ''; store.set('area', ''); }
  } catch { /* the picker stays on "whole country" */ }
  renderAreaLabel(); renderAreaList(); renderCardsList(); renderBgn();
  loadFeeds();
  search(1);
  // In-store barcode scan where the browser has a native detector and a camera.
  $('#scan-btn').hidden = !('BarcodeDetector' in window && navigator.mediaDevices?.getUserMedia);

  $('#search-form').addEventListener('submit', (e) => { e.preventDefault(); state.dept = ''; search(1); });
  $('#q').addEventListener('input', searchSoon);
  for (const id of ['#f-disc', '#f-sort']) $(id).addEventListener('change', () => search(1));
  // Card prices only add to "discounts", so on the home view ticking it also turns discounts on.
  $('#f-card').addEventListener('change', (e) => {
    if (e.target.checked) $('#f-disc').checked = true;
    search(1);
  });
  // "In 2+ chains" is not a search by itself: on the home view it filters the deals/drops feeds.
  $('#f-multi').addEventListener('change', () => { search(1); loadFeeds(); });
  $('#f-group').addEventListener('change', () => { search(1); loadFeeds(); });
  $('#more').addEventListener('click', () => search(state.page + 1));
  $('#facets').addEventListener('click', (e) => {
    const b = e.target.closest('[data-dept]');
    if (!b) return;
    state.dept = b.dataset.dept;
    for (const x of document.querySelectorAll('#facets .facet')) x.classList.toggle('on', x === b);
    search(1);
  });
  $('#store-filter-text').addEventListener('input', renderStoreList);
  $('#store-list').addEventListener('change', (e) => {
    const cb = e.target.closest('input[type=checkbox]');
    if (!cb) return;
    cb.checked ? state.selectedStores.add(cb.value) : state.selectedStores.delete(cb.value);
    store.set('stores', [...state.selectedStores]);
    renderStoreList(); search(1);
  });
  $('#store-clear').addEventListener('click', () => {
    state.selectedStores.clear(); store.set('stores', []); renderStoreList(); search(1);
  });
  $('#area-filter-text').addEventListener('input', renderAreaList);
  $('#area-list').addEventListener('change', (e) => { if (e.target.name === 'area') setArea(e.target.value); });
  $('#f-online').addEventListener('change', (e) => {
    state.online = e.target.checked; store.set('online', state.online); search(1); loadFeeds();
  });
  $('#cards-list').addEventListener('change', (e) => {
    const cb = e.target.closest('input[type=checkbox]');
    if (!cb) return;
    cb.checked ? state.cards.add(cb.value) : state.cards.delete(cb.value);
    store.set('cards', [...state.cards]);
    renderCardsList(); search(1); loadFeeds();
  });
  $('#bgn-toggle').addEventListener('click', () => {
    state.bgn = !state.bgn; store.set('bgn', state.bgn); renderBgn();
    search(1); loadFeeds();
    if ($('#basket-dlg').open) renderBasket();
  });
  $('#f-honest').addEventListener('change', loadFeeds);
  $('#scan-btn').addEventListener('click', openScanner);
  $('#scan-dlg').addEventListener('close', stopScan);
  $('#list-run').addEventListener('click', runSmartList);
  // Mobile dropdowns are position:fixed; keep them inside the visible area when the keyboard opens.
  const fitDropdown = () => {
    const vv = window.visualViewport;
    document.documentElement.style.setProperty('--vvh', `${vv ? vv.height + vv.offsetTop : window.innerHeight}px`);
    const panel = $('details.dropdown[open] .dd-panel');
    if (panel) document.documentElement.style.setProperty('--dd-top', `${Math.max(0, panel.getBoundingClientRect().top)}px`);
  };
  window.visualViewport?.addEventListener('resize', fitDropdown);
  window.visualViewport?.addEventListener('scroll', fitDropdown);
  window.addEventListener('resize', fitDropdown);
  for (const dd of document.querySelectorAll('details.dropdown')) dd.addEventListener('toggle', fitDropdown);
  fitDropdown();
  $('#loc-hint-btn').addEventListener('click', () => { $('#area-dd').open = true; $('#area-filter-text').focus(); });
  // Close an open dropdown when clicking elsewhere.
  document.addEventListener('click', (e) => {
    for (const dd of document.querySelectorAll('details.dropdown[open]')) {
      if (!dd.contains(e.target) && e.target.id !== 'loc-hint-btn') dd.open = false;
    }
  });

  document.addEventListener('click', (e) => {
    if (e.target.closest('[data-open-list]')) { openSmartList(); return; }
    const add = e.target.closest('[data-add]');
    if (add) { e.stopPropagation(); addToBasket(Number(add.dataset.add)); return; }
    if (e.target.closest('[data-close]')) { e.target.closest('dialog').close(); return; }
    const fam = e.target.closest('[data-family]');
    if (fam) { openFamily(Number(fam.dataset.family)); return; }
    const row = e.target.closest('tr.clickable[data-id], .card[data-id], td.cell[data-id]');
    if (row) openProduct(Number(row.dataset.id));
  });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    if (e.target.matches('.card[data-family]')) openFamily(Number(e.target.dataset.family));
    else if (e.target.matches('.card[data-id], td.cell[data-id]')) openProduct(Number(e.target.dataset.id));
  });
  for (const dlg of document.querySelectorAll('dialog')) {
    dlg.addEventListener('click', (e) => { if (e.target === dlg) dlg.close(); });   // backdrop click
  }

  $('#basket-open').addEventListener('click', () => { $('#basket-dlg').showModal(); renderBasket(); });
  $('#basket-body').addEventListener('click', (e) => {
    const q = e.target.closest('[data-q]'), rm = e.target.closest('[data-rm]');
    if (q) {
      const l = state.basket[Number(q.dataset.q)];
      l.qty = Math.max(1, l.qty + Number(q.dataset.d));
    } else if (rm) state.basket.splice(Number(rm.dataset.rm), 1);
    else if (e.target.id === 'bk-clear') state.basket = [];
    else return;
    saveBasket(); renderBasket();
  });
  $('#basket-body').addEventListener('change', (e) => {
    const sub = e.target.closest('[data-sub]');
    if (sub) { state.basket[Number(sub.dataset.sub)].sub = sub.checked; saveBasket(); }
    else if (e.target.id === 'bk-max') { state.maxStores = Number(e.target.value); store.set('maxStores', state.maxStores); }
    else if (e.target.id === 'bk-min') { state.minSavings = Math.max(0, Number(e.target.value) || 0); store.set('minSavings', state.minSavings); }
    else return;
    renderBasket();
  });
}

init();
