# Chạy thử toàn bộ phần PC không cần phần cứng: server + Pi giả (xe tự ra vào).
# Dùng:  powershell -ExecutionPolicy Bypass -File scripts\demo.ps1 [-Yolo | -Classifier]
param([switch]$Yolo, [switch]$Classifier)
$root = Split-Path -Parent $PSScriptRoot
$pc = Join-Path $root "pc_server"

# Pi giả vẽ xe là hình khối nên bộ nền (background) nhận diện đúng; YOLO chỉ nhận ra xe thật.
# Classifier (train trên ảnh bãi xe thật) nhận ngược trên ảnh vẽ — chỉ để so sánh.
$det = if ($Yolo) { "yolo" } elseif ($Classifier) { "classifier" } else { "background" }
$py = if (Test-Path "$pc\.venv\Scripts\python.exe") { "$pc\.venv\Scripts\python.exe" } else { "python" }
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$pc'; `$env:DETECTOR='$det'; & '$py' run.py"
Start-Sleep 6
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$pc'; & '$py' simulator/mock_pi.py --auto"
Write-Host "Server: http://localhost:8000 (máy này) + https/wss :8443 (Pi, LAN) — giao diện dev: cd pc_server\web; npm run dev -> http://localhost:5173"
Write-Host "Demo tấn công kênh Pi: cd pc_server; python tools/attack_demo.py"
Write-Host "Đăng nhập: admin / admin123"
