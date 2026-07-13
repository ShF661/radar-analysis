// ===== 金狗雷达 GMGN 特征分析 · 前端（桶为中心，全前端计算）=====
// 数据源：/api/tokens（全量行）、/api/defaults（阈值+特征名）。
// 可信过滤 / 分桶 / 特征派生 / 占比基准lift / 联动筛选 全部在浏览器完成。

const TRUST_MAX_DELAY_MIN = 5;   // 采集延迟 ≤ 5 分钟视为“第一时间采集”
const SMALL_SAMPLE = 10;         // 桶内 < 10 个 → 样本太少警告

// 维度：全部 / 最高涨幅 / 最小涨幅（同一最高涨幅值，看小头）/ 最大跌幅
const DIMS = {
  peak_high: {
    label: '最高涨幅', column: 'peak_gain_pct', sortDir: 'desc',
    buckets: [
      { label: '<50%', min: null, max: 50 },
      { label: '50–100%', min: 50, max: 100 },
      { label: '>100%', min: 100, max: null },
    ],
    defaultBucket: '>100%',
  },
  peak_low: {
    label: '最小涨幅', column: 'peak_gain_pct', sortDir: 'asc',
    buckets: [
      { label: '<10%', min: null, max: 10 },
      { label: '10–30%', min: 10, max: 30 },
      { label: '30–50%', min: 30, max: 50 },
      { label: '≥50%', min: 50, max: null },
    ],
    defaultBucket: '<10%',
  },
  drop: {
    label: '最大跌幅', column: 'max_drop_pct', sortDir: 'desc',
    buckets: [
      { label: '跌<30%', min: 0, max: 30 },
      { label: '跌30–50%', min: 30, max: 50 },
      { label: '跌50–80%', min: 50, max: 80 },
      { label: '跌>80%', min: 80, max: null },
    ],
    defaultBucket: '跌>80%',
  },
};

// 特征派生逻辑（镜像后端 app/features.py；阈值来自 /api/defaults）
const FEATURE_DEFS = [
  { key: 'smart_money_zero', fn: (r) => r.smart_wallets == null ? null : r.smart_wallets === 0 },
  { key: 'kol_zero', fn: (r) => r.kol_wallets == null ? null : r.kol_wallets === 0 },
  { key: 'high_bundler', fn: (r, t) => gt(r.bundler_rate, t.high_bundler) },
  { key: 'high_fresh', fn: (r, t) => gt(r.fresh_wallet_rate, t.high_fresh) },
  { key: 'high_rat', fn: (r, t) => gt(r.rat_rate, t.high_rat) },
  { key: 'high_top10', fn: (r, t) => gt(r.top10_rate, t.high_top10) },
  { key: 'high_dev', fn: (r, t) => gt(r.dev_hold_rate, t.high_dev) },
  { key: 'high_bot', fn: (r, t) => gt(r.bot_degen_rate, t.high_bot) },
  { key: 'low_turnover', fn: (r, t) => lt(r.turnover, t.low_turnover) },
  { key: 'low_liquidity', fn: (r, t) => lt(r.liquidity, t.low_liquidity) },
  { key: 'high_rug', fn: (r, t) => gt(r.rug_ratio, t.high_rug) },
  { key: 'high_entrapment', fn: (r, t) => gt(r.entrapment_rate, t.high_entrapment) },
  { key: 'low_holders', fn: (r, t) => lt(r.holder_count, t.low_holders) },
  { key: 'security_risk', fn: (r) => securityFlag(r) },
];
const gt = (v, t) => v == null ? null : v > t;
const lt = (v, t) => v == null ? null : v < t;

