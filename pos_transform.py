import csv
import json
import math
import os
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk
from pyproj import Transformer, CRS
from pyproj.database import query_crs_info
from pyproj.enums import PJType

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

def compute_pole_vertical_offset(height, radius=0.0, mode="vertical"):
    """
    Vertical distance (m) from ground mark to GNSS receiver.

    Vertical mode: height is used as-is (user-entered total vertical distance).
    Slant mode:    height is the slant distance and radius is the receiver's
                   horizontal radius; returns sqrt(height² - radius²).
    """
    if mode == "slant":
        if height <= radius:
            raise ValueError("Slant height must be greater than the receiver radius.")
        return math.sqrt(height ** 2 - radius ** 2)
    else:
        return height


def compute_gcp_delta(gcp_src_easting, gcp_src_northing, gcp_src_elev,
                       gcp_tgt_easting, gcp_tgt_northing, gcp_tgt_elev,
                       rod_height=0.0, radius=0.0, rod_mode="vertical"):
    """
    Translation delta from a single GCP pair (projected coords).

    The pole vertical offset is subtracted from the source elevation to bring
    it down to the ground mark before differencing against the known target.

        ground_source_elev = gcp_src_elev - height                   [vertical mode]
        ground_source_elev = gcp_src_elev - sqrt(slant² - radius²)   [slant mode]

    Returns (dE, dN, dZ).
    """
    pole_vertical = compute_pole_vertical_offset(rod_height, radius, rod_mode) \
        if (rod_height or radius) else 0.0

    dE = gcp_tgt_easting - gcp_src_easting
    dN = gcp_tgt_northing - gcp_src_northing
    dZ = gcp_tgt_elev - (gcp_src_elev - pole_vertical)
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
            "Easting": f"{easting:.10f}",
            "Northing": f"{northing:.10f}",
            "Elevation": f"{elevation:.10f}",
            "Yaw": row["Yaw"],
            "Pitch": row["Pitch"],
            "Roll": row["Roll"],
            "Horizontal Accuracy": row["Horizontal Accuracy"],
            "Vertical Accuracy": row["Vertical Accuracy"],
        })
    return results


# ── Settings Persistence ────────────────────────────────────────────────────

SETTINGS_PATH = os.path.join(
    os.path.expanduser("~"), ".dji_terra_pos_transform", "settings.json"
)

DEFAULT_SETTINGS = {
    "src_crs": "WGS 84 (EPSG:4326)",
    "dst_crs": "PRS 92 Zone 3 (EPSG:3123)",
    "rod_height": "1.83915",
    "rod_mode": "vertical",
    "radius": "",
}


def load_settings():
    """Read saved user preferences. Falls back to defaults on any failure."""
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {**DEFAULT_SETTINGS, **data}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return dict(DEFAULT_SETTINGS)


def save_settings(settings):
    """Persist user preferences. Silently ignores write failures."""
    try:
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except OSError:
        pass


# ── GUI ──────────────────────────────────────────────────────────────────────

class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, _event=None):
        if self.tip_window:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        ttk.Label(tw, text=self.text, background="#ffffe0",
                  relief="solid", borderwidth=1,
                  font=("Segoe UI", 9)).pack(ipadx=6, ipady=3)

    def hide(self, _event=None):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None


