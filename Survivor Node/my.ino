#include <LoRa.h>
#include <SoftwareSerial.h>
#include <TinyGPSPlus.h>
#include <WebServer.h>
#include <WiFi.h>


// =====================================================
// BeaconMe Survivor Node
// ESP32-C6 + WiFi UI + LoRa RF SOS transmitter
// =====================================================

#define LORA_RX_PIN 15
#define LORA_TX_PIN 23

#define SOS_BUTTON_PIN 6

#define GREEN_LED_PIN 18
#define RED_LED_PIN 21

#define USE_STATUS_LED 0
#define STATUS_LED_PIN 8

SoftwareSerial LoRa_rf(LORA_RX_PIN, LORA_TX_PIN);
WebServer server(80);
TinyGPSPlus gps;

// ---------------- WIFI CONFIG ----------------
const char *AP_SSID = "BeaconMe_Survivor";
const char *AP_PASS = "12345678";

// ---------------- SOS DATA ----------------
int survivorNodeId = 1;

// Default demo location
float latitude = 6.92710;
float longitude = 79.86119;

// Emergency type:
// 1 = Medical
// 2 = Fire
// 3 = Flood
// 4 = Trapped
// 5 = SOS
int emergencyType = 1;

// Message code:
// 1 = Need rescue
// 2 = Injured
// 3 = Trapped
// 4 = Need medicine
// 5 = Unconscious
// 6 = Fire nearby
int messageCode = 1;

// Danger level:
// 1 = Low
// 2 = Moderate
// 3 = Serious
// 4 = High
// 5 = Critical
int dangerLevel = 5;

// Survivor node always starts hop count from 0
const int START_HOP_COUNT = 0;

String lastPacket = "No SOS packet sent yet.";
String lastSendSource = "None";
unsigned long lastPacketSendMillis = 0;
unsigned long packetCount = 0;

// Continuous 3-second critical SOS broadcast loop state
bool emergencyLoopActive = false;
unsigned long lastSosSendTime = 0;
const unsigned long SOS_LOOP_INTERVAL_MS = 3000;

bool lastButtonState = HIGH;
bool buttonState = HIGH;
unsigned long lastDebounceTime = 0;
const unsigned long debounceDelayMs = 20;
unsigned long greenLedOffTime = 0;
const unsigned long greenLedPulseMs = 100;
const unsigned long peripheralSettleMs = 300;

String selectedAttr(int value, int current) {
  if (value == current) {
    return " selected";
  }
  return "";
}

String emergencyTypeName(int code) {
  if (code == 1)
    return "Medical";
  if (code == 2)
    return "Fire";
  if (code == 3)
    return "Flood";
  if (code == 4)
    return "Trapped";
  if (code == 5)
    return "SOS";
  return "Unknown";
}

String messageCodeName(int code) {
  if (code == 1)
    return "Need rescue";
  if (code == 2)
    return "Injured";
  if (code == 3)
    return "Trapped";
  if (code == 4)
    return "Need medicine";
  if (code == 5)
    return "Unconscious";
  if (code == 6)
    return "Fire nearby";
  return "Unknown";
}

String dangerLevelName(int code) {
  if (code == 1)
    return "Low";
  if (code == 2)
    return "Moderate";
  if (code == 3)
    return "Serious";
  if (code == 4)
    return "High";
  if (code == 5)
    return "Critical";
  return "Unknown";
}

String buildSosPacket() {
  int32_t latE5 = (int32_t)(latitude * 100000.0);
  int32_t lonE5 = (int32_t)(longitude * 100000.0);

  String packet = "";
  packet += "S";
  packet += ",";
  packet += String(survivorNodeId);
  packet += ",";
  packet += String(latE5);
  packet += ",";
  packet += String(lonE5);
  packet += ",";
  packet += String(emergencyType);
  packet += ",";
  packet += String(messageCode);
  packet += ",";
  packet += String(dangerLevel);
  packet += ",";
  packet += String(START_HOP_COUNT);

  return packet;
}

void blinkStatus() {
#if USE_STATUS_LED
  digitalWrite(STATUS_LED_PIN, HIGH);
  delay(50);
  digitalWrite(STATUS_LED_PIN, LOW);
#endif
}

void sendSosPacket(String source) {
  if (!gps.location.isValid()) {
    Serial.println("GPS FIX NOT AVAILABLE");
    return;
  }

  String packet = buildSosPacket();

  lastPacket = packet;
  lastSendSource = source;
  lastPacketSendMillis = millis();
  packetCount++;

  Serial.println();
  Serial.println("========== BeaconMe SOS SENT ==========");
  Serial.print("Source: ");
  Serial.println(source);
  Serial.print("LoRa Packet #");
  Serial.print(packetCount);
  Serial.print(": ");
  Serial.println(packet);
  Serial.print("Emergency: ");
  Serial.println(emergencyTypeName(emergencyType));
  Serial.print("Loop Mode: ");
  Serial.println(emergencyLoopActive ? "ACTIVE (3s Loop)"
                                     : "SINGLE TRANSMISSION");
  Serial.println("=======================================");

  // Non-blocking single RF pulse with LED indication so web UI & GPS keep
  // streaming
  digitalWrite(RED_LED_PIN, HIGH);
  LoRa_rf.println(packet);
  blinkStatus();
  delay(60);
  digitalWrite(RED_LED_PIN, LOW);
}

void updateValuesFromRequest() {
  if (server.hasArg("node")) {
    survivorNodeId = server.arg("node").toInt();
  }

  if (server.hasArg("etype")) {
    emergencyType = server.arg("etype").toInt();
  }

  if (server.hasArg("msg")) {
    messageCode = server.arg("msg").toInt();
  }

  if (server.hasArg("danger")) {
    dangerLevel = server.arg("danger").toInt();
  }
}

void handleSend() {
  // Block manual send while the SOS emergency loop is running
  if (emergencyLoopActive) {
    server.sendHeader("Location", "/?locked=1");
    server.send(303);
    return;
  }

  updateValuesFromRequest();
  sendSosPacket("BeaconMe WiFi UI");

  server.sendHeader("Location", "/?sent=1");
  server.send(303);
}

void handleStartLoop() {
  emergencyLoopActive = true;
  dangerLevel = 5;   // Force Critical
  messageCode = 1;   // Need rescue
  emergencyType = 5; // Force SOS
  sendSosPacket("WiFi UI - Emergency Loop Activated (SOS)");
  lastSosSendTime = millis();

  server.sendHeader("Location", "/");
  server.send(303);
}

void handleStopLoop() {
  emergencyLoopActive = false;
  Serial.println(">>> EMERGENCY SOS LOOP DEACTIVATED <<<");

  server.sendHeader("Location", "/");
  server.send(303);
}

void handleStatusJson() {
  String json = "{";
  json +=
      "\"emergency_active\":" + String(emergencyLoopActive ? "true" : "false") +
      ",";
  json += "\"node_id\":" + String(survivorNodeId) + ",";
  json += "\"connected_clients\":" + String(WiFi.softAPgetStationNum()) + ",";
  json += "\"latitude\":" + String(latitude, 6) + ",";
  json += "\"longitude\":" + String(longitude, 6) + ",";
  json += "\"emergency_type\":" + String(emergencyType) + ",";
  json += "\"emergency_name\":\"" + emergencyTypeName(emergencyType) + "\",";
  json += "\"gps_valid\":" + String(gps.location.isValid() ? "true" : "false") +
          ",";
  json += "\"satellites\":" +
          String(gps.satellites.isValid() ? gps.satellites.value() : 0) + ",";
  json += "\"packet_count\":" + String(packetCount) + ",";
  json +=
      "\"seconds_since_pulse\":" +
      String(lastPacketSendMillis > 0 ? (millis() - lastPacketSendMillis) / 1000
                                      : -1) +
      ",";
  json += "\"last_packet\":\"" + lastPacket + "\"";
  json += "}";
  server.send(200, "application/json; charset=utf-8", json);
}

