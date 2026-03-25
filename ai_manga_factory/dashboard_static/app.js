/* 只读 Dashboard 前端：无写操作，仅 GET /api/dashboard */

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstChild;
}

function tagPass(v) {
  if (v === true) return '<span class="tag pass">PASS</span>';
  if (v === false) return '<span class="tag fail">FAIL</span>';
  return '<span class="tag na">—</span>';
}

let lastData = null;
let selectedEp = null;

async function loadDashboard() {
  const res = await fetch("/api/dashboard");
  if (!res.ok) {
    const t = await res.text();
    throw new Error(t || res.statusText);
  }
  return res.json();
}

function renderOverview(o, ov) {
  o.innerHTML = "";
  const caps = ov.capabilities || {};
  const capChips = Object.entries(caps)
    .filter(([, v]) => v === true)
    .map(([k]) => `<span class="chip on">${k}</span>`)
    .join("");
  const cards = [
    ["系列", ov.display_title || "—"],
    ["题材", ov.genre_key || "—"],
    ["计划集数", ov.planned_episodes_from_outline ?? "—"],
    ["已扫描集目录", String(ov.episode_directories_scanned ?? 0)],
    ["Registry", ov.registry_file_exists ? "存在" : "缺失"],
    ["Registry 校验", ov.registry_strict_validation_ok ? "通过" : "降级/空壳"],
    ["Gate 文件覆盖", `${ov.gate_artifact_files_present ?? 0}/${ov.gate_artifact_episode_dirs ?? 0}`],
    ["叙事漂移", ov.story_thrust_drift_flag ? "是" : "否"],
    ["最近刷新", ov.last_refresh_hint || "—"],
  ];
  cards.forEach(([k, v]) => {
    const d = el(`<div class="ov-card"><div class="k">${k}</div><div class="v">${v}</div></div>`);
    o.appendChild(d);
  });
  const cap = el('<div class="ov-card"><div class="k">Capabilities</div><div class="chips"></div></div>');
  cap.querySelector(".chips").innerHTML = capChips || '<span class="chip">（无 true 开关）</span>';
  o.appendChild(cap);
}

function episodeFilter(row, flt, vlIncomplete) {
  const pg = row.plot_gate_pass;
  const pkg = row.package_gate_pass;
  const gateFail = pg === false || pkg === false;
  if (flt === "gate_fail") return gateFail;
  if (flt === "repeated") return !!row.repeated_failure_active;
  if (flt === "stale") return (row.stale_promise_count || 0) > 0;
  if (flt === "broken") return (row.broken_promise_count || 0) > 0;
  if (flt === "low_kf") return (row.low_confidence_knowledge_count || 0) > 0;
  // 系列级视觉锁：仅有 partial/missing 时「全集都带风险语境」，筛选项为真则显示全部集；否则本筛选项下 0 行（易误解为「没生成剧本」）
  if (flt === "vl_series") return vlIncomplete;
  return true;
}

