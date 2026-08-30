"""BeaconMe live packet dashboard.

Run with ``python app.py`` then open http://127.0.0.1:5000.
For a receiver on COM3, use ``python app.py --serial-port COM3 --baud 9600``.
"""

import argparse
import os
import threading
import time
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd
from flask import Flask, jsonify, render_template_string, request

from predict import parse_beaconme_packet

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # The dashboard can still be used with the manual input.
    serial = None
    list_ports = None


BASE_DIR = Path(__file__).resolve().parent
MODEL_FILE = BASE_DIR / "beaconme_best_model.joblib"
MAX_HISTORY = 250

app = Flask(__name__)
history = deque(maxlen=MAX_HISTORY)
history_lock = threading.Lock()
active_nodes = {}
active_nodes_lock = threading.Lock()
serial_stop = threading.Event()
serial_thread = None
serial_connection = None
serial_state = {"connected": False, "port": None, "baud": None, "error": None}


def load_bundle():
    """Load the trained model once, instead of once for every incoming packet."""
    if not MODEL_FILE.exists():
        raise FileNotFoundError(f"Model file not found: {MODEL_FILE}")
    return joblib.load(MODEL_FILE)


MODEL_BUNDLE = load_bundle()


def label_name(mapping, value):
    if mapping is MODEL_BUNDLE.get("emergency_type_map") and value == 5:
        return "SOS"
    return mapping.get(value, "Unknown")


def make_prediction(packet):
    """Parse one BeaconMe packet and return a JSON-safe dashboard record."""
    features = parse_beaconme_packet(packet)
    model = MODEL_BUNDLE["model"]
    feature_columns = MODEL_BUNDLE["feature_columns"]
    frame = pd.DataFrame([features], columns=feature_columns)
    prediction = str(model.predict(frame)[0])

    probabilities = {}
    confidence = None
    if hasattr(model, "predict_proba"):
        scores = model.predict_proba(frame)[0]
        probabilities = {
            str(label): round(float(score) * 100, 2)
            for label, score in zip(model.classes_, scores)
        }
        confidence = round(max(probabilities.values()), 2)

    emergency_type = features["emergency_type"]
    message_code = features["message_code"]
    danger_level = features["danger_level"]
    now = datetime.now(timezone.utc)
    return {
        "id": now.strftime("%Y%m%d%H%M%S%f"),
        "received_at": now.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        "packet": packet.strip(),
        "prediction": prediction,
        "confidence": confidence,
        "probabilities": probabilities,
        "node_id": features["node_id"],
        "latitude": features["latitude"],
        "longitude": features["longitude"],
        "emergency_type": emergency_type,
        "emergency_name": label_name(MODEL_BUNDLE["emergency_type_map"], emergency_type),
        "message_code": message_code,
        "message_name": label_name(MODEL_BUNDLE["message_code_map"], message_code),
        "danger_level": danger_level,
        "danger_name": label_name(MODEL_BUNDLE["danger_level_map"], danger_level),
        "hop_count": features["hop_count"],
        "forward_status": "Direct from survivor node" if features["hop_count"] == 0 else "Forwarded through ad-hoc node",
        "map_url": f"https://maps.google.com/?q={features['latitude']},{features['longitude']}",
    }


def receive_packet(packet):
    record = make_prediction(packet)
    now_epoch = time.time()
    record["received_epoch"] = now_epoch

    with history_lock:
        history.appendleft(record)

    # Only track on Live GPS Tracker if emergency_type is SOS (type 5 or name 'SOS')
    is_sos = (record["emergency_type"] == 5 or record["emergency_name"] == "SOS")
    if is_sos:
        with active_nodes_lock:
            node_id = record["node_id"]
            prev = active_nodes.get(node_id)
            if prev and "received_epoch" in prev:
                delta = round(now_epoch - prev["received_epoch"], 1)
                record["pulse_interval"] = delta
                record["is_loop_active"] = (0.5 <= delta <= 5.0)
                record["pulse_count"] = prev.get("pulse_count", 1) + 1
            else:
                record["pulse_interval"] = None
                record["is_loop_active"] = False
                record["pulse_count"] = 1
            active_nodes[node_id] = record

    return record


