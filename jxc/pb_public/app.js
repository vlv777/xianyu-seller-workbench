/* 进销存 · 前端：登录 + 首页 + 库存 + 单据 + 寄改工单 */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const r2 = (v) => Math.round((Number(v) + Number.EPSILON) * 100) / 100;
const money = (v) => (Number(v) || 0).toFixed(2).replace(/\.00$/, '');

function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

let token = localStorage.getItem('jxc_token') || '';
let me = null;
let cache = {};
const ui = { tab: 'home', docsTab: 'sales' };

/* ---------- 接口 ---------- */
function api(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = token;
  return fetch('/api' + path, {
    method: opts.method || 'GET',
    headers,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  }).then(async (r) => {
    if (r.status === 401) {
      token = '';
      localStorage.removeItem('jxc_token');
      const e = new Error('登录已过期');
      e.loginRequired = true;
      throw e;
    }
    const text = await r.text();
    const json = text ? JSON.parse(text) : null;
    if (r.status >= 400) throw new Error((json && json.message) || ('接口错误 ' + r.status));
    return json;
  });
}

async function fetchAll(collection) {
  const items = [];
  let page = 1;
  for (;;) {
    const j = await api(`/collections/${collection}/records?perPage=500&page=${page}`);
    items.push(...((j && j.items) || []));
    if (page >= ((j && j.totalPages) || 1)) break;
    page++;
  }
  return items;
}

async function load(key, fn) {
  if (cache[key]) return cache[key];
  const v = await fn();
  cache[key] = v;
  return v;
}

/* ---------- 库存计算（与 jxc-mcp 同逻辑：期初快照 + 迁移后新单） ---------- */
async function computeStock() {
  const [adjs, purchases, sales, dis, parts] = await Promise.all([
    load('adjustments', () => fetchAll('adjustments')),
    load('purchases', () => fetchAll('purchases')),
    load('sales', () => fetchAll('sales')),
    load('disassembly', () => fetchAll('disassembly')),
    load('part_items', () => fetchAll('part_items')),
  ]);
  const partPrice = new Map(parts.map((p) => [p.name, p.value]));
  const qtyOf = (name, val) => {
    if (!partPrice.has(name)) return 0;
    const up = partPrice.get(name);
    return up ? Math.max(1, Math.round(Number(val || 0) / up)) : 1;
  };
  const m = new Map();
  const add = (k, d) => m.set(k, r2((m.get(k) || 0) + d));
  for (const a of adjs) add(a.scope === '整机' ? `M:${a.model}|${a.spec}` : `P:${a.part}`, a.delta);
  for (const p of purchases) if (!p.hist) add(`M:${p.model}|${p.spec}`, p.qty || 0);
  for (const s of sales) {
    if (s.hist) continue;
    if (s.type === '退货') {
      if (s.stock_ref) add(`M:${s.stock_ref}`, s.units || 1);
      continue;
    }
    if (s.stock_ref) add(`M:${s.stock_ref}`, -(s.units || 1));
    for (const mo of s.mods || []) {
      const q = qtyOf(mo.name, mo.cost);
      if (q) add(`P:${mo.name}`, -q);
    }
    for (const rc of s.recycling || []) {
      const q = qtyOf(rc.name, rc.value);
      if (q) add(`P:${rc.name}`, q);
    }
  }
  for (const d of dis) {
    if (d.hist) continue;
    add(`M:${d.model}|${d.spec}`, -(d.qty || 0));
    for (const o of d.outputs || []) add(`P:${o.name}`, o.qty || 0);
  }
  return m;
}

/* ---------- 连接状态 ---------- */
async function checkHealth() {
  const dot = document.getElementById('dot');
  const connText = document.getElementById('connText');
  if (!dot) return;
  try {
    const r = await fetch('/api/health');
    const j = await r.json();
    dot.classList.toggle('on', true);
    dot.classList.toggle('off', false);
    connText.textContent = '服务正常';
  } catch (e) {
    dot.classList.toggle('on', false);
    dot.classList.toggle('off', true);
    connText.textContent = '服务离线';
  }
}

/* ---------- 登录 ---------- */
function loginView() {
  return `
  <div class="login-wrap">
    <div class="card">
      <div class="card-title">进销存 · 登录</div>
      <input id="loginEmail" type="email" placeholder="邮箱">
      <input id="loginPass" type="password" placeholder="密码">
      <button class="btn primary" data-action="login">登录</button>
      <div class="hint" id="loginHint"></div>
    </div>
  </div>`;
}

