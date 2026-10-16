#!/usr/bin/env node
/**
 * 进销存 · 「一个框」AI 解析服务（本地 sidecar）
 *  POST /parse {text}  → {draft:{type,fields,summary}} | {question} | {error}
 *  GET  /health        → {ok:true}
 * DeepSeek key：环境变量 DEEPSEEK_API_KEY 或 ai-config.json 的 llm_key
 * 上下文：PocketBase 的商品/最近进价/价目表/快递规则（app 用户只读）
 * 日志：同目录 jxc-ai.log
 */
import http from 'node:http';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const LOG_FILE = path.join(__dirname, 'jxc-ai.log');
const PORT = 8091;
const CFG_FILE = path.join(__dirname, 'ai-config.json');
let fileCfg = {};
try { fileCfg = JSON.parse(fs.readFileSync(CFG_FILE, 'utf8')); } catch { /* 尚未创建 ai-config.json，用环境变量或默认值 */ }
const PB = process.env.JXC_PB_URL || fileCfg.pb_url || 'http://127.0.0.1:8090';
const PB_AUTH = {
  identity: process.env.JXC_PB_IDENTITY || fileCfg.pb_identity || '',
  password: process.env.JXC_PB_PASSWORD || fileCfg.pb_password || '',
};

const r2 = (v) => Math.round((Number(v) + Number.EPSILON) * 100) / 100;

function log(...a) {
  const line = `[${new Date().toISOString()}] ${a.join(' ')}`;
  try { fs.appendFileSync(LOG_FILE, line + '\n'); } catch { /* noop */ }
  console.log(line);
}

function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

let pbToken = null;
async function pbAuth() {
  if (pbToken) return;
  const r = await fetch(PB + '/api/collections/users/auth-with-password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(PB_AUTH),
  });
  const j = await r.json();
  if (!r.ok || !j.token) throw new Error('进销存账号登录失败');
  pbToken = j.token;
}

async function pb(method, p, body, retry = true) {
  const headers = { 'Content-Type': 'application/json' };
  if (pbToken) headers['Authorization'] = pbToken;
  const r = await fetch(PB + p, { method, headers, body: body ? JSON.stringify(body) : undefined });
  if (r.status === 401 && retry) {
    pbToken = null;
    await pbAuth();
    return pb(method, p, body, false);
  }
  const t = await r.text();
  const j = t ? JSON.parse(t) : null;
  if (r.status >= 400) throw new Error('PB ' + r.status + '：' + ((j && j.message) || t.slice(0, 120)));
  return j;
}

async function fetchAll(c) {
  const items = [];
  let page = 1;
  for (;;) {
    const j = await pb('GET', `/api/collections/${c}/records?perPage=500&page=${page}`);
    items.push(...((j && j.items) || []));
    if (page >= ((j && j.totalPages) || 1)) break;
    page++;
  }
  return items;
}

