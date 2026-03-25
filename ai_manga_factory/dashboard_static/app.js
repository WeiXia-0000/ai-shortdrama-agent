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
      const box = document.getElementById("ep-detail");
      if (!row) return;
      const ts = row.trend_summary || {};
      const lv = ts.latest_verdict || {};
      box.classList.remove("hidden");
      box.textContent = JSON.stringify(
        {
          episode_id: row.episode_id,
          episode_dir: row.episode_dir,
          gate_artifact_exists: row.gate_artifact_exists,
          latest_verdict: lv,
          failure_trend_label: ts.failure_trend_label,
          repeated_same_failure: ts.repeated_same_failure_as_immediate_previous,
          recovery_light_hint: ts.recovery_light_hint,
          rerun_hint_summary: ts.rerun_hint_summary,
        },
        null,
        2
      );
    });
  });
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

refresh();
