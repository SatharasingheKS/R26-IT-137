
import argparse
import os
import threading
import time
from collections import Counter, deque
from datetime import datetime, timezone
from math import radians, sin, cos, asin, sqrt
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

# GPS area-priority settings.
# A packet is considered part of the same "nearby area" when its GPS point
# is within this radius of another packet. Areas with this many nearby
# messages are treated as high priority.
GPS_CLUSTER_RADIUS_KM = 5.0
HIGH_PRIORITY_AREA_COUNT = 12

# Nodes listed here are accepted into history but are excluded completely
# from GPS-density priority calculations. Node #3 must not increase the
# nearby-message count or make another location HIGH priority.
GPS_PRIORITY_EXCLUDED_NODES = {3}

app = Flask(__name__)
history = deque(maxlen=MAX_HISTORY)
history_lock = threading.Lock()
active_nodes = {}
active_nodes_lock = threading.Lock()
serial_stop = threading.Event()
serial_thread = None
serial_connection = None
serial_state = {"connected": False, "port": None, "baud": None, "error": None}

# Node #3 rate limiting: accept at most one incoming packet per 60 seconds.
NODE3_ACCEPT_INTERVAL_SECONDS = 60.0
node3_last_accepted_epoch = None
node3_rate_lock = threading.Lock()

# Node #1 burst filtering: accept the first packet, then reject all further
# packets from Node #1 received within 2.5 seconds of that accepted packet.
NODE1_ACCEPT_INTERVAL_SECONDS = 2.5
node1_last_accepted_epoch = None
node1_rate_lock = threading.Lock()


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
    # The ML model is used ONLY as a fake/not-fake detector.
    # Its original multi-class outputs (for example CRITICAL/HIGH/FAKE)
    # are collapsed into two dashboard states: FAKE or REAL.
    raw_prediction = str(model.predict(frame)[0])

    probabilities = {}
    confidence = None
    fake_probability = None
    if hasattr(model, "predict_proba"):
        scores = model.predict_proba(frame)[0]
        raw_probabilities = {
            str(label): float(score)
            for label, score in zip(model.classes_, scores)
        }
        fake_probability = raw_probabilities.get("FAKE", 0.0)
        real_probability = 1.0 - fake_probability
        probabilities = {
            "REAL": round(real_probability * 100, 2),
            "FAKE": round(fake_probability * 100, 2),
        }
        confidence = round(max(real_probability, fake_probability) * 100, 2)
    else:
        fake_probability = 1.0 if raw_prediction == "FAKE" else 0.0
        probabilities = {
            "REAL": 0.0 if raw_prediction == "FAKE" else 100.0,
            "FAKE": 100.0 if raw_prediction == "FAKE" else 0.0,
        }
        confidence = 100.0

    prediction = "FAKE" if raw_prediction == "FAKE" else "REAL"

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


def haversine_km(lat1, lon1, lat2, lon2):
    """Return great-circle distance between two GPS coordinates in km."""
    try:
        lat1, lon1, lat2, lon2 = map(float, (lat1, lon1, lat2, lon2))
    except (TypeError, ValueError):
        return float("inf")

    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 6371.0 * 2 * asin(min(1.0, sqrt(a)))