let ctxCache = { ts: 0, text: '' };
async function buildContext() {
  if (Date.now() - ctxCache.ts < 60000 && ctxCache.text) return ctxCache.text;
  await pbAuth();
  const [products, modPrices, partItems, settings, purchases, sales] = await Promise.all([
    fetchAll('products'), fetchAll('mod_prices'), fetchAll('part_items'), fetchAll('settings'), fetchAll('purchases'), fetchAll('sales'),
  ]);
  purchases.sort((a, b) => String(a.date).localeCompare(String(b.date)));
  const last = new Map();
  for (const x of purchases) last.set(`${x.model}|${x.spec}`, x.unit_price);
  const L = ['【商品与最近进价】'];
  for (const p of products.filter((x) => x.kind !== '服务')) {
    const key = `${p.model}${p.spec ? '|' + p.spec : ''}`;
    const lp = last.get(key);
    L.push(`${key}${p.kind ? ' [' + p.kind + ']' : ''}${lp != null ? ' 最近进价' + lp : ''}`);
  }
  L.push('', '【改装价目】（名称 价格 类型）');
  for (const m of modPrices) L.push(`${m.name} ${m.price} ${m.kind || ''}`);
  L.push('', '【拆机件回收价】');
  for (const m of partItems) L.push(`${m.name} ${m.value}`);
  const ship = ((settings.find((x) => x.key === 'shipping_rules') || {}).value) || {};
  L.push('', `【快递】普快 ${ship['普快'] ?? 4} / 顺丰 ${ship['顺丰'] ?? 14} / 自提 0`);
  sales.sort((a, b) => String(b.date).localeCompare(String(a.date)));
  const seenCfg = new Set();
  const samples = [];
  for (const s of sales) {
    if (samples.length >= 18) break;
    if (!(s.price > 0) || !s.config || seenCfg.has(s.config)) continue;
    seenCfg.add(s.config);
    const sm = (s.mods || []).map((m) => `${m.name}${m.cost}`).join(',');
    const sr = (s.recycling || []).map((m) => `${m.name}${m.value}`).join(',');
    samples.push(`${s.model} “${s.config}” → base_cost=${s.base_cost}${sm ? '；mods [' + sm + ']' : ''}${sr ? '；recycling [' + sr + ']' : ''}`);
  }
  if (samples.length) {
    L.push('', '【常见说法 → 标准配置与明细（照这个学）】');
    L.push(...samples);
  }
  ctxCache = { ts: Date.now(), text: L.join('\n') };
  return ctxCache.text;
}

function loadKey() {
  if (process.env.DEEPSEEK_API_KEY) return process.env.DEEPSEEK_API_KEY;
  const k = (fileCfg && fileCfg.llm_key) || '';
  if (!k) throw new Error('未配置 DeepSeek key：请写 ai-config.json 的 llm_key 或设环境变量 DEEPSEEK_API_KEY');
  return k;
}

async function llm(system, user, jsonMode = true) {
  const payload = {
    model: 'deepseek-chat',
    temperature: 0.1,
    max_tokens: 1200,
    messages: [
      { role: 'system', content: system },
      { role: 'user', content: user },
    ],
  };
  if (jsonMode) payload.response_format = { type: 'json_object' };
  const r = await fetch('https://api.deepseek.com/chat/completions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + loadKey() },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(60000),
  });
  if (!r.ok) throw new Error('模型接口 ' + r.status + '：' + (await r.text()).slice(0, 200));
  const j = await r.json();
  return j.choices[0].message.content;
}

function stripFences(s) {
  return String(s).replace(/^\s*```(?:json)?/i, '').replace(/```\s*$/, '').trim();
}

