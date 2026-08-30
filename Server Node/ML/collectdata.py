import serial
import pandas as pd
import random
import time
import os


SERIAL_PORT = "COM5"       # Change this
BAUD_RATE = 115200
DATASET_FILE = "beaconme_real_dataset.csv"

LABELS = ["FAKE", "LOW", "MEDIUM", "HIGH", "CRITICAL"]

COLUMNS = [
    "packet",
    "node_id",
    "latitude",
    "longitude",
    "lat_e5",
    "lon_e5",
    "emergency_type",
    "message_code",
    "danger_level",
    "hop_count",
    "label",
]


def generate_priority_label(
    emergency_type,
    message_code,
    danger_level,
    hop_count
):
    score = 0

    # Danger level
    score += danger_level * 22

    # Emergency type
    if emergency_type == 1:
        score += 25
    elif emergency_type == 2:
        score += 32
    elif emergency_type == 3:
        score += 22
    elif emergency_type == 4:
        score += 36
    elif emergency_type == 5:
        score += 30

    # Message code
    if message_code == 1:
        score += 25
    elif message_code == 2:
        score += 34
    elif message_code == 3:
        score += 36
    elif message_code == 4:
        score += 20
    elif message_code == 5:
        score += 45
    elif message_code == 6:
        score += 32

    # Hop count
    if hop_count >= 2:
        score += 5

    if hop_count >= 3:
        score += 5

    # Same noise as synthetic dataset
    score += random.randint(-12, 12)

    if score >= 145:
        return "CRITICAL"
    elif score >= 112:
        return "HIGH"
    elif score >= 75:
        return "MEDIUM"
    else:
        return "LOW"


def parse_packet(packet):
    fields = packet.strip().split(",")

    if len(fields) != 8:
        return None

    if fields[0] != "S":
        return None

    try:
        node_id = int(fields[1])
        lat_e5 = int(fields[2])
        lon_e5 = int(fields[3])
        emergency_type = int(fields[4])
        message_code = int(fields[5])
        danger_level = int(fields[6])
        hop_count = int(fields[7])
    except ValueError:
        return None

    latitude = lat_e5 / 100000.0
    longitude = lon_e5 / 100000.0

    return {
        "packet": packet,
        "node_id": node_id,
        "latitude": latitude,
        "longitude": longitude,
        "lat_e5": lat_e5,
        "lon_e5": lon_e5,
        "emergency_type": emergency_type,
        "message_code": message_code,
        "danger_level": danger_level,
        "hop_count": hop_count,
    }


def is_genuine_packet(sample):
    """
    Validation designed to match the synthetic dataset's
    genuine packet characteristics.
    """

    # Genuine node IDs in synthetic dataset are 1-3
    if not (1 <= sample["node_id"] <= 3):
        return False

    # Genuine Sri Lankan coordinate range
    if not (5.8 <= sample["latitude"] <= 9.9):
        return False

    if not (79.5 <= sample["longitude"] <= 82.1):
        return False

    # Zero location is fake
    if sample["latitude"] == 0.0 and sample["longitude"] == 0.0:
        return False

    # Genuine emergency type
    if not (1 <= sample["emergency_type"] <= 5):
        return False

    # Genuine message code
    if not (1 <= sample["message_code"] <= 6):
        return False

    # Genuine danger level
    if not (1 <= sample["danger_level"] <= 5):
        return False

    # Genuine hop count
    if not (0 <= sample["hop_count"] <= 4):
        return False

    return True


def create_dataset_row(packet):
    sample = parse_packet(packet)

    if sample is None:
        return None

    if is_genuine_packet(sample):
        sample["label"] = generate_priority_label(
            sample["emergency_type"],
            sample["message_code"],
            sample["danger_level"],
            sample["hop_count"],
        )
    else:
        sample["label"] = "FAKE"

    return sample


def save_row(row):
    df = pd.DataFrame([row], columns=COLUMNS)

    file_exists = os.path.exists(DATASET_FILE)

    df.to_csv(
        DATASET_FILE,
        mode="a",
        header=not file_exists,
        index=False,
    )


def main():

    print("==========================================")
    print(" BeaconMe USB Dataset Collector")
    print("==========================================")
    print("Serial Port :", SERIAL_PORT)
    print("Baud Rate   :", BAUD_RATE)
    print("Dataset     :", DATASET_FILE)
    print()
    print("Waiting for BeaconMe packets...")
    print("Press Ctrl+C to stop.")
    print()

    ser = serial.Serial(
        SERIAL_PORT,
        BAUD_RATE,
        timeout=1
    )

    time.sleep(2)

    genuine_count = 0
    fake_count = 0
    total_count = 0

    try:

        while True:

            line = ser.readline().decode(
                "utf-8",
                errors="ignore"
            ).strip()

            if not line:
                continue

            # Only process BeaconMe packets
            if not line.startswith("S,"):
                continue

            row = create_dataset_row(line)

            if row is None:
                print("Invalid packet:", line)
                continue

            save_row(row)

            total_count += 1

            if row["label"] == "FAKE":
                fake_count += 1
            else:
                genuine_count += 1

            print(
                f"[{total_count}] "
                f"{row['label']:8s} | "
                f"Node={row['node_id']} | "
                f"Emergency={row['emergency_type']} | "
                f"Message={row['message_code']} | "
                f"Danger={row['danger_level']} | "
                f"Hop={row['hop_count']} | "
                f"Lat={row['latitude']:.5f} | "
                f"Lon={row['longitude']:.5f}"
            )

    except KeyboardInterrupt:

        print()
        print("Stopping collector...")

    finally:

        ser.close()

        print()
        print("==========================================")
        print("Dataset collection finished")
        print("==========================================")
        print("Total samples :", total_count)
        print("Genuine       :", genuine_count)
        print("Fake          :", fake_count)
        print("Dataset       :", DATASET_FILE)

        if os.path.exists(DATASET_FILE):

            df = pd.read_csv(DATASET_FILE)

            print()
            print("Dataset shape:", df.shape)

            print()
            print("Columns:")
            print(list(df.columns))

            print()
            print("Label distribution:")
            print(df["label"].value_counts())

            print()
            print("First 5 rows:")
            print(df.head())
            

if __name__ == "__main__":
    main()