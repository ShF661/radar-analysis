// ===== 金狗雷达 GMGN 特征分析 · 前端（桶为中心，全前端计算）=====
// 数据源：/api/tokens（全量行，含数值+时间戳）、/api/defaults（阈值+特征名）。
// 可信过滤 / 分桶 / 特征派生 / 占比基准lift / 联动筛选 全部在浏览器完成。

const TRUST_MAX_DELAY_MIN = 5;   // 采集延迟 ≤ 5 分钟视为“第一时间采集”
const SMALL_SAMPLE = 10;         // 桶内 < 10 个 → 样本太少警告

// 三个维度：最高涨幅 / 最小涨幅（同一个最高涨幅值，看小头）/ 最大跌幅
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
  { key: 'honeypot', fn: (r) => r.is_honeypot == null ? null : r.is_honeypot === 'yes' },
  { key: 'not_open_source', fn: (r) => r.open_source == null ? null : r.open_source === 'no' },
  { key: 'not_renounced', fn: (r) => r.owner_renounced == null ? null : r.owner_renounced === 'no' },
  { key: 'has_tax', fn: (r) => {
      if (r.buy_tax == null && r.sell_tax == null) return null;
      return (r.buy_tax || 0) > 0 || (r.sell_tax || 0) > 0;
    } },
];
const gt = (v, t) => v == null ? null : v > t;
const lt = (v, t) => v == null ? null : v < t;

// B 表列：身份/结果 + 钱包构成 + 规模集中度（安全类只在详情弹窗）
const COLUMNS = [
  { key: 'symbol', label: '符号', type: 'sym', first: true },
  { key: 'grade', label: '评级', type: 'grade' },
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
  { key: '_delay', label: '采集', type: 'delay' },
];