async function parseText(text) {
  const ctx = await buildContext();
  const today = todayStr();
  const system = `你是进销存的录单助手。把用户的一句话解析成一笔单据 JSON 草稿。今天日期：${today}

用户业务：二手数码（路由器为主）。单据分：出货 sale / 进货 purchase / 拆机 disassembly / 寄改工单 rework_create。
特殊：寄改=客户寄机器来改装（进价填0，只填改装/回收，stock_ref 留空）；售后补发=售价0、成本放进 mods；多台一单=units 填台数；以物换物抵入用 purchase 记。

${ctx}

输出要求：只输出一个 JSON 对象、不要其他文字。
- 能解析：{"type":"sale|purchase|disassembly|rework_create","fields":{...}}
  sale.fields: {"date":"YYYY-MM-DD","type":"出货|寄改|售后补发","model":"","config":"","price":0,"base_cost":0,"mods":[{"name":"","cost":0}],"recycling":[{"name":"","value":0}],"shipping":4,"units":1,"stock_ref":"型号|规格","note":""}
  purchase.fields: {"date":"YYYY-MM-DD","model":"","spec":"","qty":0,"unit_price":0,"batch":"","note":""}
  disassembly.fields: {"date":"YYYY-MM-DD","model":"","spec":"","qty":0,"outputs":[{"name":"","qty":0,"unit_value":0}],"note":""}
  rework_create.fields: {"date_order":"YYYY-MM-DD","customer":"","model":"","target":"","fee":0,"note":""}
- 关键信息缺 / 拿不准 / 一句话里有多笔：{"question":"一句简短追问"}

规则：快递 包邮或普快=4、顺丰=14、自提=0、没提=4；进价没说就用【商品与最近进价】里对应型号规格的最近进价（没记录填0）；配置写法与改装/回收明细优先照【常见说法→标准配置与明细】样例（用【价目表】的标准名称与价格）；stock_ref 只写「型号|规格」本身、不带任何括号/方括号后缀（如 360V6|原机；寄改/电源/售后填 ""）；没说数量=1。`;

  const content = stripFences(await llm(system, text));
  let obj;
  try {
    obj = JSON.parse(content);
  } catch {
    return { error: '模型输出不是 JSON', raw: content.slice(0, 300) };
  }
  if (obj.question) return { question: String(obj.question) };
  const type = obj.type;
  const f = obj.fields || {};
  if (type === 'sale') {
    if (!f.model) return { question: '卖的哪个型号？' };
    const mods = (f.mods || []).map((m) => ({ name: String(m.name || ''), cost: Number(m.cost) || 0 }));
    const recs = (f.recycling || []).map((m) => ({ name: String(m.name || ''), value: Number(m.value) || 0 }));
    const price = Number(f.price) || 0;
    const base = Number(f.base_cost) || 0;
    const ship = Number(f.shipping ?? 4) || 0;
    const profit = r2(price - ship - base - mods.reduce((a, m) => a + m.cost, 0) + recs.reduce((a, m) => a + m.value, 0));
    const fields = {
      date: f.date || today, type: f.type || '出货', model: String(f.model), config: f.config || '',
      price, base_cost: base, mods, recycling: recs, shipping: ship,
      units: Number(f.units) || 1, stock_ref: f.stock_ref || '', note: f.note || '', profit,
    };
    return { draft: { type, fields, summary: `${fields.type} · ${fields.model} ${fields.config} · 售价${price} 利润${profit}${fields.stock_ref ? ' · 扣 ' + fields.stock_ref : ''}` } };
  }
  if (type === 'purchase') {
    if (!f.model) return { question: '进的哪个型号？' };
    const fields = {
      date: f.date || today, model: String(f.model), spec: f.spec || '', qty: Number(f.qty) || 1,
      unit_price: Number(f.unit_price) || 0, batch: f.batch || '', note: f.note || '',
    };
    return { draft: { type, fields, summary: `进货 · ${fields.model}|${fields.spec} x${fields.qty} @${fields.unit_price}` } };
  }
  if (type === 'disassembly') {
    if (!f.model) return { question: '拆的哪个型号？' };
    const outputs = (f.outputs || []).map((o) => ({ name: String(o.name || ''), qty: Number(o.qty) || 1, unit_value: Number(o.unit_value) || 0 }));
    const fields = { date: f.date || today, model: String(f.model), spec: f.spec || '', qty: Number(f.qty) || 1, outputs, note: f.note || '' };
    return { draft: { type, fields, summary: `拆机 · ${fields.model}|${fields.spec} x${fields.qty} → ${outputs.map((o) => o.name + 'x' + o.qty).join('、') || '无产出'}` } };
  }
  if (type === 'rework_create') {
    if (!f.customer) return { question: '谁的机器？客户怎么称呼？' };
    const fields = {
      date_order: f.date_order || today, customer: String(f.customer), model: f.model || '',
      target: f.target || '', fee: Number(f.fee) || 0, note: f.note || '',
    };
    return { draft: { type, fields, summary: `寄改工单 · ${fields.customer} ${fields.model} ${fields.target}` } };
  }
  return { question: '这是哪类单据？卖货、进货、拆机还是寄改？' };
}