def analyze_gps_priority(records):
    """
    Classify packets by local message density.

    For every packet, count all session packets within
    GPS_CLUSTER_RADIUS_KM. If that local count reaches
    HIGH_PRIORITY_AREA_COUNT, the packet belongs to a high-priority area;
    otherwise it is low priority.

    This is intentionally independent of the ML emergency prediction:
    GPS density is an additional triage signal.
    """
    valid = []
    for idx, item in enumerate(records):
        # Node #3 is deliberately excluded from GPS-density calculations.
        # Its packets may still appear in history, but they must not count
        # toward nearby_message_count or influence HIGH/LOW classification
        # of any other node.
        try:
            if int(item["node_id"]) in GPS_PRIORITY_EXCLUDED_NODES:
                continue
            lat = float(item["latitude"])
            lon = float(item["longitude"])
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                valid.append((idx, lat, lon))
        except (KeyError, TypeError, ValueError):
            continue

    for item in records:
        item["gps_priority"] = "LOW"
        item["nearby_message_count"] = 0
        item["priority_area"] = None

    for idx, lat, lon in valid:
        nearby = []
        for other_idx, other_lat, other_lon in valid:
            if haversine_km(lat, lon, other_lat, other_lon) <= GPS_CLUSTER_RADIUS_KM:
                nearby.append(other_idx)

        count = len(nearby)
        record = records[idx]
        record["nearby_message_count"] = count
        record["gps_priority"] = (
            "HIGH" if count >= HIGH_PRIORITY_AREA_COUNT else "LOW"
        )

        # Approximate local area center for display.
        if nearby:
            center_lat = sum(float(records[j]["latitude"]) for j in nearby) / len(nearby)
            center_lon = sum(float(records[j]["longitude"]) for j in nearby) / len(nearby)
            record["priority_area"] = {
                "latitude": round(center_lat, 6),
                "longitude": round(center_lon, 6),
                "radius_km": GPS_CLUSTER_RADIUS_KM,
            }

    return records


def receive_packet(packet):
    global node3_last_accepted_epoch, node1_last_accepted_epoch

    now_epoch = time.time()

    # Identify the incoming node before ML prediction/history insertion so
    # packets rejected by the rate filters are not processed or stored.
    try:
        parts = [part.strip() for part in str(packet).strip().split(",")]
        incoming_node_id = int(parts[1])
    except (IndexError, TypeError, ValueError):
        incoming_node_id = None

    # Reject Node #3 BEFORE ML prediction/history insertion. This means a
    # Node #3 packet received less than 60 seconds after the last accepted
    # Node #3 packet is not processed or stored at all.
    if incoming_node_id == 3:
        with node3_rate_lock:
            if (node3_last_accepted_epoch is not None and
                    now_epoch - node3_last_accepted_epoch < NODE3_ACCEPT_INTERVAL_SECONDS):
                return None

    # Node #1 sends packets in bursts. Accept the first packet immediately,
    # then reject ALL additional Node #1 packets for the next 2.5 seconds.
    # The timestamp is reserved before ML prediction so simultaneous requests
    # cannot cause multiple packets from the same burst to be accepted.
    if incoming_node_id == 1:
        with node1_rate_lock:
            if (node1_last_accepted_epoch is not None and
                    now_epoch - node1_last_accepted_epoch < NODE1_ACCEPT_INTERVAL_SECONDS):
                return None
            node1_last_accepted_epoch = now_epoch

    # Only process the packet after the admission checks above.
    record = make_prediction(packet)

    # Record the acceptance time only after successful packet processing.
    if incoming_node_id == 3:
        with node3_rate_lock:
            # Protect against another request accepting Node #3 while the
            # prediction above was being calculated.
            if (node3_last_accepted_epoch is not None and
                    now_epoch - node3_last_accepted_epoch < NODE3_ACCEPT_INTERVAL_SECONDS):
                return None
            node3_last_accepted_epoch = now_epoch

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

    # Recalculate GPS-density priority whenever the dashboard is refreshed,
    # so an area can move from LOW to HIGH as more messages arrive.
    records = analyze_gps_priority(records)
    ml_counts = Counter(item["prediction"] for item in records)
    danger_counts = Counter(item.get("danger_name", "Unknown") for item in records)
    high_priority_gps = [item for item in records if item.get("gps_priority") == "HIGH"]
    low_priority_gps = [item for item in records if item.get("gps_priority") == "LOW"]
    highest = next((item for item in records if item.get("danger_name") == "CRITICAL" and item.get("prediction") != "FAKE"), None)

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
            # Critical/High are packet danger levels, NOT ML predictions.
            "critical": danger_counts["CRITICAL"],
            "high": danger_counts["HIGH"],
            "suspicious": ml_counts["FAKE"],
            # ML distribution is deliberately binary: REAL vs FAKE.
            "distribution": {"REAL": ml_counts["REAL"], "FAKE": ml_counts["FAKE"]},
            "highest_priority": highest,
            "gps_high_count": len(high_priority_gps),
            "gps_low_count": len(low_priority_gps),
            "gps_settings": {
                "radius_km": GPS_CLUSTER_RADIUS_KM,
                "high_threshold": HIGH_PRIORITY_AREA_COUNT,
            },
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
        record = receive_packet(packet)
        if record is None:
            try:
                parts = [part.strip() for part in packet.strip().split(",")]
                rejected_node_id = int(parts[1])
            except (IndexError, TypeError, ValueError):
                rejected_node_id = None

            if rejected_node_id == 1:
                return jsonify(error="Node #1 packet rejected: only the first packet within each 2.5-second window is accepted."), 429
            if rejected_node_id == 3:
                return jsonify(error="Node #3 packet rejected: only one packet per 60 seconds is accepted."), 429
            return jsonify(error="Packet rejected by the admission filter."), 429
        return jsonify(record), 201
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


