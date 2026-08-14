$ErrorActionPreference = "Stop"
python -m PyInstaller --clean --noconfirm packaging/recruiting_assistant.spec
Write-Output "Built dist/RecruitingAssistant/RecruitingAssistant.exe"
