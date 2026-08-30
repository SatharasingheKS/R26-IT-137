package com.cy.beaconme;

import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ImageButton;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.recyclerview.widget.RecyclerView;

import java.util.ArrayList;
import java.util.List;

public final class DeviceAdapter extends RecyclerView.Adapter<DeviceAdapter.Holder> {

    public interface Listener {
        void onDeviceClick(@NonNull IoTDevice device);

        void onDeviceMenu(@NonNull IoTDevice device, @NonNull View anchor);
    }

    private final List<IoTDevice> items = new ArrayList<>();
    private final Listener listener;

    public DeviceAdapter(@NonNull Listener listener) {
        this.listener = listener;
    }

    public void setItems(@NonNull List<IoTDevice> devices) {
        items.clear();
        items.addAll(devices);
        notifyDataSetChanged();
    }

    @NonNull
    @Override
    public Holder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        View v = LayoutInflater.from(parent.getContext()).inflate(R.layout.item_device, parent, false);
        return new Holder(v);
    }

    @Override
    public void onBindViewHolder(@NonNull Holder holder, int position) {
        IoTDevice d = items.get(position);
        holder.textName.setText(d.getName());
        holder.textUrl.setText(d.getUrl());
        holder.itemView.setOnClickListener(v -> listener.onDeviceClick(d));
        holder.btnMore.setOnClickListener(v -> listener.onDeviceMenu(d, holder.btnMore));
    }

    @Override
    public int getItemCount() {
        return items.size();
    }

    static final class Holder extends RecyclerView.ViewHolder {
        final TextView textName;
        final TextView textUrl;
        final ImageButton btnMore;

        Holder(@NonNull View itemView) {
            super(itemView);
            textName = itemView.findViewById(R.id.textName);
            textUrl = itemView.findViewById(R.id.textUrl);
            btnMore = itemView.findViewById(R.id.btnMore);
        }
    }
}