#alertsBadge{background:white;color:#c62828;border-radius:50px;padding:2px 8px;font-size:0.8rem;font-weight:900;min-width:22px;text-align:center;}
#priorityLinks{display:flex;gap:10px;flex-wrap:wrap;margin:10px 0 20px;}
#priorityLinks a{display:inline-flex;align-items:center;gap:7px;text-decoration:none;border-radius:6px;padding:8px 13px;font-size:.88rem;font-weight:700;box-shadow:0 2px 6px rgba(0,0,0,.12);}
#priorityLinks .confirmed-link{background:#c62828;color:white;}
#priorityLinks .high-link{background:#f2711c;color:white;}
#priorityLinks .low-link{background:#475569;color:white;}
#priorityLinks .badge{background:white;border-radius:12px;padding:2px 7px;font-size:.75rem;min-width:20px;text-align:center;}

#priorityModal{display:none;position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,0.55);backdrop-filter:blur(3px);align-items:flex-start;justify-content:center;padding:40px 16px;overflow-y:auto;}
#priorityModal.open{display:flex;}
#priorityModalBox{background:#fff;border-radius:12px;width:100%;max-width:1050px;box-shadow:0 20px 60px rgba(0,0,0,0.3);overflow:hidden;}
#priorityModalBox .modal-head{color:white;padding:18px 22px;display:flex;justify-content:space-between;align-items:center;}
#priorityModal.high-mode .modal-head{background:linear-gradient(120deg,#7f1d1d,#dc2626);}
#priorityModal.low-mode .modal-head{background:linear-gradient(120deg,#334155,#64748b);}
#priorityModalBox .modal-body{padding:18px 22px;max-height:70vh;overflow-y:auto;}





