#include <SoftwareSerial.h>
#include <LoRa.h>
// =====================================================
// BeaconMe Server Receiver Node
// NodeMCU + LoRa RF receiver + USB serial to laptop
// =====================================================


SoftwareSerial LoRa_rf(D5, D6);

#define LED_PIN LED_BUILTIN

// BeaconMe SOS packet format:
// S,node_id,latE5,lonE5,emergency_type,message_code,danger_level,hop_count

int splitCSV(String input, String output[], int maxParts) {
  int count = 0;

  while (input.length() > 0 && count < maxParts) {
    int commaIndex = input.indexOf(',');

    if (commaIndex == -1) {
      output[count++] = input;
      break;
    } else {
      output[count++] = input.substring(0, commaIndex);
      input = input.substring(commaIndex + 1);
    }
  }

  return count;
}

String emergencyTypeName(int code) {
  if (code == 1) return "Medical";
  if (code == 2) return "Fire";
  if (code == 3) return "Flood";
  if (code == 4) return "Trapped";
  if (code == 5) return "Security Threat";
  return "Unknown";
}

String messageCodeName(int code) {
  if (code == 1) return "Need rescue";
  if (code == 2) return "Injured";
  if (code == 3) return "Trapped";
  if (code == 4) return "Need medicine";
  if (code == 5) return "Unconscious";
  if (code == 6) return "Fire nearby";
  return "Unknown";
}

String dangerLevelName(int code) {
  if (code == 1) return "Low";
  if (code == 2) return "Moderate";
  if (code == 3) return "Serious";
  if (code == 4) return "High";
  if (code == 5) return "Critical";
  return "Unknown";
}

bool isValidBeaconMeSosPacket(String packet, String fields[]) {
  int count = splitCSV(packet, fields, 8);

  if (count != 8) {
    return false;
  }

  if (fields[0] != "S") {
    return false;
  }

  int nodeId = fields[1].toInt();
  int emergencyType = fields[4].toInt();
  int messageCode = fields[5].toInt();
  int dangerLevel = fields[6].toInt();
  int hopCount = fields[7].toInt();

  if (nodeId < 1 || nodeId > 9) {
    return false;
  }

  if (emergencyType < 1 || emergencyType > 5) {
    return false;
  }

  if (messageCode < 1 || messageCode > 6) {
    return false;
  }

  if (dangerLevel < 1 || dangerLevel > 5) {
    return false;
  }

  if (hopCount < 0 || hopCount > 9) {
    return false;
  }

  return true;
}

void blinkLed() {
  digitalWrite(LED_PIN, LOW);
  delay(80);
  digitalWrite(LED_PIN, HIGH);
}

void printPacketDetails(String fields[]) {
  int nodeId = fields[1].toInt();
  int32_t latE5 = fields[2].toInt();
  int32_t lonE5 = fields[3].toInt();
  int emergencyType = fields[4].toInt();
  int messageCode = fields[5].toInt();
  int dangerLevel = fields[6].toInt();
  int hopCount = fields[7].toInt();

  float latitude = latE5 / 100000.0;
  float longitude = lonE5 / 100000.0;

  Serial.println("----- BeaconMe SOS Details -----");
  Serial.print("Survivor Node ID: ");
  Serial.println(nodeId);

  Serial.print("Latitude: ");
  Serial.println(latitude, 5);

  Serial.print("Longitude: ");
  Serial.println(longitude, 5);

  Serial.print("Emergency Type: ");
  Serial.print(emergencyType);
  Serial.print(" - ");
  Serial.println(emergencyTypeName(emergencyType));

  Serial.print("Message Code: ");
  Serial.print(messageCode);
  Serial.print(" - ");
  Serial.println(messageCodeName(messageCode));

  Serial.print("Danger Level: ");
  Serial.print(dangerLevel);
  Serial.print(" - ");
  Serial.println(dangerLevelName(dangerLevel));

  Serial.print("Hop Count: ");
  Serial.println(hopCount);

  if (hopCount == 0) {
    Serial.println("Forward Status: Direct from survivor node");
  } else {
    Serial.println("Forward Status: Forwarded through ad-hoc node");
  }

  Serial.println("--------------------------------");
}

void setup() {
  Serial.begin(115200);
  LoRa_rf.begin(9600);

  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, HIGH);

  Serial.println();
  Serial.println("BeaconMe Server Receiver Node Started");
  Serial.println("Waiting for BeaconMe LoRa SOS packets...");
}

void loop() {
  if (LoRa_rf.available()) {
    String packet = LoRa_rf.readStringUntil('\n');
    packet.trim();

    if (packet.length() == 0) {
      return;
    }

    String fields[8];

    if (!isValidBeaconMeSosPacket(packet, fields)) {
      Serial.print("BAD:");
      Serial.println(packet);
      return;
    }

    Serial.print("PKT:");
    Serial.println(packet);

    printPacketDetails(fields);

    blinkLed();
  }
}