def dashboard_data():
    with history_lock:
        records = list(history)
    counts = Counter(item["prediction"] for item in records)
    highest = next((item for item in records if item["prediction"] in {"CRITICAL", "HIGH"}), None)

    now_epoch = time.time()
    tracked_nodes = []
    with active_nodes_lock:
        stale_nodes = []
        for nid, node_data in list(active_nodes.items()):
            elapsed = round(now_epoch - node_data.get("received_epoch", now_epoch), 1)
            # Hide / expire live tracker after 3 minutes (180 seconds) of inactivity
            if elapsed > 180.0:
                stale_nodes.append(nid)
            else:
                r = dict(node_data)
                r["seconds_ago"] = elapsed
                if elapsed <= 5.0:
                    r["live_status"] = "Active 3s Loop" if r.get("is_loop_active") else "Live Pulse"
                    r["status_color"] = "red"
                elif elapsed <= 30.0:
                    r["live_status"] = "Online"
                    r["status_color"] = "olive"
                else:
                    r["live_status"] = "Silent (Within 3m)"
                    r["status_color"] = "yellow"
                tracked_nodes.append(r)

        for nid in stale_nodes:
            active_nodes.pop(nid, None)

    return {
        "history": records,
        "active_nodes": tracked_nodes,
        "analytics": {
            "total": len(records),
            "critical": counts["CRITICAL"],
            "high": counts["HIGH"],
            "suspicious": counts["FAKE"],
            "distribution": {label: counts[label] for label in MODEL_BUNDLE["labels"]},
            "highest_priority": highest,
        },
        "model": {"name": MODEL_BUNDLE["model_name"], "accuracy": round(float(MODEL_BUNDLE["accuracy"]) * 100, 2)},
        "serial": serial_state.copy(),
    }


def serial_worker(port, baud):
    global serial_connection
    try:
        serial_connection = serial.Serial(port, baudrate=baud, timeout=1)
        serial_state.update(connected=True, port=port, baud=baud, error=None)
        while not serial_stop.is_set():
            raw = serial_connection.readline().decode("utf-8", errors="replace").strip()
            if raw:
                serial_state["received_packet"] = raw
                try:
                    receive_packet(raw)
                except (ValueError, TypeError) as error:
                    serial_state["error"] = f"Ignored malformed packet: {error}"
    except Exception as error:
        serial_state.update(connected=False, error=str(error))
    finally:
        if serial_connection and serial_connection.is_open:
            serial_connection.close()
        serial_connection = None
        serial_state["connected"] = False


def connect_serial(port, baud):
    global serial_thread
    if serial is None:
        raise RuntimeError("pyserial is not installed. Install it with: pip install pyserial")
    if serial_thread and serial_thread.is_alive():
        raise RuntimeError("A serial connection is already active. Disconnect it before connecting another port.")
    serial_stop.clear()
    serial_thread = threading.Thread(target=serial_worker, args=(port, baud), daemon=True, name="beaconme-serial")
    serial_thread.start()


def disconnect_serial():
    serial_stop.set()
    if serial_connection and serial_connection.is_open:
        serial_connection.close()
    serial_state["connected"] = False


@app.get("/")
def index():
    return render_template_string(PAGE)


@app.get("/api/dashboard")
def api_dashboard():
    return jsonify(dashboard_data())


@app.get("/api/serial/ports")
def api_serial_ports():
    """Return currently available ports for the serial-port selector."""
    if list_ports is None:
        return jsonify(ports=[], error="pyserial is not installed."), 503
    ports = [
        {"device": port.device, "description": port.description or "Serial device"}
        for port in list_ports.comports()
    ]
    return jsonify(ports=ports)


@app.post("/api/packets")
def api_packet():
    payload = request.get_json(silent=True) or request.form
    packet = str(payload.get("packet", "")).strip()
    if not packet:
        return jsonify(error="Send a packet field containing the BeaconMe packet."), 400
    try:
        return jsonify(receive_packet(packet)), 201
    except (ValueError, TypeError) as error:
        return jsonify(error=str(error)), 400


