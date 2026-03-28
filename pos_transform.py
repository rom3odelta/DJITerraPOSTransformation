import csv
import os
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk
from pyproj import Transformer, CRS

# ── CRS Presets ──────────────────────────────────────────────────────────────
# Friendly name → EPSG code. Users can also type any EPSG code directly.
CRS_PRESETS = {
    "WGS 84 (EPSG:4326)": "4326",
    "PRS 92 Zone 1 (EPSG:3121)": "3121",
    "PRS 92 Zone 2 (EPSG:3122)": "3122",
    "PRS 92 Zone 3 (EPSG:3123)": "3123",
    "PRS 92 Zone 4 (EPSG:3124)": "3124",
    "PRS 92 Zone 5 (EPSG:3125)": "3125",
}

POS_INPUT_COLUMNS = [
    "Photo Name", "Latitude", "Longitude", "Altitude",
    "Yaw", "Pitch", "Roll", "Horizontal Accuracy", "Vertical Accuracy"
]

POS_OUTPUT_COLUMNS = [
    "Photo Name", "Easting", "Northing", "Elevation",
    "Yaw", "Pitch", "Roll", "Horizontal Accuracy", "Vertical Accuracy"
]

# ── Transformation helpers (copied from ct.py) ──────────────────────────────

def is_geographic(epsg_code):
    """Determine if an EPSG code represents a geographic (lat/lon) CRS."""
    try:
        crs = CRS.from_epsg(int(epsg_code))
        return crs.is_geographic
    except Exception:
        return False


def build_transformer(src_epsg, dst_epsg):
    """Create a pyproj Transformer from source to destination EPSG codes."""
    return Transformer.from_crs(
        f"EPSG:{src_epsg}", f"EPSG:{dst_epsg}", always_xy=True
    )


def transform_point(transformer, lon, lat):
    """Transform a single (lon, lat) point. always_xy=True expects (x=lon, y=lat)."""
    return transformer.transform(lon, lat)  # returns (x/easting, y/northing)


# ── GCP Delta Computation ────────────────────────────────────────────────────

def compute_gcp_delta(gcp_src_easting, gcp_src_northing, gcp_src_elev,
                       gcp_tgt_easting, gcp_tgt_northing, gcp_tgt_elev):
    """
    Compute the translation delta from a single GCP pair.
    Both source and target are in projected coordinates (Easting, Northing, Elevation).

    Delta = target_known - source.

    Returns (dE, dN, dZ).
    """
    dE = gcp_tgt_easting - gcp_src_easting
    dN = gcp_tgt_northing - gcp_src_northing
    dZ = gcp_tgt_elev - gcp_src_elev
    return dE, dN, dZ


# ── POS CSV I/O ──────────────────────────────────────────────────────────────