// 安全风险：只讲“哪里有风险”，无风险不展开
function securityRisks(r) {
  const out = [];
  const isEvm = r.chain && r.chain !== 'sol';   // 开源/弃权是 EVM 概念，SOL 不适用
  // SOL 专属：铸币权 / 冻结权
  if (r.chain === 'sol' && r.renounced_mint === 'no') out.push('铸币权未放弃（开发者可增发砸盘）');
  if (r.chain === 'sol' && r.renounced_freeze === 'no') out.push('冻结权未放弃（开发者可冻结你的钱包）');
  // 通用
  if (r.is_honeypot === 'yes') out.push('蜜罐（能买不能卖）');
  if ((r.buy_tax || 0) > 0) out.push('买税 ' + Math.round(r.buy_tax * 100) + '%');
  if ((r.sell_tax || 0) > 0) out.push('卖税 ' + Math.round(r.sell_tax * 100) + '%');
  if (r.rug_ratio != null && r.rug_ratio > 0.3) out.push('rug风险高 (' + r.rug_ratio + ')');
  // EVM 专属：合约弃权 / 开源验证
  if (isEvm && r.owner_renounced === 'no') out.push('合约未弃权');
  if (isEvm && r.open_source === 'no') out.push('合约未开源');
  return out;
}
function securityFlag(r) {
  if (securityRisks(r).length) return true;          // 有风险
  const hasData = [r.is_honeypot, r.open_source, r.owner_renounced, r.buy_tax, r.sell_tax, r.rug_ratio, r.renounced_mint, r.renounced_freeze].some((v) => v != null);
  return hasData ? false : null;                     // 有数据但无风险=false；完全无数据=null(不统计)
}
const LOCAL_LABELS = { security_risk: '有安全风险' };
const labelOf = (k) => S.featureLabels[k] || LOCAL_LABELS[k] || k;

// B 表列：身份/结果 + 钱包构成 + 规模集中度（安全类只在详情弹窗）
const COLUMNS = [
  { key: 'symbol', label: '符号', type: 'sym', first: true },
  { key: 'grade', label: '评级', type: 'grade' },
  { key: 'base_market_cap', label: '市值 推荐→最高', type: 'mcap' },
  { key: 'peak_gain_pct', label: '最高涨幅', type: 'gain' },
  { key: 'max_drop_pct', label: '最大跌幅', type: 'drop' },
  { key: 'smart_wallets', label: '聪明钱', type: 'int' },
  { key: 'kol_wallets', label: 'KOL', type: 'int' },
  { key: 'bundler_rate', label: '集群%', type: 'rate' },
  { key: 'fresh_wallet_rate', label: '新钱包%', type: 'rate' },
  { key: 'rat_rate', label: '老鼠%', type: 'rate' },
  { key: 'bot_degen_rate', label: '机器人%', type: 'rate' },
  { key: 'holder_count', label: '持有人', type: 'int' },
  { key: 'turnover', label: '换手率', type: 'turn' },
  { key: 'avg_holding_usd', label: '人均持币', type: 'usd' },
  { key: 'top10_rate', label: 'TOP10%', type: 'rate' },
  { key: 'dev_hold_rate', label: 'DEV%', type: 'rate' },
  { key: 'pushed_at', label: '推荐时间', type: 'time' },
];

// ===== 状态 =====
const S = {
  dimKey: 'all',
  bucketLabel: null,
  trustOnly: false,
  thresholds: {},
  defaultThresholds: {},
  featureLabels: {},
  tokens: [],
  activeFeature: null,
  sortCol: null,
  sortDir: 'desc',
  search: '',
};

// ===== 工具 =====
const $ = (id) => document.getElementById(id);
function delayMin(r) {
  if (!r.pushed_at || !r.created_at) return null;
  const d = (new Date(r.created_at) - new Date(r.pushed_at)) / 60000;
  return isNaN(d) ? null : d;
}
const trustworthy = (r) => { const d = delayMin(r); return d != null && d <= TRUST_MAX_DELAY_MIN; };
function assignBucket(v, buckets) {
  if (v == null) return null;
  for (const b of buckets) {
    if ((b.min == null || v >= b.min) && (b.max == null || v < b.max)) return b.label;
  }
  return null;
}
function deriveFeatures(r) {
  const out = {};
  for (const f of FEATURE_DEFS) out[f.key] = f.fn(r, S.thresholds);
  return out;
}
function rate(rows, key, feats) {
  const vals = rows.map((r) => feats[r.task_id][key]).filter((v) => v !== null && v !== undefined);
  if (!vals.length) return { rate: null, hits: 0, n: 0 };
  const hits = vals.filter((v) => v).length;
  return { rate: hits / vals.length, hits, n: vals.length };
}