void handleAllDataJson() {
  String json = "{";
  json +=
      "\"emergency_active\":" + String(emergencyLoopActive ? "true" : "false") +
      ",";
  json += "\"node_id\":" + String(survivorNodeId) + ",";
  json += "\"connected_clients\":" + String(WiFi.softAPgetStationNum()) + ",";
  json += "\"latitude\":" + String(latitude, 6) + ",";
  json += "\"longitude\":" + String(longitude, 6) + ",";
  json += "\"emergency_type\":" + String(emergencyType) + ",";
  json += "\"emergency_name\":\"" + emergencyTypeName(emergencyType) + "\",";
  json += "\"message_code\":" + String(messageCode) + ",";
  json += "\"message_name\":\"" + messageCodeName(messageCode) + "\",";
  json += "\"danger_level\":" + String(dangerLevel) + ",";
  json += "\"danger_name\":\"" + dangerLevelName(dangerLevel) + "\",";
  json += "\"gps_valid\":" + String(gps.location.isValid() ? "true" : "false") +
          ",";
  json += "\"satellites\":" +
          String(gps.satellites.isValid() ? gps.satellites.value() : 0) + ",";
  json += "\"packet_count\":" + String(packetCount) + ",";
  json += "\"last_packet_send_millis\":" + String(lastPacketSendMillis) + ",";
  json +=
      "\"seconds_since_pulse\":" +
      String(lastPacketSendMillis > 0 ? (millis() - lastPacketSendMillis) / 1000
                                      : -1) +
      ",";
  json += "\"last_send_source\":\"" + lastSendSource + "\",";
  json += "\"last_packet\":\"" + lastPacket + "\",";
  json += "\"start_hop_count\":" + String(START_HOP_COUNT) + ",";
  json += "\"sos_loop_interval_ms\":" + String(SOS_LOOP_INTERVAL_MS);
  json += "}";
  server.send(200, "application/json; charset=utf-8", json);
}

void addOption(String &html, int value, int current, String label) {
  html += "<option value='";
  html += String(value);
  html += "'";
  html += selectedAttr(value, current);
  html += ">";
  html += label;
  html += "</option>";
}

