#include <SoftwareSerial.h>
#include <LoRa.h>
// =====================================================
// BeaconMe Ad-Hoc Node A1
// NodeMCU + LoRa RF relay
// =====================================================

SoftwareSerial LoRa_rf(D5, D6);

#define LED_PIN LED_BUILTIN

const char* ADHOC_NODE_ID = "A1";
const unsigned long RELAY_DELAY_MS = 200;

// BeaconMe SOS packet format:
// S,node_id,latE5,lonE5,emergency_type,message_code,danger_level,hop_count

const int CACHE_SIZE = 20;
String packetKeyCache[CACHE_SIZE];
unsigned long packetCacheTime[CACHE_SIZE];
int cacheIndex = 0;

const unsigned long DUPLICATE_WINDOW_MS = 8000;
const int MAX_HOP_COUNT = 5;

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

String makePacketKey(String fields[]) {
  String key = "";
  key += fields[0];
  key += ",";
  key += fields[1];
  key += ",";
  key += fields[2];
  key += ",";
  key += fields[3];
  key += ",";
  key += fields[4];
  key += ",";
  key += fields[5];
  key += ",";
  key += fields[6];

  return key;
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

  if (hopCount < 0 || hopCount > MAX_HOP_COUNT) {
    return false;
  }

  return true;
}

bool recentlyForwarded(String packetKey) {
  unsigned long now = millis();

  for (int i = 0; i < CACHE_SIZE; i++) {
    if (packetKeyCache[i] == packetKey) {
      if (now - packetCacheTime[i] < DUPLICATE_WINDOW_MS) {
        return true;
      }
    }
  }

  return false;
}

void rememberPacket(String packetKey) {
  packetKeyCache[cacheIndex] = packetKey;
  packetCacheTime[cacheIndex] = millis();

  cacheIndex++;

  if (cacheIndex >= CACHE_SIZE) {
    cacheIndex = 0;
  }
}

String buildForwardPacket(String fields[]) {
  int currentHop = fields[7].toInt();

  if (currentHop >= MAX_HOP_COUNT) {
    return "";
  }

  int newHop = currentHop + 1;

  String packet = "";
  packet += fields[0];
  packet += ",";
  packet += fields[1];
  packet += ",";
  packet += fields[2];
  packet += ",";
  packet += fields[3];
  packet += ",";
  packet += fields[4];
  packet += ",";
  packet += fields[5];
  packet += ",";
  packet += fields[6];
  packet += ",";
  packet += String(newHop);

  return packet;
}

void blinkLed() {
  digitalWrite(LED_PIN, LOW);
  delay(80);
  digitalWrite(LED_PIN, HIGH);
}

void setup() {
  Serial.begin(9600);
  LoRa_rf.begin(9600);

  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, HIGH);

  Serial.println();
  Serial.println("BeaconMe Ad-Hoc Node Started");
  Serial.print("Ad-Hoc Node ID: ");
  Serial.println(ADHOC_NODE_ID);
  Serial.println("Waiting for BeaconMe LoRa SOS packets...");
}

void loop() {
  if (LoRa_rf.available()) {
    String packet = LoRa_rf.readStringUntil('\n');
    packet.trim();

    if (packet.length() == 0) {
      return;
    }

    Serial.println();
    Serial.print("Received BeaconMe LoRa Packet: ");
    Serial.println(packet);

    String fields[8];

    if (!isValidBeaconMeSosPacket(packet, fields)) {
      Serial.println("Dropped: invalid BeaconMe SOS packet");
      return;
    }

    int currentHop = fields[7].toInt();

    Serial.print("Current Hop Count: ");
    Serial.println(currentHop);

    String packetKey = makePacketKey(fields);

    if (recentlyForwarded(packetKey)) {
      Serial.println("Dropped: recently forwarded duplicate emergency packet");
      return;
    }

    rememberPacket(packetKey);

    String forwardPacket = buildForwardPacket(fields);

    if (forwardPacket.length() == 0) {
      Serial.println("Dropped: max hop count reached");
      return;
    }

    int newHop = currentHop + 1;

    delay(RELAY_DELAY_MS);

    Serial.print("Forwarding from ");
    Serial.print(ADHOC_NODE_ID);
    Serial.print(" with Hop Count ");
    Serial.print(newHop);
    Serial.print(": ");
    Serial.println(forwardPacket);

    for (int i = 0; i < 2; i++) {
      LoRa_rf.println(forwardPacket);
      blinkLed();
      delay(200);
    }
  }
}
