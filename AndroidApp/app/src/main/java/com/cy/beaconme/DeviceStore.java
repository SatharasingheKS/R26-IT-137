package com.cy.beaconme;

import android.content.Context;
import android.content.SharedPreferences;

import androidx.annotation.NonNull;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public final class DeviceStore {

    private static final String PREFS = "iot_devices_store";
    private static final String KEY_LIST = "devices_json";

    private final SharedPreferences prefs;

    public DeviceStore(@NonNull Context context) {
        prefs = context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    @NonNull
    public List<IoTDevice> loadAll() {
        String raw = prefs.getString(KEY_LIST, "[]");
        if (raw == null || raw.isEmpty()) {
            return Collections.emptyList();
        }
        List<IoTDevice> out = new ArrayList<>();
        try {
            JSONArray arr = new JSONArray(raw);
            for (int i = 0; i < arr.length(); i++) {
                JSONObject o = arr.optJSONObject(i);
                if (o == null) {
                    continue;
                }
                IoTDevice d = IoTDevice.fromJson(o);
                if (d != null) {
                    out.add(d);
                }
            }
        } catch (JSONException ignored) {
            return Collections.emptyList();
        }
        return out;
    }

    public void saveAll(@NonNull List<IoTDevice> devices) {
        JSONArray arr = new JSONArray();
        for (IoTDevice d : devices) {
            try {
                arr.put(d.toJson());
            } catch (JSONException ignored) {
            }
        }
        prefs.edit().putString(KEY_LIST, arr.toString()).apply();
    }

    public void upsert(@NonNull IoTDevice device) {
        List<IoTDevice> list = new ArrayList<>(loadAll());
        boolean found = false;
        for (int i = 0; i < list.size(); i++) {
            if (list.get(i).getId().equals(device.getId())) {
                list.set(i, device);
                found = true;
                break;
            }
        }
        if (!found) {
            list.add(device);
        }
        saveAll(list);
    }

    public void deleteById(@NonNull String id) {
        List<IoTDevice> list = new ArrayList<>(loadAll());
        for (int i = list.size() - 1; i >= 0; i--) {
            if (list.get(i).getId().equals(id)) {
                list.remove(i);
            }
        }
        saveAll(list);
    }
}