void handleRoot() {
  String html = "";

  html += "<!DOCTYPE html><html lang='en'><head>";
  html += "<meta charset='UTF-8'>";
  html += "<meta name='viewport' content='width=device-width, initial-scale=1, "
          "maximum-scale=1, user-scalable=no'>";
  html += "<title>BeaconMe Survivor Node &bull; Emergency HUD</title>";

  html += "<style>";
  html += "*,*::before,*::after{margin:0;padding:0;box-sizing:border-box;-"
          "webkit-tap-highlight-color:transparent;}";
  html += ":root{--bg-pri:#070b14;--bg-card:rgba(11,18,33,0.8);--border-subtle:"
          "rgba(56,189,248,0.15);--text-main:#f1f5f9;--text-muted:#8493a8;--"
          "text-dim:#50617a;--sos-red:#ff2a55;--sos-glow:rgba(255,42,85,0.45);-"
          "-hud-cyan:#00f0ff;--ok-green:#10b981;}";
  html += "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe "
          "UI',Roboto,sans-serif;background-color:var(--bg-pri);color:var(--"
          "text-main);min-height:100vh;padding:16px 12px "
          "40px;overflow-x:hidden;position:relative;background-image:radial-"
          "gradient(circle at 50% 0%,rgba(0,240,255,0.08) 0%,transparent "
          "65%),radial-gradient(circle at 10% 40%,rgba(255,42,85,0.06) "
          "0%,transparent 50%),radial-gradient(circle at 90% "
          "80%,rgba(59,130,246,0.07) 0%,transparent "
          "60%);background-attachment:fixed;}";
  html += "body::after{content:'';position:fixed;top:0;left:0;right:0;bottom:0;"
          "background-size:32px 32px;background-image:linear-gradient(to "
          "right,rgba(255,255,255,0.015) 1px,transparent "
          "1px),linear-gradient(to bottom,rgba(255,255,255,0.015) "
          "1px,transparent 1px);pointer-events:none;z-index:0;}";
  html +=
      ".container{max-width:480px;margin:0 auto;position:relative;z-index:1;}";

  // Header & Beacon Ring Pulse
  html +=
      ".hud-header{text-align:center;padding:10px 0 18px;position:relative;}";
  html +=
      ".beacon-visualizer{position:relative;width:72px;height:72px;margin:0 "
      "auto 12px;display:flex;align-items:center;justify-content:center;}";
  html += ".beacon-core{width:44px;height:44px;border-radius:50%;background:"
          "radial-gradient(circle,#ff2a55 0%,#b91c1c "
          "80%);display:flex;align-items:center;justify-content:center;box-"
          "shadow:0 0 20px var(--sos-glow),0 0 35px "
          "rgba(255,42,85,0.3);position:relative;z-index:3;animation:corePulse "
          "2s ease-in-out infinite;}";
  html +=
      ".beacon-core svg{width:22px;height:22px;fill:#fff;filter:drop-shadow(0 "
      "0 4px rgba(255,255,255,0.8));}";
  html += ".beacon-ring{position:absolute;top:50%;left:50%;transform:translate("
          "-50%,-50%);border-radius:50%;border:1.5px solid "
          "rgba(255,42,85,0.6);pointer-events:none;animation:ringRipple 3s "
          "cubic-bezier(0.1,0.7,0.3,1) infinite;}";
  html += ".beacon-ring:nth-child(2){animation-delay:1s;}.beacon-ring:nth-"
          "child(3){animation-delay:2s;}";
  html += "@keyframes "
          "ringRipple{0%{width:44px;height:44px;opacity:0.9;border-color:rgba("
          "255,42,85,0.9);box-shadow:0 0 10px "
          "rgba(255,42,85,0.4);}100%{width:90px;height:90px;opacity:0;border-"
          "color:rgba(255,42,85,0);}}";
  html += "@keyframes corePulse{0%,100%{transform:scale(1);box-shadow:0 0 20px "
          "var(--sos-glow),0 0 35px "
          "rgba(255,42,85,0.3);}50%{transform:scale(1.06);box-shadow:0 0 30px "
          "var(--sos-glow),0 0 50px rgba(255,42,85,0.5);}}";

  html += ".hud-title{font-size:24px;font-weight:900;letter-spacing:0.8px;text-"
          "transform:uppercase;background:linear-gradient(135deg,#ffffff "
          "0%,#cbd5e1 50%,#94a3b8 "
          "100%);-webkit-background-clip:text;-webkit-text-fill-color:"
          "transparent;background-clip:text;line-height:1.1;}";
  html +=
      ".hud-title span{background:linear-gradient(135deg,#ff2a55 0%,#ff7828 "
      "100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;"
      "background-clip:text;}";
  html += ".hud-badges{display:flex;align-items:center;justify-content:center;"
          "gap:6px;flex-wrap:wrap;margin-top:8px;}";
  html += ".pill-badge{font-size:10px;font-weight:700;letter-spacing:0.8px;"
          "padding:4px "
          "10px;border-radius:9999px;display:inline-flex;align-items:center;"
          "gap:5px;text-transform:uppercase;}";
  html += ".pill-offline{background:rgba(30,41,59,0.7);color:#94a3b8;border:"
          "1px solid rgba(71,85,105,0.4);}";
  html +=
      ".pill-lora{background:rgba(0,240,255,0.08);color:var(--hud-cyan);border:"
      "1px solid rgba(0,240,255,0.3);box-shadow:0 0 10px rgba(0,240,255,0.1);}";
  html += ".pill-wifi{background:rgba(16,185,129,0.12);color:#34d399;border:"
          "1px solid rgba(16,185,129,0.4);box-shadow:0 0 12px "
          "rgba(16,185,129,0.2);font-size:10px;font-weight:800;letter-spacing:"
          "0.6px;display:inline-flex;align-items:center;gap:6px;}";
  html += ".wifi-dot{width:7px;height:7px;border-radius:50%;background:#10b981;"
          "box-shadow:0 0 8px #10b981;animation:wifiPulse 1.6s ease-in-out "
          "infinite;display:inline-block;}";
  html +=
      "@keyframes wifiPulse{0%,100%{transform:scale(1);opacity:1;box-shadow:0 "
      "0 6px #10b981;}50%{transform:scale(1.45);opacity:0.45;box-shadow:0 0 "
      "14px #34d399,0 0 20px rgba(52,211,153,0.5);}}";
  html += ".form-row{display:grid;grid-template-columns:1fr 1fr;gap:10px;}";
  html += "@media(max-width:380px){.form-row{grid-template-columns:1fr;}}";

  // Cards & Glow
  html +=
      ".card{background:var(--bg-card);backdrop-filter:blur(16px);-webkit-"
      "backdrop-filter:blur(16px);border:1px solid "
      "var(--border-subtle);border-radius:20px;padding:16px;margin-bottom:14px;"
      "position:relative;overflow:hidden;box-shadow:0 8px 24px "
      "rgba(0,0,0,0.4),inset 0 1px 0 "
      "rgba(255,255,255,0.05);transition:transform 0.2s ease,border-color 0.2s "
      "ease,box-shadow 0.2s ease;animation:cardFadeIn 0.45s ease-out both;}";
  html += ".card:nth-child(1){animation-delay:0.05s;}.card:nth-child(2){"
          "animation-delay:0.12s;}.card:nth-child(3){animation-delay:0.18s;}."
          "card:nth-child(4){animation-delay:0.24s;}";
  html += "@keyframes "
          "cardFadeIn{from{opacity:0;transform:translateY(14px);}to{opacity:1;"
          "transform:translateY(0);}}";
  html += ".card::before{content:'';position:absolute;top:0;left:0;right:0;"
          "height:1px;background:linear-gradient(90deg,transparent "
          "0%,rgba(56,189,248,0.4) 50%,transparent 100%);}";

  // Card Header & Badges
  html += ".card-header{display:flex;justify-content:space-between;align-items:"
          "center;margin-bottom:12px;}";
  html += ".card-title{font-size:13px;font-weight:800;color:var(--text-main);"
          "letter-spacing:0.6px;text-transform:uppercase;display:flex;align-"
          "items:center;gap:8px;}";
  html += ".card-title-icon{width:18px;height:18px;display:inline-flex;align-"
          "items:center;justify-content:center;}";
  html += ".card-title-icon svg{width:16px;height:16px;}";

  html += ".status-pill{font-size:10px;font-weight:800;padding:4px "
          "10px;border-radius:9999px;letter-spacing:0.8px;display:inline-flex;"
          "align-items:center;gap:6px;}";
  html += ".status-standby{background:rgba(30,41,59,0.7);color:#94a3b8;border:"
          "1px solid rgba(71,85,105,0.5);}";
  html += ".status-standby "
          ".dot{width:6px;height:6px;border-radius:50%;background:#64748b;}";
  html +=
      ".status-active{background:rgba(255,42,85,0.2);color:#ff94a8;border:1px "
      "solid rgba(255,42,85,0.5);box-shadow:0 0 12px rgba(255,42,85,0.3);}";
  html += ".status-active "
          ".dot{width:6px;height:6px;border-radius:50%;background:var(--sos-"
          "red);box-shadow:0 0 8px var(--sos-red);animation:sosDotFlash 0.8s "
          "ease-in-out infinite;}";
  html += "@keyframes "
          "sosDotFlash{0%,100%{opacity:1;transform:scale(1);}50%{opacity:0.3;"
          "transform:scale(0.7);}}";
  html +=
      ".status-live{background:rgba(16,185,129,0.15);color:#6ee7b7;border:1px "
      "solid rgba(16,185,129,0.4);box-shadow:0 0 10px rgba(16,185,129,0.15);}";
  html += ".status-live "
          ".dot{width:6px;height:6px;border-radius:50%;background:var(--ok-"
          "green);box-shadow:0 0 8px var(--ok-green);animation:liveBlink 1.4s "
          "ease-in-out infinite;}";
  html += "@keyframes liveBlink{0%,100%{opacity:1;}50%{opacity:0.25;}}";

  // Active Emergency Danger Card
  html += ".card-danger-active{background:linear-gradient(180deg,rgba(70,10,20,"
          "0.85) 0%,rgba(25,8,15,0.9) 100%);border:1.5px solid "
          "var(--sos-red);box-shadow:0 0 30px rgba(255,42,85,0.3),inset 0 0 "
          "20px rgba(255,42,85,0.15);animation:activeCardPulse 2.5s "
          "ease-in-out infinite;}";
  html += "@keyframes activeCardPulse{0%,100%{box-shadow:0 0 25px "
          "rgba(255,42,85,0.25),inset 0 0 15px "
          "rgba(255,42,85,0.1);}50%{box-shadow:0 0 45px "
          "rgba(255,42,85,0.5),inset 0 0 30px rgba(255,42,85,0.25);}}";
  html += ".card-danger-active::after{content:'';position:absolute;top:0;left:"
          "0;right:0;height:3px;background:linear-gradient(90deg,transparent,"
          "rgba(255,255,255,0.8),var(--sos-red),transparent);box-shadow:0 0 "
          "10px var(--sos-red);animation:radarScan 2.4s linear "
          "infinite;pointer-events:none;}";
  html +=
      "@keyframes "
      "radarScan{0%{top:0;opacity:1;}90%{opacity:1;}100%{top:100%;opacity:0;}}";
  html += ".em-desc{font-size:12px;color:var(--text-muted);line-height:1.5;"
          "margin-bottom:14px;}";

  // Buttons & Animations
  html += "a{text-decoration:none;display:block;}";
  html += "button{width:100%;display:flex;align-items:center;justify-content:"
          "center;gap:10px;padding:15px "
          "18px;border:0;border-radius:14px;font-size:14px;font-weight:800;"
          "letter-spacing:0.8px;text-transform:uppercase;cursor:pointer;"
          "position:relative;overflow:hidden;transition:transform 0.15s "
          "cubic-bezier(0.4,0,0.2,1),box-shadow 0.2s ease,filter 0.2s "
          "ease;user-select:none;}";
  html += "button:active{transform:scale(0.975);}";

  html += ".btn-sos{background:linear-gradient(135deg,#ff1a40 0%,#e11d48 "
          "40%,#ff6b00 100%);color:#fff;font-size:16px;padding:18px "
          "20px;border-radius:14px;border:1px solid "
          "rgba(255,255,255,0.3);box-shadow:0 6px 25px rgba(255,26,64,0.45),0 "
          "0 45px rgba(255,107,0,0.25);animation:sosGlowBreath 2.2s "
          "ease-in-out infinite;}";
  html += "@keyframes sosGlowBreath{0%,100%{box-shadow:0 6px 25px "
          "rgba(255,26,64,0.45),0 0 35px rgba(255,107,0,0.2);}50%{box-shadow:0 "
          "8px 38px rgba(255,26,64,0.7),0 0 65px rgba(255,107,0,0.45);}}";
  html += ".btn-sos::after{content:'';position:absolute;top:-50%;left:-60%;"
          "width:220%;height:200%;background:linear-gradient(60deg,transparent "
          "20%,rgba(255,255,255,0.22) 40%,rgba(255,255,255,0.35) "
          "50%,rgba(255,255,255,0.22) 60%,transparent "
          "80%);transform:rotate(25deg);animation:lightSweep 3.5s infinite "
          "cubic-bezier(0.4,0,0.2,1);}";
  html += "@keyframes lightSweep{0%{transform:translateX(-120%) "
          "rotate(25deg);}35%,100%{transform:translateX(120%) rotate(25deg);}}";

  html += ".btn-stop{background:linear-gradient(135deg,rgba(30,41,59,0.9) "
          "0%,rgba(15,23,42,0.95) 100%);color:#ff94a8;border:1.5px solid "
          "rgba(255,42,85,0.6);box-shadow:0 4px 20px rgba(0,0,0,0.5),inset 0 0 "
          "15px rgba(255,42,85,0.15);}";
  html += ".btn-stop:hover{background:linear-gradient(135deg,rgba(45,20,30,0.9)"
          " 0%,rgba(30,10,20,0.95) 100%);border-color:var(--sos-red);}";

  html += ".btn-send{background:linear-gradient(135deg,#1d4ed8 0%,#2563eb "
          "50%,#00d2ff 100%);color:#fff;border:1px solid "
          "rgba(255,255,255,0.25);box-shadow:0 4px 20px rgba(37,99,235,0.4),0 "
          "0 30px rgba(0,210,255,0.2);margin-top:14px;}";
  html += ".btn-send:hover{filter:brightness(1.1);box-shadow:0 6px 28px "
          "rgba(37,99,235,0.6),0 0 40px rgba(0,210,255,0.35);}";

  // Telemetry Grid & Tiles
  html += ".meta-grid{display:grid;grid-template-columns:1fr "
          "1fr;gap:10px;margin:6px 0 10px;}";
  html += ".meta-tile{background:rgba(15,23,42,0.6);border:1px solid "
          "rgba(56,189,248,0.12);border-radius:14px;padding:12px;position:"
          "relative;transition:all 0.25s ease;}";
  html += ".meta-tile:hover{border-color:rgba(56,189,248,0.35);background:rgba("
          "15,23,42,0.85);}";
  html += ".meta-tile-label{font-size:9px;font-weight:700;color:var(--text-dim)"
          ";text-transform:uppercase;letter-spacing:1px;margin-bottom:5px;"
          "display:flex;align-items:center;gap:4px;}";
  html += ".meta-tile-value{font-size:15px;font-weight:800;color:var(--text-"
          "main);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;"
          "letter-spacing:-0.2px;display:flex;align-items:baseline;gap:4px;"
          "transition:color 0.3s ease,text-shadow 0.3s ease;}";
  html += ".meta-tile-value.cyan-glow{color:#38bdf8;text-shadow:0 0 10px "
          "rgba(56,189,248,0.4);}";
  html += ".coord-updated{animation:coordFlash 0.6s ease-out;}";
  html += "@keyframes coordFlash{0%{color:#00ffff;text-shadow:0 0 16px "
          "#00ffff;transform:scale(1.03);}100%{color:#38bdf8;text-shadow:0 0 "
          "10px rgba(56,189,248,0.4);transform:scale(1);}}";

  // Terminal & Code Screen
  html += ".terminal-container{margin-top:8px;position:relative;}";
  html += ".terminal-header{background:rgba(15,23,42,0.95);border-top-left-"
          "radius:8px;border-top-right-radius:8px;border:1px solid "
          "rgba(56,189,248,0.2);border-bottom:0;padding:6px "
          "12px;display:flex;align-items:center;justify-content:space-between;"
          "font-size:9px;font-family:ui-monospace,monospace;color:var(--text-"
          "dim);text-transform:uppercase;}";
  html +=
      ".terminal-dots{display:flex;gap:4px;}.terminal-dot{width:6px;height:6px;"
      "border-radius:50%;}.terminal-dot.r{background:#ef4444;}.terminal-dot.y{"
      "background:#f59e0b;}.terminal-dot.g{background:#10b981;}";
  html += "code.datastream-code{display:block;font-family:ui-monospace,SFMono-"
          "Regular,Menlo,monospace;font-size:11px;line-height:1.6;color:#"
          "38bdf8;background:#060a12;padding:12px "
          "14px;border-bottom-left-radius:8px;border-bottom-right-radius:8px;"
          "border:1px solid "
          "rgba(56,189,248,0.2);word-break:break-all;text-shadow:0 0 8px "
          "rgba(56,189,248,0.35);box-shadow:inset 0 2px 8px rgba(0,0,0,0.6);}";
  html += ".protocol-legend{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;"
          "font-size:9px;font-family:ui-monospace,monospace;color:var(--text-"
          "dim);}";
  html += ".legend-tag{background:rgba(30,41,59,0.5);padding:2px "
          "6px;border-radius:4px;border:1px solid rgba(51,65,85,0.5);}";

  // Form Controls
  html += ".form-group{margin-bottom:12px;}";
  html += "label{display:flex;align-items:center;gap:6px;font-size:11px;font-"
          "weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:0."
          "8px;margin-bottom:6px;}";
  html += "label svg{width:14px;height:14px;fill:#64748b;}";
  html +=
      "input,select{width:100%;padding:13px 14px;border-radius:14px;border:1px "
      "solid "
      "rgba(56,189,248,0.2);background:rgba(15,23,42,0.7);color:#f8fafc;font-"
      "size:14px;font-weight:600;transition:all 0.2s "
      "ease;-webkit-appearance:none;appearance:none;box-sizing:border-box;}";
  html += "input:focus,select:focus{outline:none;border-color:var(--hud-cyan);"
          "background:rgba(15,23,42,0.95);box-shadow:0 0 0 3px "
          "rgba(0,240,255,0.15),0 0 15px rgba(0,240,255,0.1);}";
  html += "select{background-image:url(\"data:image/svg+xml,%3Csvg "
          "xmlns='http://www.w3.org/2000/svg' width='14' height='14' "
          "viewBox='0 0 24 24' fill='none' stroke='%2338bdf8' "
          "stroke-width='2.5' stroke-linecap='round' "
          "stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 "
          "9'%3E%3C/polyline%3E%3C/"
          "svg%3E\");background-repeat:no-repeat;background-position:right "
          "14px center;padding-right:38px;cursor:pointer;}";
  html += "select option{background-color:#0b1326;color:#ffffff;padding:10px;}";

  // Footer & Toast
  html += ".status-bar{display:flex;align-items:center;justify-content:center;"
          "gap:8px;padding:12px "
          "6px;font-size:10px;font-weight:700;color:var(--text-dim);letter-"
          "spacing:1px;text-transform:uppercase;}";
  html += ".status-bar "
          ".pulse-dot{width:7px;height:7px;border-radius:50%;background:var(--"
          "ok-green);box-shadow:0 0 8px var(--ok-green);animation:liveBlink "
          "1.8s infinite;}";
  html +=
      ".toast{position:fixed;top:24px;left:50%;transform:translateX(-50%) "
      "translateY(-100px);background:linear-gradient(135deg,rgba(5,150,105,0."
      "95) 0%,rgba(4,120,87,0.95) 100%);color:#fff;padding:12px "
      "24px;border-radius:9999px;font-size:13px;font-weight:800;letter-spacing:"
      "0.5px;display:flex;align-items:center;gap:8px;z-index:9999;border:1px "
      "solid rgba(255,255,255,0.3);box-shadow:0 10px 35px "
      "rgba(5,150,105,0.5),0 0 20px rgba(16,185,129,0.4);transition:transform "
      "0.4s cubic-bezier(0.34,1.56,0.64,1);pointer-events:none;}";
  html += ".toast.show{transform:translateX(-50%) translateY(0);}.toast "
          "svg{width:18px;height:18px;fill:#fff;}";

  html += "</style>";
  html += "</head><body><div class='container'>";

  // HUD Header
  html += "<header class='hud-header'>";
  html += "<div class='beacon-visualizer'>";
  html += "<div class='beacon-ring'></div><div class='beacon-ring'></div><div "
          "class='beacon-ring'></div>";
  html += "<div class='beacon-core'>";
  html += "<svg viewBox='0 0 24 24'><path d='M12 2L4 5v6.09c0 5.05 3.41 9.76 8 "
          "10.91 4.59-1.15 8-5.86 8-10.91V5l-8-3zm1 "
          "14h-2v-2h2v2zm0-4h-2V7h2v5z'/></svg>";
  html += "</div></div>";
  html += "<h1 class='hud-title'>BEACON<span>ME</span> SURVIVOR</h1>";
  html += "<div class='hud-badges'>";
  html += "<span class='pill-badge pill-offline'><svg width='10' height='10' "
          "viewBox='0 0 24 24' fill='currentColor'><path d='M12 2C6.48 2 2 "
          "6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 "
          "14H9V8h2v8zm4 0h-2V8h2v8z'/></svg> OFFLINE CAPTIVE PORTAL</span>";
  html += "<span class='pill-badge pill-lora'><svg width='10' height='10' "
          "viewBox='0 0 24 24' fill='currentColor'><path d='M12 3a9 9 0 0 0-9 "
          "9c0 2.4.9 4.6 2.4 6.2l1.4-1.4A7 7 0 0 1 5 12a7 7 0 0 1 7-7 7 7 0 0 "
          "1 7 7c0 1.9-.8 3.7-2.1 5l1.4 1.4A9 9 0 0 0 21 12a9 9 0 0 0-9-9zm0 "
          "4a5 5 0 0 0-5 5c0 1.4.6 2.6 1.5 3.5l1.4-1.4c-.6-.6-.9-1.3-.9-2.1a3 "
          "3 0 0 1 3-3 3 3 0 0 1 3 3c0 .8-.3 1.5-.9 2.1l1.4 1.4c.9-.9 1.5-2.1 "
          "1.5-3.5a5 5 0 0 0-5-5zm0 4a1 1 0 1 0 0 2 1 1 0 0 0 0-2z'/></svg> "
          "LORA MESH SOS NODE</span>";
  html += "</div>";
  html += "</header>";

  // Distress Beacon State (Standby vs Active Loop)
  if (emergencyLoopActive) {
    html += "<div class='card card-danger-active'>";
    html += "<div class='card-header'>";
    html += "<div class='card-title' style='color:#ff94a8;'>";
    html += "<span class='card-title-icon'><svg viewBox='0 0 24 24' "
            "fill='#ff2a55'><path d='M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 "
            "10-4.48 10-10S17.52 2 12 2zm1 "
            "15h-2v-2h2v2zm0-4h-2V7h2v6z'/></svg></span>";
    html += "CRITICAL SOS BROADCAST</div>";
    html += "<span class='status-pill status-active'><span class='dot'></span> "
            "LOOP ACTIVE (3s)</span>";
    html += "</div>";
    html += "<p class='em-desc' style='color:#ffb3c1;'>Continuous emergency "
            "distress pulses broadcasting over LoRa RF every 3 seconds.</p>";
    html += "<a href='/stop_loop'><button type='button' class='btn-stop'>";
    html += "<svg width='18' height='18' viewBox='0 0 24 24' "
            "fill='currentColor'><path d='M6 6h12v12H6z'/></svg>";
    html += "⏹ DEACTIVATE EMERGENCY LOOP</button></a>";
    html += "</div>";
  } else {
    html += "<div class='card'>";
    html += "<div class='card-header'>";
    html += "<div class='card-title'>";
    html +=
        "<span class='card-title-icon'><svg viewBox='0 0 24 24' "
        "fill='#ff2a55'><path d='M12 2c5.52 0 10 4.48 10 10s-4.48 10-10 10S2 "
        "17.52 2 12 6.48 2 12 2zm1 14h-2v-2h2v2zm0-4h-2V7h2v5z'/></svg></span>";
    html += "Distress Beacon State</div>";
    html += "<span class='status-pill status-standby'><span "
            "class='dot'></span> STANDBY</span>";
    html += "</div>";
    html += "<p class='em-desc'>Press physical button on node or tap below to "
            "trigger continuous 3-second LoRa emergency broadcast.</p>";
    html += "<a href='/start_loop'><button type='button' class='btn-sos'>";
    html +=
        "<svg width='20' height='20' viewBox='0 0 24 24' "
        "fill='currentColor'><path d='M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 "
        "10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z'/></svg>";
    html += "🚨 TRIGGER CRITICAL SOS</button></a>";
    html += "</div>";
  }

  // Live GPS Radar & Telemetry Card (Moved Up as 2nd Card)
  html += "<div class='card'>";
  html += "<div class='card-header'>";
  html +=
      "<div class='card-title'><span class='card-title-icon'><svg viewBox='0 0 "
      "24 24' fill='#00f0ff'><path d='M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 "
      "13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5a2.5 2.5 0 0 1 0-5 2.5 2.5 0 0 1 "
      "0 5z'/></svg></span>Live GPS &amp; Telemetry</div>";
  html += "<span class='status-pill status-live'><span class='dot'></span> "
          "REALTIME GPS</span>";
  html += "</div>";

  html += "<div class='meta-grid'>";

  html += "<div class='meta-tile'><div class='meta-tile-label'>";
  html += "<svg width='12' height='12' viewBox='0 0 24 24' "
          "fill='currentColor'><path d='M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 "
          "2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z'/></svg> GPS Lock</div>";
  html += "<div class='meta-tile-value' id='gpsStatus'>";
  html += gps.location.isValid()
              ? "<span "
                "style='color:#10b981;font-weight:800;display:flex;align-items:"
                "center;gap:4px;'><svg width='14' height='14' viewBox='0 0 24 "
                "24' fill='currentColor'><path d='M9 16.17L4.83 12l-1.42 "
                "1.41L9 19 21 7l-1.41-1.41z'/></svg> FIX OK (LIVE)</span>"
              : "<span "
                "style='color:#fbbf24;font-size:13px;display:flex;align-items:"
                "center;gap:4px;'><svg width='14' height='14' viewBox='0 0 24 "
                "24' fill='currentColor'><path d='M12 4V1L8 5l4 4V6c3.31 0 6 "
                "2.69 6 6 0 1.01-.25 1.97-.7 2.8l1.46 1.46A7.93 7.93 0 0 0 20 "
                "12c0-4.42-3.58-8-8-8zm0 14c-3.31 0-6-2.69-6-6 "
                "0-1.01.25-1.97.7-2.8L5.24 7.74A7.93 7.93 0 0 0 4 12c0 4.42 "
                "3.58 8 8 8v3l4-4-4-4v3z'/></svg> SEARCHING...</span>";
  html += "</div></div>";

  html += "<div class='meta-tile'><div class='meta-tile-label'>";
  html +=
      "<svg width='12' height='12' viewBox='0 0 24 24' "
      "fill='currentColor'><path d='M19.35 10.04C18.67 6.59 15.64 4 12 4 9.11 "
      "4 6.6 5.64 5.35 8.04 2.34 8.36 0 10.91 0 14c0 3.31 2.69 6 6 6h13c2.76 0 "
      "5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96z'/></svg> Satellites</div>";
  html += "<div class='meta-tile-value' id='satCount'>";
  html += gps.satellites.isValid() ? String(gps.satellites.value()) : "--";
  html += "</div></div>";

  html += "<div class='meta-tile'><div class='meta-tile-label'>";
  html += "<svg width='12' height='12' viewBox='0 0 24 24' "
          "fill='currentColor'><path d='M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 "
          "10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 "
          "0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 "
          "2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-"
          "2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 "
          "0 2.08-.8 3.97-2.1 5.39z'/></svg> Latitude</div>";
  html += "<div class='meta-tile-value cyan-glow' id='latVal'>" +
          String(latitude, 6) + "</div></div>";

  html += "<div class='meta-tile'><div class='meta-tile-label'>";
  html += "<svg width='12' height='12' viewBox='0 0 24 24' "
          "fill='currentColor'><path d='M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 "
          "10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 "
          "0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 "
          "2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-"
          "2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 "
          "0 2.08-.8 3.97-2.1 5.39z'/></svg> Longitude</div>";
  html += "<div class='meta-tile-value cyan-glow' id='lonVal'>" +
          String(longitude, 6) + "</div></div>";

  html += "<div class='meta-tile'><div class='meta-tile-label'>";
  html += "<svg width='12' height='12' viewBox='0 0 24 24' "
          "fill='currentColor'><path d='M11.99 2C6.47 2 2 6.48 2 12s4.47 10 "
          "9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 "
          "0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm.5-13H11v6l5.25 "
          "3.15.75-1.23-4.5-2.67z'/></svg> Last RF Pulse</div>";
  html += "<div class='meta-tile-value' id='lastPulseAgo'>";
  if (lastPacketSendMillis > 0) {
    unsigned long agoSec = (millis() - lastPacketSendMillis) / 1000;
    html += String(agoSec) + "s ago";
  } else {
    html += "None yet";
  }
  html += "</div></div>";

  html += "<div class='meta-tile'><div class='meta-tile-label'>";
  html += "<svg width='12' height='12' viewBox='0 0 24 24' "
          "fill='currentColor'><path d='M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 "
          "2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-5 "
          "14H7v-2h7v2zm3-4H7v-2h10v2zm0-4H7V7h10v2z'/></svg> Packets "
          "Transmitted</div>";
  html += "<div class='meta-tile-value' id='pktCount'>" + String(packetCount) +
          "</div></div>";

  html += "</div>";
  html += "</div>";

  // Custom SOS Transmission Card (Next Card)
  // Manual form: show locked banner when SOS loop is active, full form
  // otherwise
  if (emergencyLoopActive) {
    html += "<div class='card' style='border:1.5px solid "
            "var(--sos-red);background:linear-gradient(180deg,rgba(70,10,20,0."
            "85) 0%,rgba(25,8,15,0.9) 100%);'>";
    html += "<div class='card-header'>";
    html +=
        "<div class='card-title' style='color:#ff94a8;'><span "
        "class='card-title-icon'><svg viewBox='0 0 24 24' fill='#ff2a55'><path "
        "d='M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 "
        "2zm-1 15h-2v-2h2v2zm0-4h-2V7h2v6z'/></svg></span>Manual Transmission "
        "— Disabled</div>";
    html += "<span class='status-pill status-active'><span class='dot'></span> "
            "LOCKED</span>";
    html += "</div>";
    html += "<p class='em-desc' style='color:#ffb3c1;'>Manual beacon controls "
            "are locked while the SOS emergency loop is broadcasting.</p>";
    html += "<p style='margin:0;font-size:11px;color:#94a3b8;'>Stop the SOS "
            "loop first to regain manual control.</p>";
    html += "</div>";
  } else {
    uint8_t currentClients = WiFi.softAPgetStationNum();
    String initialClientText =
        (currentClients == 1 ? "1 DEVICE CONNECTED"
                             : (String(currentClients) + " DEVICES CONNECTED"));

    html += "<div class='card' id='customSosCard'>";
    html += "<div class='card-header'>";
    html +=
        "<div class='card-title'><span class='card-title-icon'><svg viewBox='0 "
        "0 24 24' fill='#a78bfa'><path d='M19.14 12.94c.04-.3.06-.61.06-.94 "
        "0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-"
        ".22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-."
        "24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 "
        "2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 "
        "8.87c-.12.21-.08.47.12.61l2.03 "
        "1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 "
        "1.58c-.18.14-.23.41-.12.61l1.92 "
        "3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 "
        "2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 "
        "1.13-.56 1.62-.94l2.39.96c.22.08.47 0 "
        ".59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 "
        "0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 "
        "3.6z'/></svg></span>Custom SOS Transmission</div>";
    html += "<span class='pill-badge pill-wifi' id='clientBadge'><span "
            "class='wifi-dot'></span><span id='clientCountText'>" +
            initialClientText + "</span></span>";
    html += "</div>";

    html += "<p class='em-desc'>Configure tactical payload parameters to "
            "broadcast via LoRa RF mesh network to rescue responders.</p>";

    html += "<form action='/send' method='GET'>";

    html += "<div class='form-row'>";
    html += "<div class='form-group'>";
    html += "<label><svg viewBox='0 0 24 24'><path d='M12 12c2.21 0 4-1.79 "
            "4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 "
            "4v2h16v-2c0-2.66-5.33-4-8-4z'/></svg> Survivor Node ID</label>";
    html += "<input name='node' type='number' min='1' max='9' value='" +
            String(survivorNodeId) + "'>";
    html += "</div>";

    html += "<div class='form-group'>";
    html += "<label><svg viewBox='0 0 24 24'><path d='M1 21h22L12 2 1 "
            "21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z'/></svg> Danger Level</label>";
    html += "<select name='danger'>";
    addOption(html, 1, dangerLevel, "1 - Low");
    addOption(html, 2, dangerLevel, "2 - Moderate");
    addOption(html, 3, dangerLevel, "3 - Serious");
    addOption(html, 4, dangerLevel, "4 - High");
    addOption(html, 5, dangerLevel, "5 - Critical");
    html += "</select>";
    html += "</div>";
    html += "</div>";

    html += "<div class='form-group'>";
    html += "<label><svg viewBox='0 0 24 24'><path d='M12 2C6.48 2 2 6.48 2 "
            "12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 14H9V8h2v8zm4 "
            "0h-2V8h2v8z'/></svg> Emergency Type</label>";
    html += "<select name='etype'>";
    addOption(html, 1, emergencyType, "1 - Medical");
    addOption(html, 2, emergencyType, "2 - Fire");
    addOption(html, 3, emergencyType, "3 - Flood");
    addOption(html, 4, emergencyType, "4 - Trapped");
    addOption(html, 5, emergencyType, "5 - SOS");
    html += "</select>";
    html += "</div>";

    html += "<div class='form-group'>";
    html +=
        "<label><svg viewBox='0 0 24 24'><path d='M20 2H4c-1.1 0-1.99.9-1.99 "
        "2L2 22l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zM6 9h12v2H6V9zm8 "
        "5H6v-2h8v2zm4-6H6V6h12v2z'/></svg> Message Code</label>";
    html += "<select name='msg'>";
    addOption(html, 1, messageCode, "1 - Need rescue");
    addOption(html, 2, messageCode, "2 - Injured");
    addOption(html, 3, messageCode, "3 - Trapped");
    addOption(html, 4, messageCode, "4 - Need medicine");
    addOption(html, 5, messageCode, "5 - Unconscious");
    addOption(html, 6, messageCode, "6 - Fire nearby");
    html += "</select>";
    html += "</div>";

    html +=
        "<button type='submit' class='btn-send'><svg width='18' height='18' "
        "viewBox='0 0 24 24' fill='currentColor'><path d='M12 3a9 9 0 0 0-9 "
        "9c0 2.4.9 4.6 2.4 6.2l1.4-1.4A7 7 0 0 1 5 12a7 7 0 0 1 7-7 7 7 0 0 1 "
        "7 7c0 1.9-.8 3.7-2.1 5l1.4 1.4A9 9 0 0 0 21 12a9 9 0 0 0-9-9zm0 4a5 5 "
        "0 0 0-5 5c0 1.4.6 2.6 1.5 3.5l1.4-1.4c-.6-.6-.9-1.3-.9-2.1a3 3 0 0 1 "
        "3-3 3 3 0 0 1 3 3c0 .8-.3 1.5-.9 2.1l1.4 1.4c.9-.9 1.5-2.1 1.5-3.5a5 "
        "5 0 0 0-5-5zm0 4a1 1 0 1 0 0 2 1 1 0 0 0 0-2z'/></svg> SEND SINGLE "
        "SOS BEACON</button>";
    html += "</form>";
    html += "</div>";
  }

  // Last LoRa Packet Datastream Card
  html += "<div class='card'>";
  html += "<div class='card-header'>";
  html +=
      "<div class='card-title'><span class='card-title-icon'><svg viewBox='0 0 "
      "24 24' fill='#38bdf8'><path d='M12 3a9 9 0 0 0-9 9c0 2.4.9 4.6 2.4 "
      "6.2l1.4-1.4A7 7 0 0 1 5 12a7 7 0 0 1 7-7 7 7 0 0 1 7 7c0 1.9-.8 3.7-2.1 "
      "5l1.4 1.4A9 9 0 0 0 21 12a9 9 0 0 0-9-9zm0 4a5 5 0 0 0-5 5c0 1.4.6 2.6 "
      "1.5 3.5l1.4-1.4c-.6-.6-.9-1.3-.9-2.1a3 3 0 0 1 3-3 3 3 0 0 1 3 3c0 "
      ".8-.3 1.5-.9 2.1l1.4 1.4c.9-.9 1.5-2.1 1.5-3.5a5 5 0 0 0-5-5zm0 4a1 1 0 "
      "1 0 0 2 1 1 0 0 0 0-2z'/></svg></span>LoRa RF Datastream</div>";
  html += "<span class='pill-badge pill-offline' id='lastSendSourceBadge'>" +
          lastSendSource + "</span>";
  html += "</div>";

  html += "<div class='terminal-container'>";
  html += "<div class='terminal-header'><div class='terminal-dots'><span "
          "class='terminal-dot r'></span><span class='terminal-dot "
          "y'></span><span class='terminal-dot g'></span></div><span>RAW RF "
          "PACKET BUFFER</span></div>";
  html += "<code class='datastream-code' id='lastPktCode'>" + lastPacket +
          "</code>";
  html += "</div>";
  html += "<div class='protocol-legend'><span class='legend-tag'>FMT: "
          "S,NodeID,LatE5,LonE5,EType,MsgCode,Danger,Hops</span></div>";
  html += "</div>";

  // Footer status bar
  html += "<footer class='status-bar'><span class='pulse-dot'></span> BEACONME "
          "SURVIVOR NODE ONLINE &bull; READY</footer>";
  html += "</div>";

  // Toast confirmation notification
  html +=
      "<div class='toast' id='sentToast'><svg viewBox='0 0 24 24'><path d='M9 "
      "16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z'/></svg><span>SOS BEACON "
      "PACKET TRANSMITTED</span></div>";

  // Auto-refresh Script + Toast logic + Realtime GPS & Connected Clients
  // updater
  html += "<script>";
  html += "if(location.search.includes('sent=1')){var "
          "t=document.getElementById('sentToast');if(t){t.innerHTML='<svg "
          "viewBox=\"0 0 24 24\"><path d=\"M9 16.17L4.83 12l-1.42 1.41L9 19 21 "
          "7l-1.41-1.41z\"/></svg><span>SOS BEACON PACKET "
          "TRANSMITTED</"
          "span>';t.classList.add('show');setTimeout(function(){t.classList."
          "remove('show');},2800);if(window.history&&window.history."
          "replaceState){history.replaceState(null,'',location.pathname);}}}";
  html += "else if(location.search.includes('locked=1')){var "
          "t=document.getElementById('sentToast');if(t){t.style.background='"
          "linear-gradient(135deg,rgba(220,38,38,0.95) 0%,rgba(185,28,28,0.95) "
          "100%)';t.innerHTML='<svg viewBox=\"0 0 24 24\"><path d=\"M12 2C6.48 "
          "2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 "
          "15h-2v-2h2v2zm0-4h-2V7h2v6z\"/></svg><span>MANUAL TRANSMISSION "
          "LOCKED (SOS LOOP "
          "ACTIVE)</"
          "span>';t.classList.add('show');setTimeout(function(){t.classList."
          "remove('show');},3000);if(window.history&&window.history."
          "replaceState){history.replaceState(null,'',location.pathname);}}}";
  html += "function updateConnectedClients(count){";
  html += "var textEl=document.getElementById('clientCountText');";
  html += "var badgeEl=document.getElementById('clientBadge');";
  html += "var c=Number(count)||0;";
  html += "var label=c===1?'1 DEVICE CONNECTED':(c+' DEVICES CONNECTED');";
  html += "if(textEl){textEl.textContent=label;}else "
          "if(badgeEl){badgeEl.innerHTML='<span "
          "class=\"wifi-dot\"></span><span>'+label+'</span>';}";
  html += "}";
  html += "function updateCoords(lat,lon,isValid,sats){";
  html += "var "
          "latEl=document.getElementById('latVal'),lonEl=document."
          "getElementById('lonVal'),gpsStatus=document.getElementById('"
          "gpsStatus'),satCount=document.getElementById('satCount');";
  html += "var latN=Number(lat),lonN=Number(lon);";
  html += "if(!isNaN(latN)&&!isNaN(lonN)){";
  html += "var latStr=latN.toFixed(6),lonStr=lonN.toFixed(6);";
  html += "if(latEl.textContent!==latStr||lonEl.textContent!==lonStr){";
  html += "latEl.textContent=latStr;lonEl.textContent=lonStr;";
  html += "latEl.classList.remove('coord-updated');lonEl.classList.remove('"
          "coord-updated');void latEl.offsetWidth;";
  html += "latEl.classList.add('coord-updated');lonEl.classList.add('coord-"
          "updated');";
  html += "}";
  html += "}";
  html += "if(isValid!==undefined&&gpsStatus){";
  html += "gpsStatus.innerHTML=isValid?'<span "
          "style=\"color:#10b981;font-weight:800;display:flex;align-items:"
          "center;gap:4px;\"><svg width=\"14\" height=\"14\" viewBox=\"0 0 24 "
          "24\" fill=\"currentColor\"><path d=\"M9 16.17L4.83 12l-1.42 1.41L9 "
          "19 21 7l-1.41-1.41z\"/></svg> FIX OK (LIVE)</span>':'<span "
          "style=\"color:#fbbf24;font-size:13px;display:flex;align-items:"
          "center;gap:4px;\"><svg width=\"14\" height=\"14\" viewBox=\"0 0 24 "
          "24\" fill=\"currentColor\"><path d=\"M12 4V1L8 5l4 4V6c3.31 0 6 "
          "2.69 6 6 0 1.01-.25 1.97-.7 2.8l1.46 1.46A7.93 7.93 0 0 0 20 "
          "12c0-4.42-3.58-8-8-8zm0 14c-3.31 0-6-2.69-6-6 "
          "0-1.01.25-1.97.7-2.8L5.24 7.74A7.93 7.93 0 0 0 4 12c0 4.42 3.58 8 8 "
          "8v3l4-4-4-4v3z\"/></svg> SEARCHING...</span>';";
  html += "}";
  html += "if(sats!==undefined&&satCount){satCount.textContent=sats||'--';}";
  html += "}";
  html += "async function pollStatus(){";
  html += "try{";
  html += "const res=await fetch('/api/status');";
  html += "if(!res.ok)return;";
  html += "const d=await res.json();";
  html += "updateCoords(d.latitude,d.longitude,d.gps_valid,d.satellites);";
  html += "if(d.connected_clients!==undefined){updateConnectedClients(d."
          "connected_clients);}";
  html += "if(d.packet_count!==undefined){document.getElementById('pktCount')."
          "textContent=d.packet_count;}";
  html += "if(d.seconds_since_pulse!==undefined){document.getElementById('"
          "lastPulseAgo').textContent=d.seconds_since_pulse>=0?(d.seconds_"
          "since_pulse+'s ago'):'None yet';}";
  html += "if(d.last_packet!==undefined){document.getElementById('lastPktCode')"
          ".textContent=d.last_packet;}";
  html += "}catch(e){}";
  html += "}";
  html += "pollStatus();setInterval(pollStatus,1000);";
  html += "</script>";

  html += "</body></html>";

  server.send(200, "text/html; charset=utf-8", html);
}

