package com.cy.beaconme;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import org.json.JSONException;
import org.json.JSONObject;

import java.util.Objects;
import java.util.UUID;

public final class IoTDevice {

    private final String id;
    private final String name;
    private final String url;

    public IoTDevice(@NonNull String id, @NonNull String name, @NonNull String url) {
        this.id = id;
        this.name = name;
        this.url = url;
    }

    @NonNull
    public static IoTDevice createNew(@NonNull String name, @NonNull String url) {
        return new IoTDevice(UUID.randomUUID().toString(), name.trim(), normalizeUrl(url.trim()));
    }

    @NonNull
    public IoTDevice withUpdates(@NonNull String name, @NonNull String url) {
        return new IoTDevice(id, name.trim(), normalizeUrl(url.trim()));
    }

    @NonNull
    public String getId() {
        return id;
    }

    @NonNull
    public String getName() {
        return name;
    }

    @NonNull
    public String getUrl() {
        return url;
    }

    @NonNull
    JSONObject toJson() throws JSONException {
        JSONObject o = new JSONObject();
        o.put("id", id);
        o.put("name", name);
        o.put("url", url);
        return o;
    }

    @Nullable
    static IoTDevice fromJson(@NonNull JSONObject o) {
        try {
            String id = o.getString("id");
            String name = o.getString("name");
            String url = o.getString("url");
            if (id.isEmpty() || name.isEmpty() || url.isEmpty()) {
                return null;
            }
            return new IoTDevice(id, name, normalizeUrl(url));
        } catch (JSONException e) {
            return null;
        }
    }

    @NonNull
    static String normalizeUrl(@NonNull String raw) {
        if (raw.isEmpty()) {
            return raw;
        }
        String lower = raw.toLowerCase(java.util.Locale.ROOT);
        if (lower.startsWith("http://") || lower.startsWith("https://")) {
            return raw;
        }
        return "http://" + raw;
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) {
            return true;
        }
        if (o == null || getClass() != o.getClass()) {
            return false;
        }
        IoTDevice ioTDevice = (IoTDevice) o;
        return id.equals(ioTDevice.id);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id);
    }
}
