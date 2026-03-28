from pos_transform import *

# Test GCP delta: source and target both in projected coords (Easting, Northing, Elevation)
dE, dN, dZ = compute_gcp_delta(500922.9650, 1621293.6511, 85.0, 500932.9650, 1621298.6511, 87.0)
print(f"Delta: dE={dE:.4f} dN={dN:.4f} dZ={dZ:.4f}")

# Test batch transform
rows = read_pos_csv('sample_pos.csv')
print(f"Read {len(rows)} rows")
results = transform_pos_data(rows, '4326', '3123', dE=dE, dN=dN, dZ=dZ)
for r in results[:3]:
    print(f"{r['Photo Name']}: E={r['Easting']} N={r['Northing']} Z={r['Elevation']}")

# Test CSV export
write_pos_csv('test_output.csv', results)
print("Exported to test_output.csv")
