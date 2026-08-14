"""Windows Task Scheduler integration, kept separate from background work."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

TASK_NAME = "RecruitingAssistantBackground"


def task_xml(executable: str | None = None, *, interval_minutes: int = 30) -> str:
    command = executable or sys.executable
    arguments = (
        "background run-once"
        if command.lower().endswith((".exe", ".com"))
        else "-m quant_recruiting.cli background run-once"
    )
    return (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        "  <RegistrationInfo><Description>Local-only Recruiting Assistant background operations"
        "</Description></RegistrationInfo>\n"
        "  <Triggers><CalendarTrigger><StartBoundary>2026-01-01T00:00:00</StartBoundary>\n"
        f"    <Repetition><Interval>PT{max(15, interval_minutes)}M</Interval>"
        "<StopAtDurationEnd>false</StopAtDurationEnd></Repetition>\n"
        "    <Enabled>true</Enabled></CalendarTrigger></Triggers>\n"
        '  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType>'
        "<RunLevel>LeastPrivilege</RunLevel></Principal></Principals>\n"
        "  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>"
        "<ExecutionTimeLimit>PT10M</ExecutionTimeLimit><Enabled>true</Enabled></Settings>\n"
        f'  <Actions Context="Author"><Exec><Command>{escape(command)}</Command>'
        f"<Arguments>{escape(arguments)}</Arguments><WorkingDirectory>{escape(os.getcwd())}"
        "</WorkingDirectory></Exec></Actions>\n</Task>\n"
    )


def install_task(
    *, name: str = TASK_NAME, executable: str | None = None, interval_minutes: int = 30
) -> str:
    if os.name != "nt":
        raise RuntimeError("Windows Task Scheduler is available only on Windows")
    with tempfile.NamedTemporaryFile(
        suffix=".xml", delete=False, mode="w", encoding="utf-16"
    ) as handle:
        handle.write(task_xml(executable, interval_minutes=interval_minutes))
        xml_path = Path(handle.name)
    try:
        subprocess.run(
            ["schtasks.exe", "/Create", "/TN", name, "/XML", str(xml_path), "/F"],
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        xml_path.unlink(missing_ok=True)
    return name


def remove_task(name: str = TASK_NAME) -> bool:
    if os.name != "nt":
        raise RuntimeError("Windows Task Scheduler is available only on Windows")
    result = subprocess.run(
        ["schtasks.exe", "/Delete", "/TN", name, "/F"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def task_status(name: str = TASK_NAME) -> dict[str, str | bool]:
    if os.name != "nt":
        return {"supported": False, "installed": False, "reason": "Windows only"}
    result = subprocess.run(
        ["schtasks.exe", "/Query", "/TN", name, "/FO", "LIST"],
        capture_output=True,
        text=True,
    )
    return {
        "supported": True,
        "installed": result.returncode == 0,
        "task_name": name,
        "error": result.stderr.strip() if result.returncode else "",
    }
