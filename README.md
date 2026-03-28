# DJI Terra POS Transformation & Generic Coordinate Transformer

Transform Position and Orientation System (POS) data from DJI Terra aerial imagery — or any coordinates — from one coordinate system to another.

## What It Does

This tool works in two modes:

### POS Transform Mode
DJI Terra exports a POS CSV with each photo's geographic position (WGS 84 latitude/longitude) and orientation. This tool:

1. **Transforms coordinates** from a source CRS (e.g. WGS 84) to a target projected CRS (e.g. PRS 92 Zone 1–5) using [pyproj](https://pyproj4.github.io/pyproj/).
2. **Applies a GCP delta shift** — given a Ground Control Point with known source and target coordinates, computes the translation offset (dEasting, dNorthing, dElevation) and applies it to every photo position.
3. **Exports a transformed POS CSV** ready to be imported back into DJI Terra or other photogrammetry software.

### Quick Transform Mode
A generic coordinate transformer for any source/target EPSG pair:

1. **Paste coordinates** directly into the text area — one point per line (Lat Lon, X Y, or X Y Z).
2. **Transform** — instantly converts all points using the selected CRS pair.
3. **Copy** results to clipboard or **Export** to CSV.

## Input Format

Standard DJI Terra POS CSV:

```
Photo Name,Latitude,Longitude,Altitude,Yaw,Pitch,Roll,Horizontal Accuracy,Vertical Accuracy
DJI_0001.JPG,14.65943879,121.0099266,85.200,-45.3,-90.0,0.5,1.5,2.0
```

## Output Format

Transformed POS CSV with projected coordinates:

```
Photo Name,Easting,Northing,Elevation,Yaw,Pitch,Roll,Horizontal Accuracy,Vertical Accuracy
DJI_0001.JPG,500932.9650,1621298.6511,87.2000,-45.3,-90.0,0.5,1.5,2.0
```

## Supported Coordinate Systems

Any coordinate system with an EPSG code is supported. Select from the built-in presets or type any EPSG code directly into the combo box.

### Built-in Presets

| CRS | EPSG | Type |
|-----|------|------|
| WGS 84 | 4326 | Geographic (Lat/Lon) |
| PRS 92 Zone 1 | 3121 | Projected (meters) |
| PRS 92 Zone 2 | 3122 | Projected (meters) |
| PRS 92 Zone 3 | 3123 | Projected (meters) |
| PRS 92 Zone 4 | 3124 | Projected (meters) |
| PRS 92 Zone 5 | 3125 | Projected (meters) |

**Default:** WGS 84 (4326) → PRS 92 Zone 3 (3123)

You can type any valid EPSG code (e.g. `32651` for UTM Zone 51N) directly into the Source or Target CRS field.

## GCP Delta Translation

The delta shift corrects for systematic offsets between the drone's GPS positions and surveyed ground control.

1. Enter the **GCP Source** coordinates (Northing, Easting, Elevation) — the transformed position of a known ground control point from the POS data.
2. Enter the **GCP Target** coordinates (Northing, Easting, Elevation) — the surveyed/known position of that same point.
3. Click **Compute Delta** — the tool calculates:
   - `dE = Target Easting − Source Easting`
   - `dN = Target Northing − Source Northing`
   - `dZ = Target Elevation − Source Elevation`
4. Click **Transform** — the delta is applied to every photo's projected coordinates.

## Installation

### Requirements

- Python 3.8+
- pyproj

```bash
pip install pyproj
```

### Run

```bash
python pos_transform.py
```

This opens the Tkinter GUI.

### Build Executable

To create a standalone `.exe` (no Python installation required on the target machine):

```bash
pip install pyinstaller
python build.py
```

The executable will be created at `dist/DJITerraPOSTransformation.exe`.

## Usage

### POS Transform

1. **Browse** — Select your DJI Terra POS CSV file.
2. **Select CRS** — Choose source (e.g. WGS 84) and target (e.g. PRS 92 Zone 3) from the dropdown presets, or type any EPSG code directly.
3. **Enter GCP** *(optional)* — Fill in the GCP Source and Target coordinates, then click **Compute Delta** to see the offset values.
4. **Transform** — Click to project all photo positions and apply the delta shift.
5. **Export CSV** — Save the transformed POS file.

### Quick Transform

1. **Select CRS** — Set your source and target CRS using the dropdowns or type any EPSG code.
2. **Switch to the Quick Transform tab** in the bottom panel.
3. **Paste coordinates** into the text area — one point per line:
   - `14.6594 121.0099` (Lat Lon for geographic CRS)
   - `500000.00 1600000.00` (Easting Northing for projected CRS)
   - `14.6594 121.0099 85.2` (with elevation)
   - Comma-separated: `14.6594,121.0099,85.2`
4. **Transform** — Results appear in the table below.
5. **Copy Results** — Copies transformed coordinates to clipboard (tab-separated).
6. **Export CSV** — Saves full input→output table as CSV.

## Project Structure

```
├── pos_transform.py    # Main application (GUI + transformation engine)
├── build.py            # Build script to create standalone .exe
├── sample_pos.csv      # Sample DJI Terra POS input file
├── test_transform.py   # Test script for verifying transformations
├── requirements.txt    # Python dependencies
├── LICENSE             # MIT License
└── README.md           # This file
```

## License

MIT License — see [LICENSE](LICENSE) for details.
