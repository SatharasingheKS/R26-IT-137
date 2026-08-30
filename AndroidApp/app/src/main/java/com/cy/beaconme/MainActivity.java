package com.cy.beaconme;

import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.LayoutInflater;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import androidx.activity.EdgeToEdge;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;

import com.google.android.material.button.MaterialButton;
import com.google.android.material.card.MaterialCardView;
import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.google.android.material.materialswitch.MaterialSwitch;
import com.google.android.material.textfield.TextInputEditText;

public final class MainActivity extends AppCompatActivity {

    private static final String DEFAULT_ENDPOINT = "http://192.168.4.1/api/data";
    private static final long POLL_INTERVAL_MS = 3000L;

    private TelemetryFetcher fetcher;
    private final Handler pollHandler = new Handler(Looper.getMainLooper());
    private Runnable pollRunnable;

    private String endpointUrl = DEFAULT_ENDPOINT;
    private boolean isDemoMode = false;
    @Nullable
    private EmergencyData currentData;

    // UI elements
    private TextView textStatusBadge;
    private MaterialCardView cardEmergencyBanner;
    private View viewPulseDot;
    private TextView textBannerTitle;
    private TextView textNodeId;
    private TextView textEmergencyType;
    private TextView textMessageName;
    private TextView textLoopStatus;

    private TextView textDangerTitle;
    private View barDanger1;
    private View barDanger2;
    private View barDanger3;
    private View barDanger4;
    private View barDanger5;

    private TextView textGpsStatus;
    private TextView textCoordinates;
    private MaterialButton btnOpenMaps;
    private MaterialButton btnCopyCoords;

    private TextView textPacketCount;
    private TextView textPulseSeconds;
    private TextView textHopCount;
    private TextView textLoopInterval;
    private TextView textRawPacket;
    private MaterialButton btnCopyPacket;

    private MaterialSwitch switchDemoMode;
    private LinearLayout layoutDemoButtons;
    private MaterialButton btnCycleType;
    private MaterialButton btnCycleDanger;
    private MaterialButton btnRefresh;
    private MaterialButton btnWebView;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        EdgeToEdge.enable(this);
        setContentView(R.layout.activity_main);

        View root = findViewById(R.id.main);
        ViewCompat.setOnApplyWindowInsetsListener(root, (v, insets) -> {
            Insets systemBars = insets.getInsets(WindowInsetsCompat.Type.systemBars());
            v.setPadding(systemBars.left, systemBars.top, systemBars.right, systemBars.bottom);
            return insets;
        });

        fetcher = new TelemetryFetcher();
        bindViews();
        setupListeners();

