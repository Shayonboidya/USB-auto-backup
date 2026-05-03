"""Main daemon for USB auto-backup (Windows) with robust logging and error handling."""

import sys
import os
import time
import logging
import ctypes
import shutil
from pathlib import Path
from typing import Optional

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
    try:
        PROCESS_QUERY_INFORMATION = 0x0400
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
        if not h:
            return False
        exit_code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(h)
        return exit_code.value == 259  # STILL_ACTIVE
    except Exception:
        return False

def acquire_pid_lock() -> bool:
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            if _is_process_alive(pid):
                return False
        except Exception:
            pass
        try:
            PID_FILE.unlink()
        except Exception:
            pass
    PID_FILE.write_text(str(os.getpid()))
    return True

def release_pid_lock():
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            if pid == os.getpid():
                PID_FILE.unlink()
        except Exception:
            pass

# ---------------------------------------------------------------------
# Logging setup with fallback for unwritable paths
# ---------------------------------------------------------------------
def setup_logging(config: dict) -> logging.Logger:
    log_path = Path(config.get("log_file", "./usb_backup.log"))

    # Test log path writability, fallback if needed
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write('')
    except Exception:
        # Fallback to backup_dir/logs
        backup_dir = Path(config.get("backup_dir", "./backups"))
        fallback_dir = backup_dir / "logs"
        try:
            fallback_dir.mkdir(parents=True, exist_ok=True)
            log_path = fallback_dir / "usb_backup.log"
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write('')
        except Exception:
            # Last resort: temp directory
            import tempfile
            fallback_dir = Path(tempfile.gettempdir()) / "usb_auto_backup"
            fallback_dir.mkdir(exist_ok=True)
            log_path = fallback_dir / "usb_backup.log"

    # Configure handlers
    handlers = []
    try:
        file_handler = logging.FileHandler(log_path, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        handlers.append(file_handler)
    except Exception as e:
        print(f"Failed to create log file: {e}", file=sys.stderr)

    if sys.stdout is not None:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setLevel(logging.INFO)
        handlers.append(stream_handler)

    if not handlers:
        handlers.append(logging.NullHandler())

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=handlers,
        force=True,
    )

    logger = logging.getLogger(__name__)
    logger.info(f"Log file initialized at: {log_path}")
    return logger

# ---------------------------------------------------------------------
# Load configuration and validate paths
# ---------------------------------------------------------------------
config = cfg_mod.load_config()
backup_root = Path(config["backup_dir"])
log_path = Path(config["log_file"])

# Validate backup directory
try:
    backup_root.mkdir(parents=True, exist_ok=True)
    test_file = backup_root / ".write_test"
    test_file.touch()
    test_file.unlink()
    print(f"Backup directory ready: {backup_root}")
except Exception as e:
    print(f"ERROR: Backup directory {backup_root} is not writable: {e}", file=sys.stderr)
    sys.exit(1)

# Setup logging
logger = setup_logging(config)

# ---------------------------------------------------------------------
# Watchdog handler
# ---------------------------------------------------------------------
class BackupHandler(FileSystemEventHandler):
    def __init__(self, engine: backup_engine.BackupEngine, usb_root: Path):
        self.engine = engine
        self.usb_root = usb_root
        self.allowed_ext = {f".{ext.lower()}" for ext in config.get("file_types", [])}
        self.max_file_size_mb = config.get("max_file_size_mb", 0)

    def on_created(self, event):
        if not event.is_directory:
            self._process(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._process(event.src_path)

    def _process(self, src_path: str):
        src = Path(src_path)
        logger.debug(f"Processing: {src}")

        if not src.is_file():
            return

        if src.suffix.lower() not in self.allowed_ext:
            logger.debug(f"Skipped (unsupported extension): {src}")
            return

        if self.max_file_size_mb > 0:
            try:
                size = src.stat().st_size
                if size > self.max_file_size_mb * 1024 * 1024:
                    logger.warning(f"Skipped (too large: {size/1024/1024:.1f}MB): {src}")
                    return
            except OSError as e:
                logger.error(f"Failed to check size of {src}: {e}")
                return

        file_hash = self.engine.compute_file_hash(str(src))
        if not file_hash:
            logger.error(f"Hash computation failed: {src}")
            return

        if self.engine.is_duplicate(file_hash):
            logger.debug(f"Skipped (duplicate): {src}")
            return

        try:
            rel_path = src.relative_to(self.usb_root)
        except ValueError:
            logger.error(f"File {src} outside USB root {self.usb_root}")
            return

        dest = backup_root / rel_path
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create {dest.parent}: {e}")
            return

        if self._copy_with_retry(str(src), str(dest)):
            self.engine.add_backup_record(file_hash, str(src), str(dest))
            logger.info(f"Backed up: {src} → {dest}")
        else:
            logger.error(f"Copy failed after retries: {src}")

    @staticmethod
    def _copy_with_retry(src: str, dst: str, retries: int = 4, base_delay: float = 0.5) -> bool:
        delay = base_delay
        for attempt in range(1, retries + 1):
            try:
                shutil.copy2(src, dst)
                logger.debug(f"Copy succeeded (attempt {attempt}): {src}")
                return True
            except PermissionError as e:
                logger.warning(f"Copy attempt {attempt} failed: {e}. Retrying in {delay}s")
                time.sleep(delay)
                delay *= 2
            except Exception as e:
                logger.error(f"Copy failed: {e}", exc_info=True)
                return False
        return False

# ---------------------------------------------------------------------
# Drive monitoring
# ---------------------------------------------------------------------
def _monitor_drive(usb_root: Path, engine: backup_engine.BackupEngine):
    logger.info(f"Monitoring drive: {usb_root}")
    handler = BackupHandler(engine, usb_root)

    # Initial scan
    logger.info(f"Scanning existing files on {usb_root}...")
    for path in usb_root.rglob("*"):
        if path.is_file():
            handler._process(str(path))
    logger.info("Initial scan complete")

    observer = Observer()
    observer.schedule(handler, str(usb_root), recursive=True)
    observer.start()
    logger.info("Watchdog observer started")

    try:
        while usb_root.exists():
            time.sleep(config.get("monitor_interval", 2))
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
    finally:
        observer.stop()
        observer.join(timeout=5)
        logger.info(f"Stopped monitoring {usb_root}")

# ---------------------------------------------------------------------
# Main daemon loop
# ---------------------------------------------------------------------
def main():
    if not acquire_pid_lock():
        logger.error("Another instance is already running")
        sys.exit(1)

    logger.info(f"Daemon started (PID {os.getpid()})")
    logger.info(f"Backup dir: {backup_root}")
    logger.info(f"Monitored file types: {config.get('file_types')}")

    engine = backup_engine.BackupEngine(db_path=config.get('db_path'))
    logger.info(f"Backup engine initialized (DB: {config.get('db_path')})")

    try:
        while True:
            current = usb_device.list_removable_drives()
            if current:
                usb_path = sorted(current)[0]
                logger.info(f"Found USB drive: {usb_path}")
            else:
                logger.info("Waiting for USB insertion...")
                usb_path = usb_device.wait_for_new_usb(poll_interval=config.get("monitor_interval", 2))
                if not usb_path:
                    logger.error("Timeout waiting for USB")
                    break

            try:
                _monitor_drive(Path(usb_path), engine)
            except Exception as e:
                logger.error(f"Drive monitor error: {e}", exc_info=True)
            logger.info("Waiting for next USB drive...")
    finally:
        release_pid_lock()
        logger.info("Daemon stopped")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)
