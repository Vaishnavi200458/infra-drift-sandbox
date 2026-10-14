import subprocess

print("Infrastructure Drift Correction System")
print("----------------------------------------")

print("Applying Terraform desired state...")

result = subprocess.run(
    ["terraform", "apply", "-auto-approve", "-no-color"],
    capture_output=True,
    text=True
)

if result.returncode == 0:
    print("STATUS: Infrastructure successfully restored.")
else:
    print("STATUS: Failed to correct infrastructure drift.")
    print(result.stderr)