async function doLogin() {
  const identity = $('#loginEmail').value.trim();
  const password = $('#loginPass').value;
  $('#loginHint').textContent = '登录中…';
  try {
    const r = await fetch('/api/collections/users/auth-with-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ identity, password }),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.message || '登录失败');
    token = j.token;
    me = j.record;
    localStorage.setItem('jxc_token', token);
    render();
  } catch (e) {
    $('#loginHint').textContent = '登录失败：' + e.message;
  }
}

/* ---------- 页面 ---------- */
async function renderHome() {
  const [sales, rw] = await Promise.all([
    load('sales', () => fetchAll('sales')),
    load('rework', () => fetchAll('rework')),
  ]);
  const real = sales.filter((s) => s.price > 0);
  const today = todayStr();
  const month = today.slice(0, 7);
  const seg = (arr) => {
    const n = arr.length;
    const rev = r2(arr.reduce((a, s) => a + (s.price || 0), 0));
    const pf = r2(arr.reduce((a, s) => a + (s.profit || 0), 0));
    return `单 ${n} · 销售额 ${money(rev)} · 利润 ${money(pf)}`;
  };
  const openRw = rw.filter((r) => !['完成', '取消'].includes(r.status));
  return `
    <div class="card">
      <div class="card-title">问一句</div>
      <div class="ask-row">
        <input id="askText" type="text" placeholder="比如：亚瑟128G还有几台 / 这个月卖了多少 / 还剩几单寄改">
        <button class="btn primary" data-action="ask">问</button>
      </div>
      <div class="ask-answer" id="askAnswer"></div>
    </div>
    <div class="card"><div class="card-title">今日（${today}）</div><div class="big">${seg(real.filter((s) => s.date === today))}</div></div>
    <div class="card"><div class="card-title">本月</div><div class="big">${seg(real.filter((s) => String(s.date || '').startsWith(month)))}</div></div>
    <div class="card"><div class="card-title">累计（有效单）</div><div class="big">${seg(real)}</div></div>
    <div class="card"><div class="card-title">在办寄改</div><div class="big">${openRw.length} 单</div></div>`;
}

async function renderStock() {
  const m = await computeStock();
  const mach = [];
  const parts = [];
  for (const [k, v] of [...m.entries()].sort()) {
    if (r2(v) === 0) continue;
    if (k.startsWith('M:')) mach.push([k.slice(2), money(v)]);
    else parts.push([k.slice(2), money(v)]);
  }
  const row = ([n, v]) => `<div class="row"><span class="row-name">${esc(n)}</span><b>${v}</b></div>`;
  return `
    <div class="card">
      <div class="card-title">整机（${mach.length}）</div>
      ${mach.map(row).join('') || '<div class="empty">（无）</div>'}
    </div>
    <div class="card">
      <div class="card-title">拆机件（${parts.length}）</div>
      ${parts.map(row).join('') || '<div class="empty">（无）</div>'}
    </div>
    <div class="empty" style="padding:0 4px">= 期初快照 + 迁移后新单自动汇总</div>`;
}

const DOC_TABS = [['sales', '出货'], ['returned', '退货'], ['purchases', '进货'], ['disassembly', '拆机'], ['adjustments', '调整'], ['rework', '工单']];

async function renderDocs() {
  const t = ui.docsTab;
  const items = t === 'returned'
    ? (await load('sales', () => fetchAll('sales'))).filter((s) => s.type === '退货')
    : await load(t, () => fetchAll(t));
  items.sort((a, b) => String(b.date || b.date_order || '').localeCompare(String(a.date || a.date_order || '')));
  const tabsHtml = DOC_TABS.map(([k, label]) => `<button data-docstab="${k}" class="${ui.docsTab === k ? 'active' : ''}">${label}</button>`).join('');

  let rows = '';
  if (t === 'sales' || t === 'returned') {
    rows = items.map((s) => {
      const cls = s.type === '退货' ? 'bad' : (s.type === '售后补发' ? 'warn' : '');
      const canReturn = t === 'sales' && s.type !== '退货' && s.price > 0;
      return `<div class="row col">
        <div class="row-head"><span class="badge ${cls}">${esc(s.type)}</span><b>${esc(s.model)}</b><span class="dim">${esc(s.date)}</span>${canReturn ? `<button class="mini-btn" data-return="${s.id}">退货</button>` : ''}</div>
        <div class="row-body">${esc(s.config || '')} · 价 ${money(s.price)} · 利 ${money(s.profit)}${s.note ? ' · ' + esc(String(s.note).slice(0, 40)) : ''}</div>
      </div>`;
    }).join('');
  } else if (t === 'purchases') {
    rows = items.map((p) => `<div class="row col">
        <div class="row-head"><b>${esc(p.model)}${p.spec ? ' | ' + esc(p.spec) : ''}</b><span class="dim">${esc(p.date)}</span></div>
        <div class="row-body">x${p.qty} @ ${money(p.unit_price)} · 合计 ${money((p.qty || 0) * (p.unit_price || 0))}${p.batch ? ' · 批次 ' + esc(p.batch) : ''}</div>
      </div>`).join('');
  } else if (t === 'disassembly') {
    rows = items.map((d) => `<div class="row col">
        <div class="row-head"><b>${esc(d.model)}${d.spec ? ' | ' + esc(d.spec) : ''}</b><span class="dim">${esc(d.date)}</span></div>
        <div class="row-body">拆 ${d.qty} 台 · 产出 ${(d.outputs || []).map((o) => esc(o.name) + 'x' + o.qty).join('、') || '无'}</div>
      </div>`).join('');
  } else if (t === 'adjustments') {
    rows = items.map((a) => `<div class="row col">
        <div class="row-head"><span class="badge">${esc(a.scope)}</span><b>${esc(a.scope === '整机' ? a.model + '|' + a.spec : a.part)}</b><span class="dim">${esc(a.date)}</span></div>
        <div class="row-body">Δ ${a.delta}${a.note ? ' · ' + esc(a.note) : ''}</div>
      </div>`).join('');
  } else {
    rows = items.map((rw) => {
      const cls = rw.status === '完成' ? 'ok' : (['取消'].includes(rw.status) ? 'bad' : (['待寄出', '在途'].includes(rw.status) ? 'warn' : ''));
      return `<div class="row col">
        <div class="row-head"><span class="badge ${cls}">${esc(rw.status || '')}</span><b>${esc(rw.customer || '')}</b><span class="dim">下单 ${esc(rw.date_order || '-')}</span></div>
        <div class="row-body">${esc(rw.model || '')} ${esc(rw.target || '')} · 寄出 ${esc(rw.date_shipped_in || '-')} · 收 ${esc(rw.date_received || '-')} · 寄回 ${esc(rw.date_shipped_back || '-')} · 单号 ${esc(rw.tracking_in || '-')} / ${esc(rw.tracking_out || '-')}</div>
      </div>`;
    }).join('');
  }

  const exportBtn = (t === 'sales' || t === 'returned')
    ? `<button class="mini-btn plain" data-action="export-sales">导出出货 CSV</button>`
    : (t === 'purchases' ? `<button class="mini-btn plain" data-action="export-purchases">导出进货 CSV</button>` : '');
  return `
    <div class="subtabs">${tabsHtml}</div>
    ${exportBtn ? `<div class="toolbar-sm">${exportBtn}</div>` : ''}
    <div class="card">${rows || '<div class="empty">（无记录）</div>'}</div>
    <div class="empty" style="padding:0 4px">共 ${items.length} 条</div>`;
}

let draft = null;
let commitMsg = null;
let xyList = null;
let xyStatus = 'NOT_SHIP';
let xyHidden = false;  // 手动点过「收起」后，开单页不再自动恢复缓存
const XY_CACHE_KEY = 'jxc_xy_cache';

function saveXyCache() {
  try {
    if (!xyList || xyList.error || !Array.isArray(xyList.orders)) return;
    localStorage.setItem(XY_CACHE_KEY, JSON.stringify({
      ts: Date.now(), status: xyStatus, page: xyList.page,
      total: xyList.total, nextPage: xyList.nextPage, orders: xyList.orders,
    }));
  } catch (e) { /* 隐私模式等落不了盘就忽略 */ }
}

function loadXyCache() {
  try {
    const raw = localStorage.getItem(XY_CACHE_KEY);
    if (!raw) return null;
    const j = JSON.parse(raw);
    if (!j || !Array.isArray(j.orders) || !j.ts) return null;
    return j;
  } catch (e) { return null; }
}
const XY_TABS = [['NOT_SHIP', '待发货'], ['SHIPPED', '已发货'], ['REFUND', '退款中'], ['TRADE_SUCCESS', '交易成功'], ['TRADE_CLOSED', '交易关闭'], ['ALL', '全部']];

const FIELD_LABELS = {
  date: '日期', type: '类型', model: '型号', config: '配置', spec: '规格',
  price: '售价', base_cost: '进价', shipping: '快递', units: '台数', stock_ref: '扣库存', note: '备注',
  qty: '数量', unit_price: '单价', batch: '批次', date_order: '下单日', customer: '客户', target: '改装内容', fee: '收费',
};

function renderOrder() {
  if (commitMsg) {
    return `<div class="card">
      <div class="card-title">已入账</div>
      <div class="big">${esc(commitMsg)}</div>
      <div class="order-actions" style="margin-top:12px">
        <button class="btn primary" data-action="new-order">再记一笔</button>
      </div>
    </div>`;
  }
  if (!draft) {
    if (!xyList && !xyHidden) {
      const c = loadXyCache();
      if (c) { xyList = c; xyStatus = c.status || xyStatus; }
    }
    return `<div class="card">
      <div class="card-title">开单 · 一个框</div>
      <textarea id="orderText" class="order-input" rows="3" placeholder="说一句或打一句，例如：&#10;卖了台亚瑟1G128双风扇 133 包邮&#10;进了11台红米AX6原机 80.75&#10;拆了56台亚瑟128G，出55个128G芯片"></textarea>
      <div class="order-actions">
        <button class="btn primary" data-action="parse">记一笔</button>
        <button class="btn" data-action="pull-xy">拉闲鱼订单</button>
        <span class="hint" id="orderHint"></span>
      </div>
      <div class="empty" style="margin-top:6px">手机上点输入框，用键盘上的语音直接说话就行。</div>
    </div>
    ${xyListCard()}`;
  }
  return draftCard();
}

function draftCard() {
  const d = draft;
  const f = d.fields;
  const rows = [];
  for (const k of Object.keys(f)) {
    if (k === 'profit') continue;
    const label = FIELD_LABELS[k] || k;
    const v = f[k];
    if (Array.isArray(v)) {
      if (k === 'mods' || k === 'recycling') {
        const numKey = k === 'mods' ? 'cost' : 'value';
        const text = v.map((it) => `${it.name}:${it[numKey] != null ? it[numKey] : ''}`).join('；');
        rows.push(`<div class="row"><span class="row-name">${label}</span><input class="inline-input" data-field="${k}" data-array="${numKey}" type="text" value="${esc(text)}" placeholder="可改：名称:金额，多个用；隔开"></div>`);
      } else {
        const chips = v.length
          ? v.map((it) => `<span class="chip">${esc(it.name)} ${it.cost != null ? it.cost : (it.value != null ? it.value : '')}${it.qty != null && it.unit_value != null ? ' x' + it.qty + '@' + it.unit_value : ''}</span>`).join('')
          : '<span class="empty">无</span>';
        rows.push(`<div class="row"><span class="row-name">${label}</span><span class="chips">${chips}</span></div>`);
      }
    } else {
      const isNum = typeof v === 'number';
      rows.push(`<div class="row"><span class="row-name">${label}</span><input class="inline-input" data-field="${k}" type="${isNum ? 'number' : 'text'}" value="${esc(v)}"></div>`);
    }
  }
  const profitRow = d.type === 'sale' ? `<div class="row"><span class="row-name">利润</span><b id="profitVal">${money(f.profit)}</b></div>` : '';
  return `<div class="card">
    <div class="card-title">草稿 · ${esc(d.summary)}</div>
    ${rows.join('')}
    ${profitRow}
    <div class="empty" style="margin:8px 0 4px">原话：${esc(d.sourceText || '')}</div>
    <div class="order-actions">
      <button class="btn primary" data-action="confirm-order">确认入账</button>
      <button class="btn" data-action="discard-order">丢弃</button>
    </div>
    <div class="hint" id="orderHint"></div>
  </div>`;
}

async function doParse() {
  const el = document.getElementById('orderText');
  const text = el ? el.value.trim() : '';
  if (!text) return;
  const hint = document.getElementById('orderHint');
  if (hint) hint.textContent = 'AI 解析中（几秒）…';
  try {
    const r = await fetch(`http://${location.hostname}:8091/parse`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || ('接口 ' + r.status));
    if (j.question) {
      if (hint) hint.textContent = 'AI 问：' + j.question;
      return;
    }
    if (!j.draft) throw new Error(j.error || '解析结果为空');
    j.draft.sourceText = text;
    draft = j.draft;
    render();
  } catch (e) {
    if (hint) hint.textContent = '解析失败：' + e.message;
  }
}

function xyListCard() {
  if (!xyList) return '';
  if (xyList.error) {
    return `<div class="card"><div class="card-title">闲鱼订单</div>
      <div class="empty">拉取失败：${esc(xyList.error)}（登录态可能过期，去闲鱼助手重登后再试）</div>
      <div class="order-actions"><button class="btn" data-action="close-xy">收起</button></div>
    </div>`;
  }
  const rows = (xyList.orders || []).map((o, i) => {
    const cls = o.status === '交易成功' ? 'ok' : (o.status === '交易关闭' ? 'bad' : 'warn');
    return `<div class="row col">
      <div class="row-head"><span class="badge ${cls}">${esc(o.status)}</span><b>${esc(String(o.title).slice(0, 22))}</b><span class="dim">¥${o.totalPrice} · ${esc(o.createTime)}</span></div>
      <div class="row-body">${esc(o.spec)}${o.buyNum > 1 ? ' x' + o.buyNum : ''} · 买家 ${esc(o.buyerNick)} <button class="mini-btn plain" data-xy-open="${i}">开单</button></div>
    </div>`;
  }).join('');
  const tabs = XY_TABS.map(([k, label]) => `<button data-xy-status="${k}" class="${xyStatus === k ? 'active' : ''}">${label}</button>`).join('');
  const cacheAt = xyList.ts ? new Date(xyList.ts).toLocaleTimeString('zh-CN', { hour12: false }).slice(0, 5) : '';
  const stale = xyList.ts && (Date.now() - xyList.ts > 86400000) ? ' · 较旧，建议点「拉闲鱼订单」刷新' : '';
  return `<div class="card">
    <div class="card-title">闲鱼订单（共 ${xyList.total} 笔 · 第 ${xyList.page} 页${cacheAt ? ' · 缓存 ' + cacheAt : ''}${stale}）</div>
    <div class="subtabs">${tabs}</div>
    ${rows || '<div class="empty">没有订单</div>'}
    <div class="order-actions">
      ${xyList.nextPage ? '<button class="btn" data-action="pull-xy-more">下一页</button>' : ''}
      <button class="btn" data-action="close-xy">收起</button>
    </div>
  </div>`;
}

async function doPullXY(page) {
  const hint = document.getElementById('orderHint');
  if (hint) hint.textContent = '拉闲鱼订单中…';
  try {
    const r = await fetch(`http://${location.hostname}:8091/xy-orders?page=${page}&size=20&status=${xyStatus}`);
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || ('接口 ' + r.status));
    j.page = page;
    xyList = j;
    xyHidden = false;
    saveXyCache();
  } catch (e) {
    xyList = { error: e.message };
  }
  render();
}

