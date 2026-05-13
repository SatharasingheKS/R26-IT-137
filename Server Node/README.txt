## Server Node — Data Filtering & Message Classification

The Server Node is responsible for processing and validating incoming distress signals received from the ad-hoc RF communication network during disaster situations. Since emergency environments can generate duplicate, accidental, or false distress messages, the server acts as a filtering and prioritization layer before forwarding alerts to rescue teams.

This component analyzes incoming signals together with environmental sensor data, such as flood water level measurements, to improve reliability. For example, if a flood emergency message is received but nearby flood sensors do not detect any significant water level increase, the signal can be marked as low priority or potentially invalid.

The system also assigns priority levels (High, Medium, Low) to verified distress signals based on urgency and forwards the validated message together with GPS location data to the rescue dashboard. This helps rescue teams focus on genuine and high-priority emergencies while minimizing unnecessary network traffic and resource usage.

### Key Features

* Distress signal filtering and validation
* Flood sensor data integration for cross-checking
* Priority-based emergency message handling
* GPS location processing and forwarding
* Duplicate signal suppression
* Minimal bandwidth communication support

### Current Progress

* Message classification and filtering logic implemented
* Flood sensor integration completed
* Priority ranking system developed
* Simulated RF signal testing completed
* GPS forwarding workflow designed

