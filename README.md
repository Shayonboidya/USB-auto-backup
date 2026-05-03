# USB Auto Backup

A Windows background daemon that automatically backs up files from USB drives as soon as they are inserted. It watches for new or modified files on the USB stick, copies supported file types to a local backup directory, and skips duplicates using SHA‑256 hashing.

## Features

- **Automatic USB detection** – polls for newly inserted removable drives (Windows).
- **Live file monitoring** – uses `watchdog` (ReadDirectoryChangesW) to react to file creation/modification in real time.
- **Configurable file types** – back up only the extensions you care about (PDF, images, office docs, etc.).
- **Deduplication** – SHA‑256 hashes are stored in a SQLite database; duplicate files are never copied twice.
- **Structure preservation** – the directory tree from the USB drive is recreated inside the backup folder.
- **Background daemon** – can be run with `pythonw.exe` for a silent, windowless experience.
- **Single‑instance guard** – a PID file prevents multiple copies of the daemon from running.
- **Large‑file guard** – ignores files exceeding a configurable size limit.

## Requirements

- Python 3.8+
- Windows OS
- Packages listed in `requirements.txt`:
  - `watchdog` – filesystem events
  - `pywin32` – Windows API bindings (PID check, etc.)

## Installation

1. Clone or download this project.
2. Create and activate a virtual environment (optional but recommended):
   ```bash
   python -m venv venv
   venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

Edit `config.json` to suit your needs:

```json
{
  "backup_dir": "C:\\usb_backups",
  "file_types": ["pdf", "docx", "xlsx", "txt", "jpg", "jpeg", "png", "mp4", "mp3", "zip", "rar", "pptx", "csv"],
  "hash_method": "sha256",
  "log_file": "C:\\usb_backup.log",
  "db_path": "./backups.db",
  "monitor_interval": 2,
  "max_file_size_mb": 1000
}
```

| Key | Description | Default |
|-----|-------------|---------|
| `backup_dir` | Where backed‑up files are stored. | `C:\usb_backups` |
| `file_types` | List of allowed file extensions (without dot). | common document/media types |
| `hash_method` | Hash algorithm for deduplication. | `sha256` |
| `log_file` | Path to the daemon log file. | `C:\usb_backup.log` |
| `db_path` | SQLite database path for hash records. | `./backups.db` |
| `monitor_interval` | Seconds between USB polling / watchdog checks. | `2` |
| `max_file_size_mb` | Skip files larger than this (0 = no limit). | `1000` |

All relative paths in `config.json` are resolved relative to the project directory.

## Usage

### Start the daemon (visible console)

```bash
python usb_backup_daemon.py
```

### Start the daemon (silent / background)

```bash
pythonw usb_backup_daemon.py
```

### What happens next

1. The daemon checks for an already‑inserted USB drive.
2. If none is found, it waits until a USB drive is plugged in.
3. Once a drive is detected, it scans existing files and begins watching for new or changed files.
4. Supported files are copied to `backup_dir`, preserving the original directory structure.
5. When the USB drive is removed, the daemon goes back to waiting for the next insertion.

### Stop the daemon

Press `Ctrl+C` in the console window, or kill the process if running via `pythonw.exe`.

## Project Structure

```
usb_auto_backup/
├── backup_engine.py      # Hash computation, SQLite dedup store
├── usb_device.py         # Windows removable‑drive detection
├── usb_backup_daemon.py  # Main daemon: PID lock, watchdog, backup loop
├── config.py             # Configuration loader (resolves paths)
├── config.json           # User‑editable settings
├── requirements.txt      # Python dependencies
└── README.md             # This file
```

## How It Works

1. **USB detection** – `usb_device.list_removable_drives()` polls drive letters A–Z and returns non‑system drives.
2. **Initial scan** – when a drive is found, all existing files matching `file_types` are processed immediately.
3. **Live watch** – `watchdog.Observer` monitors the USB root recursively; `BackupHandler` reacts to `on_created` and `on_modified` events.
4. **Per file** – the daemon checks the extension, size, and SHA‑256 hash. If the hash is new, the file is copied to `backup_dir` and recorded in the SQLite database.
5. **Graceful re‑poll** – when the drive disappears, the observer is stopped and the daemon waits for the next USB insertion.

## Notes

- The daemon currently backs up from **one USB drive at a time** (the first detected).
- Only drives other than `C:\` are considered to avoid backing up the system disk.
- Logs are written to the file configured in `config.json`; if a console is attached, they also appear on stdout.