// 格式化
const fGain = (v) => v == null ? '—' : (v >= 0 ? '+' : '') + Math.round(v) + '%';
const fDrop = (v) => v == null ? '—' : (v <= 0 ? '0%' : '-' + Math.round(v) + '%');
const fRate = (v) => v == null ? '—' : Math.round(v * 100) + '%';
const fInt = (v) => v == null ? '—' : Math.round(v).toLocaleString();
const fTurn = (v) => v == null ? '—' : Number(v).toFixed(2);
const fUsd = (v) => v == null ? '—' : '$' + Math.round(v).toLocaleString();
function fmtTime(v) {
  if (!v) return '—';
  const d = new Date(v);
  if (isNaN(d)) return '—';
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
function fAbbr(v) {
  if (v == null) return '—';
  if (v >= 1e6) return '$' + (v / 1e6).toFixed(1) + 'M';
  if (v >= 1e3) return '$' + (v / 1e3).toFixed(1) + 'K';
  return '$' + Math.round(v);
}
function gmgnUrl(r) {
  return (r.address && r.chain) ? `https://gmgn.ai/${r.chain}/token/${r.address}` : '';
}
function symCell(r) {
  const addr = r.address || '';
  const short = addr ? addr.slice(0, 4) + '…' + addr.slice(-4) : '?';
  const url = gmgnUrl(r);
  return `<div class="symcell">
    <div class="symname">${esc(r.symbol || short)}</div>
    <div class="symaddr">
      <span class="addr" data-copy="${esc(addr)}" title="点击复制合约">${esc(short)}</span>
      <span class="ico" data-copy="${esc(addr)}" title="复制合约">📋</span>
      ${url ? `<a class="ico" href="${esc(url)}" target="_blank" rel="noopener" title="在GMGN看K线">↗</a>` : ''}
    </div>
  </div>`;
}
function fallbackCopy(text, done) {
  try { const ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta); done(); } catch (e) {}
}
function toast(msg) {
  let t = document.getElementById('toast');
  if (!t) { t = document.createElement('div'); t.id = 'toast'; document.body.appendChild(t); }
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove('show'), 1800);
}
function copyText(text) {
  const done = () => toast('已复制合约地址');
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(text, done));
  else fallbackCopy(text, done);
}
function cellHtml(r, col) {
  const v = r[col.key];
  switch (col.type) {
    case 'sym': return symCell(r);
    case 'grade': return v ? `<span class="grade">${esc(v)}</span>` : '—';
    case 'mcap': return `${fAbbr(r.base_market_cap)} → ${fAbbr(r.peak_market_cap)}`;
    case 'time': return fmtTime(v);
    case 'gain': return `<span class="${v > 0 ? 'pos' : v < 0 ? 'neg' : ''}">${fGain(v)}</span>`;
    case 'drop': return `<span class="${v > 0 ? 'neg' : ''}">${fDrop(v)}</span>`;
    case 'rate': return fRate(v);
    case 'int': return fInt(v);
    case 'turn': return fTurn(v);
    case 'usd': return fUsd(v);
    case 'delay': {
      const d = delayMin(r);
      if (d == null) return '<span class="badge stale">?</span>';
      if (d <= TRUST_MAX_DELAY_MIN) return '<span class="badge ok">✓</span>';
      return `<span class="badge stale" title="推送后约 ${fmtDelay(d)} 才采集">${fmtDelay(d)}</span>`;
    }
    default: return v == null ? '—' : esc(String(v));
  }
}
function fmtDelay(min) {
  if (min < 60) return Math.round(min) + '分';
  if (min < 1440) return Math.round(min / 60) + '时';
  return Math.round(min / 1440) + '天';
}
function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

// ===== 数据加载 =====
async function loadAll() {
  const d = await (await fetch('/api/defaults')).json();
  S.featureLabels = d.feature_labels || {};
  S.defaultThresholds = { ...d.thresholds };
  if (!Object.keys(S.thresholds).length) S.thresholds = { ...d.thresholds };
  S.tokens = await (await fetch('/api/tokens')).json();
}

function workingSet() {
  return S.trustOnly ? S.tokens.filter(trustworthy) : S.tokens.slice();
}

// ===== 维度按钮（含“全部”）=====
function renderDimSeg() {
  const items = [['all', '全部'], ...Object.entries(DIMS).map(([k, d]) => [k, d.label])];
  $('dim-seg').innerHTML = items.map(([k, label]) =>
    `<button data-k="${k}" class="${k === S.dimKey ? 'active' : ''}">${label}</button>`).join('');
  $('dim-seg').querySelectorAll('button').forEach((b) =>
    b.onclick = () => { S.dimKey = b.dataset.k; S.bucketLabel = null; S.activeFeature = null; S.sortCol = null; S.search = ''; $('search').value = ''; render(); });
}

