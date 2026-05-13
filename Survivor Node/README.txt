Survivor Node — Distress Signal & Location Transmission
Overview
The Survivor Node is built on an ESP32 microcomputer. It allows any civilian to send a priority-graded distress signal with GPS coordinates over RF — without internet or mobile network. Any device (phone, laptop, or tablet) can connect to the ESP32 WiFi hotspot and access the web interface using just an IP address.

Current Progress (50% Milestone)

ESP32 programmed and configured as survivor node
RF transmitter module connected and transmission tested
Web server deployed on ESP32 — accessible from any WiFi device via hotspot
Two distress modes implemented — Immediate Danger and Relatively Safe
GPS coordinates and signal mode packaged into compressed RF packet
Custom packet compression built to minimise RF bandwidth usage
Triple-send ACK mechanism working — message sends up to 3 times, stops on first confirmed ACK
Full signal flow tested: web interface → ESP32 → RF transmission → ad-hoc unit


Next Phase

Solder and integrate physical SOS button circuit onto ESP32
Connect physical GPS module — replace hardcoded coordinates with live data
Develop Android mobile application
Integrate both signal modes into Android app UI with one-tap operation
Finalise waterproof device housing