@app.post("/api/serial/connect")
def api_connect_serial():
    payload = request.get_json(silent=True) or request.form
    port = str(payload.get("port", "")).strip()
    try:
        baud = int(payload.get("baud", 9600))
        if not port:
            raise ValueError("Enter a COM port, for example COM3.")
        connect_serial(port, baud)
        return jsonify(message=f"Connecting to {port} at {baud} baud.", serial=serial_state)
    except (ValueError, RuntimeError) as error:
        return jsonify(error=str(error)), 400


@app.post("/api/serial/disconnect")
def api_disconnect_serial():
    disconnect_serial()
    return jsonify(message="Serial receiver disconnected.", serial=serial_state)


PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BeaconMe Command Center</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/semantic-ui@2.5.0/dist/semantic.min.css">
<style>
body{background:#f4f7fb;color:#263238}.topbar{background:linear-gradient(120deg,#102a43,#1565c0);padding:22px 0;color:white}.topbar h1{margin:0!important}.sub{opacity:.8;margin-top:5px}.main{padding:24px 0}.ui.statistic>.value{font-size:2rem!important}.critical{border-left:5px solid #db2828!important}.high{border-left:5px solid #f2711c!important}.fake{border-left:5px solid #767676!important}.metric-card{min-height:110px}.packet-card{min-height:260px}.muted{color:#718096}.severity{font-weight:700}.table td{vertical-align:middle!important}.status-dot{font-size:.85em}.packet-text{font-family:monospace;word-break:break-all}.empty{padding:32px!important;color:#718096}.bar{height:8px;background:#e9edf2;border-radius:8px;overflow:hidden}.bar i{display:block;height:100%;background:#2185d0}.compact-label{font-size:.8rem;color:#718096}.assessment{width:100%}.assessment-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding-bottom:14px;border-bottom:1px solid #e8edf3}.assessment-time{font-size:.9rem}.assessment-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;padding:18px 0}.assessment-box{background:#f8fafc;border:1px solid #e5eaf0;border-radius:6px;padding:14px}.assessment-box h4{margin:0 0 10px;color:#34495e}.assessment-title{font-size:1.1rem;font-weight:700}.assessment-meta{margin-top:5px;line-height:1.55}.probability-row{margin:9px 0}.probability-row:first-of-type{margin-top:12px}.probability-row .bar{margin-top:4px}.raw-packet{padding:10px 12px;background:#eef3f8;border-radius:5px;color:#526b84;font-size:.9rem}.node-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px;margin-top:10px}.node-card{background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;padding:14px;position:relative;box-shadow:0 1px 3px rgba(0,0,0,0.05)}.node-card.pulse-red{border-left:5px solid #db2828;animation:card-glow 1.5s infinite}.node-card.pulse-green{border-left:5px solid #21ba45}@keyframes card-glow{0%{box-shadow:0 0 0 0 rgba(219,40,40,0.4);}70%{box-shadow:0 0 0 8px rgba(219,40,40,0);}100%{box-shadow:0 0 0 0 rgba(219,40,40,0);}}
#sosAlertPopup{position:fixed;top:24px;right:24px;z-index:9999;max-width:440px;box-shadow:0 10px 30px rgba(0,0,0,0.35);display:none;animation:slide-in-right 0.35s ease-out;}
@keyframes slide-in-right{from{transform:translateX(100%);opacity:0;}to{transform:translateX(0);opacity:1;}}
#alertsModal{display:none;position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,0.55);backdrop-filter:blur(3px);align-items:flex-start;justify-content:center;padding:40px 16px;overflow-y:auto;}
#alertsModal.open{display:flex;}
#alertsModalBox{background:#fff;border-radius:12px;width:100%;max-width:860px;box-shadow:0 20px 60px rgba(0,0,0,0.3);overflow:hidden;position:relative;}
#alertsModalBox .modal-head{background:linear-gradient(120deg,#102a43,#c62828);color:white;padding:18px 22px;display:flex;justify-content:space-between;align-items:center;}
#alertsModalBox .modal-head h2{margin:0;font-size:1.15rem;}
#alertsModalBox .modal-body{padding:18px 22px;max-height:70vh;overflow-y:auto;}
#alertsModal table{width:100%;}
#alertsCloseBtn{background:transparent;border:1.5px solid rgba(255,255,255,0.6);color:white;border-radius:6px;padding:5px 12px;cursor:pointer;font-size:0.9rem;}
#alertsCloseBtn:hover{background:rgba(255,255,255,0.15);}
#openAlertsBtn{position:fixed;bottom:28px;right:28px;z-index:9998;background:#c62828;color:white;border:none;border-radius:50px;padding:13px 22px;font-size:0.95rem;font-weight:700;cursor:pointer;box-shadow:0 6px 20px rgba(198,40,40,0.5);display:flex;align-items:center;gap:8px;transition:background 0.2s;}
#openAlertsBtn:hover{background:#b71c1c;}
#alertsBadge{background:white;color:#c62828;border-radius:50px;padding:2px 8px;font-size:0.8rem;font-weight:900;min-width:22px;text-align:center;}
@media(max-width:600px){.assessment-grid{grid-template-columns:1fr}.packet-card{min-height:0}#sosAlertPopup{top:12px;right:12px;left:12px;max-width:none;}#openAlertsBtn{bottom:16px;right:16px;}}
</style></head><body>

<!-- Confirmed Alerts Modal -->
<div id="alertsModal" role="dialog" aria-modal="true" aria-labelledby="alertsModalTitle" onclick="if(event.target===this)closeAlertsModal()">
  <div id="alertsModalBox">
    <div class="modal-head">
      <h2 id="alertsModalTitle"><i class="exclamation triangle icon"></i> Confirmed Emergency Alerts <span id="alertsModalCount" style="font-weight:400;font-size:0.85rem;opacity:0.85;"></span></h2>
      <button id="alertsCloseBtn" onclick="closeAlertsModal()">&#x2715; Close</button>
    </div>
    <div class="modal-body">
      <p style="color:#718096;font-size:0.85rem;margin:0 0 14px 0;">Showing all non-fake (CRITICAL, HIGH, MEDIUM, LOW) emergency packets from this session. Sorted newest first.</p>
      <table class="ui very basic compact selectable table">
        <thead><tr><th>Received</th><th>Node</th><th>Emergency</th><th>Location</th><th>Result</th><th>Confidence</th><th>Route</th></tr></thead>
        <tbody id="alertsModalBody"><tr><td colspan="7" class="center aligned empty">No confirmed alerts yet.</td></tr></tbody>
      </table>
    </div>
  </div>
</div>

<!-- Floating button to open the Confirmed Alerts popup -->
<button id="openAlertsBtn" onclick="openAlertsModal()" title="View confirmed emergency alerts">
  <i class="exclamation circle icon"></i> Confirmed Alerts
  <span id="alertsBadge">0</span>
</button>
<div id="sosAlertPopup">
  <div class="ui red inverted segment" style="border:2px solid #ffffff;border-radius:10px;padding:16px;">
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <h3 class="ui header" style="color:white;margin:0;"><i class="exclamation triangle icon"></i> NEW SOS BEACON DETECTED!</h3>
      <i class="close icon" style="cursor:pointer;font-size:1.2rem;" onclick="dismissAlert()"></i>
    </div>
    <div id="sosAlertContent" style="margin-top:10px;font-size:0.95rem;line-height:1.45;"></div>
  </div>
</div>

<div class="topbar"><div class="ui container"><h1><i class="broadcast tower icon"></i> BeaconMe Command Center</h1><div class="sub">Live emergency packet intelligence · ML-assisted triage & Real-time SOS GPS Tracker</div></div></div>
<main class="ui container main">
<div class="ui four stackable cards" id="metrics"><div class="ui card metric-card"><div class="content"><div class="header">Packets received</div><div class="ui blue statistic"><div class="value" id="total">0</div><div class="label">this session</div></div></div></div><div class="ui card metric-card critical"><div class="content"><div class="header">Critical</div><div class="ui red statistic"><div class="value" id="critical">0</div><div class="label">immediate action</div></div></div></div><div class="ui card metric-card high"><div class="content"><div class="header">High priority</div><div class="ui orange statistic"><div class="value" id="high">0</div><div class="label">needs review</div></div></div></div><div class="ui card metric-card fake"><div class="content"><div class="header">Suspicious</div><div class="ui grey statistic"><div class="value" id="suspicious">0</div><div class="label">marked fake</div></div></div></div></div>

<!-- Live Survivor Node Fleet & GPS Tracking Section (Hidden until active SOS is received; auto-hides after 3 min inactivity) -->
<section class="ui raised segment" id="fleetSection" style="display:none;border-top:4px solid #db2828;">
<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
<h3 class="ui header" style="margin:0;"><i class="map marker alternate icon" style="color:#db2828;"></i><div class="content">Live SOS GPS Tracker<div class="sub header">Real-time GPS tracking for active SOS nodes (auto-hides after 3 minutes of inactivity)</div></div></h3>
<span class="ui mini red label" id="fleetCount">0 Active SOS Beacons</span>
</div>
<div id="fleetCards" class="node-grid"></div>
</section>

<div class="ui stackable grid"><section class="ten wide column"><div class="ui raised segment packet-card"><h3 class="ui header"><i class="heartbeat icon"></i><div class="content">Latest assessment<div class="sub header">The newest valid BeaconMe transmission</div></div></h3><div id="latest"><div class="ui active inline loader"></div></div></div></section><aside class="six wide column"><div class="ui raised segment"><h3 class="ui header"><i class="plug icon"></i> Serial receiver</h3><div class="ui tiny form"><div class="two fields"><div class="field"><label>COM port</label><select id="port"><option value="">Loading available ports…</option></select></div><div class="field"><label>Baud rate</label><select id="baud"><option value="9600">9600</option><option value="115200" selected>115200</option></select></div></div><button class="ui primary button" onclick="connectSerial()">Connect</button><button class="ui button" onclick="disconnectSerial()">Disconnect</button></div><div class="ui small message" id="serialStatus">Checking receiver status…</div><div class="ui tiny message"><b><i class="terminal icon"></i> Last received raw message</b><br><code id="receivedPacket" class="packet-text muted">Waiting for serial data…</code></div><div class="ui divider"></div><h4 class="ui header">Model health</h4><p><b id="modelName">—</b><br><span class="muted">Saved test accuracy: <b id="modelAccuracy">—</b></span></p></div></aside></div>
<div class="ui stackable grid"><section class="six wide column"><div class="ui raised segment"><h3 class="ui header"><i class="chart pie icon"></i> Session analytics</h3><div id="distribution"></div></div></section><section class="ten wide column"><div class="ui raised segment"><h3 class="ui header"><i class="keyboard outline icon"></i> Manual packet test</h3><div class="ui form"><div class="field"><label>BeaconMe packet</label><input id="packet" class="packet-text" value="S,1,692710,7986119,2,1,2,0"></div><button class="ui teal button" onclick="submitPacket()"><i class="paper plane icon"></i> Process packet</button></div><div id="notice" style="margin-top:12px"></div></div></section></div>
<section class="ui raised segment"><h3 class="ui header"><i class="history icon"></i> Packet history <span class="muted" style="font-weight:normal;font-size:.75em">Latest 250 packets retained for this server session</span></h3><table class="ui very basic compact selectable table"><thead><tr><th>Received</th><th>Node</th><th>Emergency</th><th>Location</th><th>Result</th><th>Confidence</th><th>Route</th></tr></thead><tbody id="history"><tr><td colspan="7" class="center aligned empty">No packets received yet.</td></tr></tbody></table></section>
</main>
<script>
const escapeHtml=s=>String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const severity=c=>({CRITICAL:'red',HIGH:'orange',MEDIUM:'yellow',LOW:'blue',FAKE:'grey'}[c]||'grey');
function notice(text,type='info'){document.getElementById('notice').innerHTML=`<div class="ui ${type} message">${escapeHtml(text)}</div>`}

const activeSosNodes = new Set();
let alertTimeout = null;

function playEmergencyChime(){
  try{
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(880, now);
    osc.frequency.setValueAtTime(1174.66, now + 0.15);
    osc.frequency.setValueAtTime(1760, now + 0.3);
    gain.gain.setValueAtTime(0.3, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.6);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(now);
    osc.stop(now + 0.6);
  }catch(e){}
}

function showFirstTimeSosAlert(node){
  const popup = document.getElementById('sosAlertPopup');
  const body = document.getElementById('sosAlertContent');
  body.innerHTML = `<b>Node #${node.node_id}</b> has initiated a Live SOS Emergency Beacon.<br>` +
    `📍 <b>Location:</b> ${node.latitude.toFixed(5)}, ${node.longitude.toFixed(5)}<br>` +
    `⏱ <b>Detected at:</b> ${escapeHtml(node.received_at)}<br>` +
    `<a class="ui tiny white basic button" style="margin-top:8px;background:white;color:#db2828;font-weight:bold;" target="_blank" rel="noopener" href="${node.map_url}">Open Google Maps</a>`;
  
  popup.style.display = 'block';
  playEmergencyChime();
  
  if(alertTimeout) clearTimeout(alertTimeout);
  alertTimeout = setTimeout(() => { popup.style.display = 'none'; }, 12000);
}

function dismissAlert(){
  document.getElementById('sosAlertPopup').style.display = 'none';
  if(alertTimeout) clearTimeout(alertTimeout);
}

function renderFleet(nodes){
  const section = document.getElementById('fleetSection');
  const target = document.getElementById('fleetCards');
  
  // When no active SOS nodes exist (or after 3 minutes of inactivity):
  // Hide GPS Live Tracker and clear active node registry so any returning SOS triggers a new alert!
  if(!nodes || !nodes.length){
    section.style.display = 'none';
    target.innerHTML = '';
    activeSosNodes.clear();
    return;
  }
  
  section.style.display = 'block';
  document.getElementById('fleetCount').textContent = `${nodes.length} Active SOS Beacon${nodes.length===1?'':'s'}`;

  // Clean up any nodes that expired from the active set
  const incomingIds = new Set(nodes.map(n => n.node_id));
  for (const id of activeSosNodes) {
    if (!incomingIds.has(id)) {
      activeSosNodes.delete(id);
    }
  }

  // Trigger alert for any new/returning SOS node
  nodes.forEach(n => {
    if(!activeSosNodes.has(n.node_id)){
      activeSosNodes.add(n.node_id);
      showFirstTimeSosAlert(n);
    }
  });

  target.innerHTML = nodes.map(n => {
    const isCritical = n.prediction === 'CRITICAL';
    const isPulsing = n.seconds_ago <= 5.0 && n.is_loop_active;
    const cardClass = isCritical ? 'pulse-red' : (n.seconds_ago <= 5.0 ? 'pulse-green' : '');
    const pulseBadge = isPulsing 
      ? '<span class="ui mini red label" style="margin-left:5px;"><i class="bolt icon"></i> 3s SOS LOOP</span>' 
      : `<span class="ui mini ${n.status_color} label" style="margin-left:5px;">${escapeHtml(n.live_status)}</span>`;

    return `<div class="node-card ${cardClass}">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <h4 style="margin:0;"><i class="microchip icon"></i> Node #${n.node_id}</h4>
        <div>${pulseBadge}</div>
      </div>
      <div style="margin:8px 0 6px 0;font-size:0.95rem;">
        <span class="ui ${severity(n.prediction)} tiny label">${escapeHtml(n.prediction)}</span>
        <b>SOS</b>
      </div>
      <div style="font-size:0.85rem;color:#4a5568;line-height:1.45;">
        <div><b>📍 GPS:</b> ${n.latitude.toFixed(5)}, ${n.longitude.toFixed(5)}</div>
        <div><b>🕒 Last Alive:</b> ${escapeHtml(n.received_at)} <span style="color:#e53e3e;font-weight:bold;">(${n.seconds_ago}s ago)</span></div>
        <div><b>📡 Pulses Received:</b> ${n.pulse_count || 1} &nbsp;|&nbsp; <b>Route:</b> ${escapeHtml(n.forward_status)}</div>
      </div>
      <a class="ui tiny primary fluid button" style="margin-top:10px;" target="_blank" rel="noopener" href="${n.map_url}">
        <i class="external alternate icon"></i> Open in Google Maps
      </a>
    </div>`;
  }).join('');
}

function renderLatest(item){
  const target=document.getElementById('latest');
  if(!item){target.innerHTML='<div class="empty center aligned">Awaiting the first valid packet…</div>';return}
  const prob=Object.entries(item.probabilities).map(([k,v])=>`<div class="probability-row"><div class="compact-label">${escapeHtml(k)} <span class="right floated">${v}%</span></div><div class="bar"><i style="width:${v}%"></i></div></div>`).join('');
  const isSos=(item.emergency_type === 5 || item.emergency_name === 'SOS');
  const titleDisplay=isSos ? 'SOS' : `${escapeHtml(item.emergency_name)} — ${escapeHtml(item.message_name)}`;

  target.innerHTML=`<div class="assessment"><div class="assessment-head"><span class="ui ${severity(item.prediction)} large label">${escapeHtml(item.prediction)}</span><b>Node ${item.node_id}</b><span class="muted assessment-time"><i class="clock outline icon"></i>${escapeHtml(item.received_at)}</span></div><div class="assessment-grid"><div class="assessment-box"><h4><i class="first aid icon"></i> Incident details</h4><div class="assessment-title">${titleDisplay}</div><div class="assessment-meta muted">Danger: <b>${escapeHtml(item.danger_name)}</b><br>${escapeHtml(item.forward_status)}</div><a class="ui small basic button" style="margin-top:12px" target="_blank" rel="noopener" href="${item.map_url}"><i class="map marker alternate icon"></i> Open location</a></div><div class="assessment-box"><h4><i class="brain icon"></i> ML confidence <span class="right floated">${item.confidence ?? '—'}%</span></h4>${prob}</div></div><div class="raw-packet"><b>Raw packet</b> <code>${escapeHtml(item.packet)}</code></div></div>`;
}

let _lastAlertRows = [];

function openAlertsModal(){
  document.getElementById('alertsModal').classList.add('open');
  document.body.style.overflow='hidden';
  renderAlertsModal(_lastAlertRows);
}
function closeAlertsModal(){
  document.getElementById('alertsModal').classList.remove('open');
  document.body.style.overflow='';
}
document.addEventListener('keydown', e => { if(e.key==='Escape') closeAlertsModal(); });

function renderAlertsModal(rows){
  const confirmedRows = rows.filter(x => x.prediction !== 'FAKE');
  const badge = document.getElementById('alertsBadge');
  const count = document.getElementById('alertsModalCount');
  badge.textContent = confirmedRows.length;
  count.textContent = `(${confirmedRows.length} alert${confirmedRows.length===1?'':'s'})`;
  const target = document.getElementById('alertsModalBody');
  if(!confirmedRows.length){
    target.innerHTML='<tr><td colspan="7" class="center aligned empty">No confirmed alerts yet.</td></tr>';
    return;
  }
  target.innerHTML = confirmedRows.map(x => {
    const isSos = (x.emergency_type === 5 || x.emergency_name === 'SOS');
    const msgSub = isSos ? '' : `<div class="muted">${escapeHtml(x.message_name)}</div>`;
    return `<tr><td>${escapeHtml(x.received_at)}</td><td>#${x.node_id}</td><td>${escapeHtml(x.emergency_name)}${msgSub}</td><td><a target="_blank" rel="noopener" href="${x.map_url}">${x.latitude.toFixed(5)}, ${x.longitude.toFixed(5)}</a></td><td><span class="ui ${severity(x.prediction)} label">${escapeHtml(x.prediction)}</span></td><td>${x.confidence ?? '—'}%</td><td>${escapeHtml(x.forward_status)}</td></tr>`;
  }).join('');
}

function renderHistory(rows){
  _lastAlertRows = rows;
  renderAlertsModal(rows);
  const target=document.getElementById('history');
  if(!rows.length){target.innerHTML='<tr><td colspan="7" class="center aligned empty">No packets received yet.</td></tr>';return}
  target.innerHTML=rows.map(x=>{
    const isSos = (x.emergency_type === 5 || x.emergency_name === 'SOS');
    const msgSub = isSos ? '' : `<div class="muted">${escapeHtml(x.message_name)}</div>`;
    return `<tr><td>${escapeHtml(x.received_at)}</td><td>#${x.node_id}</td><td>${escapeHtml(x.emergency_name)}${msgSub}</td><td><a target="_blank" rel="noopener" href="${x.map_url}">${x.latitude.toFixed(5)}, ${x.longitude.toFixed(5)}</a></td><td><span class="ui ${severity(x.prediction)} label">${escapeHtml(x.prediction)}</span></td><td>${x.confidence ?? '—'}%</td><td>${escapeHtml(x.forward_status)}</td></tr>`;
  }).join('');
}
function renderDistribution(data,total){document.getElementById('distribution').innerHTML=Object.entries(data).map(([key,value])=>{let p=total?Math.round(value/total*100):0;return `<div style="margin:11px 0"><b>${escapeHtml(key)}</b><span class="right floated muted">${value} (${p}%)</span><div class="bar" style="margin-top:5px"><i style="width:${p}%;background:${severity(key)==='red'?'#db2828':severity(key)==='orange'?'#f2711c':'#2185d0'}"></i></div></div>`}).join('')}
async function refresh(){try{const data=await (await fetch('/api/dashboard')).json(),a=data.analytics;['total','critical','high','suspicious'].forEach(k=>document.getElementById(k).textContent=a[k]);document.getElementById('modelName').textContent=data.model.name;document.getElementById('modelAccuracy').textContent=data.model.accuracy+'%';document.getElementById('serialStatus').innerHTML=`<i class="${data.serial.connected?'green check circle':'grey circle'} icon"></i> ${data.serial.connected?`Connected to ${escapeHtml(data.serial.port)} at ${data.serial.baud} baud`:'Not connected'}${data.serial.error?`<br><span class="red text">${escapeHtml(data.serial.error)}</span>`:''}`;const received=document.getElementById('receivedPacket');received.textContent=data.serial.received_packet||'Waiting for serial data…';renderLatest(data.history[0]);renderFleet(data.active_nodes);renderHistory(data.history);renderDistribution(a.distribution,a.total)}catch(e){console.error(e)}}
async function loadPorts(){const select=document.getElementById('port');try{const data=await (await fetch('/api/serial/ports')).json(),previous=select.value;select.innerHTML='';if(!data.ports.length){select.innerHTML='<option value="">No serial ports detected</option>';return}data.ports.forEach(item=>{const option=document.createElement('option');option.value=item.device;option.textContent=`${item.device} — ${item.description}`;if(item.device===previous||(!previous&&item.device==='COM19'))option.selected=true;select.appendChild(option)})}catch(e){select.innerHTML='<option value="">Unable to load ports</option>'}}
async function submitPacket(){const packet=document.getElementById('packet').value;const r=await fetch('/api/packets',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({packet})}),d=await r.json();notice(r.ok?`Packet accepted: ${d.prediction} (${d.confidence ?? '—'}% confidence).`:d.error,r.ok?'positive':'negative');if(r.ok)refresh()}
async function connectSerial(){const r=await fetch('/api/serial/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({port:document.getElementById('port').value,baud:document.getElementById('baud').value})}),d=await r.json();notice(r.ok?d.message:d.error,r.ok?'positive':'negative');setTimeout(refresh,500)}
async function disconnectSerial(){const r=await fetch('/api/serial/disconnect',{method:'POST'}),d=await r.json();notice(d.message,'info');refresh()}
loadPorts();refresh();setInterval(refresh,2000);
</script></body></html>'''


def main():
    parser = argparse.ArgumentParser(description="BeaconMe Flask dashboard")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "5000")))
    parser.add_argument("--serial-port", help="Connect to this serial port immediately, e.g. COM3")
    parser.add_argument("--baud", type=int, default=9600)
    args = parser.parse_args()
    if args.serial_port:
        try:
            connect_serial(args.serial_port, args.baud)
        except RuntimeError as error:
            print(f"Serial receiver not started: {error}")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