function renderThresholds() {
  const grid = $('thr-grid');
  grid.innerHTML = Object.entries(S.thresholds).map(([k, v]) =>
    `<label>${esc(S.featureLabels[k] || k)}<input type="number" step="any" data-k="${k}" value="${v}"></label>`).join('');
  grid.querySelectorAll('input').forEach((i) =>
    i.onchange = () => { const n = parseFloat(i.value); if (!isNaN(n)) { S.thresholds[i.dataset.k] = n; render(); } });
}

// ===== 代币表（全部 / 桶内 共用）=====
function paintTable(rows, feats) {
  let list = rows.slice();
  const tip = $('feat-filter-tip');
  if (feats && S.activeFeature) {
    list = list.filter((r) => feats[r.task_id][S.activeFeature] === true);
    tip.classList.remove('hidden');
    tip.innerHTML = `已只看命中特征「${esc(labelOf(S.activeFeature))}」的 ${list.length} 个币 <button id="clr-feat">✕ 清除</button>`;
    $('clr-feat').onclick = () => { S.activeFeature = null; render(); };
  } else tip.classList.add('hidden');

  if (!S.sortCol) { S.sortCol = 'peak_gain_pct'; S.sortDir = 'desc'; }
  list.sort((a, b) => {
    const x = a[S.sortCol], y = b[S.sortCol];
    if (x == null && y == null) return 0;
    if (x == null) return 1; if (y == null) return -1;
    if (typeof x === 'string') return S.sortDir === 'asc' ? String(x).localeCompare(y) : String(y).localeCompare(x);
    return S.sortDir === 'asc' ? x - y : y - x;
  });

  const head = COLUMNS.map((c) => {
    const arrow = c.key === S.sortCol ? (S.sortDir === 'asc' ? ' ▲' : ' ▼') : '';
    return `<th class="${c.first ? 'first' : ''}" data-c="${c.key}">${esc(c.label)}${arrow}</th>`;
  }).join('');
  const body = list.map((r, i) =>
    `<tr data-i="${i}">` + COLUMNS.map((c) => `<td class="${c.first ? 'first' : ''}">${cellHtml(r, c)}</td>`).join('') + `</tr>`).join('');
  $('table').innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
  $('table').querySelectorAll('th').forEach((th) =>
    th.onclick = () => {
      const c = th.dataset.c;
      if (S.sortCol === c) S.sortDir = S.sortDir === 'asc' ? 'desc' : 'asc';
      else { S.sortCol = c; S.sortDir = 'desc'; }
      render();
    });
  const tbody = $('table').querySelector('tbody');
  if (tbody) tbody.onclick = (e) => {
    const copyEl = e.target.closest('[data-copy]');
    if (copyEl) { e.stopPropagation(); copyText(copyEl.dataset.copy, copyEl); return; }
    if (e.target.closest('a')) return; // GMGN 链接，默认新标签打开
    const tr = e.target.closest('tr');
    if (tr && tr.dataset.i != null) showDetail(list[+tr.dataset.i]);
  };
}