// ===== 状态 =====
const S = {
  dimKey: 'peak_high',
  bucketLabel: null,
  trustOnly: false,
  thresholds: {},
  defaultThresholds: {},
  featureLabels: {},
  tokens: [],
  activeFeature: null,
  sortCol: null,
  sortDir: 'desc',
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
function cellHtml(r, col) {
  const v = r[col.key];
  switch (col.type) {
    case 'sym': return `<span>${esc(v || r.address?.slice(0, 6) || '?')}</span>`;
    case 'grade': return v ? `<span class="grade">${esc(v)}</span>` : '—';
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

// ===== 渲染 =====
function workingSet() {
  return S.trustOnly ? S.tokens.filter(trustworthy) : S.tokens.slice();
}

function renderDimSeg() {
  $('dim-seg').innerHTML = Object.entries(DIMS)
    .map(([k, d]) => `<button data-k="${k}" class="${k === S.dimKey ? 'active' : ''}">${d.label}</button>`).join('');
  $('dim-seg').querySelectorAll('button').forEach((b) =>
    b.onclick = () => { S.dimKey = b.dataset.k; S.bucketLabel = null; S.activeFeature = null; S.sortCol = null; render(); });
}

function renderThresholds() {
  const grid = $('thr-grid');
  grid.innerHTML = Object.entries(S.thresholds).map(([k, v]) =>
    `<label>${esc(S.featureLabels[k] || k)}<input type="number" step="any" data-k="${k}" value="${v}"></label>`).join('');
  grid.querySelectorAll('input').forEach((i) =>
    i.onchange = () => { const n = parseFloat(i.value); if (!isNaN(n)) { S.thresholds[i.dataset.k] = n; render(); } });
}

function render() {
  const dim = DIMS[S.dimKey];
  // 维度按钮高亮跟随当前维度
  $("dim-seg").querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.k === S.dimKey));
  const ws = workingSet();
  const total = S.tokens.length;
  const trustCount = S.tokens.filter(trustworthy).length;

  // 样本说明
  if (S.trustOnly) {
    $('sample-info').textContent = `基于 ${trustCount} 个可信样本（共 ${total} 条，已排除 ${total - trustCount} 条迟采/存量）`;
  } else {
    $('sample-info').textContent = `显示全部 ${total} 条（含存量/迟采，仅供体验界面，入场指标无参考价值）`;
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

  // 特征派生
  const feats = {};
  for (const r of ws) feats[r.task_id] = deriveFeatures(r);

  // 维度行 + 分桶
  const dimRows = ws.filter((r) => r[dim.column] != null);

  // 桶计数
  const counts = {};
  for (const b of dim.buckets) counts[b.label] = 0;
  for (const r of dimRows) { const lb = assignBucket(r[dim.column], dim.buckets); if (lb) counts[lb]++; }

  // 默认选桶：优先维度默认桶；若它没数据，则自动选数量最多的非空桶
  if (!S.bucketLabel || !dim.buckets.some((b) => b.label === S.bucketLabel)) {
    S.bucketLabel = dim.defaultBucket;
    if (!counts[S.bucketLabel]) {
      const best = dim.buckets.map((b) => b.label).filter((l) => counts[l] > 0)
        .sort((a, b) => counts[b] - counts[a])[0];
      if (best) S.bucketLabel = best;
    }
  }

  // 桶导航（带数量）
  $('bucket-seg').innerHTML = dim.buckets.map((b) =>
    `<button data-b="${esc(b.label)}" class="${b.label === S.bucketLabel ? 'active' : ''}">${esc(b.label)} (${counts[b.label]})</button>`).join('');
  $('bucket-seg').querySelectorAll('button').forEach((btn) =>
    btn.onclick = () => { S.bucketLabel = btn.dataset.b; S.activeFeature = null; S.sortCol = null; render(); });

  // 当前桶成员
  const members = dimRows.filter((r) => assignBucket(r[dim.column], dim.buckets) === S.bucketLabel);
  const pct = dimRows.length ? Math.round(members.length / dimRows.length * 100) : 0;
  $('bucket-head').innerHTML = `${dim.label} ${esc(S.bucketLabel)} <span class="meta">${members.length} 个币，占样本 ${pct}%</span>`;
  $('small-warn').classList.toggle('hidden', members.length >= SMALL_SAMPLE);

  // ===== A. 共同特征 =====
  const baseline = {};
  for (const f of FEATURE_DEFS) baseline[f.key] = rate(dimRows, f.key, feats);
  const stats = FEATURE_DEFS.map((f) => {
    const m = rate(members, f.key, feats);
    const base = baseline[f.key].rate;
    const lift = (m.rate != null && base != null) ? m.rate - base : null;
    return { key: f.key, label: S.featureLabels[f.key] || f.key, ...m, baseline: base, lift };
  }).filter((s) => s.rate != null)
    .sort((a, b) => (b.lift ?? -9) - (a.lift ?? -9));

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

  // ===== B. 代币明细（可被特征筛选）=====
  let rows = members.slice();
  if (S.activeFeature) rows = rows.filter((r) => feats[r.task_id][S.activeFeature] === true);

  const tip = $('feat-filter-tip');
  if (S.activeFeature) {
    tip.classList.remove('hidden');
    tip.innerHTML = `已只看命中特征「${esc(S.featureLabels[S.activeFeature] || S.activeFeature)}」的 ${rows.length} 个币 <button id="clr-feat">✕ 清除</button>`;
    $('clr-feat').onclick = () => { S.activeFeature = null; render(); };
  } else tip.classList.add('hidden');

  // 排序（默认按当前维度列）
  if (!S.sortCol) { S.sortCol = dim.column; S.sortDir = dim.sortDir; }
  rows.sort((a, b) => {
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
  const body = rows.map((r, i) =>
    `<tr data-i="${i}">` + COLUMNS.map((c) => `<td class="${c.first ? 'first' : ''}">${cellHtml(r, c)}</td>`).join('') + `</tr>`).join('');
  $('table').innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
  $('table').querySelectorAll('th').forEach((th) =>
    th.onclick = () => {
      const c = th.dataset.c;
      if (S.sortCol === c) S.sortDir = S.sortDir === 'asc' ? 'desc' : 'asc';
      else { S.sortCol = c; S.sortDir = 'desc'; }
      render();
    });
  $('table').querySelectorAll('tbody tr').forEach((tr) =>
    tr.onclick = () => showDetail(rows[+tr.dataset.i]));
}

// ===== 单币完整详情 =====
function showDetail(r) {
  const d = delayMin(r);
  const rowsHtml = (pairs) => pairs.map(([k, v]) => `<div class="k">${esc(k)}</div><div>${v == null || v === '' ? '—' : v}</div>`).join('');
  const created = r.creation_timestamp ? new Date(r.creation_timestamp * 1000).toLocaleString() : '—';
  $('modal-body').innerHTML =
    `<h2>${esc(r.symbol || '?')} <span class="muted">${esc(r.name || '')}</span></h2>
     <div class="kv">
       <div class="sec">基本信息</div>
       ${rowsHtml([
        ['链', r.chain], ['评级', r.grade], ['合约', r.address], ['推送时间', r.pushed_at],
        ['部署时间', created], ['采集延迟', d == null ? '—' : fmtDelay(d) + (d <= TRUST_MAX_DELAY_MIN ? '（可信✓）' : '（存量/迟采，指标仅参考）')],
        ['叙事', r.narrative],
      ])}
       <div class="sec">入场指标（推送时）</div>
       ${rowsHtml([
        ['市值', fUsd(r.market_cap)], ['流动性', fUsd(r.liquidity)], ['24h成交量', fUsd(r.volume_24h)],
        ['持有人', fInt(r.holder_count)], ['换手率', fTurn(r.turnover)], ['人均持币', fUsd(r.avg_holding_usd)],
        ['TOP10持仓', fRate(r.top10_rate)], ['DEV持仓', fRate(r.dev_hold_rate)],
        ['聪明钱买入', fInt(r.smart_wallets)], ['KOL买入', fInt(r.kol_wallets)],
        ['集群钱包', fRate(r.bundler_rate)], ['新钱包', fRate(r.fresh_wallet_rate)],
        ['老鼠仓', fRate(r.rat_rate)], ['钓鱼钱包', fRate(r.entrapment_rate)], ['机器人占比', fRate(r.bot_degen_rate)],
      ])}
       <div class="sec">安全风险</div>
       ${rowsHtml([
        ['蜜罐', r.is_honeypot], ['rug风险', r.rug_ratio], ['买税', fRate(r.buy_tax)], ['卖税', fRate(r.sell_tax)],
        ['开源', r.open_source], ['弃权', r.owner_renounced], ['烧池', r.burn_status],
      ])}
       <div class="sec">推送后表现</div>
       ${rowsHtml([
        ['最高涨幅', fGain(r.peak_gain_pct)], ['最大跌幅', fDrop(r.max_drop_pct)],
        ['当前涨幅', fGain(r.current_gain_pct)], ['最终涨幅', fGain(r.final_gain_pct)],
        ['追踪状态', r.track_status],
      ])}
     </div>`;
  $('modal').classList.remove('hidden');
}

// ===== 事件 =====
$('trust').onchange = (e) => { S.trustOnly = e.target.checked; render(); };
$('reload').onclick = async () => { await loadAll(); render(); };
$('thr-reset').onclick = () => { S.thresholds = { ...S.defaultThresholds }; renderThresholds(); render(); };
$('modal-close').onclick = () => $('modal').classList.add('hidden');
$('modal').onclick = (e) => { if (e.target.id === 'modal') $('modal').classList.add('hidden'); };

// ===== 启动 =====
(async () => {
  await loadAll();
  renderDimSeg();
  renderThresholds();
  render();
})();