async function doXyOpen(idx) {
  const o = xyList && xyList.orders ? xyList.orders[idx] : null;
  if (!o) return;
  const text = `卖了 ${o.title} ${o.spec} 成交价${o.totalPrice} 包邮`;
  const hint = document.getElementById('orderHint');
  if (hint) hint.textContent = 'AI 解析中（几秒）…';
  try {
    const r = await fetch(`http://${location.hostname}:8091/parse`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || ('接口 ' + r.status));
    if (j.question) {
      if (hint) hint.textContent = 'AI 问：' + j.question;
      return;
    }
    if (!j.draft) throw new Error(j.error || '解析结果为空');
    j.draft.sourceText = text;
    const f = j.draft.fields || {};
    if (j.draft.type === 'sale') {
      f.price = o.totalPrice;
      f.note = `闲鱼单 ${o.orderId} · ${o.buyerNick}`;
    }
    draft = j.draft;
    xyList = null;
    render();
  } catch (e) {
    if (hint) hint.textContent = '解析失败：' + e.message;
  }
}

async function doConfirmOrder() {
  if (!draft) return;
  const d = draft;
  const f = d.fields;
  const hint = document.getElementById('orderHint');
  try {
    if (hint) hint.textContent = '入账中…';
    let created;
    if (d.type === 'sale') {
      const profit = r2(
        (Number(f.price) || 0) - (Number(f.shipping) || 0) - (Number(f.base_cost) || 0)
        - (f.mods || []).reduce((a, m) => a + (Number(m.cost) || 0), 0)
        + (f.recycling || []).reduce((a, m) => a + (Number(m.value) || 0), 0)
      );
      created = await api('/collections/sales/records', {
        method: 'POST',
        body: {
          date: f.date, type: f.type || '出货', model: f.model, config: f.config || '',
          price: Number(f.price) || 0, base_cost: Number(f.base_cost) || 0,
          mods: (f.mods || []).map((m) => ({ name: m.name, cost: Number(m.cost) || 0 })),
          recycling: (f.recycling || []).map((m) => ({ name: m.name, value: Number(m.value) || 0 })),
          shipping: Number(f.shipping) || 0, units: Number(f.units) || 1,
          note: f.note || '', profit, hist: false,
          stock_ref: /电源|适配器/.test(String(f.model || '') + String(f.config || ''))
            ? ''
            : String(f.stock_ref || '').replace(/[（(]整机[）)]/g, '').trim(),
        },
      });
    } else if (d.type === 'purchase') {
      created = await api('/collections/purchases/records', {
        method: 'POST',
        body: {
          batch: f.batch || '', date: f.date, model: f.model, spec: f.spec || '',
          qty: Number(f.qty) || 1, unit_price: Number(f.unit_price) || 0, hist: false, note: f.note || '',
        },
      });
    } else if (d.type === 'disassembly') {
      created = await api('/collections/disassembly/records', {
        method: 'POST',
        body: {
          date: f.date, model: f.model, spec: f.spec || '', qty: Number(f.qty) || 1,
          outputs: (f.outputs || []).map((o) => ({ name: o.name, qty: Number(o.qty) || 1, unit_value: Number(o.unit_value) || 0 })),
          note: f.note || '', hist: false,
        },
      });
    } else if (d.type === 'rework_create') {
      created = await api('/collections/rework/records', {
        method: 'POST',
        body: {
          date_order: f.date_order, customer: f.customer, model: f.model || '', target: f.target || '',
          status: '待寄出', fee: Number(f.fee) || 0, note: f.note || '',
        },
      });
    } else {
      throw new Error('未知草稿类型 ' + d.type);
    }
    cache = {};
    commitMsg = `#${created.id} ${d.summary}`;
    draft = null;
    render();
  } catch (e) {
    if (hint) hint.textContent = '入账失败：' + e.message;
  }
}