// ===== 渲染 =====
function render() {
  $('dim-seg').querySelectorAll('button').forEach((b) => b.classList.toggle('active', b.dataset.k === S.dimKey));
  const ws = workingSet();
  const total = S.tokens.length;
  const trustCount = S.tokens.filter(trustworthy).length;
  $('sample-info').textContent = S.trustOnly
    ? `基于 ${trustCount} 个可信样本（共 ${total} 条，已排除 ${total - trustCount} 条迟采/存量）· 每25秒自动刷新`
    : `显示全部 ${total} 条（含存量/迟采，仅供体验界面，入场指标无参考价值）· 每25秒自动刷新`;

  // 搜索：按合约/符号定位单个币（忽略维度，但遵循“只看可信样本”勾选）
  const q = S.search.trim().toLowerCase();
  if (q) {
    $('empty').classList.add('hidden');
    $('sec-buckets').classList.add('hidden');
    $('sec-features').classList.add('hidden');
    $('thr-box').classList.add('hidden');
    const list = ws.filter((r) => (r.symbol || '').toLowerCase().includes(q) || (r.address || '').toLowerCase().includes(q));
    const scopeNote = S.trustOnly ? '仅在可信样本中（延迟&lt;5分）' : '跨全部数据';
    $('tbl-title').innerHTML = `搜索 “${esc(S.search.trim())}”：${list.length} 个 <span class="muted sub">（${scopeNote}；点行看详情）</span>`;
    paintTable(list, null);
    return;
  }

  // 空态
  if (!ws.length) {
    ['bucket-seg', 'bucket-head', 'features', 'table'].forEach((id) => $(id).innerHTML = '');
    $('small-warn').classList.add('hidden');
    $('empty').classList.remove('hidden');
    $('empty').innerHTML = S.trustOnly
      ? `暂无“第一时间采集”的可信样本（当前数据均为存量回填，已被排除）。<br>真实可信数据需让采集器持续挂着、在新币推送几秒内抓取。<br><button class="ghost" id="see-all">先查看全部数据（仅体验界面）</button>`
      : `数据库暂无代币。`;
    const sa = $('see-all'); if (sa) sa.onclick = () => { $('trust').checked = false; S.trustOnly = false; render(); };
    return;
  }
  $('empty').classList.add('hidden');

  // 「全部」：不分桶，平铺所有币 + 全样本特征占比概览
  if (S.dimKey === 'all') {
    $('sec-buckets').classList.add('hidden');
    $('sec-features').classList.remove('hidden');
    $('thr-box').classList.remove('hidden');

    // 全样本特征派生
    const feats = {};
    for (const r of ws) feats[r.task_id] = deriveFeatures(r);

    // A. 全样本特征占比（无桶、无基准/lift，按占比从高到低）
    $('feat-title').innerHTML = `A · 全部样本的特征占比<span class="muted sub"> （占比从高到低；点一行可在下方只看命中该特征的币）</span>`;
    const stats = FEATURE_DEFS.map((f) => ({ key: f.key, label: labelOf(f.key), ...rate(ws, f.key, feats) }))
      .filter((s) => s.rate != null).sort((a, b) => b.rate - a.rate);
    $('features').innerHTML = stats.map((s) => {
      const sel = s.key === S.activeFeature ? ' sel' : '';
      return `<div class="feat flat${sel}" data-f="${s.key}">
        <span class="fname">${esc(s.label)}</span>
        <span class="bar"><span class="val" style="width:${s.rate * 100}%"></span></span>
        <span class="nums">${Math.round(s.rate * 100)}% (${s.hits}/${s.n})</span>
      </div>`;
    }).join('');
    $('features').querySelectorAll('.feat').forEach((el) =>
      el.onclick = () => { S.activeFeature = (S.activeFeature === el.dataset.f) ? null : el.dataset.f; render(); });

    // B. 全部代币明细
    $('tbl-title').innerHTML = `B · 全部代币明细（${ws.length} 个）<span class="muted sub"> （点任意行看完整指标；点表头排序）</span>`;
    if (!S.sortCol) { S.sortCol = 'pushed_at'; S.sortDir = 'desc'; }
    paintTable(ws, feats);
    return;
  }
  $('sec-buckets').classList.remove('hidden');
  $('sec-features').classList.remove('hidden');
  $('thr-box').classList.remove('hidden');
  $('feat-title').innerHTML = `A · 这组的共同特征<span class="muted sub"> （绿=高于大盘=共同特征；灰=不高于。点一行可在下方只看命中该特征的币）</span>`;
  $('tbl-title').innerHTML = `B · 这组的代币明细<span class="muted sub"> （点任意行看该币完整指标；点表头排序）</span>`;

  const dim = DIMS[S.dimKey];

  // 特征派生
  const feats = {};
  for (const r of ws) feats[r.task_id] = deriveFeatures(r);

  // 维度行 + 分桶
  const dimRows = ws.filter((r) => r[dim.column] != null);
  const counts = {};
  for (const b of dim.buckets) counts[b.label] = 0;
  for (const r of dimRows) { const lb = assignBucket(r[dim.column], dim.buckets); if (lb) counts[lb]++; }
  if (!S.bucketLabel || !dim.buckets.some((b) => b.label === S.bucketLabel)) {
    S.bucketLabel = dim.defaultBucket;
    if (!counts[S.bucketLabel]) {
      const best = dim.buckets.map((b) => b.label).filter((l) => counts[l] > 0).sort((a, b) => counts[b] - counts[a])[0];
      if (best) S.bucketLabel = best;
    }
  }

  // 桶导航
  $('bucket-seg').innerHTML = dim.buckets.map((b) =>
    `<button data-b="${esc(b.label)}" class="${b.label === S.bucketLabel ? 'active' : ''}">${esc(b.label)} (${counts[b.label]})</button>`).join('');
  $('bucket-seg').querySelectorAll('button').forEach((btn) =>
    btn.onclick = () => { S.bucketLabel = btn.dataset.b; S.activeFeature = null; S.sortCol = null; render(); });

  // 当前桶
  const members = dimRows.filter((r) => assignBucket(r[dim.column], dim.buckets) === S.bucketLabel);
  const pct = dimRows.length ? Math.round(members.length / dimRows.length * 100) : 0;
  $('bucket-head').innerHTML = `${dim.label} ${esc(S.bucketLabel)} <span class="meta">${members.length} 个币，占样本 ${pct}%</span>`;
  $('small-warn').classList.toggle('hidden', members.length >= SMALL_SAMPLE);

  // A. 共同特征
  const baseline = {};
  for (const f of FEATURE_DEFS) baseline[f.key] = rate(dimRows, f.key, feats);
  const stats = FEATURE_DEFS.map((f) => {
    const m = rate(members, f.key, feats);
    const base = baseline[f.key].rate;
    const lift = (m.rate != null && base != null) ? m.rate - base : null;
    return { key: f.key, label: labelOf(f.key), ...m, baseline: base, lift };
  }).filter((s) => s.rate != null).sort((a, b) => (b.lift ?? -9) - (a.lift ?? -9));

  $('features').innerHTML = stats.map((s) => {
    const up = (s.lift ?? 0) > 0.0001;
    const liftPts = s.lift == null ? '—' : (s.lift >= 0 ? '+' : '') + Math.round(s.lift * 100) + 'pt';
    const basePct = s.baseline == null ? '—' : Math.round(s.baseline * 100) + '%';
    const sel = s.key === S.activeFeature ? ' sel' : '';
    return `<div class="feat ${up ? 'up' : 'down'}${sel}" data-f="${s.key}">
      <span class="fname">${esc(s.label)}</span>
      <span class="bar"><span class="base" style="width:${(s.baseline || 0) * 100}%"></span><span class="val" style="width:${s.rate * 100}%"></span></span>
      <span class="nums">${Math.round(s.rate * 100)}% (${s.hits}/${s.n}) · 基准${basePct} · <span class="lift">${liftPts}</span></span>
    </div>`;
  }).join('');
  $('features').querySelectorAll('.feat').forEach((el) =>
    el.onclick = () => { S.activeFeature = (S.activeFeature === el.dataset.f) ? null : el.dataset.f; render(); });

  // B. 代币明细（按当前维度列默认排序）
  if (!S.sortCol) { S.sortCol = dim.column; S.sortDir = dim.sortDir; }
  paintTable(members, feats);
}