def read_pos_csv(filepath):
    """Read a DJI Terra POS CSV. Returns list of dicts."""
    rows = []
    with open(filepath, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def write_pos_csv(filepath, rows):
    """Write transformed POS CSV."""
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=POS_OUTPUT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


# ── Batch Transform ──────────────────────────────────────────────────────────

def transform_pos_data(pos_rows, src_epsg, dst_epsg, dE=0.0, dN=0.0, dZ=0.0):
    """
    Transform all POS rows from source CRS to destination CRS,
    then apply GCP delta shifts.

    Returns list of output dicts with POS_OUTPUT_COLUMNS.
    """
    transformer = build_transformer(src_epsg, dst_epsg)
    results = []
    for row in pos_rows:
        lat = float(row["Latitude"])
        lon = float(row["Longitude"])
        alt = float(row["Altitude"])

        easting, northing = transform_point(transformer, lon, lat)
        easting += dE
        northing += dN
        elevation = alt + dZ

        results.append({
            "Photo Name": row["Photo Name"],
            "Easting": f"{easting:.4f}",
            "Northing": f"{northing:.4f}",
            "Elevation": f"{elevation:.4f}",
            "Yaw": row["Yaw"],
            "Pitch": row["Pitch"],
            "Roll": row["Roll"],
            "Horizontal Accuracy": row["Horizontal Accuracy"],
            "Vertical Accuracy": row["Vertical Accuracy"],
        })
    return results


# ── GUI ──────────────────────────────────────────────────────────────────────

def run_gui():
    pos_rows = []       # raw input rows
    result_rows = []    # transformed output rows
    delta_vals = [0.0, 0.0, 0.0]  # dE, dN, dZ

    # ── Helpers ──────────────────────────────────────────────────────────

    def get_epsg(combo):
        """Resolve EPSG code from combo value (preset name or raw EPSG code)."""
        val = combo.get().strip()
        # If it matches a preset name, return the mapped EPSG code
        if val in CRS_PRESETS:
            return CRS_PRESETS[val]
        # Otherwise treat the raw value as an EPSG code
        return val

    def resolve_crs_name(epsg_code):
        """Look up the official CRS name for an EPSG code."""
        try:
            crs = CRS.from_epsg(int(epsg_code))
            return crs.name
        except Exception:
            return None

    def on_crs_input(combo, label_var):
        """When user types or selects in a CRS combo, resolve and display the CRS name."""
        epsg = get_epsg(combo)
        if not epsg:
            label_var.set("")
            return
        name = resolve_crs_name(epsg)
        if name:
            label_var.set(f"\u2714 {name} (EPSG:{epsg})")
        else:
            label_var.set(f"\u2716 Unknown EPSG code: {epsg}")
        # Auto-refresh transformation parameters whenever CRS changes
        update_transform_params()

    def get_transform_info():
        """Build a text summary of the transformation parameters from pyproj."""
        try:
            src_epsg = get_epsg(src_combo)
            dst_epsg = get_epsg(dst_combo)
        except Exception:
            return "Select source and target CRS to see parameters."
        if not src_epsg or not dst_epsg:
            return "Select source and target CRS to see parameters."
        try:
            src_crs = CRS.from_epsg(int(src_epsg))
            dst_crs = CRS.from_epsg(int(dst_epsg))
        except Exception:
            return "Invalid EPSG code(s). Cannot resolve transformation."

        lines = []
        friendly = {
            "Longitude of natural origin": "Central Meridian",
            "Latitude of natural origin": "Latitude of Origin",
            "Scale factor at natural origin": "Scale Factor",
        }

        def append_crs_details(label, crs, epsg):
            lines.append(f"{label} (EPSG:{epsg})")
            lines.append(f"  Name: {crs.name}")
            lines.append(f"  Type: {'Geographic' if crs.is_geographic else 'Projected'}")
            lines.append(f"  Datum: {crs.datum.name}")
            lines.append(f"  Ellipsoid: {crs.ellipsoid.name}")
            if crs.coordinate_operation:
                lines.append(f"  Projection: {crs.coordinate_operation.method_name}")
                if crs.coordinate_operation.params:
                    lines.append("  Parameters:")
                    for p in crs.coordinate_operation.params:
                        name = friendly.get(p.name, p.name)
                        lines.append(f"    {name}: {p.value} {p.unit_name}")

        append_crs_details("SOURCE CRS", src_crs, src_epsg)
        lines.append("")
        append_crs_details("TARGET CRS", dst_crs, dst_epsg)
        lines.append("")

        # Transformation pipeline
        try:
            transformer = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
            lines.append("TRANSFORMATION PIPELINE")
            for op in transformer.operations:
                lines.append(f"  \u2192 {op.name}")
                if hasattr(op, 'method_name') and op.method_name:
                    lines.append(f"    Method: {op.method_name}")
                if hasattr(op, 'params') and op.params:
                    for p in op.params:
                        name = friendly.get(p.name, p.name)
                        lines.append(f"    {name}: {p.value} {p.unit_name}")
                if hasattr(op, 'accuracy') and op.accuracy is not None and op.accuracy >= 0:
                    lines.append(f"    Accuracy: {op.accuracy} m")
        except AttributeError:
            # transformer.operations not available in older pyproj
            lines.append("TRANSFORMATION")
            lines.append(f"  {src_crs.name} \u2192 {dst_crs.name}")
        except Exception as e:
            lines.append(f"  (Could not resolve pipeline: {e})")

        return "\n".join(lines)

    # ── File Browse ──────────────────────────────────────────────────────

    def browse_input():
        filepath = filedialog.askopenfilename(
            title="Select POS CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if not filepath:
            return
        input_path_var.set(filepath)
        try:
            nonlocal pos_rows
            pos_rows = read_pos_csv(filepath)
            status_var.set(f"Loaded {len(pos_rows)} photos from POS file.")
            populate_input_preview()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read POS CSV:\n{e}")

    def populate_input_preview():
        for item in tree_input.get_children():
            tree_input.delete(item)
        for row in pos_rows:
            tree_input.insert("", "end", values=[
                row.get("Photo Name", ""),
                row.get("Latitude", ""),
                row.get("Longitude", ""),
                row.get("Altitude", ""),
                row.get("Yaw", ""),
                row.get("Pitch", ""),
                row.get("Roll", ""),
            ])

    # ── Compute Delta ────────────────────────────────────────────────────

    def on_compute_delta():
        src_epsg = get_epsg(src_combo)
        dst_epsg = get_epsg(dst_combo)
        if not src_epsg or not dst_epsg:
            messagebox.showerror("Error", "Please select source and target CRS.")
            return
        try:
            gcp_src_e = float(gcp_src_e_entry.get())
            gcp_src_n = float(gcp_src_n_entry.get())
            gcp_src_elev = float(gcp_src_elev_entry.get())
            gcp_tgt_e = float(gcp_tgt_e_entry.get())
            gcp_tgt_n = float(gcp_tgt_n_entry.get())
            gcp_tgt_elev = float(gcp_tgt_elev_entry.get())
        except ValueError:
            messagebox.showerror("Error", "All GCP fields must be valid numbers.")
            return

        try:
            dE, dN, dZ = compute_gcp_delta(
                gcp_src_e, gcp_src_n, gcp_src_elev,
                gcp_tgt_e, gcp_tgt_n, gcp_tgt_elev
            )
        except Exception as e:
            messagebox.showerror("Error", f"Delta computation failed:\n{e}")
            return

        delta_vals[0], delta_vals[1], delta_vals[2] = dE, dN, dZ
        delta_e_var.set(f"{dE:.4f}")
        delta_n_var.set(f"{dN:.4f}")
        delta_z_var.set(f"{dZ:.4f}")
        status_var.set(f"Delta computed: dE={dE:.4f}  dN={dN:.4f}  dZ={dZ:.4f}")

    # ── Transform ────────────────────────────────────────────────────────

    def on_transform():
        nonlocal result_rows
        if not pos_rows:
            messagebox.showerror("Error", "No POS data loaded. Browse for a CSV first.")
            return
        src_epsg = get_epsg(src_combo)
        dst_epsg = get_epsg(dst_combo)
        if not src_epsg or not dst_epsg:
            messagebox.showerror("Error", "Please select source and target CRS.")
            return
        try:
            result_rows = transform_pos_data(
                pos_rows, src_epsg, dst_epsg,
                dE=delta_vals[0], dN=delta_vals[1], dZ=delta_vals[2]
            )
        except Exception as e:
            messagebox.showerror("Error", f"Transformation failed:\n{e}")
            return

        populate_output_table()
        status_var.set(f"Transformed {len(result_rows)} photos successfully.")

    def populate_output_table():
        for item in tree_output.get_children():
            tree_output.delete(item)
        for row in result_rows:
            tree_output.insert("", "end", values=[
                row["Photo Name"],
                row["Easting"],
                row["Northing"],
                row["Elevation"],
                row["Yaw"],
                row["Pitch"],
                row["Roll"],
                row["Horizontal Accuracy"],
                row["Vertical Accuracy"],
            ])

    # ── Export ────────────────────────────────────────────────────────────

    def on_export():
        if not result_rows:
            messagebox.showerror("Error", "No transformed data to export. Run Transform first.")
            return
        filepath = filedialog.asksaveasfilename(
            title="Export Transformed POS",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile="transformed_pos.csv"
        )
        if not filepath:
            return
        try:
            write_pos_csv(filepath, result_rows)
            messagebox.showinfo("Exported", f"Saved to:\n{filepath}")
            status_var.set(f"Exported to {filepath}")
        except Exception as e:
            messagebox.showerror("Error", f"Export failed:\n{e}")

    # ── Build Window ─────────────────────────────────────────────────────

    root = tk.Tk()
    root.title("DJI Terra POS Transformation")
    root.geometry("1100x780")
    root.minsize(900, 650)

    # Variables
    input_path_var = tk.StringVar()
    delta_e_var = tk.StringVar(value="0.0000")
    delta_n_var = tk.StringVar(value="0.0000")
    delta_z_var = tk.StringVar(value="0.0000")
    status_var = tk.StringVar(value="Ready")

    PAD = {"padx": 6, "pady": 3}

    # ── Row 0: Input File ────────────────────────────────────────────────
    frm_input = ttk.LabelFrame(root, text="POS Input File", padding=6)
    frm_input.pack(fill="x", padx=8, pady=(8, 4))

    ttk.Label(frm_input, text="CSV File:").grid(row=0, column=0, sticky="e", **PAD)
    ttk.Entry(frm_input, textvariable=input_path_var, width=70, state="readonly").grid(
        row=0, column=1, columnspan=3, sticky="ew", **PAD
    )
    ttk.Button(frm_input, text="Browse...", command=browse_input).grid(row=0, column=4, **PAD)
    frm_input.columnconfigure(1, weight=1)

    # ── Row 1: CRS Selection ─────────────────────────────────────────────
    frm_crs = ttk.LabelFrame(root, text="Coordinate Reference Systems", padding=6)
    frm_crs.pack(fill="x", padx=8, pady=4)

    preset_names = list(CRS_PRESETS.keys())
    src_crs_name_var = tk.StringVar(value="\u2714 WGS 84 (EPSG:4326)")
    dst_crs_name_var = tk.StringVar(value="\u2714 PRS92 / Philippines zone 3 (EPSG:3123)")

    # Source CRS
    ttk.Label(frm_crs, text="Source CRS:").grid(row=0, column=0, sticky="e", **PAD)
    src_combo = ttk.Combobox(frm_crs, values=preset_names, width=30)
    src_combo.set("WGS 84 (EPSG:4326)")
    src_combo.grid(row=0, column=1, sticky="w", **PAD)
    ttk.Label(frm_crs, textvariable=src_crs_name_var, foreground="#006600").grid(
        row=0, column=2, columnspan=2, sticky="w", **PAD
    )

    # Target CRS
    ttk.Label(frm_crs, text="Target CRS:").grid(row=1, column=0, sticky="e", **PAD)
    dst_combo = ttk.Combobox(frm_crs, values=preset_names, width=30)
    dst_combo.set("PRS 92 Zone 3 (EPSG:3123)")
    dst_combo.grid(row=1, column=1, sticky="w", **PAD)
    ttk.Label(frm_crs, textvariable=dst_crs_name_var, foreground="#006600").grid(
        row=1, column=2, columnspan=2, sticky="w", **PAD
    )

    src_combo.bind("<<ComboboxSelected>>", lambda e: on_crs_input(src_combo, src_crs_name_var))
    src_combo.bind("<FocusOut>", lambda e: on_crs_input(src_combo, src_crs_name_var))
    src_combo.bind("<Return>", lambda e: on_crs_input(src_combo, src_crs_name_var))
    dst_combo.bind("<<ComboboxSelected>>", lambda e: on_crs_input(dst_combo, dst_crs_name_var))
    dst_combo.bind("<FocusOut>", lambda e: on_crs_input(dst_combo, dst_crs_name_var))
    dst_combo.bind("<Return>", lambda e: on_crs_input(dst_combo, dst_crs_name_var))

    # ── Row 2: GCP Delta + Transformation Parameters (side by side) ────
    frm_gcp_row = ttk.Frame(root)
    frm_gcp_row.pack(fill="x", padx=8, pady=4)

    # Left: GCP Delta
    frm_gcp = ttk.LabelFrame(frm_gcp_row, text="Ground Control Point (GCP) Delta Translation", padding=6)
    frm_gcp.pack(side="left", fill="both", expand=True)

    # Right: Transformation Parameters
    frm_params = ttk.LabelFrame(frm_gcp_row, text="Transformation Parameters", padding=6)
    frm_params.pack(side="right", fill="both", padx=(6, 0))

    params_text = tk.Text(frm_params, width=48, height=16, state="disabled",
                          font=("Consolas", 9), wrap="word", relief="flat",
                          background="#f5f5f5")
    params_text.pack(fill="both", expand=True)

    def update_transform_params():
        """Refresh the transformation parameters display."""
        info = get_transform_info()
        params_text.config(state="normal")
        params_text.delete("1.0", "end")
        params_text.insert("1.0", info)
        params_text.config(state="disabled")

    # GCP Source
    ttk.Label(frm_gcp, text="GCP Source (from POS / transformed):").grid(
        row=0, column=0, columnspan=6, sticky="w", **PAD
    )
    ttk.Label(frm_gcp, text="Northing:").grid(row=1, column=0, sticky="e", **PAD)
    gcp_src_n_entry = ttk.Entry(frm_gcp, width=18)
    gcp_src_n_entry.grid(row=1, column=1, sticky="w", **PAD)
    ttk.Label(frm_gcp, text="Easting:").grid(row=1, column=2, sticky="e", **PAD)
    gcp_src_e_entry = ttk.Entry(frm_gcp, width=18)
    gcp_src_e_entry.grid(row=1, column=3, sticky="w", **PAD)
    ttk.Label(frm_gcp, text="Elevation:").grid(row=1, column=4, sticky="e", **PAD)
    gcp_src_elev_entry = ttk.Entry(frm_gcp, width=18)
    gcp_src_elev_entry.grid(row=1, column=5, sticky="w", **PAD)

    # GCP Target
    ttk.Label(frm_gcp, text="GCP Target (surveyed / known):").grid(
        row=2, column=0, columnspan=6, sticky="w", **PAD
    )
    ttk.Label(frm_gcp, text="Northing:").grid(row=3, column=0, sticky="e", **PAD)
    gcp_tgt_n_entry = ttk.Entry(frm_gcp, width=18)
    gcp_tgt_n_entry.grid(row=3, column=1, sticky="w", **PAD)
    ttk.Label(frm_gcp, text="Easting:").grid(row=3, column=2, sticky="e", **PAD)
    gcp_tgt_e_entry = ttk.Entry(frm_gcp, width=18)
    gcp_tgt_e_entry.grid(row=3, column=3, sticky="w", **PAD)
    ttk.Label(frm_gcp, text="Elevation:").grid(row=3, column=4, sticky="e", **PAD)
    gcp_tgt_elev_entry = ttk.Entry(frm_gcp, width=18)
    gcp_tgt_elev_entry.grid(row=3, column=5, sticky="w", **PAD)

    # Compute Delta button + display
    ttk.Button(frm_gcp, text="Compute Delta", command=on_compute_delta).grid(
        row=4, column=0, columnspan=2, **PAD
    )
    ttk.Label(frm_gcp, text="dE:").grid(row=4, column=2, sticky="e", **PAD)
    ttk.Entry(frm_gcp, textvariable=delta_e_var, width=14, state="readonly").grid(
        row=4, column=3, sticky="w", **PAD
    )
    ttk.Label(frm_gcp, text="dN:").grid(row=5, column=2, sticky="e", **PAD)
    ttk.Entry(frm_gcp, textvariable=delta_n_var, width=14, state="readonly").grid(
        row=5, column=3, sticky="w", **PAD
    )
    ttk.Label(frm_gcp, text="dZ:").grid(row=4, column=4, sticky="e", **PAD)
    ttk.Entry(frm_gcp, textvariable=delta_z_var, width=14, state="readonly").grid(
        row=4, column=5, sticky="w", **PAD
    )

    # ── Row 3: Action Buttons ────────────────────────────────────────────
    frm_actions = ttk.Frame(root, padding=4)
    frm_actions.pack(fill="x", padx=8, pady=4)

    ttk.Button(frm_actions, text="Transform", command=on_transform).pack(side="left", padx=8)
    ttk.Button(frm_actions, text="Export CSV...", command=on_export).pack(side="left", padx=8)

    # ── Quick Transform helpers ──────────────────────────────────────────

    quick_result_rows = []  # list of tuples for quick transform output

    def parse_coordinates(text):
        """Parse pasted coordinate text. Accepts lines of X Y [Z] or X,Y[,Z].
        Returns list of tuples: (x, y) or (x, y, z)."""
        coords = []
        for line in text.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            # Split on comma, whitespace, or tab
            parts = line.replace(",", " ").split()
            if len(parts) < 2:
                continue
            try:
                vals = [float(p) for p in parts]
                coords.append(tuple(vals))
            except ValueError:
                continue
        return coords

    def on_quick_transform():
        nonlocal quick_result_rows
        src_epsg = get_epsg(src_combo)
        dst_epsg = get_epsg(dst_combo)
        if not src_epsg or not dst_epsg:
            messagebox.showerror("Error", "Please select source and target CRS.")
            return
        text = quick_input_text.get("1.0", "end")
        coords = parse_coordinates(text)
        if not coords:
            messagebox.showerror("Error", "No valid coordinates found.\nPaste lines of: X Y [Z]  or  X,Y[,Z]")
            return
        try:
            transformer = build_transformer(src_epsg, dst_epsg)
        except Exception as e:
            messagebox.showerror("Error", f"Transformer failed:\n{e}")
            return

        quick_result_rows = []
        for item in tree_quick.get_children():
            tree_quick.delete(item)

        src_geo = is_geographic(src_epsg)
        for i, c in enumerate(coords, 1):
            x_in, y_in = c[0], c[1]
            z_in = c[2] if len(c) > 2 else None
            # For geographic CRS input, user pastes Lat,Lon → need (lon,lat) for always_xy
            if src_geo:
                x_out, y_out = transform_point(transformer, y_in, x_in)
            else:
                x_out, y_out = transformer.transform(x_in, y_in)
            row = (i, f"{x_in}", f"{y_in}",
                   f"{z_in}" if z_in is not None else "",
                   f"{x_out:.6f}", f"{y_out:.6f}",
                   f"{z_in}" if z_in is not None else "")
            quick_result_rows.append(row)
            tree_quick.insert("", "end", values=row)

        status_var.set(f"Quick Transform: {len(quick_result_rows)} points transformed.")
        notebook.select(frm_tab_quick)

    def on_quick_copy():
        if not quick_result_rows:
            return
        lines = []
        for row in quick_result_rows:
            # Copy: X_out, Y_out, Z
            parts = [row[4], row[5]]
            if row[6]:
                parts.append(row[6])
            lines.append("\t".join(parts))
        root.clipboard_clear()
        root.clipboard_append("\n".join(lines))
        status_var.set(f"Copied {len(quick_result_rows)} transformed points to clipboard.")

    def on_quick_export():
        if not quick_result_rows:
            messagebox.showerror("Error", "No transformed data to export.")
            return
        filepath = filedialog.asksaveasfilename(
            title="Export Quick Transform Results",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile="quick_transform.csv"
        )
        if not filepath:
            return
        try:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["#", "Src_X", "Src_Y", "Src_Z", "Dst_X", "Dst_Y", "Dst_Z"])
                for row in quick_result_rows:
                    writer.writerow(row)
            messagebox.showinfo("Exported", f"Saved to:\n{filepath}")
            status_var.set(f"Quick Transform exported to {filepath}")
        except Exception as e:
            messagebox.showerror("Error", f"Export failed:\n{e}")

    # ── Row 4: Notebook with Input Preview / Output / Quick Transform ────
    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=8, pady=(4, 4))

    # Input preview tab
    frm_tab_input = ttk.Frame(notebook)
    notebook.add(frm_tab_input, text="Input Preview")

    input_cols = ("Photo Name", "Latitude", "Longitude", "Altitude", "Yaw", "Pitch", "Roll")
    tree_input = ttk.Treeview(frm_tab_input, columns=input_cols, show="headings", height=12)
    for col in input_cols:
        tree_input.heading(col, text=col)
        tree_input.column(col, width=110, anchor="center")
    tree_input.column("Photo Name", width=200, anchor="w")

    sb_input_y = ttk.Scrollbar(frm_tab_input, orient="vertical", command=tree_input.yview)
    sb_input_x = ttk.Scrollbar(frm_tab_input, orient="horizontal", command=tree_input.xview)
    tree_input.configure(yscrollcommand=sb_input_y.set, xscrollcommand=sb_input_x.set)

    tree_input.grid(row=0, column=0, sticky="nsew")
    sb_input_y.grid(row=0, column=1, sticky="ns")
    sb_input_x.grid(row=1, column=0, sticky="ew")
    frm_tab_input.rowconfigure(0, weight=1)
    frm_tab_input.columnconfigure(0, weight=1)

    # Output tab
    frm_tab_output = ttk.Frame(notebook)
    notebook.add(frm_tab_output, text="Transformed Output")

    output_cols = tuple(POS_OUTPUT_COLUMNS)
    tree_output = ttk.Treeview(frm_tab_output, columns=output_cols, show="headings", height=12)
    for col in output_cols:
        tree_output.heading(col, text=col)
        tree_output.column(col, width=110, anchor="center")
    tree_output.column("Photo Name", width=200, anchor="w")

    sb_output_y = ttk.Scrollbar(frm_tab_output, orient="vertical", command=tree_output.yview)
    sb_output_x = ttk.Scrollbar(frm_tab_output, orient="horizontal", command=tree_output.xview)
    tree_output.configure(yscrollcommand=sb_output_y.set, xscrollcommand=sb_output_x.set)

    tree_output.grid(row=0, column=0, sticky="nsew")
    sb_output_y.grid(row=0, column=1, sticky="ns")
    sb_output_x.grid(row=1, column=0, sticky="ew")
    frm_tab_output.rowconfigure(0, weight=1)
    frm_tab_output.columnconfigure(0, weight=1)

    # Quick Transform tab
    frm_tab_quick = ttk.Frame(notebook)
    notebook.add(frm_tab_quick, text="Quick Transform")

    # Top pane: input text + buttons
    frm_quick_top = ttk.Frame(frm_tab_quick)
    frm_quick_top.pack(fill="x", padx=4, pady=4)

    ttk.Label(frm_quick_top, text="Paste coordinates (one per line: X Y [Z]  or  X,Y[,Z]):").pack(
        anchor="w", padx=4
    )

    quick_input_frame = ttk.Frame(frm_quick_top)
    quick_input_frame.pack(fill="x", padx=4, pady=2)

    quick_input_text = tk.Text(quick_input_frame, width=60, height=6, font=("Consolas", 10))
    quick_input_text.pack(side="left", fill="x", expand=True)

    quick_input_sb = ttk.Scrollbar(quick_input_frame, orient="vertical", command=quick_input_text.yview)
    quick_input_text.configure(yscrollcommand=quick_input_sb.set)
    quick_input_sb.pack(side="right", fill="y")

    frm_quick_btns = ttk.Frame(frm_quick_top)
    frm_quick_btns.pack(fill="x", padx=4, pady=4)

    ttk.Button(frm_quick_btns, text="Transform", command=on_quick_transform).pack(side="left", padx=4)
    ttk.Button(frm_quick_btns, text="Copy Results", command=on_quick_copy).pack(side="left", padx=4)
    ttk.Button(frm_quick_btns, text="Export CSV...", command=on_quick_export).pack(side="left", padx=4)

    ttk.Label(frm_quick_btns,
              text="Uses the Source/Target CRS selected above. For geographic CRS, paste Lat Lon.",
              foreground="#666666").pack(side="left", padx=12)

    # Bottom pane: results table
    quick_cols = ("#", "Src_X", "Src_Y", "Src_Z", "Dst_X", "Dst_Y", "Dst_Z")
    tree_quick = ttk.Treeview(frm_tab_quick, columns=quick_cols, show="headings", height=10)
    for col in quick_cols:
        tree_quick.heading(col, text=col)
        tree_quick.column(col, width=130, anchor="center")
    tree_quick.column("#", width=50, anchor="center")

    sb_quick_y = ttk.Scrollbar(frm_tab_quick, orient="vertical", command=tree_quick.yview)
    sb_quick_x = ttk.Scrollbar(frm_tab_quick, orient="horizontal", command=tree_quick.xview)
    tree_quick.configure(yscrollcommand=sb_quick_y.set, xscrollcommand=sb_quick_x.set)

    tree_quick.pack(fill="both", expand=True, side="left", padx=(4, 0), pady=(0, 4))
    sb_quick_y.pack(fill="y", side="right", pady=(0, 4))

    # ── Status Bar ───────────────────────────────────────────────────────
    ttk.Label(root, textvariable=status_var, relief="sunken", anchor="w").pack(
        fill="x", side="bottom", padx=8, pady=(0, 4)
    )

    # Populate transformation parameters on startup
    update_transform_params()

    root.mainloop()


# ── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_gui()