// 闲鱼订单：统一从闲鱼助手面板取（令牌握手自愈逻辑在 Python 侧单点维护，不再自建 mtop 请求）
async function xyOrders(page, size, status) {
  const url = `http://127.0.0.1:8767/api/orders?page=${encodeURIComponent(page)}&size=${encodeURIComponent(size)}&status=${encodeURIComponent(status)}`;
  const r = await fetch(url, { signal: AbortSignal.timeout(60000) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok || j.ok === false || j.error) {
    throw new Error('闲鱼接口：' + String((j && j.error) || r.status).slice(0, 120));
  }
  return { total: j.total || 0, nextPage: j.nextPage === true, orders: j.orders || [] };
}

let snapCache = { ts: 0, text: '' };
async function buildSnapshot() {
  if (Date.now() - snapCache.ts < 60000 && snapCache.text) return snapCache.text;
  await pbAuth();
  const [adjs, purchases, sales, dis, parts, rw] = await Promise.all([
    fetchAll('adjustments'), fetchAll('purchases'), fetchAll('sales'),
    fetchAll('disassembly'), fetchAll('part_items'), fetchAll('rework'),
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
  const mach = [];
  const pList = [];
  for (const [k, v] of [...m.entries()].sort()) {
    if (r2(v) === 0) continue;
    if (k.startsWith('M:')) mach.push(`${k.slice(2)}: ${r2(v)}`);
    else pList.push(`${k.slice(2)}: ${r2(v)}`);
  }
  const real = sales.filter((s) => s.price > 0);
  const agg = (arr) => {
    const rev = r2(arr.reduce((a, s) => a + (s.price || 0), 0));
    const pf = r2(arr.reduce((a, s) => a + (s.profit || 0), 0));
    return `单 ${arr.length} · 销售额 ${rev} · 利润 ${pf}`;
  };
  const today = todayStr();
  const month = today.slice(0, 7);
  const byDay = new Map();
  const byMonth = new Map();
  for (const s of real) {
    if (!byDay.has(s.date)) byDay.set(s.date, []);
    byDay.get(s.date).push(s);
    const k = String(s.date || '').slice(0, 7);
    if (!byMonth.has(k)) byMonth.set(k, []);
    byMonth.get(k).push(s);
  }
  const dayLines = [...byDay.entries()].sort((a, b) => b[0].localeCompare(a[0])).slice(0, 31).map(([d, arr]) => `${d}: ${agg(arr)}`);
  const monthLines = [...byMonth.entries()].sort((a, b) => b[0].localeCompare(a[0])).map(([k, arr]) => `${k}: ${agg(arr)}`);
  const openRw = rw.filter((r) => !['完成', '取消'].includes(r.status));
  const after = sales.filter((s) => s.type === '售后补发');
  const rets = sales.filter((s) => s.type === '退货');
  const L = [];
  L.push(`【累计（有效单）】${agg(real)}`);
  L.push(`【今日 ${today}】${agg(real.filter((s) => s.date === today))}`);
  L.push(`【本月 ${month}】${agg(real.filter((s) => String(s.date || '').startsWith(month)))}`);
  L.push('', '【每月】');
  L.push(...monthLines);
  L.push('', '【最近每日（最多31天）】');
  L.push(...dayLines);
  L.push('', '【当前库存·整机】');
  L.push(...(mach.length ? mach : ['（无）']));
  L.push('【当前库存·拆机件】');
  L.push(...(pList.length ? pList : ['（无）']));
  L.push('', `【在办寄改】${openRw.length} 单` + (openRw.length ? '：' + openRw.map((r) => `${r.customer}(${r.model || ''} ${r.status})`).join('；') : ''));
  L.push(`【售后补发】${after.length} 笔，支出合计 ${r2(-after.reduce((a, s) => a + (s.profit || 0), 0))} 元`);
  L.push(`【退货作废】${rets.length} 笔`);
  L.push('', '【最近订单明细（最多40笔，日期 型号|配置 价/快递/进价/利 备注）】');
  const recentList = [...sales].sort((a, b) => String(b.date || '').localeCompare(String(a.date || ''))).slice(0, 40);
  for (const s of recentList) {
    L.push(`${s.date} ${s.type || '出货'} ${s.model || ''}|${s.config || ''} 价${s.price} 快递${s.shipping ?? 0} 进${s.base_cost ?? 0} 利${s.profit}${s.note ? ' · ' + String(s.note).slice(0, 40) : ''}`);
  }
  snapCache = { ts: Date.now(), text: L.join('\n') };
  return snapCache.text;
}

async function toolAsk(question) {
  const snap = await buildSnapshot();
  const system = `你是进销存的问答助手。只根据【数据快照】回答；数字必须来自快照，快照里没有的就回“账里没有这项”；中文回答、一两句、口语化、不要 markdown。\n\n【数据快照】\n${snap}`;
  return (await llm(system, question, false)).trim();
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let b = '';
    req.on('data', (c) => {
      b += c;
      if (b.length > 100000) {
        reject(new Error('body 太大'));
        req.destroy();
      }
    });
    req.on('end', () => {
      try { resolve(JSON.parse(b || '{}')); } catch { reject(new Error('body 不是 JSON')); }
    });
    req.on('error', reject);
  });
}

const server = http.createServer(async (req, res) => {
  const cors = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
  };
  const sendJson = (code, obj) => {
    res.writeHead(code, { ...cors, 'Content-Type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify(obj));
  };
  if (req.method === 'OPTIONS') {
    res.writeHead(204, cors);
    res.end();
    return;
  }
  if (req.method === 'GET' && req.url.startsWith('/health')) return sendJson(200, { ok: true });
  if (req.method === 'POST' && req.url.startsWith('/parse')) {
    try {
      const body = await readBody(req);
      const text = String(body.text || '').trim();
      if (!text) return sendJson(400, { error: 'text 为空' });
      const out = await parseText(text);
      log('parse:', text.slice(0, 50), '→', out.draft ? out.draft.summary : (out.question || out.error || '?'));
      return sendJson(200, out);
    } catch (e) {
      log('parse-error:', (e && e.message) || String(e));
      return sendJson(500, { error: (e && e.message) || String(e) });
    }
  }
  if (req.method === 'POST' && req.url.startsWith('/ask')) {
    try {
      const body = await readBody(req);
      const q = String(body.question || '').trim();
      if (!q) return sendJson(400, { error: 'question 为空' });
      const answer = await toolAsk(q);
      log('ask:', q.slice(0, 50), '→', answer.slice(0, 60));
      return sendJson(200, { answer });
    } catch (e) {
      log('ask-error:', (e && e.message) || String(e));
      return sendJson(500, { error: (e && e.message) || String(e) });
    }
  }
  if (req.method === 'GET' && req.url.startsWith('/xy-orders')) {
    try {
      const u = new URL(req.url, 'http://x');
      const page = Math.max(1, Number(u.searchParams.get('page') || 1));
      const size = Math.min(50, Math.max(1, Number(u.searchParams.get('size') || 20)));
      const status = String(u.searchParams.get('status') || 'ALL');
      const out = await xyOrders(page, size, status);
      log('xy-orders:', page, size, '->', out.orders.length, '/', out.total);
      return sendJson(200, out);
    } catch (e) {
      log('xy-orders-error:', (e && e.message) || String(e));
      return sendJson(500, { error: (e && e.message) || String(e) });
    }
  }
  if (req.method === 'GET' && req.url.startsWith('/dump.json')) {
    try {
      await pbAuth();
      const names = ['products', 'purchases', 'sales', 'disassembly', 'adjustments', 'part_items', 'mod_prices', 'rework', 'settings'];
      const out = { generated_at: new Date().toISOString(), source: 'jxc-ai /dump.json' };
      for (const n of names) out[n] = await fetchAll(n);
      log('dump.json served');
      return sendJson(200, out);
    } catch (e) {
      log('dump-error:', (e && e.message) || String(e));
      return sendJson(500, { error: (e && e.message) || String(e) });
    }
  }
  res.writeHead(404, cors);
  res.end('not found');
});

server.listen(PORT, '0.0.0.0', () => log('jxc-ai listening on :' + PORT));