// ===== 单币完整详情 =====
function showDetail(r) {
  const d = delayMin(r);
  const rowsHtml = (pairs) => pairs.map(([k, v]) => `<div class="k">${esc(k)}</div><div>${v == null || v === '' ? '—' : v}</div>`).join('');
  const created = r.creation_timestamp ? new Date(r.creation_timestamp * 1000).toLocaleString() : '—';
  const addr = r.address || '';
  const url = gmgnUrl(r);
  const contractHtml = addr ? `<span class="addr-copy" data-copy="${esc(addr)}" title="点击复制">${esc(addr)} 📋</span>` : '—';
  $('modal-body').innerHTML =
    `<h2>${esc(r.symbol || '?')} <span class="muted">${esc(r.name || '')}</span>${url ? ` <a class="gmgn-btn" href="${esc(url)}" target="_blank" rel="noopener">在 GMGN 看K线 ↗</a>` : ''}</h2>
     <div class="kv">
       <div class="sec">基本信息</div>
       ${rowsHtml([
        ['链', r.chain], ['评级', r.grade], ['合约', contractHtml], ['推荐时间', fmtTime(r.pushed_at)],
        ['部署时间', created], ['采集延迟', d == null ? '—' : fmtDelay(d) + (d <= TRUST_MAX_DELAY_MIN ? '（可信✓）' : '（存量/迟采，指标仅参考）')],
        ['叙事', r.narrative],
      ])}
       <div class="sec">入场指标（推送时）</div>
       ${rowsHtml([
        ['采集时间', fmtTime(r.created_at) + (r.enrich_attempts ? '　⚠️ 详细指标二次采集（可能非推送瞬间）' : '')],
        ['市值', fUsd(r.market_cap)], ['流动性', fUsd(r.liquidity)], ['24h成交量', fUsd(r.volume_24h)],
        ['持有人', fInt(r.holder_count)], ['换手率', fTurn(r.turnover)], ['人均持币', fUsd(r.avg_holding_usd)],
        ['TOP10持仓', fRate(r.top10_rate)], ['DEV持仓', fRate(r.dev_hold_rate)],
        ['聪明钱买入', fInt(r.smart_wallets)], ['KOL买入', fInt(r.kol_wallets)],
        ['集群钱包', fRate(r.bundler_rate)], ['新钱包', fRate(r.fresh_wallet_rate)],
        ['老鼠仓', fRate(r.rat_rate)], ['钓鱼钱包', fRate(r.entrapment_rate)], ['机器人占比', fRate(r.bot_degen_rate)],
      ])}
       <div class="sec">安全风险</div>
       ${(() => {
          const risks = securityRisks(r);
          const out = risks.map((x) => `<div class="k">⚠️</div><div style="color:#ff6b6b">${esc(x)}</div>`);
          // SOL 链：始终显示买/卖税，便于核对数据（0 税为正常，绿色；非 0 红色提示）
          if (r.chain === 'sol') {
            const pct = (v) => v == null ? '—' : Math.round(v * 100) + '%';
            const clean = (r.buy_tax || 0) === 0 && (r.sell_tax || 0) === 0;
            out.push(`<div class="k">买/卖税</div><div style="color:${clean ? '#4ade80' : '#ff6b6b'}">买 ${pct(r.buy_tax)} · 卖 ${pct(r.sell_tax)}</div>`);
          }
          if (!risks.length && r.chain !== 'sol') out.push(`<div class="k"></div><div style="color:#4ade80">无明显风险</div>`);
          return out.join('') || `<div class="k"></div><div style="color:#4ade80">无明显风险</div>`;
       })()}
       <div class="sec">推送后表现</div>
       ${rowsHtml([
        ['推荐市值', fUsd(r.base_market_cap)], ['推荐后最高市值', fUsd(r.peak_market_cap)],
        ['最高涨幅', fGain(r.peak_gain_pct)], ['最大跌幅', fDrop(r.max_drop_pct)],
        ['当前涨幅', fGain(r.current_gain_pct)], ['最终涨幅', fGain(r.final_gain_pct)],
        ['追踪状态', r.track_status],
      ])}
     </div>`;
  $('modal-body').querySelectorAll('[data-copy]').forEach((el) => el.onclick = () => copyText(el.dataset.copy, el));
  $('modal').classList.remove('hidden');
}

// ===== 事件 =====
$('trust').onchange = (e) => { S.trustOnly = e.target.checked; render(); };
$('reload').onclick = async () => { await loadAll(); render(); };
$('search').oninput = (e) => { S.search = e.target.value; render(); };
$('thr-reset').onclick = () => { S.thresholds = { ...S.defaultThresholds }; renderThresholds(); render(); };
$('modal-close').onclick = () => $('modal').classList.add('hidden');
$('modal').onclick = (e) => { if (e.target.id === 'modal') $('modal').classList.add('hidden'); };
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') $('modal').classList.add('hidden'); });

// ===== 启动 =====
(async () => {
  await loadAll();
  renderDimSeg();
  renderThresholds();
  render();
})();

// 自动刷新：每 25 秒拉一次最新数据，让新采集到的币自动出现（弹窗打开时跳过，避免打断阅读）
setInterval(async () => {
  if (!$('modal').classList.contains('hidden')) return;
  try { S.tokens = await (await fetch('/api/tokens')).json(); render(); } catch (e) {}
}, 25000);
