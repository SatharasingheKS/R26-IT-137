#include <LoRa.h>
#include <SoftwareSerial.h>

SoftwareSerial LoRa_rf(D5, D6);

// Status LEDs matching Ad-Hoc Node A2
#define GREEN_LED_PIN D1
#define YELLOW_LED_PIN D2
#define RED_LED_PIN D3


const int PIN_LOW  = D7;  // Transistor Q1 Collector (LOW water level ~25%)
const int PIN_MED  = D4;  // Transistor Q2 Collector (MED water level ~50%)
const int PIN_HIGH = D0;  // Transistor Q3 Collector (HIGH water level ~100%)


const int SENSOR_NODE_ID = 3; // Node ID within valid range [1..9]


const int32_t LAT_E5 = 692710;
const int32_t LON_E5 = 7986119;

// Emergency Type: 3 = Flood
const int EMERGENCY_TYPE = 3;

// Message Code: 1 = Need rescue
const int MESSAGE_CODE = 1;

// Sensor node is origin of SOS packet (Hop count = 0)
const int START_HOP_COUNT = 0;

// Timing variables
unsigned long lastSensorReadTime = 0;
const unsigned long SENSOR_READ_INTERVAL_MS = 2000; // Read sensors every 2s

unsigned long lastSosTransmissionTime = 0;
const unsigned long SOS_TRANSMIT_INTERVAL_MS = 5000; // Transmit SOS every 5s if alert

// Function declarations
int readWaterLevel();
int calculateDangerLevel(int waterLevelPercent);
String buildSosPacket(int dangerLevel);
void sendSosPacket(String packet);
void blinkStatusLed(uint8_t pin);

void setup() {
  Serial.begin(9600);
  LoRa_rf.begin(9600);


  pinMode(PIN_LOW, INPUT);  
  pinMode(PIN_MED, INPUT);   
  pinMode(PIN_HIGH, INPUT);  

  
  pinMode(GREEN_LED_PIN, OUTPUT);
  pinMode(YELLOW_LED_PIN, OUTPUT);
  pinMode(RED_LED_PIN, OUTPUT);

  
  digitalWrite(GREEN_LED_PIN, HIGH);
  digitalWrite(YELLOW_LED_PIN, LOW);
  digitalWrite(RED_LED_PIN, LOW);

  Serial.println();
  Serial.println("=========================================");
  Serial.println(" BeaconMe Sensor Node Initialized ");
  Serial.print(" Node ID: ");
  Serial.println(SENSOR_NODE_ID);
  Serial.println(" Hardware: NodeMCU + LoRa + DIY Water Level Sensor");
  Serial.println(" Sensor Pins: D7(LOW) D4(MED) D0(HIGH)");
  Serial.println(" Emergency Type: 3 (Flood)");
  Serial.println(" Transmit Indicator: Red LED (D3)");
  Serial.println("=========================================");
}

void loop() {
  unsigned long currentMillis = millis();

  if (currentMillis - lastSensorReadTime >= SENSOR_READ_INTERVAL_MS) {
    lastSensorReadTime = currentMillis;

    int waterLevelPercent = readWaterLevel();
    int dangerLevel = calculateDangerLevel(waterLevelPercent);

    Serial.println("-----------------------------------------");
    Serial.print("Water Level: ");
    Serial.print(waterLevelPercent);
    Serial.print("% - ");

    switch (waterLevelPercent) {
    case 100:
      Serial.println("FULL [HIGH Level Reached]");
      break;
    case 50:
      Serial.println("MEDIUM [MED Level Reached]");
      break;
    case 25:
      Serial.println("LOW [LOW Level Reached]");
      break;
    default:
      Serial.println("EMPTY [No Water Detected]");
      break;
    }

    Serial.print("Calculated Danger Level: ");
    Serial.print(dangerLevel);
    switch (dangerLevel) {
    case 1:
      Serial.println(" (1 - Low)");
      break;
    case 2:
      Serial.println(" (2 - Moderate)");
      break;
    case 3:
      Serial.println(" (3 - Serious)");
      break;
    case 4:
      Serial.println(" (4 - High)");
      break;
    case 5:
      Serial.println(" (5 - Critical)");
      break;
    default:
      Serial.println(" (Unknown)");
      break;
    }

    // Transmit SOS packet if water/danger is detected or periodically
    if (dangerLevel > 1 ||
        (currentMillis - lastSosTransmissionTime >= SOS_TRANSMIT_INTERVAL_MS)) {
      lastSosTransmissionTime = currentMillis;
      String sosPacket = buildSosPacket(dangerLevel);
      sendSosPacket(sosPacket);
    }
  }
}


int readWaterLevel() {
  bool isLowReached  = (digitalRead(PIN_LOW)  == LOW);
  bool isMedReached  = (digitalRead(PIN_MED)  == LOW);
  bool isHighReached = (digitalRead(PIN_HIGH) == LOW);

  if (isHighReached) {
    return 100;  // FULL
  } else if (isMedReached) {
    return 50;   // MEDIUM
  } else if (isLowReached) {
    return 25;   // LOW
  } else {
    return 0;    // EMPTY
  }
}

/**
 * Maps water level percentage to Danger Level (1 to 5).
 *   0%  (EMPTY)  -> 1 (Low / Safe)
 *  25%  (LOW)    -> 2 (Moderate - water rising)
 *  50%  (MEDIUM) -> 3 (Serious - significant water level)
 * 100%  (FULL)   -> 5 (Critical - flood emergency)
 */
int calculateDangerLevel(int waterLevelPercent) {
  switch (waterLevelPercent) {
  case 100:
    return 5;  // Critical
  case 50:
    return 3;  // Serious
  case 25:
    return 2;  // Moderate
  default:
    return 1;  // Low / Safe
  }
}

/**
 * Constructs 8-field CSV BeaconMe SOS Packet:
 * S,node_id,latE5,lonE5,emergency_type,message_code,danger_level,hop_count
 */
String buildSosPacket(int dangerLevel) {
  String packet = "";
  packet += "S";
  packet += ",";
  packet += String(SENSOR_NODE_ID);
  packet += ",";
  packet += String(LAT_E5);
  packet += ",";
  packet += String(LON_E5);
  packet += ",";
  packet += String(EMERGENCY_TYPE);
  packet += ",";
  packet += String(MESSAGE_CODE);
  packet += ",";
  packet += String(dangerLevel);
  packet += ",";
  packet += String(START_HOP_COUNT);

  return packet;
}


void blinkStatusLed(uint8_t pin) {
  digitalWrite(pin, HIGH);
  delay(80);
  digitalWrite(pin, LOW);
}


void sendSosPacket(String packet) {
  Serial.println("========== SENSOR NODE SOS TRANSMISSION ==========");
  Serial.print("Packet: ");
  Serial.println(packet);
  Serial.println("==================================================");

  // Repeat transmission 3 times for link reliability
  for (int i = 0; i < 3; i++) {
    LoRa_rf.println(packet);
    blinkStatusLed(RED_LED_PIN);
    delay(200);
  }
}