async function doReturn(id) {
  const s = (cache.sales || []).find((x) => x.id === id) || null;
  const label = s ? `${s.model} ${s.config || ''}（${s.date}）` : id;
  if (!window.confirm(`确认把这单退货作废？\n${label}\n金额归零；库存回补（原单关联了库存时）`)) return;
  const reason = window.prompt('退货原因（可留空）：', '') || '';
  try {
    const old = s || await api(`/collections/sales/records/${id}`);
    const note = (old.note ? old.note + '；' : '') + `已退货作废：${reason || '未填原因'}（${todayStr()}）`;
    await api(`/collections/sales/records/${id}`, {
      method: 'PATCH',
      body: { type: '退货', price: 0, base_cost: 0, mods: [], recycling: [], shipping: 0, profit: 0, stock_ref: '', note },
    });
    cache = {};
    render();
  } catch (e) {
    window.alert('退货失败：' + e.message);
  }
}

async function doAsk() {
  const el = document.getElementById('askText');
  const q = el ? el.value.trim() : '';
  if (!q) return;
  const box = document.getElementById('askAnswer');
  if (box) box.textContent = '查询中…';
  try {
    const r = await fetch(`http://${location.hostname}:8091/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: q }),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || ('接口 ' + r.status));
    if (box) box.textContent = j.answer || '（没有答案）';
  } catch (e) {
    if (box) box.textContent = '查询失败：' + e.message;
  }
}

function csvEsc(v) {
  const s = v === null || v === undefined ? '' : String(v);
  return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

function downloadCsv(filename, rows) {
  const csv = '\uFEFF' + rows.map((r) => r.map(csvEsc).join(',')).join('\r\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 1500);
}

async function doExport(kind) {
  if (kind === 'sales') {
    const sales = await load('sales', () => fetchAll('sales'));
    const rows = [['日期', '类型', '型号', '规格', '数量', '售价', '快递', '进价', '改装明细', '回收明细', '利润', '备注']];
    for (const s of [...sales].sort((a, b) => String(a.date || '').localeCompare(String(b.date || '')))) {
      const mods = (s.mods || []).map((x) => `${x.name}:${x.cost}`).join('；');
      const recs = (s.recycling || []).map((x) => `${x.name}:${x.value}`).join('；');
      rows.push([s.date, s.type || '出货', s.model || '', s.config || '', s.units || 1, s.price ?? '', s.shipping ?? '', s.base_cost ?? '', mods, recs, s.profit ?? '', s.note || '']);
    }
    downloadCsv(`出货明细_${todayStr()}.csv`, rows);
  } else {
    const pur = await load('purchases', () => fetchAll('purchases'));
    const rows = [['日期', '型号', '规格', '数量', '单价', '金额', '批次', '备注']];
    for (const p of [...pur].sort((a, b) => String(a.date || '').localeCompare(String(b.date || '')))) {
      rows.push([p.date, p.model || '', p.spec || '', p.qty ?? '', p.unit_price ?? '', r2((p.qty || 0) * (p.unit_price || 0)), p.batch || '', p.note || '']);
    }
    downloadCsv(`进货明细_${todayStr()}.csv`, rows);
  }
}

async function renderReport() {
  const sales = await load('sales', () => fetchAll('sales'));
  const real = sales.filter((s) => s.price > 0);
  const agg = (arr) => {
    const rev = r2(arr.reduce((a, s) => a + (s.price || 0), 0));
    const pf = r2(arr.reduce((a, s) => a + (s.profit || 0), 0));
    const rate = rev ? ((pf / rev) * 100).toFixed(1) + '%' : '-';
    return { n: arr.length, rev, pf, rate };
  };
  const today = todayStr();
  const month = today.slice(0, 7);
  const tot = agg(real);
  const mo = agg(real.filter((s) => String(s.date || '').startsWith(month)));
  const td = agg(real.filter((s) => s.date === today));
  const byDay = new Map();
  const byMonth = new Map();
  for (const s of real) {
    if (!byDay.has(s.date)) byDay.set(s.date, []);
    byDay.get(s.date).push(s);
    const k = String(s.date || '').slice(0, 7);
    if (!byMonth.has(k)) byMonth.set(k, []);
    byMonth.get(k).push(s);
  }
  const dayRows = [...byDay.entries()].sort((a, b) => b[0].localeCompare(a[0])).slice(0, 31)
    .map(([d, arr]) => { const g = agg(arr); return `<div class="row"><span class="row-name">${d}</span><span class="row-nums">${g.n}单 · ${money(g.rev)} · 利 ${money(g.pf)}</span></div>`; }).join('');
  const monRows = [...byMonth.entries()].sort((a, b) => b[0].localeCompare(a[0]))
    .map(([d, arr]) => { const g = agg(arr); return `<div class="row"><span class="row-name">${d}</span><span class="row-nums">${g.n}单 · ${money(g.rev)} · 利 ${money(g.pf)}</span></div>`; }).join('');
  const after = sales.filter((s) => s.type === '售后补发');
  const rets = sales.filter((s) => s.type === '退货');
  const kpi = (label, g) => `<div class="card"><div class="card-title">${label}</div><div class="big">${g.n} 单 · 销售额 ${money(g.rev)} · 利润 ${money(g.pf)} · 利润率 ${g.rate}</div></div>`;
  return `
    ${kpi('累计（有效单）', tot)}
    ${kpi('本月', mo)}
    ${kpi('今日', td)}
    <div class="card"><div class="card-title">每月</div>${monRows || '<div class="empty">（无）</div>'}</div>
    <div class="card"><div class="card-title">每日（最近31天）</div>${dayRows || '<div class="empty">（无）</div>'}</div>
    <div class="card"><div class="card-title">售后 / 退货</div>
      <div class="row"><span class="row-name">售后补发</span><span class="row-nums">${after.length} 笔 · 支出 ${money(-after.reduce((a, s) => a + (s.profit || 0), 0))}</span></div>
      <div class="row"><span class="row-name">退货作废</span><span class="row-nums">${rets.length} 笔（明细见「退货」页签）</span></div>
    </div>`;
}

async function renderSettings() {
  return `
    <div class="card">
      <div class="card-title">账号</div>
      <div class="kv"><span>已登录</span><b>${esc((me && me.email) || '')}</b></div>
      <button class="btn" data-action="logout">退出登录</button>
    </div>
    <div class="card">
      <div class="card-title">数据 / 后台</div>
      <div class="kv"><span>服务地址</span><b>${esc(location.origin)}</b></div>
      <div class="kv"><span>管理后台</span><b><a href="/_/" target="_blank">/_/</a></b></div>
      <div class="kv"><span>版本</span><b>v0.3（M3a）</b></div>
    </div>
    <div class="card">
      <div class="card-title">工具</div>
      <button class="btn" data-action="refresh">刷新全部缓存</button>
    </div>`;
}

/* ---------- 渲染框架 ---------- */
function syncTabs() {
  $$('#tabbar button').forEach((b) => b.classList.toggle('active', b.dataset.tab === ui.tab));
}

async function render() {
  const view = $('#view');
  syncTabs();
  if (!token) {
    view.innerHTML = loginView();
    return;
  }
  view.innerHTML = '<div class="empty" style="padding:24px 4px">加载中…</div>';
  try {
    let html;
    if (ui.tab === 'home') html = await renderHome();
    else if (ui.tab === 'stock') html = await renderStock();
    else if (ui.tab === 'docs') html = await renderDocs();
    else if (ui.tab === 'order') html = renderOrder();
    else if (ui.tab === 'report') html = await renderReport();
    else html = await renderSettings();
    view.innerHTML = html;
  } catch (e) {
    if (e && e.loginRequired) {
      view.innerHTML = loginView();
      return;
    }
    view.innerHTML = `<div class="card"><div class="card-title">出错了</div><div class="empty">${esc(e.message)}</div><div class="empty" style="margin-top:8px"><button class="btn" data-action="refresh">重试</button></div></div>`;
  }
}

document.addEventListener('click', (e) => {
  const tab = e.target.closest('#tabbar button');
  if (tab) {
    ui.tab = tab.dataset.tab;
    render();
    return;
  }
  const dt = e.target.closest('[data-docstab]');
  if (dt) {
    ui.docsTab = dt.dataset.docstab;
    render();
    return;
  }
  const ret = e.target.closest('[data-return]');
  if (ret) {
    doReturn(ret.dataset.return);
    return;
  }
  const xySt = e.target.closest('[data-xy-status]');
  if (xySt) {
    xyStatus = xySt.dataset.xyStatus;
    xyHidden = false;
    doPullXY(1);
    return;
  }
  const xyOpen = e.target.closest('[data-xy-open]');
  if (xyOpen) {
    doXyOpen(Number(xyOpen.dataset.xyOpen));
    return;
  }
  const act = e.target.closest('[data-action]');
  if (act) {
    const a = act.dataset.action;
    if (a === 'login') doLogin();
    else if (a === 'logout') {
      token = '';
      me = null;
      localStorage.removeItem('jxc_token');
      render();
    } else if (a === 'refresh') {
      cache = {};
      render();
    } else if (a === 'parse') doParse();
    else if (a === 'confirm-order') doConfirmOrder();
    else if (a === 'ask') doAsk();
    else if (a === 'export-sales') doExport('sales');
    else if (a === 'export-purchases') doExport('purchases');
    else if (a === 'pull-xy') doPullXY(1);
    else if (a === 'pull-xy-more') doPullXY(((xyList && xyList.page) || 1) + 1);
    else if (a === 'close-xy') {
      xyList = null;
      xyHidden = true;
      render();
    }
    else if (a === 'discard-order') {
      draft = null;
      render();
    } else if (a === 'new-order') {
      commitMsg = null;
      render();
    }
  }
});

function parsePairText(text, numKey) {
  return String(text || '')
    .split(/[；;，,、\n]/)
    .map((s) => s.trim())
    .filter(Boolean)
    .map((part) => {
      const m = part.match(/^(.+?)[:：]?\s*([\d.]*)$/);
      const name = ((m && m[1]) || part).trim();
      const num = Number((m && m[2]) || 0) || 0;
      return { name, [numKey]: num };
    });
}

document.addEventListener('input', (e) => {
  const el = e.target;
  const key = el && el.dataset && el.dataset.field;
  if (!key || !draft) return;
  if (el.dataset.array) {
    draft.fields[key] = parsePairText(el.value, el.dataset.array);
  } else {
    draft.fields[key] = el.type === 'number' ? Number(el.value) : el.value;
  }
  if (draft.type === 'sale') {
    const f = draft.fields;
    const profit = r2(
      (Number(f.price) || 0) - (Number(f.shipping) || 0) - (Number(f.base_cost) || 0)
      - (f.mods || []).reduce((a, m) => a + (Number(m.cost) || 0), 0)
      + (f.recycling || []).reduce((a, m) => a + (Number(m.value) || 0), 0)
    );
    const pv = document.getElementById('profitVal');
    if (pv) pv.textContent = money(profit);
  }
});

/* ---------- 启动 ---------- */
async function boot() {
  if (token) {
    try {
      const r = await api('/collections/users/auth-refresh', { method: 'POST' });
      token = r.token;
      localStorage.setItem('jxc_token', token);
      me = r.record;
    } catch (e) {
      if (!e.loginRequired) { /* 网络问题的场合保持现状 */ }
    }
  }
  checkHealth();
  setInterval(checkHealth, 15000);
  render();
}

boot();