function renderEpisodes(data) {
  const tbody = document.getElementById("tbody-ep");
  const flt = document.getElementById("flt-ep").value;
  const vl = data.visual_lock?.counts || {};
  const vlIncomplete = (vl.partial || 0) + (vl.missing || 0) > 0;
  tbody.innerHTML = "";
  const all = data.episodes || [];
  const rows = all.filter((r) => episodeFilter(r, flt, vlIncomplete));
  if (rows.length === 0 && all.length > 0) {
    const tr = document.createElement("tr");
    let hint =
      "当前筛选条件下没有匹配的分集。请把「筛选」改回「全部」。";
    if (flt === "vl_series" && !vlIncomplete) {
      hint =
        "已选「系列视觉锁未齐」，但当前系列无 partial/missing 角色（或为空壳）；请改回「全部」查看各集。";
    }
    if (flt === "gate_fail") {
      hint +=
        " 若从未跑过 plot/package Judge，Gate 列多为「—」，选「Gate 未通过」也会空。";
    }
    tr.innerHTML = `<td colspan="9" style="cursor:default;color:#8b939e">${hint}</td>`;
    tbody.appendChild(tr);
    return;
  }
  rows.forEach((r) => {
    const tr = document.createElement("tr");
    tr.dataset.epid = String(r.episode_id);
    tr.innerHTML = `
      <td>${r.episode_id}</td>
      <td>${escapeHtml(r.title || "")}</td>
      <td></td>
      <td></td>
      <td>${escapeHtml(r.failure_trend_label || "—")}</td>
      <td>${r.open_promise_count ?? 0}</td>
      <td>${r.stale_promise_count ?? 0}/${r.broken_promise_count ?? 0}</td>
      <td>${r.low_confidence_knowledge_count ?? 0}</td>
      <td>${r.relation_touch_count ?? 0}</td>
    `;
    tr.cells[2].innerHTML = tagPass(r.plot_gate_pass);
    tr.cells[3].innerHTML = tagPass(r.package_gate_pass);
    tbody.appendChild(tr);
  });

  tbody.querySelectorAll("tr").forEach((tr) => {
    tr.addEventListener("click", () => {
      const id = parseInt(tr.dataset.epid, 10);
      selectedEp = id;
      const row = (data.episodes || []).find((x) => x.episode_id === id);
      const drawer = document.getElementById("ep-drawer");
      const body = document.getElementById("drawer-body");
      const title = document.getElementById("drawer-title");
      if (!row || !drawer || !body || !title) return;

      const details = (data.episode_details || {})[String(id)] || {};
      title.textContent = `Episode #${id}`;
      body.innerHTML = renderEpisodeDrawer(details, row);
      drawer.classList.remove("hidden");
      drawer.setAttribute("aria-hidden", "false");
    });
  });
}

function mkTag(cls, text) {
  if (text === null || text === undefined || text === "") return `<span class="tag na">—</span>`;
  return `<span class="tag ${cls}">${escapeHtml(String(text))}</span>`;
}

