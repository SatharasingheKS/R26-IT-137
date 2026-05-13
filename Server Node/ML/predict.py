import argparse
import joblib
import pandas as pd


MODEL_FILE = "beaconme_best_model.joblib"


def parse_beaconme_packet(packet):
    packet = packet.strip()

    fields = packet.split(",")

    if len(fields) != 8:
        raise ValueError(
            f"Invalid packet. Expected 8 fields, got {len(fields)}.\n"
            "Expected format: S,node_id,latE5,lonE5,emergency_type,message_code,danger_level,hop_count"
        )

    if fields[0] != "S":
        raise ValueError("Invalid packet. First field must be S.")

    node_id = int(fields[1])
    lat_e5 = int(fields[2])
    lon_e5 = int(fields[3])
    emergency_type = int(fields[4])
    message_code = int(fields[5])
    danger_level = int(fields[6])
    hop_count = int(fields[7])

    latitude = lat_e5 / 100000.0
    longitude = lon_e5 / 100000.0

    features = {
        "node_id": node_id,
        "latitude": latitude,
        "longitude": longitude,
        "emergency_type": emergency_type,
        "message_code": message_code,
        "danger_level": danger_level,
        "hop_count": hop_count,
    }

    return features


def get_name(mapping, code):
    return mapping.get(code, "Unknown")


def predict_packet(packet):
    bundle = joblib.load(MODEL_FILE)

    model = bundle["model"]
    model_name = bundle["model_name"]
    accuracy = bundle["accuracy"]
    feature_columns = bundle["feature_columns"]

    emergency_type_map = bundle["emergency_type_map"]
    message_code_map = bundle["message_code_map"]
    danger_level_map = bundle["danger_level_map"]

    features = parse_beaconme_packet(packet)

    X = pd.DataFrame([features], columns=feature_columns)

    prediction = model.predict(X)[0] 

    confidence = None
    probabilities_table = None

    if hasattr(model, "predict_proba"):
        probabilities = model.predict_proba(X)[0]
        classes = list(model.classes_)

        probabilities_table = sorted(
            zip(classes, probabilities),
            key=lambda x: x[1],
            reverse=True,
        )

        confidence = float(max(probabilities))

    print("\n" + "=" * 70)
    print("BeaconMe Sample Prediction")
    print("=" * 70)

    print("\nRaw packet:")
    print(packet)

    print("\nParsed data:")
    print("Survivor Node ID:", features["node_id"])
    print("Latitude:", features["latitude"])
    print("Longitude:", features["longitude"])

    print(
        "Emergency Type:",
        features["emergency_type"],
        "-",
        get_name(emergency_type_map, features["emergency_type"]),
    )

    print(
        "Message Code:",
        features["message_code"],
        "-",
        get_name(message_code_map, features["message_code"]),
    )

    print(
        "Danger Level:",
        features["danger_level"],
        "-",
        get_name(danger_level_map, features["danger_level"]),
    )

    print("Hop Count:", features["hop_count"])

    if features["hop_count"] == 0:
        print("Forward Status: Direct from survivor node")
    else:
        print("Forward Status: Forwarded through ad-hoc node")

    print("\nML model:")
    print("Selected model:", model_name)
    print("Saved test accuracy:", round(accuracy, 4))

    print("\nPrediction result:")
    print("Predicted class:", prediction)

    if confidence is not None:
        print("Confidence:", round(confidence, 4))

    if probabilities_table is not None:
        print("\nClass probabilities:")
        for label, prob in probabilities_table:
            print(f"{label}: {prob:.4f}")

    print("\nDecision:")

    if prediction == "FAKE":
        print("Reject packet / mark as suspicious")
    elif prediction == "LOW":
        print("Accept packet / low priority")
    elif prediction == "MEDIUM":
        print("Accept packet / medium priority")
    elif prediction == "HIGH":
        print("Accept packet / high priority")
    elif prediction == "CRITICAL":
        print("Accept packet / highest emergency priority")

    print("\nGoogle Maps:")
    print(f"https://maps.google.com/?q={features['latitude']},{features['longitude']}")

    print("=" * 70)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--packet",
        type=str,
        default="S,1,692710,7986119,1,1,5,1",
        help="BeaconMe packet: S,node_id,latE5,lonE5,emergency_type,message_code,danger_level,hop_count",
    )

    args = parser.parse_args()

    predict_packet(args.packet)


if __name__ == "__main__":
    main()