def run_gui():
    pos_rows = []       # raw input rows
    result_rows = []    # transformed output rows
    delta_vals = [0.0, 0.0, 0.0]  # dE, dN, dZ
    settings = load_settings()

    # ── Helpers ──────────────────────────────────────────────────────────

    def get_epsg(combo):
        """Resolve EPSG code from combo value (preset name or raw EPSG code)."""
        val = combo.get().strip()
        # If it matches a preset name, return the mapped EPSG code
        if val in CRS_PRESETS:
            return CRS_PRESETS[val]
        # Otherwise treat the raw value as an EPSG code
        return val

    def open_crs_browser(combo, label_var):
        """Pop a searchable CRS picker that queries the pyproj database."""
        win = tk.Toplevel(root)
        win.title("Browse Coordinate Reference Systems")
        win.geometry("720x520")
        win.transient(root)

        ttk.Label(win, text="Search (name, authority, area, or EPSG code):").pack(
            anchor="w", padx=8, pady=(8, 2)
        )
        search_var = tk.StringVar()
        entry = ttk.Entry(win, textvariable=search_var)
        entry.pack(fill="x", padx=8, pady=(0, 4))

        type_var = tk.StringVar(value="All")
        type_frame = ttk.Frame(win)
        type_frame.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Label(type_frame, text="Type:").pack(side="left")
        for t in ("All", "Geographic", "Projected"):
            ttk.Radiobutton(type_frame, text=t, value=t, variable=type_var,
                            command=lambda: refresh()).pack(side="left", padx=4)

        cols = ("EPSG", "Name", "Type", "Area")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=18)
        tree.heading("EPSG", text="EPSG")
        tree.heading("Name", text="Name")
        tree.heading("Type", text="Type")
        tree.heading("Area", text="Area of Use")
        tree.column("EPSG", width=80, anchor="center")
        tree.column("Name", width=300, anchor="w")
        tree.column("Type", width=90, anchor="center")
        tree.column("Area", width=220, anchor="w")

        sb = ttk.Scrollbar(win, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=4)
        sb.pack(side="left", fill="y", padx=(0, 8), pady=4)

        # Cache the full EPSG list once — querying is somewhat slow
        cache = {"geographic": None, "projected": None}

        def get_list(which):
            if cache[which] is not None:
                return cache[which]
            pj_type = PJType.GEOGRAPHIC_2D_CRS if which == "geographic" else PJType.PROJECTED_CRS
            try:
                infos = query_crs_info(auth_name="EPSG", pj_types=pj_type)
            except Exception:
                infos = []
            cache[which] = infos
            return infos

        def refresh(*_):
            q = search_var.get().strip().lower()
            t = type_var.get()
            tree.delete(*tree.get_children())
            items = []
            if t in ("All", "Geographic"):
                items += [(i, "Geographic") for i in get_list("geographic")]
            if t in ("All", "Projected"):
                items += [(i, "Projected") for i in get_list("projected")]
            count = 0
            for info, kind in items:
                code = info.code
                name = info.name
                area = (info.area_of_use.name if info.area_of_use else "")
                if q:
                    haystack = f"{code} {name} {area}".lower()
                    if q not in haystack:
                        continue
                tree.insert("", "end", values=(code, name, kind, area))
                count += 1
                if count >= 500:  # cap UI rows
                    break
            win.title(f"Browse Coordinate Reference Systems  —  {count} match(es)"
                     + (" (showing first 500)" if count >= 500 else ""))

        search_var.trace_add("write", lambda *_: refresh())

        def select_and_close(*_):
            sel = tree.selection()
            if not sel:
                return
            vals = tree.item(sel[0], "values")
            epsg = vals[0]
            combo.set(str(epsg))
            on_crs_input(combo, label_var)
            win.destroy()

        ttk.Button(win, text="Select", command=select_and_close).pack(
            side="bottom", pady=(0, 8)
        )
        tree.bind("<Double-1>", select_and_close)
        entry.focus_set()
        refresh()

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

    def on_compute_delta(*_args):
        src_epsg = get_epsg(src_combo)
        dst_epsg = get_epsg(dst_combo)
        if not src_epsg or not dst_epsg:
            return
        try:
            gcp_src_e = float(gcp_src_e_entry.get())
            gcp_src_n = float(gcp_src_n_entry.get())
            gcp_src_elev = float(gcp_src_elev_entry.get())
            gcp_tgt_e = float(gcp_tgt_e_entry.get())
            gcp_tgt_n = float(gcp_tgt_n_entry.get())
            gcp_tgt_elev = float(gcp_tgt_elev_entry.get())
        except ValueError:
            # Not all fields valid yet — silently skip auto-compute
            delta_e_var.set("")
            delta_n_var.set("")
            delta_z_var.set("")
            return

        try:
            rod = float(rod_height_var.get() or 0)
            radius = float(radius_var.get() or 0)
        except ValueError:
            rod, radius = 0.0, 0.0
        mode = rod_mode_var.get() or "vertical"

        if mode == "slant" and radius <= 0:
            delta_e_var.set("")
            delta_n_var.set("")
            delta_z_var.set("")
            return

        try:
            dE, dN, dZ = compute_gcp_delta(
                gcp_src_e, gcp_src_n, gcp_src_elev,
                gcp_tgt_e, gcp_tgt_n, gcp_tgt_elev,
                rod_height=rod, radius=radius, rod_mode=mode
            )
        except Exception as e:
            status_var.set(f"Delta computation error: {e}")
            return

        delta_vals[0], delta_vals[1], delta_vals[2] = dE, dN, dZ
        delta_e_var.set(f"{dE:.10f}")
        delta_n_var.set(f"{dN:.10f}")
        delta_z_var.set(f"{dZ:.10f}")
        try:
            pole = compute_pole_vertical_offset(rod, radius, mode) if (rod or radius) else 0.0
            status_var.set(
                f"Delta auto-computed: dE={dE:.4f}  dN={dN:.4f}  dZ={dZ:.4f}  "
                f"(vertical offset = {pole:.4f} m, mode={mode})"
            )
        except Exception:
            status_var.set(f"Delta auto-computed: dE={dE:.4f}  dN={dN:.4f}  dZ={dZ:.4f}")

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
        messagebox.showinfo(
            "Transformation Successful",
            f"Successfully transformed {len(result_rows)} photo positions.\n\n"
            f"Source CRS: EPSG:{src_epsg}\n"
            f"Target CRS: EPSG:{dst_epsg}\n\n"
            f"GCP Delta applied:\n"
            f"  dE = {delta_vals[0]:.4f} m\n"
            f"  dN = {delta_vals[1]:.4f} m\n"
            f"  dZ = {delta_vals[2]:.4f} m\n\n"
            f"Switch to the 'Transformed Output' tab to review,\n"
            f"then click 'Export CSV...' to save."
        )

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
    rod_height_var = tk.StringVar(value=settings["rod_height"])
    radius_var = tk.StringVar(value=settings["radius"])
    rod_mode_var = tk.StringVar(value=settings["rod_mode"])
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
    src_crs_name_var = tk.StringVar()
    dst_crs_name_var = tk.StringVar()

    # Source CRS
    ttk.Label(frm_crs, text="Source CRS:").grid(row=0, column=0, sticky="e", **PAD)
    src_combo = ttk.Combobox(frm_crs, values=preset_names, width=30)
    src_combo.set(settings["src_crs"])
    src_combo.grid(row=0, column=1, sticky="w", **PAD)
    ttk.Button(frm_crs, text="…", width=3,
               command=lambda: open_crs_browser(src_combo, src_crs_name_var)).grid(
        row=0, column=2, sticky="w", padx=(0, 6))
    ttk.Label(frm_crs, textvariable=src_crs_name_var, foreground="#006600").grid(
        row=0, column=3, columnspan=2, sticky="w", **PAD
    )

    # Target CRS
    ttk.Label(frm_crs, text="Target CRS:").grid(row=1, column=0, sticky="e", **PAD)
    dst_combo = ttk.Combobox(frm_crs, values=preset_names, width=30)
    dst_combo.set(settings["dst_crs"])
    dst_combo.grid(row=1, column=1, sticky="w", **PAD)
    ttk.Button(frm_crs, text="…", width=3,
               command=lambda: open_crs_browser(dst_combo, dst_crs_name_var)).grid(
        row=1, column=2, sticky="w", padx=(0, 6))
    ttk.Label(frm_crs, textvariable=dst_crs_name_var, foreground="#006600").grid(
        row=1, column=3, columnspan=2, sticky="w", **PAD
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
    ttk.Label(frm_gcp, text="Easting:").grid(row=1, column=0, sticky="e", **PAD)
    gcp_src_e_entry = ttk.Entry(frm_gcp, width=18)
    gcp_src_e_entry.grid(row=1, column=1, sticky="w", **PAD)
    ttk.Label(frm_gcp, text="Northing:").grid(row=1, column=2, sticky="e", **PAD)
    gcp_src_n_entry = ttk.Entry(frm_gcp, width=18)
    gcp_src_n_entry.grid(row=1, column=3, sticky="w", **PAD)
    ttk.Label(frm_gcp, text="Elevation:").grid(row=1, column=4, sticky="e", **PAD)
    gcp_src_elev_entry = ttk.Entry(frm_gcp, width=18)
    gcp_src_elev_entry.grid(row=1, column=5, sticky="w", **PAD)

    # GCP Target
    gcp_tgt_lbl = ttk.Label(frm_gcp, text="GCP Target (ground coordinates)  ℹ")
    gcp_tgt_lbl.grid(row=2, column=0, columnspan=6, sticky="w", **PAD)
    ToolTip(gcp_tgt_lbl,
            "Enter the known ground-level coordinates (e.g. from a benchmark or control point).\n"
            "The vertical offset (from your height entry and chosen mode) will be subtracted\n"
            "from the GCP Source elevation to bring it down to ground level before computing the delta.")
    ttk.Label(frm_gcp, text="Easting:").grid(row=3, column=0, sticky="e", **PAD)
    gcp_tgt_e_entry = ttk.Entry(frm_gcp, width=18)
    gcp_tgt_e_entry.grid(row=3, column=1, sticky="w", **PAD)
    ttk.Label(frm_gcp, text="Northing:").grid(row=3, column=2, sticky="e", **PAD)
    gcp_tgt_n_entry = ttk.Entry(frm_gcp, width=18)
    gcp_tgt_n_entry.grid(row=3, column=3, sticky="w", **PAD)
    ttk.Label(frm_gcp, text="Elevation:").grid(row=3, column=4, sticky="e", **PAD)
    gcp_tgt_elev_entry = ttk.Entry(frm_gcp, width=18)
    gcp_tgt_elev_entry.grid(row=3, column=5, sticky="w", **PAD)

    # Height input + mode radio. Receiver radius input is shown only in slant mode.
    rod_height_label_var = tk.StringVar(value="Vertical Height:")
    ttk.Label(frm_gcp, textvariable=rod_height_label_var).grid(row=4, column=0, sticky="e", **PAD)
    rod_height_entry = ttk.Entry(frm_gcp, width=18, textvariable=rod_height_var)
    rod_height_entry.grid(row=4, column=1, sticky="w", **PAD)

    rod_mode_frame = ttk.Frame(frm_gcp)
    rod_mode_frame.grid(row=4, column=2, columnspan=2, sticky="w", **PAD)

    radius_label = ttk.Label(frm_gcp, text="Receiver Radius:")
    radius_entry = ttk.Entry(frm_gcp, width=18, textvariable=radius_var)
    radius_label.grid(row=4, column=4, sticky="e", **PAD)
    radius_entry.grid(row=4, column=5, sticky="w", **PAD)
    radius_label.grid_remove()
    radius_entry.grid_remove()

    def on_mode_change():
        if rod_mode_var.get() == "slant":
            rod_height_label_var.set("Slant Height:")
            radius_label.grid()
            radius_entry.grid()
        else:
            rod_height_label_var.set("Vertical Height:")
            radius_label.grid_remove()
            radius_entry.grid_remove()
        on_compute_delta()

    ttk.Radiobutton(rod_mode_frame, text="Vertical", value="vertical",
                    variable=rod_mode_var,
                    command=on_mode_change).pack(side="left")
    ttk.Radiobutton(rod_mode_frame, text="Slant", value="slant",
                    variable=rod_mode_var,
                    command=on_mode_change).pack(side="left", padx=(6, 0))

    # Delta display (auto-computed)
    ttk.Label(frm_gcp, text="Delta (auto):",
              font=("Segoe UI", 9, "bold")).grid(row=5, column=0, sticky="e", **PAD)
    ttk.Label(frm_gcp, text="dE:").grid(row=5, column=2, sticky="e", **PAD)
    ttk.Entry(frm_gcp, textvariable=delta_e_var, width=22, state="readonly").grid(
        row=5, column=3, sticky="w", **PAD
    )
    ttk.Label(frm_gcp, text="dN:").grid(row=6, column=2, sticky="e", **PAD)
    ttk.Entry(frm_gcp, textvariable=delta_n_var, width=22, state="readonly").grid(
        row=6, column=3, sticky="w", **PAD
    )
    ttk.Label(frm_gcp, text="dZ:").grid(row=5, column=4, sticky="e", **PAD)
    ttk.Entry(frm_gcp, textvariable=delta_z_var, width=22, state="readonly").grid(
        row=5, column=5, sticky="w", **PAD
    )

    # Wire auto-compute on every keystroke in any GCP / height / radius field
    for _entry in (gcp_src_n_entry, gcp_src_e_entry, gcp_src_elev_entry,
                   gcp_tgt_n_entry, gcp_tgt_e_entry, gcp_tgt_elev_entry,
                   rod_height_entry, radius_entry):
        _entry.bind("<KeyRelease>", on_compute_delta)
        _entry.bind("<FocusOut>", on_compute_delta)

    # Excel paste: pasting tab-separated E/N/Z into any field fills all three
    def make_gcp_paste_handler(e_ent, n_ent, z_ent):
        def handler(_event):
            try:
                clip = root.clipboard_get()
            except tk.TclError:
                return
            clip = clip.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n").strip()
            parts = [p.strip() for p in clip.replace(",", "\t").split("\t") if p.strip()]
            if len(parts) >= 3:
                for ent, val in zip((e_ent, n_ent, z_ent), parts[:3]):
                    ent.delete(0, "end")
                    ent.insert(0, val)
                on_compute_delta()
                return "break"
        return handler

    for _e, _n, _z in (
        (gcp_src_e_entry, gcp_src_n_entry, gcp_src_elev_entry),
        (gcp_tgt_e_entry, gcp_tgt_n_entry, gcp_tgt_elev_entry),
    ):
        _h = make_gcp_paste_handler(_e, _n, _z)
        for _ent in (_e, _n, _z):
            _ent.bind("<Control-v>", _h)
            _ent.bind("<Control-V>", _h)

    # ── Row 3: Action Buttons ────────────────────────────────────────────
    frm_actions = ttk.Frame(root, padding=4)
    frm_actions.pack(fill="x", padx=8, pady=4)

    ttk.Button(frm_actions, text="Transform", command=on_transform).pack(side="left", padx=8)
    ttk.Button(frm_actions, text="Export CSV...", command=on_export).pack(side="left", padx=8)

    # ── Quick Transform helpers ──────────────────────────────────────────

    quick_result_rows = []  # list of tuples for quick transform output

    def parse_coordinates(text):
        """Parse pasted coordinate text. Accepts lines of X Y [Z] or X,Y[,Z].
        Handles Excel paste (tab-separated, \\r\\n line endings, null bytes).
        Returns list of tuples: (x, y) or (x, y, z)."""
        # Clean up Excel/Windows clipboard artifacts
        text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
        coords = []
        for line in text.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            # Split on comma, tab, or whitespace
            parts = line.replace(",", " ").replace("\t", " ").split()
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
                   f"{x_out:.10f}", f"{y_out:.10f}",
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
            # Copy: Easting, Northing, Elevation
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
                writer.writerow(["#", "Src_1", "Src_2", "Src_Z", "Easting", "Northing", "Elevation"])
                for row in quick_result_rows:
                    writer.writerow(row)
            messagebox.showinfo("Exported", f"Saved to:\n{filepath}")
            status_var.set(f"Quick Transform exported to {filepath}")
        except Exception as e:
            messagebox.showerror("Error", f"Export failed:\n{e}")

    # ── Row 4: Notebook with Input Preview / Output / Quick Transform ────
    style = ttk.Style()
    style.configure("Main.TNotebook.Tab", font=("Segoe UI", 11, "bold"), padding=[14, 6])

    notebook = ttk.Notebook(root, style="Main.TNotebook")
    notebook.pack(fill="both", expand=True, padx=8, pady=(4, 4))

    # Input preview tab
    frm_tab_input = ttk.Frame(notebook)
    notebook.add(frm_tab_input, text="  \U0001F4C4  Input Preview  ")

    ttk.Label(frm_tab_input,
              text="Browse a DJI Terra POS CSV above. The loaded photo positions are shown here.",
              foreground="#555555", font=("Segoe UI", 9)).grid(
        row=0, column=0, sticky="w", padx=6, pady=(4, 2))

    input_cols = ("Photo Name", "Latitude", "Longitude", "Altitude", "Yaw", "Pitch", "Roll")
    tree_input = ttk.Treeview(frm_tab_input, columns=input_cols, show="headings", height=11)
    for col in input_cols:
        tree_input.heading(col, text=col)
        tree_input.column(col, width=110, anchor="center")
    tree_input.column("Photo Name", width=200, anchor="w")

    sb_input_y = ttk.Scrollbar(frm_tab_input, orient="vertical", command=tree_input.yview)
    sb_input_x = ttk.Scrollbar(frm_tab_input, orient="horizontal", command=tree_input.xview)
    tree_input.configure(yscrollcommand=sb_input_y.set, xscrollcommand=sb_input_x.set)

    tree_input.grid(row=1, column=0, sticky="nsew")
    sb_input_y.grid(row=1, column=1, sticky="ns")
    sb_input_x.grid(row=2, column=0, sticky="ew")
    frm_tab_input.rowconfigure(1, weight=1)
    frm_tab_input.columnconfigure(0, weight=1)

    # Output tab
    frm_tab_output = ttk.Frame(notebook)
    notebook.add(frm_tab_output, text="  \U0001F504  Transformed Output  ")

    ttk.Label(frm_tab_output,
              text="Click Transform to project all photo positions. Use Export CSV to save results.",
              foreground="#555555", font=("Segoe UI", 9)).grid(
        row=0, column=0, sticky="w", padx=6, pady=(4, 2))

    output_cols = tuple(POS_OUTPUT_COLUMNS)
    tree_output = ttk.Treeview(frm_tab_output, columns=output_cols, show="headings", height=11)
    for col in output_cols:
        tree_output.heading(col, text=col)
        tree_output.column(col, width=110, anchor="center")
    tree_output.column("Photo Name", width=200, anchor="w")

    sb_output_y = ttk.Scrollbar(frm_tab_output, orient="vertical", command=tree_output.yview)
    sb_output_x = ttk.Scrollbar(frm_tab_output, orient="horizontal", command=tree_output.xview)
    tree_output.configure(yscrollcommand=sb_output_y.set, xscrollcommand=sb_output_x.set)

    tree_output.grid(row=1, column=0, sticky="nsew")
    sb_output_y.grid(row=1, column=1, sticky="ns")
    sb_output_x.grid(row=2, column=0, sticky="ew")
    frm_tab_output.rowconfigure(1, weight=1)
    frm_tab_output.columnconfigure(0, weight=1)

    # Quick Transform tab
    frm_tab_quick = ttk.Frame(notebook)
    notebook.add(frm_tab_quick, text="  \u26A1  Quick Transform  ")

    # Top pane: input text + buttons
    frm_quick_top = ttk.Frame(frm_tab_quick)
    frm_quick_top.pack(fill="x", padx=4, pady=4)

    ttk.Label(frm_quick_top,
              text="Paste coordinates below (one point per line). Accepts: Lat Lon  |  X Y  |  X Y Z  |  comma or tab separated.  Supports Excel paste.",
              foreground="#555555", font=("Segoe UI", 9)).pack(anchor="w", padx=4, pady=(0, 4))

    quick_input_frame = ttk.Frame(frm_quick_top)
    quick_input_frame.pack(fill="x", padx=4, pady=2)

    quick_input_text = tk.Text(quick_input_frame, width=60, height=6, font=("Consolas", 10))
    quick_input_text.pack(side="left", fill="x", expand=True)

    def on_paste(event):
        """Handle Ctrl+V paste — clean clipboard data (Excel uses \\r\\n and trailing nulls)."""
        try:
            clipboard = root.clipboard_get()
        except tk.TclError:
            return
        # Clean: strip null bytes and normalize line endings
        clipboard = clipboard.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
        # Insert cleaned text at cursor
        quick_input_text.insert("insert", clipboard)
        return "break"  # prevent default paste

    quick_input_text.bind("<Control-v>", on_paste)
    quick_input_text.bind("<Control-V>", on_paste)

    quick_input_sb = ttk.Scrollbar(quick_input_frame, orient="vertical", command=quick_input_text.yview)
    quick_input_text.configure(yscrollcommand=quick_input_sb.set)
    quick_input_sb.pack(side="right", fill="y")

    frm_quick_btns = ttk.Frame(frm_quick_top)
    frm_quick_btns.pack(fill="x", padx=4, pady=4)

    ttk.Button(frm_quick_btns, text="Transform", command=on_quick_transform).pack(side="left", padx=4)
    ttk.Button(frm_quick_btns, text="Copy Results", command=on_quick_copy).pack(side="left", padx=4)
    ttk.Button(frm_quick_btns, text="Export CSV...", command=on_quick_export).pack(side="left", padx=4)

    ttk.Label(frm_quick_btns,
              text="\u2190 Uses the Source / Target CRS selected above",
              foreground="#888888", font=("Segoe UI", 9)).pack(side="left", padx=12)

    # Bottom pane: results table
    quick_cols = ("#", "Src_1", "Src_2", "Src_Z", "Easting", "Northing", "Elevation")
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

    # Apply loaded settings: refresh CRS labels, show/hide radius field
    on_crs_input(src_combo, src_crs_name_var)
    on_crs_input(dst_combo, dst_crs_name_var)
    on_mode_change()
    update_transform_params()

    def on_close():
        save_settings({
            "src_crs": src_combo.get(),
            "dst_crs": dst_combo.get(),
            "rod_height": rod_height_var.get(),
            "rod_mode": rod_mode_var.get(),
            "radius": radius_var.get(),
        })
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    root.mainloop()


# ── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_gui()
