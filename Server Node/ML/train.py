import joblib
import pandas as pd

from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier

from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix


DATASET_FILE = "beaconme_synth_dataset.csv"
MODEL_FILE = "beaconme_best_model.joblib"
METRICS_FILE = "beaconme_model_metrics.txt"

FEATURE_COLUMNS = [
    "node_id",
    "latitude",
    "longitude",
    "emergency_type",
    "message_code",
    "danger_level",
    "hop_count",
]

LABELS = [
    "FAKE",
    "LOW",
    "MEDIUM",
    "HIGH",
    "CRITICAL",
]


def load_dataset():
    df = pd.read_csv(DATASET_FILE)

    required_columns = FEATURE_COLUMNS + ["label"]
    missing_columns = []

    for col in required_columns:
        if col not in df.columns:
            missing_columns.append(col)

    if missing_columns:
        raise ValueError(f"Missing required columns: {missing_columns}")

    return df


def train_models(df):
    X = df[FEATURE_COLUMNS]
    y = df["label"]

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.25,
        random_state=42,
        stratify=y,
    )

    models = {
        "Logistic Regression": Pipeline([
            ("scaler", StandardScaler()),
            ("model", LogisticRegression(
                max_iter=2000,
                class_weight="balanced",
            )),
        ]),

        "Decision Tree": DecisionTreeClassifier(
            max_depth=12,
            random_state=42,
            class_weight="balanced",
        ),

        "Random Forest": RandomForestClassifier(
            n_estimators=250,
            max_depth=14,
            random_state=42,
            class_weight="balanced",
        ),
    }

    best_model_name = None
    best_model = None
    best_accuracy = -1.0

    report_lines = []

    report_lines.append("BeaconMe ML Training Report")
    report_lines.append("=" * 60)
    report_lines.append(f"Dataset file: {DATASET_FILE}")
    report_lines.append(f"Total samples: {len(df)}")
    report_lines.append(f"Training samples: {len(X_train)}")
    report_lines.append(f"Testing samples: {len(X_test)}")
    report_lines.append("")
    report_lines.append("Feature columns:")
    report_lines.append(", ".join(FEATURE_COLUMNS))
    report_lines.append("")

    print("\nTraining started...")

    for model_name, model in models.items():
        print(f"\nTraining {model_name}...")

        model.fit(X_train, y_train)

        y_pred = model.predict(X_test)
        accuracy = accuracy_score(y_test, y_pred)

        print(f"{model_name} accuracy: {accuracy:.4f}")

        report_lines.append("")
        report_lines.append(f"Model: {model_name}")
        report_lines.append("-" * 60)
        report_lines.append(f"Accuracy: {accuracy:.4f}")
        report_lines.append("")
        report_lines.append("Classification Report:")
        report_lines.append(classification_report(y_test, y_pred))
        report_lines.append("")
        report_lines.append("Confusion Matrix:")
        report_lines.append(str(confusion_matrix(y_test, y_pred, labels=LABELS)))
        report_lines.append("Labels order:")
        report_lines.append(str(LABELS))
        report_lines.append("")

        if accuracy > best_accuracy:
            best_accuracy = accuracy
            best_model_name = model_name
            best_model = model

    bundle = {
        "model": best_model,
        "model_name": best_model_name,
        "accuracy": best_accuracy,
        "feature_columns": FEATURE_COLUMNS,
        "labels": LABELS,
        "emergency_type_map": {
            1: "Medical",
            2: "Fire",
            3: "Flood",
            4: "Trapped",
            5: "Security Threat",
        },
        "message_code_map": {
            1: "Need rescue",
            2: "Injured",
            3: "Trapped",
            4: "Need medicine",
            5: "Unconscious",
            6: "Fire nearby",
        },
        "danger_level_map": {
            1: "Low",
            2: "Moderate",
            3: "Serious",
            4: "High",
            5: "Critical",
        },
    }

    joblib.dump(bundle, MODEL_FILE)

    report_lines.append("")
    report_lines.append("Best Model")
    report_lines.append("=" * 60)
    report_lines.append(f"Best model: {best_model_name}")
    report_lines.append(f"Best accuracy: {best_accuracy:.4f}")

    with open(METRICS_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))

    return best_model_name, best_accuracy


def main():
    print("Loading dataset:", DATASET_FILE)

    df = load_dataset()

    print("Dataset loaded successfully")
    print("Shape:", df.shape)

    print("\nLabel distribution:")
    print(df["label"].value_counts())

    best_model_name, best_accuracy = train_models(df)

    print("\n" + "=" * 60)
    print("Training complete")
    print("=" * 60)
    print("Best model:", best_model_name)
    print("Best accuracy:", round(best_accuracy, 4))

    print("\nFiles created:")
    print(MODEL_FILE)
    print(METRICS_FILE)


if __name__ == "__main__":
    main()