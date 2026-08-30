package com.cy.beaconme;

import android.os.Handler;
import android.os.Looper;

import androidx.annotation.NonNull;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class TelemetryFetcher {

    public interface Callback {
        void onSuccess(@NonNull EmergencyData data);
        void onError(@NonNull Exception e);
    }

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    public void fetch(@NonNull String endpointUrl, @NonNull Callback callback) {
        executor.execute(() -> {
            try {
                URL url = new URL(endpointUrl);
                HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("GET");
                conn.setConnectTimeout(4000);
                conn.setReadTimeout(4000);
                conn.setRequestProperty("Accept", "application/json");

                int statusCode = conn.getResponseCode();
                if (statusCode != 200) {
                    throw new Exception("HTTP error code: " + statusCode);
                }

                BufferedReader reader = new BufferedReader(new InputStreamReader(conn.getInputStream()));
                StringBuilder builder = new StringBuilder();
                String line;
                while ((line = reader.readLine()) != null) {
                    builder.append(line);
                }
                reader.close();
                conn.disconnect();

                JSONObject json = new JSONObject(builder.toString());
                EmergencyData data = EmergencyData.fromJsonObject(json);

                mainHandler.post(() -> callback.onSuccess(data));
            } catch (Exception e) {
                mainHandler.post(() -> callback.onError(e));
            }
        });
    }

    public void shutdown() {
        executor.shutdownNow();
    }
}