function renderEpisodeDrawer(details, row) {
  const header = details.header || {};
  const ps = details.promise_snapshot || {};
  const kf = details.knowledge_snapshot || {};
  const vs = details.visual_snapshot || {};
  const gs = details.gate_snapshot || {};
  const files = details.artifacts_presence || {};

  const riskTags = header.risk_tags || [];
  const riskPills = riskTags.length ? riskTags.map((t) => `<span class="pill">${escapeHtml(t)}</span>`).join("") : `<span class="empty">无明显风险标签</span>`;

  const promEmpty =
    (!ps.touched_promises || ps.touched_promises.length === 0) && (!ps.new_promises || ps.new_promises.length === 0);

  const factsEmpty = (!kf.facts || kf.facts.length === 0);
  const castEmpty = (!vs.cast_rows || vs.cast_rows.length === 0);

  const openSmart = (n) => `${n ?? 0}`;

  const promiseRows = (ps.touched_promises || []).slice(0, 10);
  const promiseHtml = promEmpty
    ? `<div class="empty">无关联 promises（或 registry 为空壳）</div>`
    : `<table class="mini-table"><thead><tr><th>promise</th><th>状态</th><th>创建/触达</th></tr></thead><tbody>${promiseRows
        .map((p) => {
          return `<tr>
            <td>
              <div><strong>${escapeHtml(p.promise_id || "")}</strong></div>
              <div class="empty">${escapeHtml(p.description || "")}</div>
            </td>
            <td>${escapeHtml(p.status || "open")}${p.manual_override ? " · 人工" : ""}</td>
            <td>${p.created_episode ?? "—"} / ${p.last_seen_episode ?? "—"}</td>
          </tr>`;
        })
        .join("")}</tbody></table>`;

  const highlightPromises = (ps.highlight_promises || []).slice(0, 5);
  const highlightHtml =
    highlightPromises.length === 0
      ? `<div class="empty">暂无最值得注意的 promises</div>`
      : `<div class="pill-list">${highlightPromises
          .map(
            (p) =>
              `<span class="pill">${escapeHtml(p.promise_id || "")}: ${escapeHtml(p.status || "")}</span>`
          )
          .join("")}</div>`;

  const factsRows = (kf.facts || []).slice(0, 10);
  const factsHtml = factsEmpty
    ? `<div class="empty">无关联 knowledge_fence facts</div>`
    : `<table class="mini-table"><thead><tr><th>fact</th><th>置信/可见</th><th>集范围</th></tr></thead><tbody>${factsRows
        .map((f) => {
          return `<tr>
            <td>
              <div><strong>${escapeHtml(f.fact_id || "")}</strong></div>
              <div class="empty">${escapeHtml(f.fact_text || "")}</div>
            </td>
            <td>${escapeHtml(f.visibility || "")} / ${escapeHtml(f.confidence || "")}${f.known_by && f.known_by.length ? ` · known_by:${escapeHtml(f.known_by.join("、"))}` : ""}</td>
            <td>${f.first_seen_episode ?? "—"}→${f.last_confirmed_episode ?? "—"}</td>
          </tr>`;
        })
        .join("")}</tbody></table>`;

  const castRows = (vs.cast_rows || []).slice(0, 12);
  const castHtml = castEmpty
    ? `<div class="empty">无关联 visual_lock 数据</div>`
    : `<table class="mini-table"><thead><tr><th>角色</th><th>视觉状态</th><th>缺项摘要</th></tr></thead><tbody>${castRows
        .map((c) => {
          const missing = c.missing_items && c.missing_items.length ? c.missing_items.join("，") : "";
          return `<tr>
            <td><strong>${escapeHtml(c.display_name || c.cast_id || "")}</strong></td>
            <td>${escapeHtml(c.visual_state || "")}</td>
            <td>${escapeHtml(missing || "—")}</td>
          </tr>`;
        })
        .join("")}</tbody></table>`;

  const latestPlot = gs.latest_plot_gate;
  const latestPkg = gs.latest_package_gate;
  const plotSummary = latestPlot ? `${latestPlot.pass === true ? "PASS" : latestPlot.pass === false ? "FAIL" : "—"} · ${latestPlot.summary || ""}` : "未找到 plot gate（可能尚未跑 judge）";
  const pkgSummary = latestPkg ? `${latestPkg.pass === true ? "PASS" : latestPkg.pass === false ? "FAIL" : "—"} · ${latestPkg.summary || ""}` : "未找到 package gate（可能尚未跑 judge）";

  const debugRaw = details.raw_debug ? JSON.stringify(details.raw_debug, null, 2) : "";

  const filesHtml = (() => {
    const f = files.files || {};
    const item = (k, label) => {
      const row = f[k] || {};
      const ex = row.exists;
      if (ex === undefined) return `<div>${escapeHtml(label)}：—</div>`;
      return `<div>${escapeHtml(label)}：${ex ? "存在" : "缺失"}</div>`;
    };
    return `<div class="kv">
      ${item("episode_function", "episode_function")}
      ${item("plot", "plot")}
      ${item("script", "script")}
      ${item("storyboard", "storyboard")}
      ${item("creative_scorecard", "creative_scorecard")}
      ${item("package", "package")}
      ${item("gate_artifacts", "gate_artifacts")}
    </div>
    <div class="empty" style="margin-top:0.5rem">最新 artifact 更新时间：${escapeHtml(files.latest_artifact_update_at || "—")}</div>`;
  })();

  return `
    <div class="dsec">
      <h3>Episode Header / Summary</h3>
      <div class="kv">
        <div class="k">Episode</div><div>${escapeHtml(details.episode_id ?? row.episode_id)}</div>
        <div class="k">Title</div><div>${escapeHtml(details.title || row.title || "")}</div>
        <div class="k">整体 Gate</div><div>${escapeHtml(details.header?.episode_overall_gate ?? row.episode_overall_gate ?? "")}</div>
      </div>
      <div class="pill-list" style="margin-top:0.5rem">
        <span class="pill">plot: ${escapeHtml(row.plot_gate_pass === true ? "PASS" : row.plot_gate_pass === false ? "FAIL" : "—")}</span>
        <span class="pill">pkg: ${escapeHtml(row.package_gate_pass === true ? "PASS" : row.package_gate_pass === false ? "FAIL" : "—")}</span>
        <span class="pill">趋势: ${escapeHtml(row.failure_trend_label || "—")}</span>
      </div>
      <div style="margin-top:0.65rem">
        <div class="k">风险标签</div>
        ${riskPills}
      </div>
      <div style="margin-top:0.65rem" class="empty">rerun hint：${escapeHtml(header.rerun_hint_summary || "—")}</div>
      <div class="empty">recovery：${escapeHtml(gs.recovery_light_hint || "—")}</div>
    </div>

    <div class="dsec">
      <h3>Promise Snapshot</h3>
      <div class="mini-stats">
        <span>open <strong>${escapeHtml(openSmart(ps.open_promise_count))}</strong></span>
        <span>stale <strong>${escapeHtml(openSmart(ps.stale_promise_count))}</strong></span>
        <span>broken <strong>${escapeHtml(openSmart(ps.broken_promise_count))}</strong></span>
        <span>人工 <strong>${escapeHtml(openSmart(ps.manual_override_count))}</strong></span>
        <span>supersede <strong>${escapeHtml(openSmart(ps.supersede_count))}</strong></span>
      </div>
      <div class="empty">最值得注意的 2-5 条：${highlightHtml}</div>
      ${promiseHtml}
    </div>

    <div class="dsec">
      <h3>Knowledge Snapshot</h3>
      <div class="mini-stats">
        <span>facts(触达) <strong>${escapeHtml(kf.total_facts_touching_episode ?? kf.total_facts ?? 0)}</strong></span>
        <span>低置信 <strong>${escapeHtml(kf.low_confidence_count ?? 0)}</strong></span>
        <span>audience_only <strong>${escapeHtml(kf.audience_only_count ?? 0)}</strong></span>
        <span>recent changes <strong>${escapeHtml(kf.recent_changes_count ?? 0)}</strong></span>
      </div>
      ${factsHtml}
    </div>

    <div class="dsec">
      <h3>Visual Snapshot</h3>
      <div class="mini-stats">
        <span>related roles <strong>${escapeHtml(vs.related_cast_count ?? vs.related_cast_count ?? 0)}</strong></span>
        <span>complete <strong>${escapeHtml(vs.complete_count ?? 0)}</strong></span>
        <span>partial <strong>${escapeHtml(vs.partial_count ?? 0)}</strong></span>
        <span>missing <strong>${escapeHtml(vs.missing_count ?? 0)}</strong></span>
      </div>
      ${castHtml}
    </div>

    <div class="dsec">
      <h3>Gate Snapshot</h3>
      <div class="empty">plot：${escapeHtml(plotSummary)}</div>
      <div class="empty" style="margin-top:0.35rem">package：${escapeHtml(pkgSummary)}</div>
      <div class="empty" style="margin-top:0.35rem">last failure primary cause：${escapeHtml(gs.last_failure_primary_cause || "—")}</div>
      <div class="empty">repeated failure：${escapeHtml(gs.repeated_failure_active ? "是" : "否")}</div>
      <div class="empty">rerun hint summary：${escapeHtml(gs.rerun_hint_summary || "—")}</div>
    </div>

    <div class="dsec">
      <h3>Files / Artifacts Presence</h3>
      ${filesHtml}
    </div>

    <div class="dsec">
      <h3>Raw JSON（可调试，默认折叠不可展示展开按钮，避免影响阅读）</h3>
      <div class="empty" style="white-space:pre-wrap;max-height:220px;overflow:auto;border:1px dashed #2a3038;padding:0.5rem;margin-top:0.5rem">
        ${escapeHtml(debugRaw || "{}")}
      </div>
    </div>
  `;
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function renderPromises(data) {
  const st = document.getElementById("flt-promise-status").value;
  const manual = document.getElementById("flt-manual").checked;
  const sup = document.getElementById("flt-supersede").checked;
  let list = (data.promises?.promises || []).slice();
  if (st !== "all") list = list.filter((p) => (p.status || "open") === st);
  if (manual)
    list = list.filter(
      (p) =>
        p.override_reason ||
        p.override_source ||
        String(p.provenance || "").includes("manual")
    );
  if (sup)
    list = list.filter((p) => p.superseded_by_promise_id || (p.supersedes_promise_ids || []).length);
  const tb = document.getElementById("tbody-promise");
  tb.innerHTML = "";
  list.slice(0, 200).forEach((p) => {
    const tr = document.createElement("tr");
    const desc = String(p.description || p.promise_id || "").slice(0, 120);
    tr.innerHTML = `
      <td>${escapeHtml(String(p.promise_id || ""))}</td>
      <td>${escapeHtml(String(p.status || ""))}</td>
      <td>${escapeHtml(desc)}</td>
      <td>${p.created_episode ?? "—"}</td>
      <td>${p.last_seen_episode ?? "—"}</td>
    `;
    tb.appendChild(tr);
  });
  const sum = data.promises?.summary_counts || {};
  document.getElementById("promise-summary").innerHTML = `
    <span>open <strong>${sum.open ?? 0}</strong></span>
    <span>stale <strong>${sum.stale ?? 0}</strong></span>
    <span>broken <strong>${sum.broken ?? 0}</strong></span>
    <span>paid_off <strong>${sum.paid_off ?? 0}</strong></span>
    <span>人工覆盖 <strong>${data.promises?.manual_override_count ?? 0}</strong></span>
    <span>supersede <strong>${(data.promises?.supersede_digest?.with_superseded_by ?? 0) +
      "/" +
      (data.promises?.supersede_digest?.with_supersedes_list ?? 0)}</strong></span>
  `;
}

function renderKf(data) {
  const mode = document.getElementById("flt-kf").value;
  let facts = (data.knowledge_fence?.facts || []).slice();
  if (mode === "low") facts = facts.filter((f) => f.confidence === "low");
  else if (mode === "audience") facts = facts.filter((f) => f.visibility === "audience_only");
  else if (mode === "recent")
    facts = facts.filter((f) => f.first_seen_episode !== f.last_seen_episode);
  const st = data.knowledge_fence?.stats || {};
  document.getElementById("kf-summary").innerHTML = `
    <span>总计 <strong>${st.total ?? 0}</strong></span>
    <span>低置信 <strong>${st.low_confidence ?? 0}</strong></span>
    <span>audience_only <strong>${st.audience_only ?? 0}</strong></span>
    <span>recent_changes <strong>${st.recent_changes ?? 0}</strong></span>
  `;
  const tb = document.getElementById("tbody-kf");
  tb.innerHTML = "";
  facts.slice(0, 200).forEach((f) => {
    const tr = document.createElement("tr");
    const ft = String(f.fact_text || f.text || "").slice(0, 100);
    tr.innerHTML = `
      <td>${escapeHtml(ft)}</td>
      <td>${escapeHtml(String(f.confidence || ""))}</td>
      <td>${escapeHtml(String(f.visibility || ""))}</td>
      <td>${f.first_seen_episode ?? "—"}→${f.last_seen_episode ?? "—"}</td>
    `;
    tb.appendChild(tr);
  });
}

function renderVl(data) {
  const vl = data.visual_lock || {};
  const c = vl.counts || {};
  const host = document.getElementById("vl-panel");
  const mem = (vl.memory_only_names || []).filter(Boolean);
  host.innerHTML = `
    <p class="mini-stats">
      complete <strong>${c.complete ?? 0}</strong> · partial <strong>${c.partial ?? 0}</strong> · missing <strong>${c.missing ?? 0}</strong>
      · 覆盖率（complete） <strong>${vl.coverage_complete_pct ?? "—"}%</strong>
    </p>
    ${mem.length ? `<p>仅 memory、圣经未齐：<strong>${mem.map(escapeHtml).join("、")}</strong></p>` : "<p>无「仅 memory」名单或已全部对齐。</p>"}
    <div class="vl-grid">
      ${(vl.characters || [])
        .slice(0, 48)
        .map(
          (ch) => `
        <div class="vl-card">
          <div><strong>${escapeHtml(String(ch.display_name || ch.cast_id || ""))}</strong></div>
          <div class="tag ${ch.lock_status === "complete" ? "pass" : ch.lock_status === "partial" ? "warn" : "fail"}">${escapeHtml(
            String(ch.lock_status || "?")
          )}</div>
        </div>`
        )
        .join("")}
    </div>
  `;
}

function renderGate(data) {
  const tb = document.getElementById("tbody-gate");
  tb.innerHTML = "";
  (data.episodes || []).forEach((r) => {
    const ts = r.trend_summary || {};
    const lv = ts.latest_verdict || {};
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${r.episode_id}</td>
      <td>plot:${r.plot_gate_pass === true ? "✓" : r.plot_gate_pass === false ? "✗" : "—"} pkg:${r.package_gate_pass === true ? "✓" : r.package_gate_pass === false ? "✗" : "—"}</td>
      <td>${ts.repeated_same_failure_as_immediate_previous ? "是" : "否"}</td>
      <td>${escapeHtml(String(ts.recovery_light_hint || "—"))}</td>
      <td>${escapeHtml(String(ts.rerun_hint_summary || "—"))}</td>
      <td>${escapeHtml(String(lv.last_failure_primary_cause || "—")).slice(0, 80)}</td>
    `;
    tb.appendChild(tr);
  });
}

async function refresh() {
  const banner = document.getElementById("banner-warn");
  try {
    const data = await loadDashboard();
    lastData = data;
    const warns = data.warnings || [];
    if (warns.length) {
      banner.classList.remove("hidden");
      banner.textContent = "提示：" + warns.join(" | ");
    } else {
      banner.classList.add("hidden");
    }
    const ov = data.overview || {};
    document.getElementById("hdr-title").textContent = ov.display_title || "制作调度台";
    document.getElementById("hdr-sub").textContent =
      `只读 · ${ov.layout || ""} · ${ov.series_dir || ""}`;
    renderOverview(document.getElementById("overview"), ov);
    renderEpisodes(data);
    renderPromises(data);
    renderKf(data);
    renderVl(data);
    renderGate(data);
    document.getElementById("foot-meta").textContent =
      `生成时间 ${data.generated_at || "—"} · schema ${data.schema || ""}`;
  } catch (e) {
    banner.classList.remove("hidden");
    banner.textContent = "加载失败：" + (e && e.message ? e.message : String(e));
  }
}

document.getElementById("btn-reload").addEventListener("click", refresh);
document.getElementById("flt-ep").addEventListener("change", () => lastData && renderEpisodes(lastData));
document.getElementById("flt-promise-status").addEventListener("change", () => lastData && renderPromises(lastData));
document.getElementById("flt-manual").addEventListener("change", () => lastData && renderPromises(lastData));
document.getElementById("flt-supersede").addEventListener("change", () => lastData && renderPromises(lastData));
document.getElementById("flt-kf").addEventListener("change", () => lastData && renderKf(lastData));

const epDrawer = document.getElementById("ep-drawer");
const btnDrawerClose = document.getElementById("btn-drawer-close");
if (epDrawer && btnDrawerClose) {
  btnDrawerClose.addEventListener("click", () => {
    epDrawer.classList.add("hidden");
    epDrawer.setAttribute("aria-hidden", "true");
  });
}

refresh();
