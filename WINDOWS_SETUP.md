# Windows setup for History Dashboard

This guide is for transferring `history_dashboard` from the Mac development machine to the office Windows laptop.

## Prerequisites

- Python is installed with company IT approval.
- OneDrive is signed in on the Windows laptop.
- The correct SharePoint document library is synced locally through OneDrive.
- The operational workbook, normally `logistics_operations_demo.xlsm`, is visible as a local file in File Explorer.
- Do not copy the workbook into the project folder unless the business workflow changes later. The app should point to the OneDrive-synced workbook.

## Transfer

1. Install Python 3.13 once with company IT approval. A typical command is `winget install Python.Python.3.13`.
2. Verify `python --version` and `python -m pip --version` if IT is troubleshooting the installation.
3. Copy the complete `history_dashboard` folder to the Windows laptop.
4. Open the copied project folder in File Explorer.
5. Double-click `install_dependencies.bat` once. It finds Python 3.13, creates `.venv`, installs `requirements.txt` into that project-local environment, and runs `check_environment.py`.
6. Double-click `launch_history_dashboard.vbs` for normal use. It starts the GUI without a Command Prompt window.
7. `launch_history_dashboard.bat` is an alternative visible troubleshooting launcher and uses the same `.venv`.
8. If the app says the workbook is not configured, click `Locate Workbook`.
9. Choose the local OneDrive-synced workbook, usually ending in `.xlsm`.
10. The app validates the workbook before saving the path.
11. Confirm the Dashboard opens.
12. Close and reopen the app to confirm the workbook setting persisted.

## Environment check

You can run:

```text
.venv\Scripts\python.exe check_environment.py
```

It reports:

- Python version;
- operating system;
- project version;
- whether required modules are importable;
- whether Tkinter/Tk is importable;
- configured workbook path;
- workbook health status;
- config and log folders.

No workbook row contents are printed.

## Normal future use

After setup, employees should not need Terminal or source-code editing.

Use:

```text
launch_history_dashboard.vbs
```

Normal launch does not install or update dependencies. A Windows desktop shortcut can point to the VBS launcher.

## Configuration location

The workbook path is stored per Windows user at:

```text
%APPDATA%\HistoryDashboard\config.json
```

This file should contain user/application settings only, such as:

```json
{
  "workbook_path": "C:\\Users\\Employee\\OneDrive - Example Company SIA\\Latvia Documents\\logistics_operations_demo.xlsm"
}
```

The project’s own `config.json` is only a safe default file and does not contain the production workbook path.

## Logs

The app writes a modest rotating troubleshooting log to:

```text
%LOCALAPPDATA%\HistoryDashboard\logs\app.log
```

Use Settings → Open Log Folder if support needs the log.

The log records startup, config resolution, workbook validation, successful workbook loads, refresh failures, and unexpected errors. It does not intentionally log workbook row contents.

## Troubleshooting

### Python command not found

Ask IT to confirm Python is installed and available from Command Prompt. The launch/install scripts try `python` first and then `py`.

### Missing dependency

Run `install_dependencies.bat` again from inside the project folder. It reuses the existing project `.venv`. If company policy blocks installation, ask IT to approve installing packages from `requirements.txt`.

### Tk unavailable

The GUI needs Tkinter/Tk. Ask IT to install a standard Python distribution that includes Tkinter.

### Workbook not found

Open File Explorer and confirm the workbook exists locally in the synced OneDrive/SharePoint folder. If it moved, launch the app and use Settings → Change Workbook.

### OneDrive file unavailable

If OneDrive is still syncing, wait until the workbook has a normal local file icon and try Refresh again. If refresh fails after a previous successful load, the app keeps showing the last loaded data.

### Invalid workbook structure

The dashboard requires at least:

- `WEEKLY`
- `LOG_HISTORY`

Other known sheets (`TEMPLATE`, `MASTER_DATA`, `REPORT`, `README`) are helpful context and may create warnings if absent, but the app’s core read-only analytics are based on `WEEKLY` and `LOG_HISTORY`.

### Application log location

Open the app and go to Settings → Open Log Folder, or navigate manually to:

```text
%LOCALAPPDATA%\HistoryDashboard\logs
```

## What this milestone does not do

Milestone 5 does not create an `.exe`, installer, MSI, desktop shortcut, SharePoint API connection, Microsoft Graph authentication, database, background polling, auto-update, telemetry, email notifications, scheduled reports, or workbook editing.
