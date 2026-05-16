$ngrok = "$env:LOCALAPPDATA\ngrok-v3\ngrok.exe"
$config = "C:\Users\yurik\Code\social-media-automation\config\ngrok.yml"
$project = "C:\Users\yurik\Code\legal-suite"

Write-Output "=== Legal Suite - Ngrok Tunnel ==="
Write-Output ""

Write-Output "Starting ngrok tunnel to backend (port 8000)..."
Start-Process -NoNewWindow -FilePath $ngrok -ArgumentList "start", "legal-suite", "--config=$config"

Write-Output ""
Write-Output "Ngrok Web Interface: http://localhost:4040"
Write-Output ""

Write-Output "=== Quick Start ==="
Write-Output "1. Start legal-suite: cd $project; docker-compose up -d"
Write-Output "2. Run: .\scripts\serve_legal.ps1"
Write-Output "3. Check http://localhost:4040 for the public URL"
