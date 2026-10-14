import subprocess
from datetime import datetime
from pathlib import Path

print("Infrastructure Drift Detection System")
print("-------------------------------------")

result = subprocess.run(
    ["terraform", "plan", "-detailed-exitcode", "-no-color"],
    capture_output=True,
    text=True
)

if result.returncode == 0:
    print("STATUS: No infrastructure drift detected.")

elif result.returncode == 2:
    print("STATUS: Infrastructure drift detected!")

    report_dir = Path("reports")
    report_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    report_file = report_dir / f"drift_report_{timestamp}.txt"

    with open(report_file, "w", encoding="utf-8") as file:
        file.write("INFRASTRUCTURE DRIFT REPORT\n")
        file.write("===========================\n")
        file.write(f"Generated: {datetime.now()}\n\n")
        file.write(result.stdout)

    print(f"Drift report saved to: {report_file}")

else:
    print("STATUS: Error while checking infrastructure.")
    print(result.stderr)