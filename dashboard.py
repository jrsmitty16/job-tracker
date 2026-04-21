#!/usr/bin/env python3
"""
Job Tracker Dashboard
Interactive web dashboard — run this then open http://localhost:5000 in your browser.
"""

import threading
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, jsonify, request
from db import get_conn

app = Flask(__name__)


@app.after_request
def no_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response

STATUS_ORDER  = ["New", "Applied", "Interviewing", "Offer", "Rejected/Passed"]
STATUS_COLORS = {
    "New":             "#3498db",
    "Applied":         "#e67e22",
    "Interviewing":    "#27ae60",
    "Offer":           "#f1c40f",
    "Rejected/Passed": "#95a5a6",
    "Not a Fit":       "#c0392b",
}

SCORE_COLORS = ["#bdc3c7", "#e67e22", "#f1c40f", "#2ecc71", "#27ae60"]  # 1-5

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_pipeline():
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        "SELECT COALESCE(status,'New') as status, COUNT(*) as cnt "
        "FROM seen_jobs WHERE COALESCE(status,'New') != 'Not a Fit' "
        "GROUP BY COALESCE(status,'New')"
    )
    rows = cur.fetchall()
    cur.close(); conn.close()
    return {r[0]: r[1] for r in rows}


def get_jobs():
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        "SELECT id, campaign, title, company, location, url, source, "
        "posted_at, COALESCE(status,'New') as status, status_updated_at, "
        "COALESCE(score,0) as score "
        "FROM seen_jobs "
        "WHERE COALESCE(status,'New') != 'Not a Fit' "
        "ORDER BY score DESC, found_at DESC"
    )
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    cur.close(); conn.close()
    return [dict(zip(cols, r)) for r in rows]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Job Tracker Dashboard</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
       background: #f0f2f5; color: #333; min-height: 100vh; }
.topbar { background: #2c3e50; color: #fff; padding: 16px 32px;
          display: flex; align-items: center; justify-content: space-between; }
.topbar h1 { font-size: 20px; font-weight: 600; }
.topbar .updated { font-size: 12px; opacity: .7; }
.main { max-width: 1300px; margin: 0 auto; padding: 28px 24px; }

/* Pipeline boxes */
.pipeline { display: flex; gap: 14px; margin-bottom: 28px; flex-wrap: wrap; }
.pip { padding: 18px 24px; border-radius: 10px; color: #fff; min-width: 130px;
       box-shadow: 0 2px 8px rgba(0,0,0,.15); cursor: pointer; transition: transform .15s; }
