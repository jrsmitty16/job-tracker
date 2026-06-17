#!/usr/bin/env python3
"""
Job Tracker Dashboard
Interactive web dashboard — run this then open http://localhost:5000 in your browser.
"""

import json
import os
import threading
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, jsonify, request
from db import get_conn

CONFIG_PATH = Path(__file__).parent / "config.yaml"

DASHBOARD_TITLE = os.environ.get("DASHBOARD_TITLE", "Job Tracker Dashboard")

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
#kanban-wrap { overflow-x: auto; }
.kanban-board { display: flex; gap: 12px; padding-bottom: 16px;
                align-items: flex-start; min-width: max-content; }
.kanban-col { flex: 0 0 240px; width: 240px; max-width: 240px;
              min-width: 240px; overflow: hidden;
              background: #e8eaed; border-radius: 10px; padding: 12px; }
.kanban-col-hdr { display: flex; align-items: center; justify-content: space-between;
                  margin-bottom: 10px; padding: 0 2px; }
.kanban-col-title { font-size: 13px; font-weight: 700; }
.kanban-col-count { font-size: 11px; background: rgba(0,0,0,.13); color: #555;
                    border-radius: 10px; padding: 2px 8px; font-weight: 600; min-width: 22px;
                    text-align: center; }
.kanban-cards { min-height: 60px; display: flex; flex-direction: column; gap: 8px; }
.kanban-card { background: #fff; border-radius: 8px; padding: 11px 12px;
               box-shadow: 0 1px 3px rgba(0,0,0,.1); cursor: grab; user-select: none;
               transition: box-shadow .15s; min-width: 0; max-width: 100%;
               overflow: hidden; }
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

/* Cover letter modal */
.cl-modal { display:none; position:fixed; inset:0; background:rgba(0,0,0,.55);
            z-index:1000; align-items:center; justify-content:center; }
.cl-modal.open { display:flex; }
.cl-modal-box { background:#fff; border-radius:12px; width:680px; max-width:94vw;
                max-height:88vh; display:flex; flex-direction:column;
                box-shadow:0 8px 40px rgba(0,0,0,.25); }
.cl-modal-hdr { padding:18px 24px 14px; border-bottom:1px solid #eee;
                display:flex; align-items:center; justify-content:space-between; }
.cl-modal-hdr h3 { font-size:16px; font-weight:700; color:#2c3e50; }
.cl-close { background:none; border:none; font-size:20px; cursor:pointer;
            color:#aaa; line-height:1; padding:2px 6px; border-radius:4px; }
.cl-close:hover { background:#f5f5f5; color:#555; }
.cl-modal-body { flex:1; overflow-y:auto; padding:20px 24px; }
.cl-spinner { text-align:center; padding:60px 0; color:#aaa; font-size:14px; }
.cl-text { font-size:14px; line-height:1.8; white-space:pre-wrap; color:#333; }
.cl-modal-footer { padding:14px 24px; border-top:1px solid #eee;
                   display:flex; gap:10px; justify-content:flex-end; }
.cl-btn { padding:8px 16px; border-radius:6px; border:none; cursor:pointer;
          font-size:13px; font-weight:600; transition:opacity .15s; }
.cl-btn:hover { opacity:.85; }
.cl-btn-copy     { background:#2980b9; color:#fff; }
.cl-btn-download { background:#27ae60; color:#fff; }
.cl-btn-regen    { background:#f0f2f5; color:#555; }
.cl-btn-sm { background:none; border:1px solid #ddd; border-radius:4px; color:#666;
             font-size:11px; padding:2px 7px; cursor:pointer; margin-top:4px;
             white-space:nowrap; transition:all .15s; display:inline-block; }
.cl-btn-sm:hover { background:#f0f2f5; border-color:#bbb; color:#333; }
.kanban-card-footer { margin-top:6px; padding-top:6px; border-top:1px solid #f0f2f5; }
.cl-card-link { background:none; border:none; color:#2980b9; font-size:11px;
                cursor:pointer; padding:0; text-decoration:underline; }
.cl-card-link:hover { color:#1a5276; }

/* Campaign editor */
.tab.campaigns-tab { background: #16a085; color: #fff; border-color: #16a085; }
.tab.campaigns-tab:hover { background: #138d75; border-color: #138d75; }
.ce-hdr { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
.ce-hdr h2 { font-size: 18px; font-weight: 700; color: #2c3e50; }
.ce-add-btn { background: #27ae60; color: #fff; border: none; padding: 9px 18px;
              border-radius: 6px; font-size: 13px; font-weight: 600; cursor: pointer; }
.ce-add-btn:hover { background: #219a52; }
.ce-card { background: #fff; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,.08);
           padding: 20px 24px; margin-bottom: 16px; }
.ce-name-row { display: flex; align-items: center; gap: 12px; margin-bottom: 16px;
               padding-bottom: 14px; border-bottom: 1px solid #f0f2f5; }
.ce-cname { font-size: 16px; font-weight: 700; color: #2c3e50; flex: 1; }
.ce-name-input { flex: 1; padding: 7px 12px; border: 1px solid #ddd; border-radius: 6px;
                 font-size: 15px; font-weight: 600; color: #2c3e50; }
.ce-section { margin-bottom: 14px; }
.ce-slabel { font-size: 11px; font-weight: 700; color: #888; text-transform: uppercase;
             letter-spacing: .5px; margin-bottom: 6px; }
.ce-chips { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 5px; min-height: 24px; }
.ce-chip { display: inline-flex; align-items: center; gap: 3px; background: #eaf2ff;
           color: #2471a3; border: 1px solid #aed6f1; border-radius: 14px;
           padding: 3px 9px; font-size: 12px; font-weight: 500; }
.ce-chip-x { background: none; border: none; cursor: pointer; color: #5d6d7e;
             font-size: 14px; line-height: 1; padding: 0 1px; }
.ce-chip-x:hover { color: #c0392b; }
.ce-input { border: 1px solid #ddd; border-radius: 14px; padding: 3px 10px;
            font-size: 12px; outline: none; width: 180px; }
.ce-input:focus { border-color: #2980b9; }
.ce-actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 12px;
              padding-top: 14px; border-top: 1px solid #f0f2f5; }
.ce-save-btn { background: #2980b9; color: #fff; border: none; padding: 8px 20px;
               border-radius: 6px; font-size: 13px; font-weight: 600; cursor: pointer; }
.ce-save-btn:hover { background: #2471a3; }
.ce-del-btn { background: none; color: #c0392b; border: 1px solid #e0b0b0; padding: 8px 14px;
              border-radius: 6px; font-size: 13px; cursor: pointer; }
.ce-del-btn:hover { background: #fdf0ef; border-color: #c0392b; }

/* Resume manager */
.tab.resumes-tab { background: #8e44ad; color: #fff; border-color: #8e44ad; }
.tab.resumes-tab:hover { background: #7d3c98; border-color: #7d3c98; }
.rm-hdr { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
.rm-hdr h2 { font-size: 18px; font-weight: 700; color: #2c3e50; }
.rm-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
@media (max-width: 800px) { .rm-layout { grid-template-columns: 1fr; } }
.rm-card { background: #fff; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,.08); padding: 20px 24px; }
.rm-card h3 { font-size: 14px; font-weight: 700; color: #2c3e50; margin-bottom: 16px; }
.rm-drop { border: 2px dashed #bdc3c7; border-radius: 8px; padding: 32px 20px;
           text-align: center; cursor: pointer; transition: all .2s; margin-bottom: 14px; }
.rm-drop:hover, .rm-drop.dragover { border-color: #8e44ad; background: #f9f0ff; }
.rm-drop p { color: #888; font-size: 13px; margin-top: 6px; }
.rm-drop strong { color: #555; font-size: 14px; }
.rm-drop input[type=file] { display: none; }
.rm-fname { width: 100%; padding: 8px 12px; border: 1px solid #ddd; border-radius: 6px;
            font-size: 13px; margin-bottom: 10px; }
.rm-fname:focus { outline: none; border-color: #8e44ad; }
.rm-preview { background: #f8f8f8; border: 1px solid #eee; border-radius: 6px;
              padding: 10px 12px; font-size: 11px; color: #666; max-height: 100px;
              overflow-y: auto; white-space: pre-wrap; margin-bottom: 10px; display: none; }
.rm-upload-btn { width: 100%; background: #8e44ad; color: #fff; border: none;
                 padding: 10px; border-radius: 6px; font-size: 13px; font-weight: 600;
                 cursor: pointer; }
.rm-upload-btn:hover { background: #7d3c98; }
.rm-upload-btn:disabled { background: #bbb; cursor: not-allowed; }
.rm-list { display: flex; flex-direction: column; gap: 10px; }
.rm-item { display: flex; align-items: center; gap: 10px; padding: 12px 14px;
           border: 1px solid #eee; border-radius: 8px; background: #fafafa; }
.rm-item-icon { font-size: 22px; flex-shrink: 0; }
.rm-item-info { flex: 1; min-width: 0; }
.rm-item-name { font-size: 13px; font-weight: 600; color: #2c3e50;
                white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rm-item-meta { font-size: 11px; color: #999; margin-top: 2px; }
.rm-item-del { background: none; border: 1px solid #e0b0b0; color: #c0392b;
               border-radius: 5px; padding: 4px 10px; font-size: 12px; cursor: pointer;
               flex-shrink: 0; }
.rm-item-del:hover { background: #fdf0ef; }
.rm-empty { color: #aaa; font-size: 13px; text-align: center; padding: 24px 0; }
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

  <!-- Resume Manager Panel -->
  <div id="resumes-panel" style="display:none">
    <div class="rm-hdr">
      <h2>Resume Manager</h2>
    </div>
    <div class="rm-layout">
      <div class="rm-card">
        <h3>Upload Resume</h3>
        <div class="rm-drop" id="rm-drop" onclick="document.getElementById('rm-file-input').click()"
             ondragover="rmDragOver(event)" ondragleave="rmDragLeave(event)" ondrop="rmDrop(event)">
          <input type="file" id="rm-file-input" accept=".pdf,.docx,.txt" onchange="rmFileSelected(event)">
          <strong>Click to browse or drag &amp; drop</strong>
          <p>PDF, DOCX, or TXT &mdash; max 4 MB</p>
        </div>
        <input class="rm-fname" id="rm-name" placeholder="Resume name (e.g. Senior Technical Recruiter)">
        <div class="rm-preview" id="rm-preview"></div>
        <button class="rm-upload-btn" id="rm-upload-btn" onclick="rmUpload()" disabled>Upload Resume</button>
      </div>
      <div class="rm-card">
        <h3>Your Resumes</h3>
        <div id="rm-list">
          <div class="rm-empty">Loading…</div>
        </div>
      </div>
    </div>
  </div>

  <!-- Campaign Editor Panel -->
  <div id="campaigns-panel" style="display:none">
    <div class="ce-hdr">
      <h2>Campaign Editor</h2>
      <button class="ce-add-btn" onclick="addNewCampaign()">+ New Campaign</button>
    </div>
    <div id="campaigns-list"></div>
  </div>

  <!-- Table -->
  <div id="job-table-wrap">
  <div class="card">
    <table>
      <thead>
        <tr>
          <th style="width:32px"></th>
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

<!-- Cover Letter Modal -->
<div class="cl-modal" id="cl-modal" onclick="if(event.target===this)closeCLModal()">
  <div class="cl-modal-box">
    <div class="cl-modal-hdr">
      <h3 id="cl-modal-title">Cover Letter</h3>
      <button class="cl-close" onclick="closeCLModal()">✕</button>
    </div>
    <div class="cl-modal-body">
      <div class="cl-spinner" id="cl-spinner">Generating cover letter…</div>
      <div class="cl-text" id="cl-text" style="display:none"></div>
    </div>
    <div class="cl-modal-footer" id="cl-modal-footer" style="display:none">
      <button class="cl-btn cl-btn-regen"    onclick="regenerateCoverLetter()">↺ Regenerate</button>
      <button class="cl-btn cl-btn-download" onclick="downloadCoverLetter()">⬇ Download</button>
      <button class="cl-btn cl-btn-copy"     onclick="copyCoverLetter()">📋 Copy</button>
    </div>
  </div>
</div>

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
let activeStatus      = "all";
let activeCampaign    = "all";
let showingAnalytics  = false;
let showingCampaigns  = false;
let showingResumes    = false;
let analyticsCharts   = {};
let currentView       = localStorage.getItem("jobTrackerView") || "table";
let sortableInstances = [];
let campaignsData     = [];

// ---- Load data ----
async function loadData() {
  if (showingAnalytics || showingCampaigns || showingResumes) return;
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
  const isNormal  = !showingAnalytics && !showingCampaigns && !showingResumes;
  const box = document.getElementById("campaign-tabs");
  const jobTabs = campaigns.map(c =>
    `<div class="tab ${activeCampaign===c && isNormal?'active':''}" onclick="filterCampaign('${c}')">
      ${c === "all" ? "All Campaigns" : c}</div>`
  ).join("");
  const specialTabs =
    `<div class="tab${showingAnalytics?' analytics-tab':''}" onclick="openAnalyticsTab()" style="margin-left:12px">📊 Analytics</div>` +
    `<div class="tab${showingCampaigns?' campaigns-tab':''}" onclick="openCampaignsTab()" style="margin-left:6px">⚙ Campaigns</div>` +
    `<div class="tab${showingResumes?' resumes-tab':''}" onclick="openResumesTab()" style="margin-left:6px">📄 Resumes</div>`;
  box.innerHTML = jobTabs + specialTabs;
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
        <div><button class="cl-btn-sm" onclick="generateCoverLetter('${j.id}',event)">✉ Cover Letter</button></div>
      </td>
      <td style="color:#999;font-size:12px">${j.source}</td>
    </tr>
    <tr id="drawer-row-${j.id}" style="display:none">
      <td colspan="9" class="drawer-td">
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
  if (showingCampaigns) closeCampaigns();
  if (showingResumes)   closeResumes();
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
    <div class="kanban-card-footer">
      <button class="cl-card-link" onclick="generateCoverLetter('${j.id}',event)">✉ cover letter</button>
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
  if (showingCampaigns) closeCampaigns();
  if (showingResumes)   closeResumes();
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

// ---- Cover Letter ----
let clJobId   = null;
let clCompany = "";
let clTitle   = "";

async function generateCoverLetter(jobId, e) {
  if (e) e.stopPropagation();
  const job = allJobs.find(j => j.id === jobId);
  clJobId   = jobId;
  clCompany = job ? (job.company || "") : "";
  clTitle   = job ? (job.title   || "") : "";

  document.getElementById("cl-modal-title").textContent =
    "Cover Letter" + (clTitle ? " — " + clTitle : "");
  document.getElementById("cl-spinner").style.display      = "block";
  document.getElementById("cl-text").style.display         = "none";
  document.getElementById("cl-modal-footer").style.display = "none";
  document.getElementById("cl-modal").classList.add("open");
  document.body.style.overflow = "hidden";

  await fetchCoverLetter();
}

async function fetchCoverLetter() {
  document.getElementById("cl-spinner").style.display      = "block";
  document.getElementById("cl-text").style.display         = "none";
  document.getElementById("cl-modal-footer").style.display = "none";
  try {
    const res  = await fetch("/api/generate-cover-letter", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: clJobId }),
    });
    const data = await res.json();
    document.getElementById("cl-spinner").style.display = "none";
    if (data.error) {
      document.getElementById("cl-text").textContent   = "Error: " + data.error;
      document.getElementById("cl-text").style.display = "block";
    } else {
      document.getElementById("cl-text").textContent      = data.cover_letter;
      document.getElementById("cl-text").style.display    = "block";
      document.getElementById("cl-modal-footer").style.display = "flex";
    }
  } catch(err) {
    document.getElementById("cl-spinner").style.display = "none";
    document.getElementById("cl-text").textContent      = "Network error. Please try again.";
    document.getElementById("cl-text").style.display    = "block";
  }
}

function closeCLModal() {
  document.getElementById("cl-modal").classList.remove("open");
  document.body.style.overflow = "";
}

function copyCoverLetter() {
  const text = document.getElementById("cl-text").textContent;
  navigator.clipboard.writeText(text).then(() => showToast("Copied to clipboard"));
}

function downloadCoverLetter() {
  const text = document.getElementById("cl-text").textContent;
  const safe = (clCompany + "_" + clTitle)
    .replace(/[^a-z0-9_\\-]/gi, "_").slice(0, 60);
  const blob = new Blob([text], { type: "text/plain" });
  const a    = document.createElement("a");
  a.href     = URL.createObjectURL(blob);
  a.download = "cover_letter_" + safe + ".txt";
  a.click();
  URL.revokeObjectURL(a.href);
}

function regenerateCoverLetter() { fetchCoverLetter(); }

// ---- Resume Manager ----
let rmFile = null;

function rmShowPanels(show) {
  ["job-table-wrap","kanban-wrap","analytics-panel","campaigns-panel"].forEach(id => {
    document.getElementById(id).style.display = "none";
  });
  document.getElementById("search").style.display      = "none";
  document.getElementById("count-label").style.display = "none";
  document.getElementById("resumes-panel").style.display = show ? "block" : "none";
}

function rmRestoreView() {
  document.getElementById("resumes-panel").style.display = "none";
  if (currentView === "board") {
    document.getElementById("kanban-wrap").style.display    = "block";
    document.getElementById("search").style.display         = "none";
    document.getElementById("count-label").style.display    = "none";
    renderBoard();
  } else {
    document.getElementById("job-table-wrap").style.display = "block";
    document.getElementById("search").style.display         = "";
    document.getElementById("count-label").style.display    = "";
    renderTable();
  }
}

async function openResumesTab() {
  if (showingAnalytics) closeAnalytics();
  if (showingCampaigns) closeCampaigns();
  showingResumes = true;
  rmShowPanels(true);
  renderCampaignTabs();
  await rmLoadList();
}

function closeResumes() {
  showingResumes = false;
  rmRestoreView();
  renderCampaignTabs();
}

async function rmLoadList() {
  try {
    const res  = await fetch("/api/resumes");
    const data = await res.json();
    const list = document.getElementById("rm-list");
    if (!data.resumes || !data.resumes.length) {
      list.innerHTML = '<div class="rm-empty">No resumes uploaded yet.</div>';
      return;
    }
    list.innerHTML = data.resumes.map(r => `
      <div class="rm-item">
        <span class="rm-item-icon">📄</span>
        <div class="rm-item-info">
          <div class="rm-item-name">${r.name}</div>
          <div class="rm-item-meta">${r.char_count.toLocaleString()} characters &middot; ${r.uploaded_at ? r.uploaded_at.slice(0,10) : ""}</div>
        </div>
        <button class="rm-item-del" onclick="rmDelete('${r.name.replace(/'/g,"\\'")}')">Delete</button>
      </div>`).join("");
  } catch(err) {
    document.getElementById("rm-list").innerHTML =
      '<div class="rm-empty" style="color:#e74c3c">Failed to load resumes.</div>';
  }
}

function rmDragOver(e) {
  e.preventDefault();
  document.getElementById("rm-drop").classList.add("dragover");
}
function rmDragLeave(e) {
  document.getElementById("rm-drop").classList.remove("dragover");
}
function rmDrop(e) {
  e.preventDefault();
  document.getElementById("rm-drop").classList.remove("dragover");
  const f = e.dataTransfer.files[0];
  if (f) rmSetFile(f);
}
function rmFileSelected(e) {
  const f = e.target.files[0];
  if (f) rmSetFile(f);
}

function rmSetFile(f) {
  rmFile = f;
  const name = f.name.replace(/\.(pdf|docx|txt)$/i, "");
  document.getElementById("rm-name").value = name;
  const preview = document.getElementById("rm-preview");
  preview.style.display = "block";
  preview.textContent   = f.name + " (" + (f.size / 1024).toFixed(1) + " KB) — ready to upload";
  document.getElementById("rm-upload-btn").disabled = false;
}

async function rmUpload() {
  if (!rmFile) return;
  const name = document.getElementById("rm-name").value.trim();
  if (!name) { showToast("Please enter a resume name", "#e74c3c"); return; }

  const btn = document.getElementById("rm-upload-btn");
  btn.disabled = true;
  btn.textContent = "Uploading…";

  const form = new FormData();
  form.append("file", rmFile);
  form.append("name", name);

  try {
    const res  = await fetch("/api/resumes/upload", { method: "POST", body: form });
    const data = await res.json();
    if (data.ok) {
      showToast("Resume uploaded: " + name);
      rmFile = null;
      document.getElementById("rm-file-input").value = "";
      document.getElementById("rm-name").value        = "";
      document.getElementById("rm-preview").style.display = "none";
      btn.textContent = "Upload Resume";
      await rmLoadList();
    } else {
      showToast("Upload failed: " + (data.error || "unknown error"), "#e74c3c");
      btn.disabled = false;
      btn.textContent = "Upload Resume";
    }
  } catch(err) {
    showToast("Network error. Please try again.", "#e74c3c");
    btn.disabled = false;
    btn.textContent = "Upload Resume";
  }
}

async function rmDelete(name) {
  if (!confirm(`Delete resume "${name}"?`)) return;
  const res  = await fetch("/api/resumes/" + encodeURIComponent(name), { method: "DELETE" });
  const data = await res.json();
  if (data.ok) {
    showToast("Resume deleted", "#c0392b");
    await rmLoadList();
  } else {
    showToast("Delete failed", "#e74c3c");
  }
}

// ---- Campaign Editor ----
const CE_FILTER_FIELDS = [
  { key: "title_must_include",       label: "Title Must Include" },
  { key: "title_must_exclude",       label: "Title Must Exclude" },
  { key: "title_ai_specific",        label: "Title AI-Specific Keywords" },
  { key: "description_must_include", label: "Description Must Include" },
  { key: "location_allow",           label: "Locations Allowed" },
];

function ceEsc(s) {
  return String(s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
    .replace(/"/g,"&quot;").replace(/'/g,"&#39;");
}

function ceChipHtml(idx, field, value) {
  const safe = ceEsc(value);
  return `<span class="ce-chip" data-field="${field}" data-value="${safe}">${safe
    }<button class="ce-chip-x" onclick="this.closest('.ce-chip').remove()" title="Remove">&times;</button></span>`;
}

function buildCampaignCard(c, idx) {
  const filterSections = CE_FILTER_FIELDS.map(f => `
    <div class="ce-section">
      <div class="ce-slabel">${f.label}</div>
      <div class="ce-chips" id="chips-${idx}-${f.key}">
        ${((c.filters||{})[f.key]||[]).map(v => ceChipHtml(idx, f.key, v)).join("")}
      </div>
      <input class="ce-input" placeholder="Add keyword, press Enter"
        onkeydown="ceAddChip(event,${idx},'${f.key}')">
    </div>`).join("");

  return `<div class="ce-card" id="cecard-${idx}">
    <div class="ce-name-row">
      <span class="ce-cname">${ceEsc(c.name)}</span>
      <button class="ce-del-btn" onclick="deleteCampaign('${ceEsc(c.name)}')">Delete</button>
    </div>
    <div class="ce-section">
      <div class="ce-slabel">Search Queries</div>
      <div class="ce-chips" id="chips-${idx}-queries">
        ${(c.queries||[]).map(q => ceChipHtml(idx, "queries", q)).join("")}
      </div>
      <input class="ce-input" placeholder="Add query, press Enter"
        onkeydown="ceAddChip(event,${idx},'queries')">
    </div>
    ${filterSections}
    <div class="ce-actions">
      <button class="ce-save-btn" onclick="saveCampaign(${idx},'${ceEsc(c.name)}')">Save Campaign</button>
    </div>
  </div>`;
}

function buildNewCampaignCard(idx) {
  const filterSections = CE_FILTER_FIELDS.map(f => `
    <div class="ce-section">
      <div class="ce-slabel">${f.label}</div>
      <div class="ce-chips" id="chips-${idx}-${f.key}"></div>
      <input class="ce-input" placeholder="Add keyword, press Enter"
        onkeydown="ceAddChip(event,${idx},'${f.key}')">
    </div>`).join("");

  return `<div class="ce-card" id="cecard-${idx}">
    <div class="ce-name-row">
      <input class="ce-name-input" id="cename-${idx}" placeholder="Campaign name (e.g. AI Recruiting)">
    </div>
    <div class="ce-section">
      <div class="ce-slabel">Search Queries</div>
      <div class="ce-chips" id="chips-${idx}-queries"></div>
      <input class="ce-input" placeholder="Add query, press Enter"
        onkeydown="ceAddChip(event,${idx},'queries')">
    </div>
    ${filterSections}
    <div class="ce-actions">
      <button class="ce-save-btn" onclick="saveNewCampaign(${idx})">Create Campaign</button>
    </div>
  </div>`;
}

function ceAddChip(e, idx, field) {
  if (e.key !== "Enter" && e.key !== ",") return;
  e.preventDefault();
  const val = e.target.value.trim().replace(/,$/, "");
  if (!val) return;
  const container = document.getElementById(`chips-${idx}-${field}`);
  const span = document.createElement("span");
  span.className = "ce-chip";
  span.dataset.field = field;
  span.dataset.value = val;
  span.innerHTML = ceEsc(val) +
    `<button class="ce-chip-x" onclick="this.closest('.ce-chip').remove()" title="Remove">&times;</button>`;
  container.appendChild(span);
  e.target.value = "";
}

function ceGetChips(idx, field) {
  const el = document.getElementById(`chips-${idx}-${field}`);
  if (!el) return [];
  return Array.from(el.querySelectorAll(".ce-chip")).map(c => c.dataset.value);
}

function ceCollect(idx) {
  const queries = ceGetChips(idx, "queries");
  const filters = {};
  CE_FILTER_FIELDS.forEach(f => {
    const vals = ceGetChips(idx, f.key);
    if (vals.length) filters[f.key] = vals;
  });
  return { queries, filters };
}

async function openCampaignsTab() {
  if (showingAnalytics) closeAnalytics();
  if (showingResumes)   closeResumes();
  showingCampaigns = true;
  document.getElementById("job-table-wrap").style.display  = "none";
  document.getElementById("kanban-wrap").style.display     = "none";
  document.getElementById("search").style.display          = "none";
  document.getElementById("count-label").style.display     = "none";
  document.getElementById("analytics-panel").style.display = "none";
  document.getElementById("campaigns-panel").style.display = "block";
  renderCampaignTabs();
  await loadCampaigns();
}

function closeCampaigns() {
  showingCampaigns = false;
  document.getElementById("campaigns-panel").style.display = "none";
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
  renderCampaignTabs();
}

async function loadCampaigns() {
  try {
    const res  = await fetch("/api/campaigns");
    const data = await res.json();
    campaignsData = data.campaigns || [];
    renderCampaignCards();
  } catch(err) {
    document.getElementById("campaigns-list").innerHTML =
      '<p style="color:#e74c3c;padding:20px">Failed to load campaigns.</p>';
  }
}

function renderCampaignCards() {
  const list = document.getElementById("campaigns-list");
  if (!campaignsData.length) {
    list.innerHTML = '<p style="color:#aaa;text-align:center;padding:40px 0">No campaigns yet. Click "+ New Campaign" to create one.</p>';
    return;
  }
  list.innerHTML = campaignsData.map((c, i) => buildCampaignCard(c, i)).join("");
}

function addNewCampaign() {
  const idx = campaignsData.length;
  campaignsData.push({ name: "__new__", queries: [], filters: {} });
  const list = document.getElementById("campaigns-list");
  const div  = document.createElement("div");
  div.innerHTML = buildNewCampaignCard(idx);
  list.appendChild(div.firstChild);
  document.getElementById(`cename-${idx}`).focus();
}

async function saveCampaign(idx, name) {
  const { queries, filters } = ceCollect(idx);
  const res  = await fetch("/api/campaigns", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, queries, filters }),
  });
  const data = await res.json();
  if (data.ok) showToast("Campaign saved");
  else showToast("Save failed: " + (data.error || "unknown error"), "#e74c3c");
}

async function saveNewCampaign(idx) {
  const nameEl = document.getElementById(`cename-${idx}`);
  const name   = (nameEl ? nameEl.value.trim() : "");
  if (!name) { showToast("Campaign name is required", "#e74c3c"); return; }
  const { queries, filters } = ceCollect(idx);
  const res  = await fetch("/api/campaigns", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, queries, filters }),
  });
  const data = await res.json();
  if (data.ok) {
    showToast("Campaign created");
    await loadCampaigns();
  } else {
    showToast("Create failed: " + (data.error || "unknown error"), "#e74c3c");
  }
}

async function deleteCampaign(name) {
  if (!confirm(`Delete campaign "${name}"? This cannot be undone.`)) return;
  const res  = await fetch("/api/campaigns/" + encodeURIComponent(name), { method: "DELETE" });
  const data = await res.json();
  if (data.ok) {
    showToast("Campaign deleted", "#c0392b");
    await loadCampaigns();
  } else {
    showToast("Delete failed", "#e74c3c");
  }
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
renderCampaignTabs();
loadData();
setInterval(loadData, 60000);  // auto-refresh every minute
document.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    closeCLModal();
    if (showingCampaigns) closeCampaigns();
    if (showingResumes)   closeResumes();
  }
});
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return DASHBOARD_HTML.replace("Job Tracker Dashboard", DASHBOARD_TITLE)


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


@app.route("/api/generate-cover-letter", methods=["POST"])
def api_generate_cover_letter():
    import anthropic as _anthropic
    import os, yaml

    data   = request.get_json()
    job_id = data.get("job_id")
    if not job_id:
        return jsonify({"error": "job_id required"}), 400

    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        "SELECT title, company, best_resume, resume_rationale, "
        "company_summary, recent_news, funding_stage "
        "FROM seen_jobs WHERE id = %s",
        (job_id,)
    )
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        return jsonify({"error": "Job not found"}), 404

    title, company, best_resume, resume_rationale, \
        company_summary, recent_news, funding_stage = row

    # Fetch resume content
    resume_content = ""
    if best_resume:
        cur.execute("SELECT content FROM resumes WHERE name = %s", (best_resume,))
        r = cur.fetchone()
        if r:
            resume_content = r[0] or ""
    cur.close(); conn.close()

    # Build company context block
    company_ctx = []
    if company_summary: company_ctx.append(f"About: {company_summary}")
    if funding_stage:   company_ctx.append(f"Stage: {funding_stage}")
    if recent_news:     company_ctx.append(f"Recent news: {recent_news}")
    company_section = "\n".join(company_ctx) if company_ctx else "No additional company context available."
    resume_section  = resume_content if resume_content else "No resume content available."

    prompt = f"""You are writing a cover letter for Corey Weil, a senior technical recruiter and talent acquisition professional with extensive experience in full-cycle recruiting, employer branding, and AI/automation tooling.

Job Details:
- Title: {title}
- Company: {company}

Company Context:
{company_section}

Resume Content:
{resume_section}

Write a compelling, human-sounding cover letter for this role. Requirements:
- 3 paragraphs, under 250 words total
- No em dashes (use commas or restructure instead)
- Do NOT open with "I am excited to apply" or any generic opener like "I am writing to express my interest"
- Sound like a real person, not a template
- Highlight specific relevant experience from the resume that matches this role
- Reference something specific about the company when context is available
- Close with a confident but not pushy call to action
- No salutation line, no "Dear Hiring Manager", no signature block — just the 3 paragraphs

Output only the cover letter text, nothing else."""

    # Resolve API key
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        try:
            cfg_path = Path(__file__).parent / "config.yaml"
            cfg = yaml.safe_load(open(cfg_path))
            api_key = cfg.get("anthropic_api_key", "")
        except Exception:
            pass

    if not api_key:
        return jsonify({"error": "Anthropic API key not configured. Set ANTHROPIC_API_KEY env var."}), 500

    try:
        client = _anthropic.Anthropic(api_key=api_key)
        msg    = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=700,
            messages=[{"role": "user", "content": prompt}],
        )
        cover_letter = msg.content[0].text.strip()
        return jsonify({"cover_letter": cover_letter})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


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


@app.route("/api/init-db", methods=["POST"])
def api_init_db():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS seen_jobs (
                id                TEXT PRIMARY KEY,
                campaign          TEXT,
                title             TEXT,
                company           TEXT,
                location          TEXT,
                url               TEXT,
                source            TEXT,
                found_at          TEXT,
                posted_at         TEXT,
                status            TEXT DEFAULT 'New',
                status_updated_at TEXT,
                score             INTEGER DEFAULT 0,
                rationale         TEXT,
                best_resume       TEXT,
                resume_score      INTEGER,
                resume_rationale  TEXT,
                nudge             TEXT,
                funding_stage     TEXT,
                headcount         TEXT,
                recent_news       TEXT,
                company_summary   TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS resumes (
                id          SERIAL PRIMARY KEY,
                name        TEXT UNIQUE NOT NULL,
                content     TEXT,
                uploaded_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS campaigns (
                id         SERIAL PRIMARY KEY,
                name       TEXT UNIQUE NOT NULL,
                queries    JSONB NOT NULL DEFAULT '[]',
                filters    JSONB NOT NULL DEFAULT '{}',
                enabled    BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        return jsonify({"ok": True, "message": "All tables created successfully"})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500
    finally:
        conn.close()


@app.route("/api/resumes", methods=["GET"])
def api_get_resumes():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT name, LENGTH(COALESCE(content,'')), uploaded_at "
            "FROM resumes ORDER BY uploaded_at DESC"
        )
        rows = cur.fetchall()
        cur.close()
        resumes = [
            {"name": r[0], "char_count": r[1] or 0,
             "uploaded_at": r[2].isoformat() if r[2] else None}
            for r in rows
        ]
        return jsonify({"resumes": resumes})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500
    finally:
        conn.close()


@app.route("/api/resumes/upload", methods=["POST"])
def api_upload_resume():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f    = request.files["file"]
    name = (request.form.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400

    filename = f.filename or ""
    ext      = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    try:
        raw = f.read()
        if ext == "pdf":
            import io
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw))
            text   = "\n".join(
                page.extract_text() or "" for page in reader.pages
            ).strip()
            if not text:
                return jsonify({"error": "Could not extract text from PDF. "
                                         "Scanned/image PDFs are not supported."}), 422
        elif ext == "docx":
            import io
            from docx import Document
            doc  = Document(io.BytesIO(raw))
            text = "\n".join(p.text for p in doc.paragraphs).strip()
            if not text:
                return jsonify({"error": "Could not extract text from DOCX."}), 422
        elif ext == "txt":
            text = raw.decode("utf-8", errors="replace").strip()
        else:
            return jsonify({"error": "Unsupported file type. Use PDF, DOCX, or TXT."}), 400

        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(
            """INSERT INTO resumes (name, content)
               VALUES (%s, %s)
               ON CONFLICT (name) DO UPDATE
                 SET content = EXCLUDED.content, uploaded_at = NOW()""",
            (name, text),
        )
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"ok": True, "char_count": len(text)})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@app.route("/api/resumes/<name>", methods=["DELETE"])
def api_delete_resume(name):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM resumes WHERE name = %s", (name,))
        conn.commit()
        cur.close()
        return jsonify({"ok": True})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500
    finally:
        conn.close()


def _ensure_campaigns_table(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id         SERIAL PRIMARY KEY,
            name       TEXT UNIQUE NOT NULL,
            queries    JSONB NOT NULL DEFAULT '[]',
            filters    JSONB NOT NULL DEFAULT '{}',
            enabled    BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()


@app.route("/api/campaigns", methods=["GET"])
def api_get_campaigns():
    conn = get_conn()
    try:
        _ensure_campaigns_table(conn)
        cur = conn.cursor()
        cur.execute("SELECT name, queries, filters, enabled FROM campaigns ORDER BY id")
        rows = cur.fetchall()
        cur.close()
        campaigns = [
            {"name": r[0], "queries": r[1] or [], "filters": r[2] or {}, "enabled": r[3]}
            for r in rows
        ]
        return jsonify({"campaigns": campaigns})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500
    finally:
        conn.close()


@app.route("/api/campaigns", methods=["POST"])
def api_save_campaign():
    data    = request.get_json()
    name    = (data.get("name") or "").strip()
    queries = data.get("queries", [])
    filters = data.get("filters", {})
    if not name:
        return jsonify({"error": "name required"}), 400
    if not isinstance(queries, list):
        return jsonify({"error": "queries must be a list"}), 400
    conn = get_conn()
    try:
        _ensure_campaigns_table(conn)
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO campaigns (name, queries, filters)
               VALUES (%s, %s::jsonb, %s::jsonb)
               ON CONFLICT (name) DO UPDATE
                 SET queries = EXCLUDED.queries,
                     filters = EXCLUDED.filters""",
            (name, json.dumps(queries), json.dumps(filters)),
        )
        conn.commit()
        cur.close()
        return jsonify({"ok": True})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500
    finally:
        conn.close()


@app.route("/api/campaigns/<name>", methods=["DELETE"])
def api_delete_campaign(name):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM campaigns WHERE name = %s", (name,))
        conn.commit()
        cur.close()
        return jsonify({"ok": True})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500
    finally:
        conn.close()


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
