const fmtPct = (v) => (v == null ? "—" : (v * 100).toFixed(0) + "%");
const fmtNum = (v) => (v == null ? "—" : typeof v === "number" ? v.toLocaleString() : v);
const fmtGain = (v) => (v == null ? "—" : v.toFixed(0) + "%");

let DEFAULTS = null;

async function loadDefaults() {
  DEFAULTS = await (await fetch("/api/defaults")).json();
}

async function loadAnalysis(dimension) {
  const r = await fetch("/api/analysis", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ dimension }),
  });
  return r.json();
}

function renderCohorts(data) {
  const el = document.getElementById("cohorts");
  el.innerHTML = "";
  for (const b of data.buckets) {
    const div = document.createElement("div");
    div.className = "cohort";
    const top = b.features.filter((f) => f.lift > 0).slice(0, 10);
    div.innerHTML =
      `<h3>${b.label} <span class="meta">共 ${b.count} 个，占全部 ${fmtGain(b.pct_of_total * 100)}</span></h3>` +
      top.map((f) => {
        const liftPts = ((f.lift) * 100).toFixed(0);
        return `<div class="feat">
            <span>${f.label}</span>
            <span class="bar"><span class="base" style="width:${(f.baseline_rate||0)*100}%"></span><span style="width:${f.bucket_rate*100}%"></span></span>
            <span class="lift ${f.lift<=0?'neg':''}">${fmtPct(f.bucket_rate)} / 基准${fmtPct(f.baseline_rate)} (+${liftPts}pt)</span>
          </div>`;
      }).join("") +
      `<div class="tokens">${b.tokens.slice(0, 30).map((t) => t.symbol || t.address).join("、")}</div>`;
    el.appendChild(div);
  }
}

let TOKENS = [];
function renderTable(rows) {
  TOKENS = rows;
  const cols = [
    ["symbol", "符号"], ["chain", "链"], ["grade", "评级"],
    ["peak_gain_pct", "最高涨幅"], ["max_drop_pct", "最大跌幅"],
    ["smart_wallets", "聪明钱"], ["kol_wallets", "KOL"],
    ["bundler_rate", "集群%"], ["fresh_wallet_rate", "新钱包%"],
    ["holder_count", "持有人"], ["track_status", "状态"],
  ];
  const head = cols.map(([, t]) => `<th>${t}</th>`).join("");
  const body = rows.map((r, i) =>
    `<tr data-i="${i}">` + cols.map(([k]) => {
      let v = r[k];
      if (k.endsWith("_gain_pct") || k.endsWith("drop_pct")) v = fmtGain(v);
      else if (k.endsWith("_rate")) v = fmtPct(v);
      else v = fmtNum(v);
      return `<td>${v}</td>`;
    }).join("") + `</tr>`
  ).join("");
  document.getElementById("table").innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
  document.querySelectorAll("tbody tr").forEach((tr) =>
    tr.addEventListener("click", () => showDetail(TOKENS[+tr.dataset.i]))
  );
}

function showDetail(row) {
  const fields = [
    ["符号", row.symbol], ["名称", row.name], ["链", row.chain], ["合约", row.address],
    ["推送时间", row.pushed_at], ["叙事评级", row.grade], ["叙事", row.narrative],
    ["市值", fmtNum(row.market_cap)], ["流动性", fmtNum(row.liquidity)], ["24h成交量", fmtNum(row.volume_24h)],
    ["持有人", fmtNum(row.holder_count)], ["TOP10持仓", fmtPct(row.top10_rate)],
    ["DEV持仓", fmtPct(row.dev_hold_rate)], ["老鼠仓", fmtPct(row.rat_rate)],
    ["钓鱼钱包", fmtPct(row.entrapment_rate)], ["集群钱包", fmtPct(row.bundler_rate)],
    ["新钱包", fmtPct(row.fresh_wallet_rate)], ["机器人占比", fmtPct(row.bot_degen_rate)],
    ["换手率", row.turnover == null ? "—" : row.turnover.toFixed(2)],
    ["人均持币(USD)", fmtNum(row.avg_holding_usd)],
    ["聪明钱买入", fmtNum(row.smart_wallets)], ["KOL买入", fmtNum(row.kol_wallets)],
    ["蜜罐", row.is_honeypot], ["rug风险", row.rug_ratio], ["买税", fmtPct(row.buy_tax)],
    ["卖税", fmtPct(row.sell_tax)], ["开源", row.open_source], ["弃权", row.owner_renounced],
    ["烧池", row.burn_status], ["最高涨幅", fmtGain(row.peak_gain_pct)],
    ["最大跌幅", fmtGain(row.max_drop_pct)], ["最终涨幅", fmtGain(row.final_gain_pct)],
    ["当前涨幅", fmtGain(row.current_gain_pct)], ["追踪状态", row.track_status],
  ];
  document.getElementById("modal-body").innerHTML =
    `<h2>${row.symbol || ""} 完整指标</h2><div class="kv">` +
    fields.map(([k, v]) => `<div>${k}</div><div>${v == null ? "—" : v}</div>`).join("") + `</div>`;
  document.getElementById("modal").classList.remove("hidden");
}

async function refresh() {
  const dim = document.getElementById("dimension").value;
  document.getElementById("status").textContent = "加载中…";
  const [analysis, tokens] = await Promise.all([loadAnalysis(dim), fetch("/api/tokens").then((r) => r.json())]);
  renderCohorts(analysis);
  renderTable(tokens);
  document.getElementById("status").textContent = `共 ${tokens.length} 个代币`;
}

document.getElementById("refresh").addEventListener("click", refresh);
document.getElementById("dimension").addEventListener("change", refresh);
document.getElementById("modal-close").addEventListener("click", () =>
  document.getElementById("modal").classList.add("hidden"));

(async () => { await loadDefaults(); await refresh(); })();
