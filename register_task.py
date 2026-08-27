import subprocess
from pathlib import Path

task_name = "YT_Shorts_Autopilot"
vbs_path = str(Path(r"C:\Users\jisha\OneDrive\Desktop\yt automation\run_silent.vbs").resolve())
tr_cmd = f'wscript.exe "{vbs_path}"'

# 1. Remove old task if present
subprocess.run(["schtasks", "/Delete", "/TN", task_name, "/F"], capture_output=True)

# 2. Register ONLOGON task (starts every time PC boots or user logs in)
res = subprocess.run([
    "schtasks", "/Create",
    "/TN", task_name,
    "/TR", tr_cmd,
    "/SC", "ONLOGON",
    "/F"
], capture_output=True, text=True)

print("Register result:")
print(res.stdout)
if res.stderr:
    print("Stderr:", res.stderr)

# 3. Also add a Startup Folder shortcut as dual-redundancy
startup_dir = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
if startup_dir.exists():
    bat_link = startup_dir / "Start_YT_Autopilot.vbs"
    with open(bat_link, "w", encoding="utf-8") as f:
        f.write(f'Set WshShell = CreateObject("WScript.Shell")\n')
        f.write(f'WshShell.Run chr(34) & "{vbs_path}" & chr(34), 0\n')
        f.write(f'Set WshShell = Nothing\n')
    print(f"Startup folder redundancy created at: {bat_link}")

# 4. Query status
q = subprocess.run(["schtasks", "/Query", "/TN", task_name], capture_output=True, text=True)
print(q.stdout)