void setup() {
  // Put the visible outputs in their inactive state immediately.
  pinMode(GREEN_LED_PIN, OUTPUT);
  pinMode(RED_LED_PIN, OUTPUT);
  digitalWrite(GREEN_LED_PIN, LOW);
  digitalWrite(RED_LED_PIN, LOW);

  Serial.begin(115200);
  delay(peripheralSettleMs);

  Serial1.begin(9600, SERIAL_8N1, 4, 5);
  Serial.println("GPS initialized");
  Serial.println("Waiting for GPS fix...");

  LoRa_rf.begin(9600);

  pinMode(SOS_BUTTON_PIN, INPUT_PULLUP);

#if USE_STATUS_LED
  pinMode(STATUS_LED_PIN, OUTPUT);
  digitalWrite(STATUS_LED_PIN, LOW);
#endif

  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASS);

  Serial.println();
  Serial.println("BeaconMe Survivor Node Started");
  Serial.print("WiFi SSID: ");
  Serial.println(AP_SSID);
  Serial.print("WiFi Password: ");
  Serial.println(AP_PASS);
  Serial.print("Dashboard IP: ");
  Serial.println(WiFi.softAPIP());

  server.on("/", handleRoot);
  server.on("/send", handleSend);
  server.on("/start_loop", handleStartLoop);
  server.on("/stop_loop", handleStopLoop);
  server.on("/api/status", handleStatusJson);
  server.on("/api/data", handleAllDataJson);
  server.begin();

  Serial.println(
      "BeaconMe WiFi dashboard started with 3s emergency loop capability");
}

