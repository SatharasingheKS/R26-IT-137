package com.cy.beaconme;

import androidx.annotation.NonNull;

import java.util.Random;

public final class DemoTelemetry {

    private static int packetCount = 12;
    private static int dangerLevel = 5;
    private static int emergencyTypeIndex = 4; // SOS
    private static final Random random = new Random();

    private static final String[] TYPES = {"Medical", "Fire", "Flood", "Trapped", "SOS"};
    private static final String[] MESSAGES = {
            "Need rescue", "Injured", "Trapped", "Need medicine", "Unconscious", "Fire nearby"
    };
    private static final String[] DANGERS = {"Low", "Moderate", "Serious", "High", "Critical"};

    @NonNull
    public static EmergencyData getNextSample() {
        packetCount++;
        int typeCode = (emergencyTypeIndex % 5) + 1;
        String typeName = TYPES[typeCode - 1];
        int msgCode = (packetCount % 6) + 1;
        String msgName = MESSAGES[msgCode - 1];
        int danger = dangerLevel;
        String dangerName = DANGERS[danger - 1];

        // Slight position jitter for demo map testing around Colombo (6.9271, 79.8611)
        double lat = 6.927100 + (random.nextDouble() - 0.5) * 0.0008;
        double lng = 79.861190 + (random.nextDouble() - 0.5) * 0.0008;

        String rawPacket = String.format(
                java.util.Locale.US,
                "S,1,%d,%d,%d,%d,%d,0",
                (int)(lat * 100000),
                (int)(lng * 100000),
                typeCode,
                msgCode,
                danger
        );

        return new EmergencyData(
                true, // active
                1, // node 1
                lat,
                lng,
                typeCode,
                typeName,
                msgCode,
                msgName,
                danger,
                dangerName,
                true, // gps valid
                8 + random.nextInt(4),
                packetCount,
                System.currentTimeMillis(),
                random.nextInt(3),
                "Critical Emergency Loop (3s)",
                rawPacket,
                0,
                3000
        );
    }

    public static void cycleDangerLevel() {
        dangerLevel = (dangerLevel % 5) + 1;
    }

    public static void cycleEmergencyType() {
        emergencyTypeIndex = (emergencyTypeIndex + 1) % 5;
    }
}
