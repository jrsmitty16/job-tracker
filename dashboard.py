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
        "COALESCE(score,0) as score, COALESCE(rationale,'') as rationale, "
        "COALESCE(best_resume,'') as best_resume, "
        "COALESCE(resume_score,0) as resume_score, "
        "COALESCE(resume_rationale,'') as resume_rationale, "
        "COALESCE(nudge,'') as nudge, "
        "COALESCE(funding_stage,'') as funding_stage, "
        "COALESCE(headcount,'') as headcount, "
        "COALESCE(recent_news,'') as recent_news, "
        "COALESCE(company_summary,'') as company_summary "
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

/* Nudge panel */
.nudge-panel { background: #fff8e1; border: 1px solid #f0c040;
               border-radius: 10px; padding: 16px 20px; margin-bottom: 24px; }
.nudge-panel-hdr { display: flex; align-items: center; gap: 8px;
                   margin-bottom: 12px; }
.nudge-panel-hdr h3 { font-size: 14px; font-weight: 700; color: #9a6700;
                      flex: 1; }
.nudge-panel-hdr .collapse-btn { font-size: 12px; color: #9a6700; cursor: pointer;
                                  background: none; border: none; padding: 2px 8px;
                                  border-radius: 4px; }
.nudge-panel-hdr .collapse-btn:hover { background: #f0e0a0; }
.nudge-item { display: flex; align-items: flex-start; gap: 10px;
              padding: 8px 0; border-bottom: 1px solid #f0e0a0; }
.nudge-item:last-child { border-bottom: none; padding-bottom: 0; }
.nudge-meta { flex: 1; min-width: 0; }
.nudge-title-line { font-size: 13px; font-weight: 600; white-space: nowrap;
                    overflow: hidden; text-overflow: ellipsis; }
.nudge-title-line a { color: #2980b9; text-decoration: none; }
.nudge-title-line a:hover { text-decoration: underline; }
.nudge-text { font-size: 12px; color: #666; margin-top: 2px; }
.nudge-warn { font-size: 15px; flex-shrink: 0; margin-top: 1px; }

/* Analytics */
.stat-row { display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
.stat-card { background: #fff; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,.08);
             padding: 20px 28px; flex: 1; min-width: 160px; text-align: center; }
.stat-num { font-size: 38px; font-weight: 700; color: #2c3e50; line-height: 1; }
.stat-lbl { font-size: 11px; color: #999; margin-top: 6px; text-transform: uppercase;
            letter-spacing: .5px; }
.chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
@media (max-width: 900px) { .chart-grid { grid-template-columns: 1fr; } }
.chart-card { background: #fff; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,.08);
              padding: 20px 24px; }
.chart-card h4 { font-size: 11px; font-weight: 700; color: #888; margin-bottom: 16px;
                 text-transform: uppercase; letter-spacing: .6px; }
.analytics-spinner { text-align: center; padding: 80px 0; color: #aaa; font-size: 15px; }
.tab.analytics-tab { background: #8e44ad; color: #fff; border-color: #8e44ad; }
.tab.analytics-tab:hover { background: #7d3c98; border-color: #7d3c98; }

/* View toggle (Table / Board) */
.view-toggle { display: flex; border-radius: 6px; overflow: hidden;
               border: 1px solid rgba(255,255,255,.35); }
.view-btn { background: transparent; color: rgba(255,255,255,.65); border: none;
            padding: 6px 14px; cursor: pointer; font-size: 13px; font-weight: 500;
            transition: all .15s; white-space: nowrap; }
.view-btn:hover { background: rgba(255,255,255,.12); color: #fff; }
.view-btn.active { background: rgba(255,255,255,.22); color: #fff; }

/* Kanban board */
.kanban-board { display: flex; gap: 16px; overflow-x: auto; padding-bottom: 16px;
                align-items: flex-start; }
.kanban-col { flex: 0 0 270px; background: #e8eaed; border-radius: 10px;
              padding: 12px; }
.kanban-col-hdr { display: flex; align-items: center; justify-content: space-between;
                  margin-bottom: 10px; padding: 0 2px; }
.kanban-col-title { font-size: 13px; font-weight: 700; }
.kanban-col-count { font-size: 11px; background: rgba(0,0,0,.13); color: #555;
                    border-radius: 10px; padding: 2px 8px; font-weight: 600; min-width: 22px;
                    text-align: center; }
.kanban-cards { min-height: 60px; display: flex; flex-direction: column; gap: 8px; }
.kanban-card { background: #fff; border-radius: 8px; padding: 11px 12px;
               box-shadow: 0 1px 3px rgba(0,0,0,.1); cursor: grab; user-select: none;
               transition: box-shadow .15s; }
.kanban-card:hover { box-shadow: 0 3px 10px rgba(0,0,0,.16); }
.kanban-card.sortable-chosen { box-shadow: 0 6px 20px rgba(0,0,0,.2); cursor: grabbing; }
.kanban-card.sortable-ghost { opacity: .38; background: #d0d4d9; }
.kanban-card-title { font-size: 13px; font-weight: 600; margin-bottom: 2px;
                     white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kanban-card-title a { color: #2c3e50; text-decoration: none; }
.kanban-card-title a:hover { color: #2980b9; text-decoration: underline; }
.kanban-card-company { font-size: 11px; color: #888; margin-bottom: 8px;
                       white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kanban-card-meta { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; }
.kanban-source { font-size: 10px; background: #f0f2f5; color: #999; border-radius: 4px;
                 padding: 2px 5px; white-space: nowrap; }
.kanban-resume { font-size: 10px; color: #8e44ad; white-space: nowrap;
                 overflow: hidden; text-overflow: ellipsis; max-width: 100px; }
.kanban-nudge { font-size: 12px; cursor: help; line-height: 1; }
.kanban-info { font-size: 12px; cursor: help; line-height: 1; }
.kanban-card-funding { font-size: 10px; color: #aaa; margin-bottom: 6px;
                       white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* Company research drawer */
.expand-btn { background: none; border: none; cursor: pointer; color: #bbb;
              font-size: 11px; padding: 3px 5px; border-radius: 4px;
              transition: all .15s; line-height: 1; }
.expand-btn:hover { background: #eef2f7; color: #555; }
.expand-btn.open { color: #2980b9; }
.drawer-td { padding: 0 !important; border-bottom: 1px solid #e8eaed !important; }
.job-drawer { max-height: 0; overflow: hidden;
              transition: max-height .25s ease, padding .25s ease;
              padding: 0 20px; background: #f8fbff;
              border-top: 1px solid transparent; }
.job-drawer.open { max-height: 220px; padding: 14px 20px;
                   border-top-color: #e8eaed; }
.drawer-grid { display: flex; gap: 28px; flex-wrap: wrap; }
.drawer-section { flex: 1; min-width: 180px; max-width: 400px; }
.drawer-label { font-size: 10px; font-weight: 700; color: #aaa;
                text-transform: uppercase; letter-spacing: .5px; margin-bottom: 4px; }
.drawer-value { font-size: 13px; color: #444; line-height: 1.5; }
.drawer-empty { font-size: 13px; color: #aaa; font-style: italic; }
</style>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.0/Sortable.min.js"></script>
</head>
<body>

<div class="topbar">
  <h1>Job Tracker Dashboard</h1>
  <div class="view-toggle">
    <button id="btn-table" class="view-btn active" onclick="setView('table')">☰ Table</button>
    <button id="btn-board" class="view-btn"        onclick="setView('board')">⬛ Board</button>
  </div>
  <span class="updated" id="updated-label"></span>
</div>

<div class="main">

  <!-- Pipeline -->
  <div class="pipeline" id="pipeline-boxes"></div>

  <!-- Nudges -->
  <div id="nudge-panel"></div>

  <!-- Controls -->
  <div class="controls">
    <input type="text" id="search" placeholder="Search title or company..." oninput="applyFilters()">
    <div class="campaign-tabs" id="campaign-tabs"></div>
    <span class="count-label" id="count-label"></span>
  </div>

  <!-- Analytics Panel -->
  <div id="analytics-panel" style="display:none">
    <div id="analytics-loading" class="analytics-spinner">Loading analytics…</div>
    <div id="analytics-content" style="display:none">
      <div class="stat-row">
        <div class="stat-card">
          <div class="stat-num" id="stat-total">—</div>
          <div class="stat-lbl">Total Jobs Tracked</div>
        </div>
        <div class="stat-card">
          <div class="stat-num" id="stat-conversion">—</div>
          <div class="stat-lbl">Conversion Rate</div>
        </div>
        <div class="stat-card">
          <div class="stat-num" id="stat-nudges">—</div>
          <div class="stat-lbl">Active Nudges</div>
        </div>
      </div>
      <div class="chart-grid">
        <div class="chart-card" style="grid-column:1/-1">
          <h4>Jobs Scraped Per Day — Last 30 Days</h4>
          <canvas id="chart-timeline" height="80"></canvas>
        </div>
        <div class="chart-card">
          <h4>Status Breakdown</h4>
          <canvas id="chart-status"></canvas>
        </div>
        <div class="chart-card">
          <h4>Jobs by Source</h4>
          <canvas id="chart-sources"></canvas>
        </div>
        <div class="chart-card">
          <h4>Relevance Score Distribution</h4>
          <canvas id="chart-scores"></canvas>
        </div>
        <div class="chart-card">
          <h4>Best Resume Recommendations</h4>
          <canvas id="chart-resumes"></canvas>
        </div>
        <div class="chart-card" style="grid-column:1/-1">
          <h4>Top Companies — Last 30 Days</h4>
          <canvas id="chart-companies" height="60"></canvas>
        </div>
      </div>
    </div>
  </div>

  <!-- Kanban Board -->
  <div id="kanban-wrap" style="display:none">
    <div class="kanban-board" id="kanban-board">
      <div class="kanban-col" data-status="New">
        <div class="kanban-col-hdr">
          <span class="kanban-col-title" style="color:#3498db">New</span>
          <span class="kanban-col-count" id="kcount-New">0</span>
        </div>
        <div class="kanban-cards" id="cards-New"></div>
      </div>
      <div class="kanban-col" data-status="Researching">
        <div class="kanban-col-hdr">
          <span class="kanban-col-title" style="color:#16a085">Researching</span>
          <span class="kanban-col-count" id="kcount-Researching">0</span>
        </div>
        <div class="kanban-cards" id="cards-Researching"></div>
      </div>
      <div class="kanban-col" data-status="Applied">
        <div class="kanban-col-hdr">
          <span class="kanban-col-title" style="color:#e67e22">Applied</span>
          <span class="kanban-col-count" id="kcount-Applied">0</span>
        </div>
        <div class="kanban-cards" id="cards-Applied"></div>
      </div>
      <div class="kanban-col" data-status="Interviewing">
        <div class="kanban-col-hdr">
          <span class="kanban-col-title" style="color:#27ae60">Interviewing</span>
          <span class="kanban-col-count" id="kcount-Interviewing">0</span>
        </div>
        <div class="kanban-cards" id="cards-Interviewing"></div>
      </div>
    </div>
  </div>

  <!-- Table -->
  <div id="job-table-wrap">
  <div class="card">
    <table>
      <thead>
        <tr>
          <th style="width:32px"></th>
          <th>Match</th>
          <th>Title</th>
          <th>Company</th>
          <th>Location</th>
          <th>Posted</th>
          <th>Campaign</th>
          <th>Resume</th>
          <th>Status</th>
          <th>Source</th>
        </tr>
      </thead>
      <tbody id="job-tbody"></tbody>
    </table>
  </div>
  </div>

</div>

<div class="toast" id="toast"></div>

<script>
const STATUS_COLORS = {
  "New":             "#3498db",
  "Researching":     "#16a085",
  "Applied":         "#e67e22",
  "Interviewing":    "#27ae60",
  "Offer":           "#f1c40f",
  "Rejected/Passed": "#95a5a6",
  "Not a Fit":       "#c0392b",
};
const BOARD_COLUMNS = ["New","Researching","Applied","Interviewing"];
const STATUS_ORDER  = ["New","Applied","Interviewing","Offer","Rejected/Passed"];
const SCORE_COLORS  = ["#bdc3c7","#e67e22","#f1c40f","#2ecc71","#27ae60"];

let allJobs = [];
let activeStatus     = "all";
let activeCampaign   = "all";
let showingAnalytics = false;
let analyticsCharts  = {};
let currentView      = localStorage.getItem("jobTrackerView") || "table";
let sortableInstances = [];

// ---- Load data ----
async function loadData() {
  if (showingAnalytics) return;   // don't clobber analytics view on auto-refresh
  const res  = await fetch("/api/jobs");
  const data = await res.json();
  allJobs = data.jobs;

  document.getElementById("updated-label").textContent =
    "Last updated: " + new Date().toLocaleString();

  renderPipeline(data.pipeline);
  renderCampaignTabs();
  renderNudges();
  if (currentView === "board") renderBoard();
  else                         renderTable();
}

// ---- Nudge panel ----
let nudgePanelCollapsed = false;
function renderNudges() {
  const nudgedJobs = allJobs.filter(j => j.nudge && j.nudge.trim());
  const panel = document.getElementById("nudge-panel");
  if (!nudgedJobs.length) { panel.innerHTML = ""; return; }

  const bodyId = "nudge-body";
  const chevron = nudgePanelCollapsed ? "▶" : "▼";
  const bodyDisplay = nudgePanelCollapsed ? "none" : "block";

  panel.innerHTML = `
    <div class="nudge-panel">
      <div class="nudge-panel-hdr">
        <h3>⚠️ Action Needed &nbsp;<span style="font-weight:400;font-size:12px">(${nudgedJobs.length} job${nudgedJobs.length>1?'s':''})</span></h3>
        <button class="collapse-btn" onclick="toggleNudgePanel()">${chevron} ${nudgePanelCollapsed?'Show':'Hide'}</button>
      </div>
      <div id="${bodyId}" style="display:${bodyDisplay}">
        ${nudgedJobs.map(j => {
          const sc = STATUS_COLORS[j.status] || "#3498db";
          return `<div class="nudge-item">
            <span class="nudge-warn">⚠️</span>
            <div class="nudge-meta">
              <div class="nudge-title-line">
                <a href="${j.url}" target="_blank">${j.title}</a>
                &nbsp;at&nbsp;${j.company}
                &nbsp;<span class="badge" style="background:${sc};font-size:11px;padding:2px 8px;vertical-align:middle">${j.status}</span>
              </div>
              <div class="nudge-text">${j.nudge}</div>
            </div>
          </div>`;
        }).join("")}
      </div>
    </div>`;
}

function toggleNudgePanel() {
  nudgePanelCollapsed = !nudgePanelCollapsed;
  renderNudges();
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
    `<div class="tab ${activeCampaign===c && !showingAnalytics?'active':''}" onclick="filterCampaign('${c}')">
      ${c === "all" ? "All Campaigns" : c}</div>`
  ).join("") +
  `<div class="tab${showingAnalytics?' analytics-tab':''}" onclick="openAnalyticsTab()" style="margin-left:12px">
    📊 Analytics</div>`;
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
    const rationale = j.rationale || "";
    const tooltipText = rationale ? `${score}/5 — ${rationale}` : `Match score: ${score}/5`;
    const dots = Array.from({length:5}, (_,i) =>
      `<span class="score-dot" style="background:${i < score ? SCORE_COLORS[score-1] : '#e0e0e0'}"></span>`
    ).join("");

    // Resume recommendation
    const resumeName  = j.best_resume  || "";
    const resumeScore = j.resume_score || 0;
    const resumeTip   = j.resume_rationale
      ? `${resumeName} (${resumeScore}/5) — ${j.resume_rationale}`
      : resumeName ? `${resumeName} (${resumeScore}/5)` : "";
    const resumeDots  = resumeName
      ? Array.from({length:5}, (_,i) =>
          `<span class="score-dot" style="background:${i < resumeScore ? SCORE_COLORS[resumeScore-1] : '#e0e0e0'}"></span>`
        ).join("")
      : "";
    const resumeCell  = resumeName
      ? `<span style="cursor:help" title="${resumeTip}">
           <strong style="font-size:12px;display:block">${resumeName}</strong>
           <span class="score-badge">${resumeDots}</span>
         </span>`
      : `<span style="color:#bbb">—</span>`;

    // Nudge icon (⚠️ with tooltip when nudge exists)
    const nudgeIcon = j.nudge
      ? `<span title="${j.nudge.replace(/"/g,'&quot;').replace(/'/g,'&#39;')}"
               style="margin-left:5px;cursor:help;font-size:13px;vertical-align:middle">⚠️</span>`
      : "";

    // Status options
    const opts = STATUS_ORDER.map(s =>
      `<div class="status-opt" onclick="setStatus('${j.id}','${s}',event)">
        <span class="status-dot" style="background:${STATUS_COLORS[s]}"></span>${s}</div>`
    ).join("") +
    `<div class="status-opt danger" onclick="setStatus('${j.id}','Not a Fit',event)">
      <span class="status-dot" style="background:#c0392b"></span>&#10005; Not a Fit / Remove</div>`;

    return `<tr id="row-${j.id}">
      <td style="width:32px;padding:0 6px;text-align:center">
        <button class="expand-btn" id="expand-${j.id}"
          onclick="toggleDrawer('${j.id}',event)" title="Company research">▶</button>
      </td>
      <td><span class="score-badge" title="${tooltipText}" style="cursor:help">${dots}</span></td>
      <td><a href="${j.url}" target="_blank">${j.title}</a></td>
      <td>${j.company}</td>
      <td>${j.location}</td>
      <td>${posted}</td>
      <td style="font-size:12px;color:#666">${j.campaign}</td>
      <td>${resumeCell}</td>
      <td>
        <div class="status-wrap">
          <span class="badge" id="badge-${j.id}" style="background:${color}"
            onclick="toggleMenu('${j.id}',event)">${j.status}</span>
          <div class="status-menu" id="menu-${j.id}">${opts}</div>
        </div>${nudgeIcon}
      </td>
      <td style="color:#999;font-size:12px">${j.source}</td>
    </tr>
    <tr id="drawer-row-${j.id}" style="display:none">
      <td colspan="10" class="drawer-td">
        <div class="job-drawer" id="drawer-${j.id}">${buildDrawerContent(j)}</div>
      </td>
    </tr>`;
  }).join("");
  openDrawerId = null;  // reset on every re-render
}

function buildDrawerContent(j) {
  const hasData = j.company_summary || j.funding_stage || j.headcount || j.recent_news;
  if (!hasData) return '<div class="drawer-empty">No company data available</div>';
  const sections = [];
  if (j.company_summary)
    sections.push(`<div class="drawer-section">
      <div class="drawer-label">About</div>
      <div class="drawer-value">${j.company_summary}</div></div>`);
  const meta = [j.funding_stage, j.headcount].filter(Boolean).join(" &middot; ");
  if (meta)
    sections.push(`<div class="drawer-section">
      <div class="drawer-label">Stage &amp; Size</div>
      <div class="drawer-value">${meta}</div></div>`);
  if (j.recent_news)
    sections.push(`<div class="drawer-section">
      <div class="drawer-label">📰 Recent News</div>
      <div class="drawer-value">${j.recent_news}</div></div>`);
  return `<div class="drawer-grid">${sections.join("")}</div>`;
}

let openDrawerId = null;
function toggleDrawer(id, e) {
  e.stopPropagation();
  const drawerRow = document.getElementById("drawer-row-" + id);
  const drawerDiv = document.getElementById("drawer-" + id);
  const btn       = document.getElementById("expand-" + id);
  if (!drawerRow) return;

  // Close the previously open drawer first
  if (openDrawerId && openDrawerId !== id) {
    const pDiv = document.getElementById("drawer-" + openDrawerId);
    const pBtn = document.getElementById("expand-" + openDrawerId);
    const pId  = openDrawerId;
    if (pDiv) pDiv.classList.remove("open");
    if (pBtn) { pBtn.textContent = "▶"; pBtn.classList.remove("open"); }
    setTimeout(() => {
      const pRow = document.getElementById("drawer-row-" + pId);
      if (pRow) pRow.style.display = "none";
    }, 260);
    openDrawerId = null;
  }

  const isOpen = drawerDiv.classList.contains("open");
  if (isOpen) {
    drawerDiv.classList.remove("open");
    btn.textContent = "▶"; btn.classList.remove("open");
    setTimeout(() => { drawerRow.style.display = "none"; }, 260);
    openDrawerId = null;
  } else {
    drawerRow.style.display = "table-row";
    requestAnimationFrame(() => drawerDiv.classList.add("open"));
    btn.textContent = "▼"; btn.classList.add("open");
    openDrawerId = id;
  }
}

// ---- Filters ----
function closeAnalytics() {
  showingAnalytics = false;
  document.getElementById("analytics-panel").style.display = "none";
  if (currentView === "board") {
    document.getElementById("kanban-wrap").style.display    = "block";
    document.getElementById("job-table-wrap").style.display = "none";
    document.getElementById("search").style.display         = "none";
    document.getElementById("count-label").style.display    = "none";
    renderBoard();
  } else {
    document.getElementById("job-table-wrap").style.display = "block";
    document.getElementById("kanban-wrap").style.display    = "none";
    document.getElementById("search").style.display         = "";
    document.getElementById("count-label").style.display    = "";
    renderTable();
  }
}

function filterStatus(s) {
  if (showingAnalytics) { closeAnalytics(); renderCampaignTabs(); }
  // Pipeline box clicks always land in table view
  if (currentView === "board") setView("table");
  activeStatus = s;
  document.querySelectorAll(".pip").forEach(el => el.classList.remove("active"));
  event.currentTarget.classList.add("active");
  renderTable();
}

function filterCampaign(c) {
  if (showingAnalytics) closeAnalytics();
  activeCampaign = c;
  renderCampaignTabs();
  if (currentView === "board") renderBoard();
  else                         renderTable();
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
    if (job) { job.status = newStatus; job.nudge = ""; }
    showToast(`Updated: ${newStatus}`);
  }

  // Rebuild everything from the updated allJobs array
  const pipeline = {};
  allJobs.forEach(j => { pipeline[j.status] = (pipeline[j.status]||0)+1; });
  renderPipeline(pipeline);
  renderNudges();
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

// ---- View switcher ----
function setView(v) {
  currentView = v;
  localStorage.setItem("jobTrackerView", v);

  const tableWrap = document.getElementById("job-table-wrap");
  const boardWrap = document.getElementById("kanban-wrap");
  const searchEl  = document.getElementById("search");
  const countEl   = document.getElementById("count-label");
  const btnTable  = document.getElementById("btn-table");
  const btnBoard  = document.getElementById("btn-board");

  if (v === "board") {
    tableWrap.style.display = "none";
    boardWrap.style.display = "block";
    searchEl.style.display  = "none";
    countEl.style.display   = "none";
    btnTable.classList.remove("active");
    btnBoard.classList.add("active");
    renderBoard();
  } else {
    boardWrap.style.display = "none";
    tableWrap.style.display = "block";
    searchEl.style.display  = "";
    countEl.style.display   = "";
    btnBoard.classList.remove("active");
    btnTable.classList.add("active");
    renderTable();
  }
}

// ---- Kanban board ----
function renderBoard() {
  // Tear down old Sortable instances before re-rendering
  sortableInstances.forEach(s => { try { s.destroy(); } catch(_) {} });
  sortableInstances = [];

  // Apply campaign filter; show only BOARD_COLUMNS statuses
  const jobs = allJobs.filter(j =>
    (activeCampaign === "all" || j.campaign === activeCampaign) &&
    BOARD_COLUMNS.includes(j.status)
  );

  // Group by status
  const byStatus = {};
  BOARD_COLUMNS.forEach(s => { byStatus[s] = []; });
  jobs.forEach(j => { if (byStatus[j.status]) byStatus[j.status].push(j); });

  // Populate each column
  BOARD_COLUMNS.forEach(status => {
    const cardsEl = document.getElementById("cards-" + status);
    const countEl = document.getElementById("kcount-" + status);
    const colJobs = byStatus[status];
    countEl.textContent = colJobs.length;
    cardsEl.innerHTML   = colJobs.map(buildCard).join("");

    const inst = Sortable.create(cardsEl, {
      group:       { name: "kanban", pull: true, put: true },
      animation:   150,
      ghostClass:  "sortable-ghost",
      chosenClass: "sortable-chosen",
      onEnd:       handleCardDrop,
    });
    sortableInstances.push(inst);
  });
}

function buildCard(j) {
  const score = j.score || 0;
  const dots  = score > 0
    ? Array.from({length:5}, (_,i) =>
        `<span class="score-dot" style="background:${i<score?SCORE_COLORS[score-1]:'#e0e0e0'}"></span>`
      ).join("")
    : "";
  const resumePart = j.best_resume
    ? `<span class="kanban-resume" title="${j.best_resume}">📄 ${j.best_resume}</span>`
    : "";
  const nudgePart = j.nudge
    ? `<span class="kanban-nudge" title="${j.nudge.replace(/"/g,"&quot;").replace(/'/g,"&#39;")}">⚠️</span>`
    : "";

  // Funding + headcount line
  const fundingLine = [j.funding_stage, j.headcount].filter(Boolean).join(" · ");
  const fundingHtml = fundingLine
    ? `<div class="kanban-card-funding">${fundingLine}</div>` : "";

  // ℹ️ tooltip with company summary + recent news
  const infoLines = [];
  if (j.company_summary) infoLines.push(j.company_summary);
  if (j.recent_news)     infoLines.push("📰 " + j.recent_news);
  const infoHtml = infoLines.length
    ? `<span class="kanban-info" title="${infoLines.join(" | ").replace(/"/g,"&quot;").replace(/'/g,"&#39;")}">ℹ️</span>`
    : "";

  return `<div class="kanban-card" data-id="${j.id}" data-status="${j.status}">
    <div class="kanban-card-title">
      <a href="${j.url}" target="_blank" onclick="event.stopPropagation()">${j.title}</a>
    </div>
    <div class="kanban-card-company">${j.company || ""}</div>
    ${fundingHtml}
    <div class="kanban-card-meta">
      <span class="score-badge">${dots}</span>
      <span class="kanban-source">${j.source || ""}</span>
      ${resumePart}${nudgePart}${infoHtml}
    </div>
  </div>`;
}

async function handleCardDrop(evt) {
  if (evt.from === evt.to) return;   // same column — nothing to do

  const card      = evt.item;
  const newStatus = evt.to.closest(".kanban-col").dataset.status;
  const oldStatus = card.dataset.status;
  const jobId     = card.dataset.id;

  // Optimistic update
  card.dataset.status = newStatus;
  updateKanbanCounts();

  try {
    const res  = await fetch("/api/update_status", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: jobId, status: newStatus }),
    });
    const data = await res.json();
    if (!data.ok) throw new Error("Server rejected");

    // Sync allJobs in memory
    const job = allJobs.find(j => j.id === jobId);
    if (job) { job.status = newStatus; job.nudge = ""; }

    // Refresh pipeline summary and nudge panel
    const pipeline = {};
    allJobs.forEach(j => { pipeline[j.status] = (pipeline[j.status]||0)+1; });
    renderPipeline(pipeline);
    renderNudges();
    showToast(`Moved to ${newStatus}`);

  } catch(err) {
    // Rollback — put card back where it came from
    card.dataset.status = oldStatus;
    const origCol = document.getElementById("cards-" + oldStatus);
    if (origCol) {
      const ref = origCol.children[evt.oldIndex] || null;
      origCol.insertBefore(card, ref);
    }
    updateKanbanCounts();
    showToast("Status update failed — card returned", "#e74c3c");
  }
}

function updateKanbanCounts() {
  BOARD_COLUMNS.forEach(status => {
    const cardsEl = document.getElementById("cards-" + status);
    const countEl = document.getElementById("kcount-" + status);
    if (cardsEl && countEl) countEl.textContent = cardsEl.children.length;
  });
}

// ---- Analytics ----
async function openAnalyticsTab() {
  showingAnalytics = true;
  document.getElementById("job-table-wrap").style.display  = "none";
  document.getElementById("kanban-wrap").style.display     = "none";
  document.getElementById("search").style.display          = "none";
  document.getElementById("count-label").style.display     = "none";
  document.getElementById("analytics-panel").style.display = "block";
  renderCampaignTabs();
  await loadAnalytics();
}

async function loadAnalytics() {
  document.getElementById("analytics-loading").style.display = "block";
  document.getElementById("analytics-content").style.display = "none";
  try {
    const res  = await fetch("/api/analytics");
    const data = await res.json();
    document.getElementById("analytics-loading").style.display = "none";
    document.getElementById("analytics-content").style.display = "block";
    document.getElementById("stat-total").textContent      = data.total_jobs.toLocaleString();
    document.getElementById("stat-conversion").textContent = data.conversion_rate + "%";
    document.getElementById("stat-nudges").textContent     = data.nudges_active;
    renderTimelineChart(data.jobs_over_time);
    renderStatusChart(data.status_breakdown);
    renderScoreChart(data.score_distribution);
    renderSourceChart(data.source_breakdown);
    renderResumeChart(data.resume_breakdown);
    renderCompaniesChart(data.top_companies);
  } catch(err) {
    document.getElementById("analytics-loading").innerHTML =
      '<span style="color:#e74c3c">Failed to load analytics. Try refreshing.</span>';
    console.error("Analytics error:", err);
  }
}

function destroyChart(key) {
  if (analyticsCharts[key]) { analyticsCharts[key].destroy(); delete analyticsCharts[key]; }
}

function renderTimelineChart(data) {
  destroyChart("timeline");
  const labels = Object.keys(data).sort();
  analyticsCharts.timeline = new Chart(document.getElementById("chart-timeline"), {
    type: "line",
    data: { labels, datasets: [{ label: "Jobs", data: labels.map(k => data[k]),
      borderColor: "#2980b9", backgroundColor: "rgba(41,128,185,.12)",
      fill: true, tension: .35, pointRadius: 3, pointHoverRadius: 5 }] },
    options: { responsive: true, plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } }
  });
}

function renderStatusChart(data) {
  destroyChart("status");
  const order  = ["New","Applied","Interviewing","Offer","Rejected/Passed"];
  const labels = order.filter(k => data[k] !== undefined);
  analyticsCharts.status = new Chart(document.getElementById("chart-status"), {
    type: "doughnut",
    data: { labels, datasets: [{ data: labels.map(k => data[k]),
      backgroundColor: labels.map(k => STATUS_COLORS[k] || "#aaa"), borderWidth: 2 }] },
    options: { responsive: true, plugins: { legend: { position: "right" } } }
  });
}

function renderScoreChart(data) {
  destroyChart("scores");
  const labels = ["1","2","3","4","5"];
  analyticsCharts.scores = new Chart(document.getElementById("chart-scores"), {
    type: "bar",
    data: { labels: labels.map(l => l + (l==="1" ? " dot" : " dots")),
      datasets: [{ data: labels.map(k => data[k] || 0),
        backgroundColor: SCORE_COLORS, borderRadius: 4 }] },
    options: { responsive: true, plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } }
  });
}

function renderSourceChart(data) {
  destroyChart("sources");
  const labels  = Object.keys(data);
  const palette = ["#3498db","#e67e22","#2ecc71","#9b59b6","#1abc9c","#e74c3c","#f39c12","#34495e"];
  analyticsCharts.sources = new Chart(document.getElementById("chart-sources"), {
    type: "doughnut",
    data: { labels, datasets: [{ data: labels.map(k => data[k]),
      backgroundColor: palette.slice(0, labels.length), borderWidth: 2 }] },
    options: { responsive: true, plugins: { legend: { position: "right" } } }
  });
}

function renderResumeChart(data) {
  destroyChart("resumes");
  const labels = Object.keys(data);
  analyticsCharts.resumes = new Chart(document.getElementById("chart-resumes"), {
    type: "bar",
    data: { labels, datasets: [{ data: labels.map(k => data[k]),
      backgroundColor: "#8e44ad", borderRadius: 4 }] },
    options: { responsive: true, indexAxis: "y",
      plugins: { legend: { display: false } },
      scales: { x: { beginAtZero: true, ticks: { precision: 0 } } } }
  });
}

function renderCompaniesChart(data) {
  destroyChart("companies");
  analyticsCharts.companies = new Chart(document.getElementById("chart-companies"), {
    type: "bar",
    data: { labels: data.map(d => d.company),
      datasets: [{ data: data.map(d => d.count),
        backgroundColor: "#27ae60", borderRadius: 4 }] },
    options: { responsive: true, indexAxis: "y",
      plugins: { legend: { display: false } },
      scales: { x: { beginAtZero: true, ticks: { precision: 0 } } } }
  });
}

// ---- Init ----
// Apply stored view preference immediately (before data arrives)
(function applyStoredView() {
  if (currentView === "board") {
    document.getElementById("btn-table").classList.remove("active");
    document.getElementById("btn-board").classList.add("active");
    document.getElementById("job-table-wrap").style.display = "none";
    document.getElementById("kanban-wrap").style.display    = "block";
    document.getElementById("search").style.display         = "none";
    document.getElementById("count-label").style.display    = "none";
  }
})();
loadData();
setInterval(loadData, 60000);  // auto-refresh every minute
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return DASHBOARD_HTML


def get_analytics():
    conn = get_conn()
    cur  = conn.cursor()

    # Jobs per day — last 30 days
    cur.execute("""
        SELECT DATE(CAST(found_at AS TIMESTAMPTZ)) AS day, COUNT(*) AS cnt
        FROM   seen_jobs
        WHERE  CAST(found_at AS TIMESTAMPTZ) >= NOW() - INTERVAL '30 days'
        GROUP  BY day ORDER BY day
    """)
    jobs_over_time = {str(r[0]): r[1] for r in cur.fetchall()}

    # Status breakdown (exclude dismissed)
    cur.execute("""
        SELECT COALESCE(status,'New'), COUNT(*)
        FROM   seen_jobs
        WHERE  COALESCE(status,'New') != 'Not a Fit'
        GROUP  BY COALESCE(status,'New')
    """)
    status_breakdown = {r[0]: r[1] for r in cur.fetchall()}

    # Score distribution 1-5
    cur.execute("""
        SELECT COALESCE(score,0)::text, COUNT(*)
        FROM   seen_jobs
        WHERE  COALESCE(status,'New') != 'Not a Fit'
        GROUP  BY COALESCE(score,0)
        ORDER  BY COALESCE(score,0)
    """)
    score_distribution = {r[0]: r[1] for r in cur.fetchall()}

    # Source breakdown
    cur.execute("""
        SELECT COALESCE(source,'Unknown'), COUNT(*)
        FROM   seen_jobs
        WHERE  COALESCE(status,'New') != 'Not a Fit'
        GROUP  BY COALESCE(source,'Unknown')
        ORDER  BY COUNT(*) DESC
    """)
    source_breakdown = {r[0]: r[1] for r in cur.fetchall()}

    # Resume recommendations
    cur.execute("""
        SELECT COALESCE(NULLIF(best_resume,''),'Unmatched'), COUNT(*)
        FROM   seen_jobs
        WHERE  COALESCE(status,'New') != 'Not a Fit'
        GROUP  BY COALESCE(NULLIF(best_resume,''),'Unmatched')
        ORDER  BY COUNT(*) DESC
    """)
    resume_breakdown = {r[0]: r[1] for r in cur.fetchall()}

    # Totals for conversion rate
    cur.execute("SELECT COUNT(*) FROM seen_jobs WHERE COALESCE(status,'New') != 'Not a Fit'")
    total_jobs = cur.fetchone()[0] or 0

    cur.execute("SELECT COUNT(*) FROM seen_jobs WHERE status IN ('Applied','Interviewing','Offer')")
    converted = cur.fetchone()[0] or 0

    conversion_rate = round(converted / total_jobs * 100, 1) if total_jobs else 0.0

    # Top 10 companies last 30 days
    cur.execute("""
        SELECT company, COUNT(*) AS cnt
        FROM   seen_jobs
        WHERE  CAST(found_at AS TIMESTAMPTZ) >= NOW() - INTERVAL '30 days'
          AND  COALESCE(status,'New') != 'Not a Fit'
          AND  company IS NOT NULL AND company <> ''
        GROUP  BY company
        ORDER  BY cnt DESC
        LIMIT  10
    """)
    top_companies = [{"company": r[0], "count": r[1]} for r in cur.fetchall()]

    # Active nudges
    cur.execute("""
        SELECT COUNT(*) FROM seen_jobs
        WHERE  nudge IS NOT NULL AND nudge <> ''
          AND  COALESCE(status,'New') != 'Not a Fit'
    """)
    nudges_active = cur.fetchone()[0] or 0

    cur.close(); conn.close()
    return {
        "jobs_over_time":    jobs_over_time,
        "status_breakdown":  status_breakdown,
        "score_distribution": score_distribution,
        "source_breakdown":  source_breakdown,
        "resume_breakdown":  resume_breakdown,
        "conversion_rate":   conversion_rate,
        "top_companies":     top_companies,
        "total_jobs":        total_jobs,
        "nudges_active":     nudges_active,
    }


@app.route("/api/jobs")
def api_jobs():
    jobs     = get_jobs()
    pipeline = get_pipeline()
    return jsonify({"jobs": jobs, "pipeline": pipeline})


@app.route("/api/analytics")
def api_analytics():
    return jsonify(get_analytics())


VALID_STATUSES = STATUS_ORDER + ["Researching", "Not a Fit"]

@app.route("/api/update_status", methods=["POST"])
def api_update_status():
    data   = request.get_json()
    job_id = data.get("id")
    status = data.get("status")
    if job_id and status in VALID_STATUSES:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(
            "UPDATE seen_jobs SET status=%s, status_updated_at=%s, nudge=NULL WHERE id=%s",
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