void loop() {
  if (greenLedOffTime != 0 && millis() >= greenLedOffTime) {
    digitalWrite(GREEN_LED_PIN, LOW);
    greenLedOffTime = 0;
  }

  while (Serial1.available()) {
    gps.encode(Serial1.read());
  }

  if (gps.location.isUpdated()) {
    latitude = gps.location.lat();
    longitude = gps.location.lng();

    if (gps.location.isValid()) {
      digitalWrite(GREEN_LED_PIN, HIGH);
      greenLedOffTime = millis() + greenLedPulseMs;
    }

    Serial.println("GPS FIX OK");
    Serial.print("Latitude: ");
    Serial.println(latitude, 6);
    Serial.print("Longitude: ");
    Serial.println(longitude, 6);
    Serial.print("Satellites: ");
    if (gps.satellites.isValid()) {
      Serial.println(gps.satellites.value());
    } else {
      Serial.println("--");
    }
  }

  server.handleClient();

  // Non-blocking Debounced Physical SOS Button Check
  bool reading = digitalRead(SOS_BUTTON_PIN);

  if (reading != lastButtonState) {
    lastDebounceTime = millis();
  }

  if ((millis() - lastDebounceTime) > debounceDelayMs) {
    if (reading != buttonState) {
      buttonState = reading;

      if (buttonState == LOW) {
        // Physical SOS button pressed: Start continuous critical SOS loop
        emergencyLoopActive = true;
        dangerLevel = 5;   // Force Critical
        messageCode = 1;   // Need rescue
        emergencyType = 5; // Force SOS

        Serial.println();
        Serial.println(
            "************************************************************");
        Serial.println(">>> PHYSICAL SOS BUTTON TRIGGERED: CRITICAL LOOP (SOS) "
                       "STARTED <<<");
        Serial.println(
            "************************************************************");

        sendSosPacket("Physical SOS Button (Critical 3s Loop)");
        lastSosSendTime = millis();
      }
    }
  }

  lastButtonState = reading;

  // Continuous Emergency SOS Loop Execution (Every 3 Seconds)
  if (emergencyLoopActive) {
    if (millis() - lastSosSendTime >= SOS_LOOP_INTERVAL_MS) {
      lastSosSendTime = millis();
      sendSosPacket("Critical Emergency Loop (3s)");
    }
  }
}