.pip:hover { transform: translateY(-2px); }
.pip.active { outline: 3px solid #fff; outline-offset: -3px; }
.pip .num  { font-size: 32px; font-weight: 700; line-height: 1; }
.pip .lbl  { font-size: 12px; margin-top: 4px; opacity: .9; }
.pip-all   { background: #2c3e50 !important; }

/* Controls */
.controls { display: flex; gap: 10px; margin-bottom: 16px; align-items: center; }
.controls input { flex: 1; padding: 9px 14px; border: 1px solid #ddd; border-radius: 6px;
                  font-size: 14px; max-width: 340px; }
.campaign-tabs { display: flex; gap: 8px; flex-wrap: wrap; }
.tab { padding: 6px 14px; border: 1px solid #ccc; border-radius: 20px; cursor: pointer;
       font-size: 13px; background: #fff; transition: all .15s; }
.tab.active, .tab:hover { background: #2980b9; color: #fff; border-color: #2980b9; }

/* Table */
.card { background: #fff; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,.08);
        overflow: hidden; }
table { width: 100%; border-collapse: collapse; }
th { background: #2c3e50; color: #fff; padding: 12px 14px; text-align: left;
     font-size: 13px; font-weight: 600; white-space: nowrap; }
td { padding: 11px 14px; border-bottom: 1px solid #f0f2f5; font-size: 13px;
     vertical-align: middle; }
tr:hover td { background: #f8fbff; }
tr.hidden { display: none; }
a { color: #2980b9; text-decoration: none; font-weight: 500; }
a:hover { text-decoration: underline; }

/* Status badge + dropdown */
.status-wrap { position: relative; display: inline-block; }
.badge { display: inline-block; padding: 4px 11px; border-radius: 12px; color: #fff;
         font-size: 12px; font-weight: 600; cursor: pointer; white-space: nowrap;
         user-select: none; }
.badge:hover { opacity: .85; }
.status-menu { display: none; position: absolute; top: 100%; left: 0; z-index: 99;
               background: #fff; border: 1px solid #ddd; border-radius: 8px;
               box-shadow: 0 4px 16px rgba(0,0,0,.15); min-width: 170px; overflow: hidden; margin-top: 4px; }
.status-menu.open { display: block; }
.status-opt { padding: 9px 14px; cursor: pointer; font-size: 13px; display: flex;
              align-items: center; gap: 8px; }
.status-opt:hover { background: #f5f7fa; }
.status-opt.danger { color: #c0392b; border-top: 1px solid #eee; margin-top: 4px; }
.status-opt.danger:hover { background: #fdf0ef; }
.status-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.score-badge { display: inline-flex; gap: 2px; }
.score-dot { width: 9px; height: 9px; border-radius: 50%; }

/* Toast */
.toast { position: fixed; bottom: 24px; right: 24px; background: #27ae60; color: #fff;
         padding: 12px 20px; border-radius: 8px; font-size: 14px; font-weight: 500;
         box-shadow: 0 4px 16px rgba(0,0,0,.2); opacity: 0; transition: opacity .3s;
         pointer-events: none; z-index: 999; }
.toast.show { opacity: 1; }

.count-label { font-size: 13px; color: #666; margin-left: auto; }
</style>
</head>
<body>

<div class="topbar">
  <h1>Job Tracker Dashboard</h1>
  <span class="updated" id="updated-label"></span>
</div>

<div class="main">

  <!-- Pipeline -->
  <div class="pipeline" id="pipeline-boxes"></div>

  <!-- Controls -->
  <div class="controls">
    <input type="text" id="search" placeholder="Search title or company..." oninput="applyFilters()">
    <div class="campaign-tabs" id="campaign-tabs"></div>
    <span class="count-label" id="count-label"></span>
  </div>

  <!-- Table -->
  <div class="card">
    <table>
      <thead>
        <tr>
          <th>Match</th>
          <th>Title</th>
          <th>Company</th>
          <th>Location</th>
          <th>Posted</th>
          <th>Campaign</th>
          <th>Status</th>
          <th>Source</th>
        </tr>
      </thead>
      <tbody id="job-tbody"></tbody>
    </table>
  </div>

</div>

<div class="toast" id="toast"></div>

<script>
const STATUS_COLORS = {
  "New":             "#3498db",
  "Applied":         "#e67e22",
  "Interviewing":    "#27ae60",
  "Offer":           "#f1c40f",
  "Rejected/Passed": "#95a5a6",
  "Not a Fit":       "#c0392b",
};
const STATUS_ORDER  = ["New","Applied","Interviewing","Offer","Rejected/Passed"];
const SCORE_COLORS  = ["#bdc3c7","#e67e22","#f1c40f","#2ecc71","#27ae60"];

let allJobs = [];
let activeStatus   = "all";
let activeCampaign = "all";

// ---- Load data ----
async function loadData() {
  const res  = await fetch("/api/jobs");
  const data = await res.json();
  allJobs = data.jobs;

  document.getElementById("updated-label").textContent =
    "Last updated: " + new Date().toLocaleString();

  renderPipeline(data.pipeline);
  renderCampaignTabs();
  renderTable();
}

// ---- Pipeline ----
function renderPipeline(pipeline) {
  const box = document.getElementById("pipeline-boxes");
  const total = Object.values(pipeline).reduce((a,b)=>a+b,0);

  let html = `<div class="pip pip-all ${activeStatus==='all'?'active':''}"
    onclick="filterStatus('all')">
    <div class="num">${total}</div><div class="lbl">All Jobs</div></div>`;

  STATUS_ORDER.forEach(s => {
    const cnt = pipeline[s] || 0;
    html += `<div class="pip ${activeStatus===s?'active':''}"
      style="background:${STATUS_COLORS[s]}"
      onclick="filterStatus('${s}')">
      <div class="num">${cnt}</div><div class="lbl">${s}</div></div>`;
  });
  box.innerHTML = html;
}

// ---- Campaign tabs ----
function renderCampaignTabs() {
  const campaigns = ["all", ...new Set(allJobs.map(j => j.campaign))];
  const box = document.getElementById("campaign-tabs");
  box.innerHTML = campaigns.map(c =>
    `<div class="tab ${activeCampaign===c?'active':''}" onclick="filterCampaign('${c}')">
      ${c === "all" ? "All Campaigns" : c}</div>`
  ).join("");
}

// ---- Table ----
function renderTable() {
  const q   = document.getElementById("search").value.toLowerCase();
  const tbody = document.getElementById("job-tbody");

  const visible = allJobs.filter(j => {
    if (activeStatus   !== "all" && j.status   !== activeStatus)   return false;
    if (activeCampaign !== "all" && j.campaign !== activeCampaign) return false;
    if (q && !j.title.toLowerCase().includes(q) && !j.company.toLowerCase().includes(q)) return false;
    return true;
  });

  document.getElementById("count-label").textContent = `${visible.length} jobs`;

  tbody.innerHTML = visible.map(j => {
    const posted = j.posted_at ? j.posted_at.slice(0,10) : "";
    const color  = STATUS_COLORS[j.status] || "#3498db";
    const score  = j.score || 1;

    // Score dots (filled up to score, grey after)
    const dots = Array.from({length:5}, (_,i) =>
      `<span class="score-dot" style="background:${i < score ? SCORE_COLORS[score-1] : '#e0e0e0'}"></span>`
    ).join("");

    // Status options
    const opts = STATUS_ORDER.map(s =>
      `<div class="status-opt" onclick="setStatus('${j.id}','${s}',event)">
        <span class="status-dot" style="background:${STATUS_COLORS[s]}"></span>${s}</div>`
    ).join("") +
    `<div class="status-opt danger" onclick="setStatus('${j.id}','Not a Fit',event)">
      <span class="status-dot" style="background:#c0392b"></span>&#10005; Not a Fit / Remove</div>`;

    return `<tr id="row-${j.id}">
      <td><span class="score-badge" title="Match score: ${score}/5">${dots}</span></td>
      <td><a href="${j.url}" target="_blank">${j.title}</a></td>
      <td>${j.company}</td>
      <td>${j.location}</td>
      <td>${posted}</td>
      <td style="font-size:12px;color:#666">${j.campaign}</td>
      <td>
        <div class="status-wrap">
          <span class="badge" id="badge-${j.id}" style="background:${color}"
            onclick="toggleMenu('${j.id}',event)">${j.status}</span>
          <div class="status-menu" id="menu-${j.id}">${opts}</div>
        </div>
      </td>
      <td style="color:#999;font-size:12px">${j.source}</td>
    </tr>`;
  }).join("");
}

// ---- Filters ----
function filterStatus(s) {
  activeStatus = s;
  document.querySelectorAll(".pip").forEach(el => el.classList.remove("active"));
  event.currentTarget.classList.add("active");
  renderTable();
}

function filterCampaign(c) {
  activeCampaign = c;
  renderCampaignTabs();
  renderTable();
}

function applyFilters() { renderTable(); }

// ---- Status dropdown ----
function toggleMenu(id, e) {
  e.stopPropagation();
  const menu = document.getElementById("menu-" + id);
  const isOpen = menu.classList.contains("open");
  document.querySelectorAll(".status-menu").forEach(m => {
    m.classList.remove("open");
    m.style.top = ""; m.style.bottom = ""; m.style.marginTop = ""; m.style.marginBottom = "";
  });
  if (!isOpen) {
    menu.classList.add("open");
    const badge = document.getElementById("badge-" + id);
    const badgeRect = badge.getBoundingClientRect();
    const menuHeight = 280; // approximate max height of dropdown
    if (badgeRect.bottom + menuHeight > window.innerHeight) {
      menu.style.top = "auto";
      menu.style.bottom = "100%";
      menu.style.marginTop = "0";
      menu.style.marginBottom = "4px";
    }
  }
}

document.addEventListener("click", () => {
  document.querySelectorAll(".status-menu").forEach(m => m.classList.remove("open"));
});

async function setStatus(id, newStatus, e) {
  e.stopPropagation();
  document.getElementById("menu-" + id).classList.remove("open");

  await fetch("/api/update_status", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, status: newStatus }),
  });

  const job = allJobs.find(j => j.id === id);
  if (job) job.status = newStatus;

  if (newStatus === "Not a Fit") {
    allJobs = allJobs.filter(j => j.id !== id);
    showToast("Job removed from dashboard", "#c0392b");
  } else {
    const job = allJobs.find(j => j.id === id);
    if (job) job.status = newStatus;
    showToast(`Updated: ${newStatus}`);
  }

  // Rebuild everything from the updated allJobs array
  const pipeline = {};
  allJobs.forEach(j => { pipeline[j.status] = (pipeline[j.status]||0)+1; });
  renderPipeline(pipeline);
  renderTable();
}

// ---- Toast ----
function showToast(msg, color) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.style.background = color || "#27ae60";
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2500);
}

// ---- Init ----
loadData();
setInterval(loadData, 60000);  // auto-refresh every minute
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return DASHBOARD_HTML


@app.route("/api/jobs")
def api_jobs():
    jobs     = get_jobs()
    pipeline = get_pipeline()
    return jsonify({"jobs": jobs, "pipeline": pipeline})


VALID_STATUSES = STATUS_ORDER + ["Not a Fit"]

@app.route("/api/update_status", methods=["POST"])
def api_update_status():
    data   = request.get_json()
    job_id = data.get("id")
    status = data.get("status")
    if job_id and status in VALID_STATUSES:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(
            "UPDATE seen_jobs SET status=%s, status_updated_at=%s WHERE id=%s",
            (status, datetime.now(timezone.utc).isoformat(), job_id),
        )
        conn.commit()
        cur.close(); conn.close()
        return jsonify({"ok": True})
    return jsonify({"ok": False}), 400


def open_browser():
    webbrowser.open("http://localhost:5000")


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    is_local = port == 5000
    print("\n" + "="*50)
    print("  Job Tracker Dashboard")
    print(f"  Opening at http://localhost:{port}")
    print("  Press Ctrl+C to stop")
    print("="*50 + "\n")
    if is_local:
        threading.Timer(1.2, open_browser).start()
    app.run(host="0.0.0.0", port=port, debug=False)
