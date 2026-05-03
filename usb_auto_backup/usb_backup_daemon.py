"""Main daemon for the USB auto‑backup system (Windows).

- Detects USB insertion via drive‑letter polling.
- Uses watchdog’s native Windows observer (ReadDirectoryChangesW) to watch for
  file creation / modification events.
- Copies supported files to a local backup directory, preserving structure.
- Avoids duplicates via SHA‑256 hashing stored in SQLite.
- Runs in the background; can be started with pythonw.exe for a silent daemon.
- Includes PID file locking to prevent multiple instances.
"""

import sys
import os
import time
import logging
import ctypes
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

import backup_engine
import usb_device
import config as cfg_mod

# ---------------------------------------------------------------------
# PID lock helpers (Windows)
# ---------------------------------------------------------------------
PID_FILE = Path(__file__).parent / ".usb_backup.pid"

def _is_process_alive(pid: int) -> bool:
    """Return True if a process with *pid* is still running (Windows)."""
    try:
        h = ctypes.windll.kernel32.OpenProcess(0x0400, False, pid)
        if not h:
            return False
        exit_code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(h)
        return exit_code.value == 259  # STILL_ACTIVE
    except Exception:
        return False

def acquire_pid_lock() -> bool:
    """Create PID file if not already locked. Returns True on success."""
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            if _is_process_alive(pid):
                return False
        except Exception:
            pass
    PID_FILE.write_text(str(os.getpid()))
    return True

def release_pid_lock():
    """Remove PID file if it belongs to this process."""
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            if pid == os.getpid():
                PID_FILE.unlink()
        except Exception:
            pass

# ---------------------------------------------------------------------
# Load configuration (paths are resolved to absolute)
# ---------------------------------------------------------------------
config = cfg_mod.load_config()
backup_root = Path(config["backup_dir"])
log_path = Path(config["log_file"])

# Ensure essential directories exist
backup_root.mkdir(parents=True, exist_ok=True)
log_path.parent.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------
# Logging configuration – file only unless a console is attached
# ---------------------------------------------------------------------
handlers = [logging.FileHandler(log_path, encoding="utf-8")]
if sys.stdout is not None:
    handlers.append(logging.StreamHandler(sys.stdout))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=handlers,
    force=True,
)

# ---------------------------------------------------------------------
# Watchdog handler – processes file events
# ---------------------------------------------------------------------
class BackupHandler(FileSystemEventHandler):
    def __init__(self, engine: backup_engine.BackupEngine, usb_root: Path):
        self.engine = engine
        self.usb_root = usb_root
        self.allowed_ext = {f".{ext.lower()}" for ext in config.get("file_types", [])}

    def on_created(self, event):
        if event.is_directory:
            return
        self._process(event.src_path)

    def on_modified(self, event):
        if event.is_directory:
            return
        self._process(event.src_path)

    # -----------------------------------------------------------------
    # Internal helper – decide whether to back up a file
    # -----------------------------------------------------------------
    def _process(self, src_path: str):
        src = Path(src_path)
        if not src.is_file():
            return
        if src.suffix.lower() not in self.allowed_ext:
            return  # unsupported extension

        # Skip files larger than the configured maximum
        max_mb = config.get("max_file_size_mb", 0)
        if max_mb:
            try:
                size = src.stat().st_size
                if size > max_mb * 1024 * 1024:
                    logging.warning(
                        f"Skipping large file {src} ({size / 1024 / 1024:.1f} MB > {max_mb} MB)"
                    )
                    return
            except OSError:
                return

        # Compute hash
        file_hash = self.engine.compute_file_hash(str(src))
        if not file_hash:
            logging.error(f"Failed to compute hash for {src}")
            return

        if self.engine.is_duplicate(file_hash):
            logging.debug(f"Duplicate file skipped: {src}")
            return

        # Preserve relative directory structure inside the backup folder
        try:
            rel_path = src.relative_to(self.usb_root)
        except ValueError:
            logging.error(f"File {src} is outside monitored USB root {self.usb_root}")
            return

        dest = backup_root / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Copy with retry – handles temporary locks
        if self._copy_with_retry(str(src), str(dest)):
            self.engine.add_backup_record(file_hash, str(src), str(dest))
            logging.info(f"Backed up: {src} -> {dest}")
        else:
            logging.error(f"Failed to copy {src} after retries")

    @staticmethod
    def _copy_with_retry(src: str, dst: str, retries: int = 4, base_delay: float = 0.5) -> bool:
        """Copy *src* to *dst*, retrying on PermissionError with exponential back‑off."""
        import shutil
        delay = base_delay
        for attempt in range(1, retries + 1):
            try:
                shutil.copy2(src, dst)
                return True
            except PermissionError as exc:
                logging.warning(
                    f"Copy attempt {attempt}/{retries} failed for {src}: {exc}. Retrying in {delay:.1f}s"
                )
                time.sleep(delay)
                delay *= 2
            except Exception as exc:
                logging.error(f"Unexpected error copying {src}: {exc}")
                return False
        return False

# ---------------------------------------------------------------------
# Helper – monitor a single USB drive until it is removed or interrupted
# ---------------------------------------------------------------------
def _monitor_drive(usb_root: Path, engine: backup_engine.BackupEngine):
    logging.info(f"Monitoring USB drive at {usb_root}")
    handler = BackupHandler(engine, usb_root)

    # Initial scan – back up existing files
    for existing_path in usb_root.rglob("*"):
        if existing_path.is_file() and existing_path.suffix.lower() in handler.allowed_ext:
            handler._process(str(existing_path))

    observer = Observer()
    observer.schedule(handler, str(usb_root), recursive=True)
    observer.start()
    logging.info(f"Watchdog observer started for {usb_root}")

    try:
        while usb_root.exists():
            time.sleep(config.get("monitor_interval", 2))
    finally:
        observer.stop()
        observer.join()
        logging.info(f"Stopped monitoring {usb_root}")

# ---------------------------------------------------------------------
# Main daemon loop
# ---------------------------------------------------------------------
def main():
    if not acquire_pid_lock():
        logging.error("Another instance of USB Backup daemon is already running.")
        sys.exit(1)

    logging.info("USB Backup daemon started (PID %s).", os.getpid())
    logging.info("Backup directory: %s", backup_root)
    logging.info("Log file: %s", log_path)
    logging.info("Monitored file types: %s", config.get("file_types", []))

    engine = backup_engine.BackupEngine(db_path=config.get('db_path'))

    try:
        while True:
            # 1. Detect already‑inserted USB drives.
            current = usb_device.list_removable_drives()
            if current:
                usb_path = sorted(current)[0]
                logging.info(f"Found already‑inserted USB drive: {usb_path}")
            else:
                # 2. Wait for a new insertion.
                logging.info("Waiting for USB insertion …")
                usb_path = usb_device.wait_for_new_usb(
                    poll_interval=config.get("monitor_interval", 2)
                )
                if not usb_path:
                    logging.error("USB detection timed out – exiting daemon.")
                    sys.exit(1)

            usb_root = Path(usb_path)
            try:
                _monitor_drive(usb_root, engine)
            except KeyboardInterrupt:
                logging.info("Shutdown requested via KeyboardInterrupt.")
                break
            # Loop again to handle the next drive.
    finally:
        release_pid_lock()
        logging.info("USB Backup daemon stopped.")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logging.exception(f"Fatal error in daemon: {exc}")
        sys.exit(1)