.priority-badge-high{background:#fee2e2;color:#991b1b;padding:3px 8px;border-radius:20px;font-weight:800;}
.priority-badge-low{background:#e2e8f0;color:#334155;padding:3px 8px;border-radius:20px;font-weight:800;}
.danger-badge{display:inline-block!important;padding:4px 9px!important;border-radius:999px!important;font-weight:800!important;font-size:.78rem!important;line-height:1.1!important;white-space:nowrap!important;}
.danger-critical{background:#fee2e2!important;color:#991b1b!important;border:1px solid #fecaca!important;}
.danger-high{background:#ffedd5!important;color:#9a3412!important;border:1px solid #fed7aa!important;}
.danger-medium{background:#fef3c7!important;color:#92400e!important;border:1px solid #fde68a!important;}
.danger-low{background:#dbeafe!important;color:#1e40af!important;border:1px solid #bfdbfe!important;}
.danger-unknown{background:#f1f5f9!important;color:#475569!important;border:1px solid #cbd5e1!important;}
.ml-badge{display:inline-block!important;padding:4px 9px!important;border-radius:999px!important;font-weight:800!important;font-size:.78rem!important;line-height:1.1!important;white-space:nowrap!important;}
.ml-real{background:#dcfce7!important;color:#166534!important;border:1px solid #bbf7d0!important;}
.ml-fake{background:#fee2e2!important;color:#991b1b!important;border:1px solid #fecaca!important;}
.ml-unknown{background:#f1f5f9!important;color:#475569!important;border:1px solid #cbd5e1!important;}
@media(max-width:600px){.assessment-grid{grid-template-columns:1fr}.packet-card{min-height:0}#sosAlertPopup{top:70px;right:12px;left:12px;max-width:none;}#priorityLinks{justify-content:center;}#priorityLinks a{flex:1 1 100%;justify-content:center;}}


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
        <thead><tr><th>Received</th><th>Node</th><th>Emergency</th><th>Location</th><th>Danger</th><th>ML</th><th>Confidence</th><th>Route</th></tr></thead>
        <tbody id="alertsModalBody"><tr><td colspan="8" class="center aligned empty">No confirmed alerts yet.</td></tr></tbody>
      </table>
    </div>
  </div>
</div>

<!-- GPS Priority Messages Modal -->
<div id="priorityModal" role="dialog" aria-modal="true" aria-labelledby="priorityModalTitle"
     onclick="if(event.target===this)closePriorityModal()">
  <div id="priorityModalBox">
    <div class="modal-head">
      <h2 id="priorityModalTitle" style="margin:0;font-size:1.15rem;">
        <i id="priorityModalIcon" class="map marker alternate icon"></i>
        <span id="priorityModalHeading">GPS Priority Messages</span>
        <span id="priorityModalCount" style="font-weight:400;font-size:.85rem;opacity:.85;"></span>
      </h2>
      <button id="alertsCloseBtn" onclick="closePriorityModal()">&#x2715; Close</button>
    </div>
    <div class="modal-body">
      <p id="priorityModalDescription" style="color:#718096;font-size:.85rem;margin:0 0 14px 0;"></p>
      <table class="ui very basic compact selectable table">
        <thead>
          <tr><th>Received</th><th>Node</th><th>Emergency</th><th>Location</th>
              <th>GPS Priority</th><th>Nearby Messages</th><th>ML Result</th></tr>
        </thead>
        <tbody id="priorityModalBody"></tbody>
      </table>
    </div>
  </div>
</div>

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
<div class="ui four stackable cards" id="metrics"><div class="ui card metric-card"><div class="content"><div class="header">Packets received</div><div class="ui blue statistic"><div class="value" id="total">0</div><div class="label">this session</div></div></div></div><div class="ui card metric-card critical"><div class="content"><div class="header">Critical Danger</div><div class="ui red statistic"><div class="value" id="critical">0</div><div class="label">danger level</div></div></div></div><div class="ui card metric-card high"><div class="content"><div class="header">High Danger</div><div class="ui orange statistic"><div class="value" id="high">0</div><div class="label">danger level</div></div></div></div><div class="ui card metric-card fake"><div class="content"><div class="header">Suspicious</div><div class="ui grey statistic"><div class="value" id="suspicious">0</div><div class="label">ML detected</div></div></div></div></div>

<div id="priorityLinks" aria-label="Priority message links">
  <a href="#confirmed-alerts" class="confirmed-link" onclick="openAlertsModal();return false;" title="View confirmed emergency alerts">
    <i class="exclamation circle icon"></i> Confirmed Alerts
  </a>
  <a href="#high-priority" class="high-link" onclick="openPriorityModal('HIGH');return false;" title="View high GPS-density priority messages">
    <i class="fire icon"></i> High Priority
  </a>
  <a href="#low-priority" class="low-link" onclick="openPriorityModal('LOW');return false;" title="View low GPS-density priority messages">
    <i class="map marker icon"></i> Low Priority
  </a>
</div>

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
<section class="ui raised segment"><h3 class="ui header"><i class="history icon"></i> Packet history <span class="muted" style="font-weight:normal;font-size:.75em">Latest 250 packets retained for this server session</span></h3><table class="ui very basic compact selectable table"><thead><tr><th>Received</th><th>Node</th><th>Emergency</th><th>Location</th><th>Danger Level</th><th>GPS Priority</th><th>ML Result</th><th>Confidence</th><th>Route</th></tr></thead><tbody id="history"><tr><td colspan="8" class="center aligned empty">No packets received yet.</td></tr></tbody></table></section>
</main>
<script>
const escapeHtml=s=>String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const severity=c=>({CRITICAL:'red',HIGH:'orange',MEDIUM:'yellow',LOW:'blue',FAKE:'grey'}[c]||'grey');
const dangerBadge=c=>{
  const raw=String(c??'Unknown');
  const v=raw.toUpperCase();
  const styles={
    CRITICAL:'background:#dc2626!important;color:#fff!important;border:1px solid #b91c1c!important;',
    HIGH:'background:#f97316!important;color:#fff!important;border:1px solid #ea580c!important;',
    MODERATE:'background:#f59e0b!important;color:#fff!important;border:1px solid #d97706!important;',
    MEDIUM:'background:#f59e0b!important;color:#fff!important;border:1px solid #d97706!important;',
    LOW:'background:#2563eb!important;color:#fff!important;border:1px solid #1d4ed8!important;'
  };
  const style=styles[v]||'background:#64748b!important;color:#fff!important;border:1px solid #475569!important;';
  return `<span style="display:inline-block!important;padding:5px 10px!important;border-radius:5px!important;font-weight:800!important;font-size:.78rem!important;line-height:1.1!important;white-space:nowrap!important;${style}">${escapeHtml(raw)}</span>`;
};
const mlBadge=c=>{
  const raw=String(c??'Unknown');
  const v=raw.toUpperCase();
  const style=v==='REAL'
    ? 'background:#16a34a!important;color:#fff!important;border:1px solid #15803d!important;'
    : v==='FAKE'
      ? 'background:#dc2626!important;color:#fff!important;border:1px solid #b91c1c!important;'
      : 'background:#64748b!important;color:#fff!important;border:1px solid #475569!important;';
  return `<span style="display:inline-block!important;padding:5px 10px!important;border-radius:5px!important;font-weight:800!important;font-size:.78rem!important;line-height:1.1!important;white-space:nowrap!important;${style}">${escapeHtml(raw)}</span>`;
};
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
    const isCritical = n.danger_name === 'CRITICAL';
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
        ${dangerBadge(n.danger_name)}
        ${mlBadge(n.prediction)}
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

  target.innerHTML=`<div class="assessment"><div class="assessment-head">${mlBadge(item.prediction)}<b>Node ${item.node_id}</b><span class="muted assessment-time"><i class="clock outline icon"></i>${escapeHtml(item.received_at)}</span></div><div class="assessment-grid"><div class="assessment-box"><h4><i class="first aid icon"></i> Incident details</h4><div class="assessment-title">${titleDisplay}</div><div class="assessment-meta muted">Danger level: ${dangerBadge(item.danger_name)}<br>ML authenticity: ${mlBadge(item.prediction)}<br>${escapeHtml(item.forward_status)}</div><a class="ui small basic button" style="margin-top:12px" target="_blank" rel="noopener" href="${item.map_url}"><i class="map marker alternate icon"></i> Open location</a></div><div class="assessment-box"><h4><i class="brain icon"></i> ML confidence <span class="right floated">${item.confidence ?? '—'}%</span></h4>${prob}</div></div><div class="raw-packet"><b>Raw packet</b> <code>${escapeHtml(item.packet)}</code></div></div>`;
}

let _lastAlertRows = [];
let _lastRows = [];
let _priorityMode = 'HIGH';

function openPriorityModal(mode){
  _priorityMode = mode;
  const modal = document.getElementById('priorityModal');
  modal.classList.toggle('high-mode', mode === 'HIGH');
  modal.classList.toggle('low-mode', mode === 'LOW');
  document.getElementById('priorityModalHeading').textContent =
    mode === 'HIGH' ? 'High Priority Area Messages' : 'Low Priority Area Messages';
  document.getElementById('priorityModalIcon').className =
    mode === 'HIGH' ? 'fire icon' : 'map marker icon';
  document.getElementById('priorityModalDescription').textContent =
    mode === 'HIGH'
      ? 'Messages from GPS areas with multiple incoming packets inside the configured radius. These areas should be reviewed first.'
      : 'Messages from GPS areas with low incoming message density. They remain available for review but are lower in the GPS-density queue.';
  modal.classList.add('open');
  document.body.style.overflow='hidden';
  renderPriorityModal(_lastRows, mode);
}

function closePriorityModal(){
  document.getElementById('priorityModal').classList.remove('open');
  document.body.style.overflow='';
}


function renderPriorityModal(rows, mode){
  const filtered = rows.filter(x => x.gps_priority === mode);
  document.getElementById('priorityModalCount').textContent =
    `(${filtered.length} message${filtered.length===1?'':'s'})`;
  const target = document.getElementById('priorityModalBody');
  if(!filtered.length){
    target.innerHTML='<tr><td colspan="8" class="center aligned empty">No messages in this GPS priority group yet.</td></tr>';
    return;
  }
  target.innerHTML = filtered.map(x => {
    const isSos = (x.emergency_type === 5 || x.emergency_name === 'SOS');
    const msgSub = isSos ? '' : `<div class="muted">${escapeHtml(x.message_name)}</div>`;
    const badge = x.gps_priority === 'HIGH'
      ? '<span class="priority-badge-high">HIGH</span>'
      : '<span class="priority-badge-low">LOW</span>';
    return `<tr>
      <td>${escapeHtml(x.received_at)}</td>
      <td>#${escapeHtml(x.node_id)}</td>
      <td>${escapeHtml(x.emergency_name)}${msgSub}</td>
      <td><a target="_blank" rel="noopener" href="${x.map_url}">${Number(x.latitude).toFixed(5)}, ${Number(x.longitude).toFixed(5)}</a></td>
      <td>${dangerBadge(x.danger_name)}</td>
      <td>${badge}</td>
      <td><b>${x.nearby_message_count}</b> within ${Number(x.priority_area?.radius_km ?? 0).toFixed(1)} km</td>
      <td>${mlBadge(x.prediction)}</td>
    </tr>`;
  }).join('');
}

document.addEventListener('keydown', e => {
  if(e.key==='Escape'){
    closeAlertsModal();
    closePriorityModal();
  }
});



function openAlertsModal(){
  document.getElementById('alertsModal').classList.add('open');
  document.body.style.overflow='hidden';
  renderAlertsModal(_lastAlertRows);
}
function closeAlertsModal(){
  document.getElementById('alertsModal').classList.remove('open');
  document.body.style.overflow='';
}

function renderAlertsModal(rows){
  const confirmedRows = rows.filter(x => x.prediction !== 'FAKE');
  const count = document.getElementById('alertsModalCount');
  count.textContent = `(${confirmedRows.length} alert${confirmedRows.length===1?'':'s'})`;
  const target = document.getElementById('alertsModalBody');
  if(!confirmedRows.length){
    target.innerHTML='<tr><td colspan="8" class="center aligned empty">No confirmed alerts yet.</td></tr>';
    return;
  }
  target.innerHTML = confirmedRows.map(x => {
    const isSos = (x.emergency_type === 5 || x.emergency_name === 'SOS');
    const msgSub = isSos ? '' : `<div class="muted">${escapeHtml(x.message_name)}</div>`;
    return `<tr><td>${escapeHtml(x.received_at)}</td><td>#${x.node_id}</td><td>${escapeHtml(x.emergency_name)}${msgSub}</td><td><a target="_blank" rel="noopener" href="${x.map_url}">${x.latitude.toFixed(5)}, ${x.longitude.toFixed(5)}</a></td><td>${dangerBadge(x.danger_name)}</td><td>${mlBadge(x.prediction)}</td><td>${x.confidence ?? '—'}%</td><td>${escapeHtml(x.forward_status)}</td></tr>`;
  }).join('');
}

function renderHistory(rows){
  _lastRows = rows;
  _lastAlertRows = rows;
  if(document.getElementById('priorityModal').classList.contains('open')){
    renderPriorityModal(rows, _priorityMode);
  }
  if(document.getElementById('alertsModal').classList.contains('open')){
    renderAlertsModal(rows);
  }

  const target=document.getElementById('history');
  if(!rows.length){
    target.innerHTML='<tr><td colspan="9" class="center aligned empty">No packets received yet.</td></tr>';
    return;
  }
  target.innerHTML=rows.map(x=>{
    const isSos = (x.emergency_type === 5 || x.emergency_name === 'SOS');
    const msgSub = isSos ? '' : `<div class="muted">${escapeHtml(x.message_name)}</div>`;
    const priority = x.gps_priority === 'HIGH'
      ? `<span class="priority-badge-high">HIGH</span><div class="muted">${x.nearby_message_count} nearby</div>`
      : `<span class="priority-badge-low">LOW</span><div class="muted">${x.nearby_message_count} nearby</div>`;
    return `<tr>
      <td>${escapeHtml(x.received_at)}</td>
      <td>#${escapeHtml(x.node_id)}</td>
      <td>${escapeHtml(x.emergency_name)}${msgSub}</td>
      <td><a target="_blank" rel="noopener" href="${x.map_url}">${Number(x.latitude).toFixed(5)}, ${Number(x.longitude).toFixed(5)}</a></td>
      <td>${dangerBadge(x.danger_name)}</td>
      <td>${priority}</td>
      <td>${mlBadge(x.prediction)}</td>
      <td>${x.confidence ?? '—'}%</td>
      <td>${escapeHtml(x.forward_status)}</td>
    </tr>`;
  }).join('');
}

function renderDistribution(data,total){document.getElementById('distribution').innerHTML=Object.entries(data).map(([key,value])=>{let p=total?Math.round(value/total*100):0;return `<div style="margin:11px 0"><b>${escapeHtml(key)}</b><span class="right floated muted">${value} (${p}%)</span><div class="bar" style="margin-top:5px"><i style="width:${p}%;background:${severity(key)==='red'?'#db2828':severity(key)==='orange'?'#f2711c':'#2185d0'}"></i></div></div>`}).join('')}
async function refresh(){try{const data=await (await fetch('/api/dashboard')).json(),a=data.analytics;
['total','critical','high','suspicious'].forEach(k=>document.getElementById(k).textContent=a[k]);document.getElementById('modelName').textContent=data.model.name;document.getElementById('modelAccuracy').textContent=data.model.accuracy+'%';document.getElementById('serialStatus').innerHTML=`<i class="${data.serial.connected?'green check circle':'grey circle'} icon"></i> ${data.serial.connected?`Connected to ${escapeHtml(data.serial.port)} at ${data.serial.baud} baud`:'Not connected'}${data.serial.error?`<br><span class="red text">${escapeHtml(data.serial.error)}</span>`:''}`;const received=document.getElementById('receivedPacket');received.textContent=data.serial.received_packet||'Waiting for serial data…';renderLatest(data.history[0]);renderFleet(data.active_nodes);renderHistory(data.history);renderDistribution(a.distribution,a.total)}catch(e){console.error(e)}}
async function loadPorts(){const select=document.getElementById('port');try{const data=await (await fetch('/api/serial/ports')).json(),previous=select.value;select.innerHTML='';if(!data.ports.length){select.innerHTML='<option value="">No serial ports detected</option>';return}data.ports.forEach(item=>{const option=document.createElement('option');option.value=item.device;option.textContent=`${item.device} — ${item.description}`;if(item.device===previous||(!previous&&item.device==='COM19'))option.selected=true;select.appendChild(option)})}catch(e){select.innerHTML='<option value="">Unable to load ports</option>'}}
async function submitPacket(){const packet=document.getElementById('packet').value;const r=await fetch('/api/packets',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({packet})}),d=await r.json();notice(r.ok?`Packet accepted: ML ${d.prediction} (${d.confidence ?? '—'}% confidence). Danger level is read from the packet.`:d.error,r.ok?'positive':'negative');if(r.ok)refresh()}
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