        pollRunnable = new Runnable() {
            @Override
            public void run() {
                fetchTelemetryData();
                pollHandler.postDelayed(this, POLL_INTERVAL_MS);
            }
        };
    }

    @Override
    protected void onResume() {
        super.onResume();
        pollHandler.post(pollRunnable);
    }

    @Override
    protected void onPause() {
        super.onPause();
        pollHandler.removeCallbacks(pollRunnable);
    }

    @Override
    protected void onDestroy() {
        if (fetcher != null) {
            fetcher.shutdown();
        }
        super.onDestroy();
    }

    private void bindViews() {
        textStatusBadge = findViewById(R.id.textStatusBadge);
        cardEmergencyBanner = findViewById(R.id.cardEmergencyBanner);
        viewPulseDot = findViewById(R.id.viewPulseDot);
        textBannerTitle = findViewById(R.id.textBannerTitle);
        textNodeId = findViewById(R.id.textNodeId);
        textEmergencyType = findViewById(R.id.textEmergencyType);
        textMessageName = findViewById(R.id.textMessageName);
        textLoopStatus = findViewById(R.id.textLoopStatus);

        textDangerTitle = findViewById(R.id.textDangerTitle);
        barDanger1 = findViewById(R.id.barDanger1);
        barDanger2 = findViewById(R.id.barDanger2);
        barDanger3 = findViewById(R.id.barDanger3);
        barDanger4 = findViewById(R.id.barDanger4);
        barDanger5 = findViewById(R.id.barDanger5);

        textGpsStatus = findViewById(R.id.textGpsStatus);
        textCoordinates = findViewById(R.id.textCoordinates);
        btnOpenMaps = findViewById(R.id.btnOpenMaps);
        btnCopyCoords = findViewById(R.id.btnCopyCoords);

        textPacketCount = findViewById(R.id.textPacketCount);
        textPulseSeconds = findViewById(R.id.textPulseSeconds);
        textHopCount = findViewById(R.id.textHopCount);
        textLoopInterval = findViewById(R.id.textLoopInterval);
        textRawPacket = findViewById(R.id.textRawPacket);
        btnCopyPacket = findViewById(R.id.btnCopyPacket);

        switchDemoMode = findViewById(R.id.switchDemoMode);
        layoutDemoButtons = findViewById(R.id.layoutDemoButtons);
        btnCycleType = findViewById(R.id.btnCycleType);
        btnCycleDanger = findViewById(R.id.btnCycleDanger);
        btnRefresh = findViewById(R.id.btnRefresh);
        btnWebView = findViewById(R.id.btnWebView);
    }

    private void setupListeners() {
        findViewById(R.id.btnConfigIp).setOnClickListener(v -> showConfigIpDialog());

        switchDemoMode.setOnCheckedChangeListener((buttonView, isChecked) -> {
            isDemoMode = isChecked;
            layoutDemoButtons.setVisibility(isChecked ? View.VISIBLE : View.GONE);
            if (isChecked) {
                textStatusBadge.setText(R.string.status_demo);
                textStatusBadge.setBackgroundColor(Color.parseColor("#8B5CF6")); // Purple for demo
            } else {
                textStatusBadge.setText(R.string.status_connecting);
                textStatusBadge.setBackgroundColor(Color.parseColor("#F59E0B"));
            }
            fetchTelemetryData();
        });

        btnCycleType.setOnClickListener(v -> {
            if (isDemoMode) {
                DemoTelemetry.cycleEmergencyType();
                fetchTelemetryData();
            }
        });

        btnCycleDanger.setOnClickListener(v -> {
            if (isDemoMode) {
                DemoTelemetry.cycleDangerLevel();
                fetchTelemetryData();
            }
        });

        btnRefresh.setOnClickListener(v -> fetchTelemetryData());

        btnOpenMaps.setOnClickListener(v -> openMapsIntent());
        btnCopyCoords.setOnClickListener(v -> copyToClipboard("GPS Coordinates", textCoordinates.getText().toString()));
        btnCopyPacket.setOnClickListener(v -> copyToClipboard("Raw Packet", textRawPacket.getText().toString()));

        btnWebView.setOnClickListener(v -> {
            Intent intent = new Intent(this, DeviceWebActivity.class);
            intent.putExtra(DeviceWebActivity.EXTRA_TITLE, "ESP32 Web Dashboard");
            String rootUrl = endpointUrl.replace("/api/data", "");
            intent.putExtra(DeviceWebActivity.EXTRA_URL, rootUrl);
            startActivity(intent);
        });
    }

    private void fetchTelemetryData() {
        if (isDemoMode) {
            EmergencyData sample = DemoTelemetry.getNextSample();
            updateUI(sample);
            return;
        }

        fetcher.fetch(endpointUrl, new TelemetryFetcher.Callback() {
            @Override
            public void onSuccess(@NonNull EmergencyData data) {
                textStatusBadge.setText(R.string.status_connected);
                textStatusBadge.setBackgroundColor(Color.parseColor("#10B981")); // Emerald Green
                updateUI(data);
            }

            @Override
            public void onError(@NonNull Exception e) {
                textStatusBadge.setText(R.string.status_offline);
                textStatusBadge.setBackgroundColor(Color.parseColor("#EF4444")); // Red
            }
        });
    }

    private void updateUI(@NonNull EmergencyData data) {
        this.currentData = data;

        // Emergency Active Banner
        textNodeId.setText(getString(R.string.label_node_id, data.getNodeId()));
        textEmergencyType.setText(String.format("%s %s EMERGENCY", data.getEmergencyEmoji(), data.getEmergencyName().toUpperCase()));
        textMessageName.setText(String.format("%s • %s", data.getMessageName(), data.getLastSendSource()));
        textLoopStatus.setText(String.format(java.util.Locale.US, "Active Loop • %d ms interval pulse", data.getSosLoopIntervalMs()));

        if (data.isEmergencyActive()) {
            textBannerTitle.setText(R.string.label_emergency_active);
            viewPulseDot.setAlpha(1.0f);
            cardEmergencyBanner.setCardBackgroundColor(Color.parseColor("#7F1D1D")); // Dark Red
            cardEmergencyBanner.setStrokeColor(Color.parseColor("#EF4444"));
        } else {
            textBannerTitle.setText(R.string.label_monitoring);
            viewPulseDot.setAlpha(0.3f);
            cardEmergencyBanner.setCardBackgroundColor(Color.parseColor("#1E293B"));
            cardEmergencyBanner.setStrokeColor(Color.parseColor("#334155"));
        }

        // Danger Level Meter
        textDangerTitle.setText(getString(R.string.label_danger_level, data.getDangerLevel(), data.getDangerName().toUpperCase()));
        updateDangerBars(data.getDangerLevel());

        // GPS Card
        textCoordinates.setText(data.getFormattedCoordinates());
        if (data.isGpsValid()) {
            textGpsStatus.setText(getString(R.string.label_satellites, data.getSatellites()) + " • Valid 3D Fix");
            textGpsStatus.setBackgroundColor(Color.parseColor("#065F46"));
            textGpsStatus.setTextColor(Color.parseColor("#34D399"));
        } else {
            textGpsStatus.setText(R.string.label_gps_invalid);
            textGpsStatus.setBackgroundColor(Color.parseColor("#7F1D1D"));
            textGpsStatus.setTextColor(Color.parseColor("#FCA5A5"));
        }

        // Telemetry Card
        textPacketCount.setText(String.valueOf(data.getPacketCount()));
        textPulseSeconds.setText(getString(R.string.label_pulse_sec, data.getSecondsSincePulse()));
        textHopCount.setText(String.format(java.util.Locale.US, "%d (Mesh Hops)", data.getStartHopCount()));
        textLoopInterval.setText(String.format(java.util.Locale.US, "%d ms", data.getSosLoopIntervalMs()));
        textRawPacket.setText(data.getLastPacket());
    }

    private void updateDangerBars(int level) {
        int dimColor = Color.parseColor("#334155");
        barDanger1.setBackgroundColor(level >= 1 ? Color.parseColor("#10B981") : dimColor);
        barDanger2.setBackgroundColor(level >= 2 ? Color.parseColor("#EAB308") : dimColor);
        barDanger3.setBackgroundColor(level >= 3 ? Color.parseColor("#F97316") : dimColor);
        barDanger4.setBackgroundColor(level >= 4 ? Color.parseColor("#EF4444") : dimColor);
        barDanger5.setBackgroundColor(level >= 5 ? Color.parseColor("#991B1B") : dimColor);
    }

    private void openMapsIntent() {
        if (currentData == null) {
            Toast.makeText(this, "No GPS location data available yet", Toast.LENGTH_SHORT).show();
            return;
        }
        double lat = currentData.getLatitude();
        double lng = currentData.getLongitude();
        String uriString = String.format(java.util.Locale.US, "geo:%.6f,%.6f?q=%.6f,%.6f(Survivor Node %d)", lat, lng, lat, lng, currentData.getNodeId());
        Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(uriString));
        intent.setPackage("com.google.android.apps.maps");

        if (intent.resolveActivity(getPackageManager()) != null) {
            startActivity(intent);
        } else {
            // Fallback to web browser maps
            String webMapsUrl = String.format(java.util.Locale.US, "https://www.google.com/maps/search/?api=1&query=%.6f,%.6f", lat, lng);
            Intent webIntent = new Intent(Intent.ACTION_VIEW, Uri.parse(webMapsUrl));
            startActivity(webIntent);
        }
    }

    private void copyToClipboard(String label, String text) {
        ClipboardManager clipboard = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        if (clipboard != null) {
            ClipData clip = ClipData.newPlainText(label, text);
            clipboard.setPrimaryClip(clip);
            Toast.makeText(this, R.string.toast_copied, Toast.LENGTH_SHORT).show();
        }
    }

    private void showConfigIpDialog() {
        View view = LayoutInflater.from(this).inflate(R.layout.dialog_add_device, null, false);
        TextInputEditText inputUrl = view.findViewById(R.id.inputUrl);
        view.findViewById(R.id.layoutName).setVisibility(View.GONE);

        if (inputUrl != null) {
            inputUrl.setText(endpointUrl);
        }

        new MaterialAlertDialogBuilder(this)
                .setTitle(R.string.dialog_ip_title)
                .setView(view)
                .setNegativeButton(R.string.cancel, null)
                .setPositiveButton(R.string.save, (dialog, which) -> {
                    if (inputUrl != null && inputUrl.getText() != null) {
                        String newUrl = inputUrl.getText().toString().trim();
                        if (!newUrl.isEmpty()) {
                            if (!newUrl.startsWith("http://") && !newUrl.startsWith("https://")) {
                                newUrl = "http://" + newUrl;
                            }
                            if (!newUrl.endsWith("/api/data")) {
                                newUrl = newUrl.replaceAll("/+$", "") + "/api/data";
                            }
                            endpointUrl = newUrl;
                            fetchTelemetryData();
                        }
                    }
                })
                .show();
    }
}
