"""Export a balanced synthetic cohort, including scenario labels, as CSV."""
import csv
from pathlib import Path
from htn_alert.generator import SCENARIOS, generate_cohort
from htn_alert.protocol import load_protocol
from htn_alert.rules import is_severe

def export_cohort_csv(patients_per_scenario=10, output_path='data/synthetic_bp_80_patients.csv', seed=42, *, protocol=None):
    protocol = protocol if protocol is not None else load_protocol()
    cohort = generate_cohort(patients_per_scenario=patients_per_scenario, seed=seed, protocol=protocol)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['patient_id','scenario','time','systolic','diastolic','severe'])
        total = 0
        for index,(pid, readings) in enumerate(cohort.items()):
            scenario = SCENARIOS[index//patients_per_scenario]
            for r in readings:
                writer.writerow([pid,scenario,r.time.isoformat(),r.systolic,r.diastolic,is_severe(r, protocol)])
                total+=1
    print(f'Saved: {path.resolve()}')
    print(f'Patients: {len(cohort)}; readings: {total}; scenarios: {len(SCENARIOS)}')

if __name__ == '__main__':
    export_cohort_csv()
