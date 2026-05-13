# Island Wide Communication System for Disaster Situations
R26-IT-137 | Research Group | IT4010 — 2026
Project Overview
A self-contained, infrastructure-free emergency communication system designed for disaster scenarios where all mobile and internet networks are down. The system allows survivors to send priority-graded distress signals with GPS coordinates to rescue teams — using only RF communication, with no dependency on any existing network.

System Components
The system consists of three components working together:

Survivor Node — ESP32-based device survivors use to send distress signals
Ad-hoc RF Network — Self-organising LoRa mesh network that relays messages across disaster zones
Server Node — Receives signals, applies ML-based fake message filtering, and prioritises rescue response


Progress at 50% Milestone

Survivor node built on ESP32 — web interface accessible from any device via hotspot, two distress modes tested, packet compression and triple-send ACK mechanism working, RF transmission verified end-to-end
Ad-hoc network hardware assembled — single unit demonstrated, auto-discovery and hop count control mechanism implemented, unlimited scalability coded
Server node ML model developed and tested — flood sensor cross-validation working, priority ranking system implemented


Next Phase

Attach physical SOS button and GPS module to survivor node; develop Android application
Deploy multi-unit ad-hoc field testing; build weatherproof enclosures with battery backup
Connect server to live RF input; build rescue team dashboard with live GPS map display
