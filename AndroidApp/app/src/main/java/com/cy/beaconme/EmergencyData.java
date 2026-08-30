package com.cy.beaconme;

import androidx.annotation.NonNull;
import org.json.JSONObject;

public final class EmergencyData {

    private final boolean emergencyActive;
    private final int nodeId;
    private final double latitude;
    private final double longitude;
    private final int emergencyType;
    private final String emergencyName;
    private final int messageCode;
    private final String messageName;
    private final int dangerLevel;
    private final String dangerName;
    private final boolean gpsValid;
    private final int satellites;
    private final int packetCount;
    private final long lastPacketSendMillis;
    private final int secondsSincePulse;
    private final String lastSendSource;
    private final String lastPacket;
    private final int startHopCount;
    private final int sosLoopIntervalMs;

    public EmergencyData(
            boolean emergencyActive,
            int nodeId,
            double latitude,
            double longitude,
            int emergencyType,
            String emergencyName,
            int messageCode,
            String messageName,
            int dangerLevel,
            String dangerName,
            boolean gpsValid,
            int satellites,
            int packetCount,
            long lastPacketSendMillis,
            int secondsSincePulse,
            String lastSendSource,
            String lastPacket,
            int startHopCount,
            int sosLoopIntervalMs
    ) {
        this.emergencyActive = emergencyActive;
        this.nodeId = nodeId;
        this.latitude = latitude;
        this.longitude = longitude;
        this.emergencyType = emergencyType;
        this.emergencyName = emergencyName != null ? emergencyName : "SOS";
        this.messageCode = messageCode;
        this.messageName = messageName != null ? messageName : "Need rescue";
        this.dangerLevel = dangerLevel;
        this.dangerName = dangerName != null ? dangerName : "Critical";
        this.gpsValid = gpsValid;
        this.satellites = satellites;
        this.packetCount = packetCount;
        this.lastPacketSendMillis = lastPacketSendMillis;
        this.secondsSincePulse = secondsSincePulse;
        this.lastSendSource = lastSendSource != null ? lastSendSource : "Unknown";
        this.lastPacket = lastPacket != null ? lastPacket : "N/A";
        this.startHopCount = startHopCount;
        this.sosLoopIntervalMs = sosLoopIntervalMs;
    }

    @NonNull
    public static EmergencyData fromJsonObject(@NonNull JSONObject json) {
        return new EmergencyData(
                json.optBoolean("emergency_active", false),
                json.optInt("node_id", 1),
                json.optDouble("latitude", 0.0),
                json.optDouble("longitude", 0.0),
                json.optInt("emergency_type", 5),
                json.optString("emergency_name", "SOS"),
                json.optInt("message_code", 1),
                json.optString("message_name", "Need rescue"),
                json.optInt("danger_level", 5),
                json.optString("danger_name", "Critical"),
                json.optBoolean("gps_valid", false),
                json.optInt("satellites", 0),
                json.optInt("packet_count", 0),
                json.optLong("last_packet_send_millis", 0L),
                json.optInt("seconds_since_pulse", 0),
                json.optString("last_send_source", "Loop"),
                json.optString("last_packet", ""),
                json.optInt("start_hop_count", 0),
                json.optInt("sos_loop_interval_ms", 3000)
        );
    }

    public boolean isEmergencyActive() {
        return emergencyActive;
    }

    public int getNodeId() {
        return nodeId;
    }

    public double getLatitude() {
        return latitude;
    }

    public double getLongitude() {
        return longitude;
    }

    public int getEmergencyType() {
        return emergencyType;
    }

    @NonNull
    public String getEmergencyName() {
        return emergencyName;
    }

    public int getMessageCode() {
        return messageCode;
    }

    @NonNull
    public String getMessageName() {
        return messageName;
    }

    public int getDangerLevel() {
        return dangerLevel;
    }

    @NonNull
    public String getDangerName() {
        return dangerName;
    }

    public boolean isGpsValid() {
        return gpsValid;
    }

    public int getSatellites() {
        return satellites;
    }

    public int getPacketCount() {
        return packetCount;
    }

    public long getLastPacketSendMillis() {
        return lastPacketSendMillis;
    }

    public int getSecondsSincePulse() {
        return secondsSincePulse;
    }

    @NonNull
    public String getLastSendSource() {
        return lastSendSource;
    }

    @NonNull
    public String getLastPacket() {
        return lastPacket;
    }

    public int getStartHopCount() {
        return startHopCount;
    }

    public int getSosLoopIntervalMs() {
        return sosLoopIntervalMs;
    }

    @NonNull
    public String getFormattedCoordinates() {
        return String.format(java.util.Locale.US, "%.6f, %.6f", latitude, longitude);
    }

    @NonNull
    public String getEmergencyEmoji() {
        switch (emergencyType) {
            case 1:
                return "🚑"; // Medical
            case 2:
                return "🔥"; // Fire
            case 3:
                return "🌊"; // Flood
            case 4:
                return "⚠️"; // Trapped
            case 5:
            default:
                return "🆘"; // SOS
        }
    }
}
