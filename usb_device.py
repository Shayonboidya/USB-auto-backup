"""Windows‑compatible USB detection utilities using GetDriveTypeW."""

import os
import time
from typing import Optional, Set

try:
    import ctypes
    from ctypes import wintypes
    GetDriveTypeW = ctypes.windll.kernel32.GetDriveTypeW
    GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    GetDriveTypeW.restype = wintypes.UINT
    WINDOWS_API_AVAILABLE = True
except (AttributeError, ImportError):
    WINDOWS_API_AVAILABLE = False

DRIVE_REMOVABLE = 2
SYSTEM_DRIVE = os.environ.get('SystemDrive', 'C:').upper()

def list_removable_drives() -> Set[str]:
    """Return set of mounted removable USB drives (DRIVE_REMOVABLE only)."""
    drives = set()
    if not WINDOWS_API_AVAILABLE:
        # Fallback to legacy method
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            path = f"{letter}:\\"
            if os.path.isdir(path) and letter.upper() != SYSTEM_DRIVE[0]:
                drives.add(path)
        return drives

    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        drive = f"{letter}:"
        if drive.upper() == SYSTEM_DRIVE:
            continue
        path = f"{letter}:\\"
        drive_type = GetDriveTypeW(path)
        if drive_type == DRIVE_REMOVABLE:
            drives.add(path)
    return drives

def wait_for_new_usb(poll_interval: float = 1.0, timeout: Optional[int] = None) -> Optional[str]:
    """Block until a new removable drive is inserted."""
    known = list_removable_drives()
    start = time.time()
    while True:
        current = list_removable_drives()
        new = current - known
        if new:
            return sorted(new)[0]
        if timeout is not None and (time.time() - start) >= timeout:
            return None
        time.sleep(poll_interval)

def wait_for_any_usb(poll_interval: float = 1.0, timeout: Optional[int] = None) -> Optional[str]:
    """Return existing or newly inserted removable drive."""
    known: Set[str] = set()
    start = time.time()
    while True:
        current = list_removable_drives()
        new = current - known
        if new:
            return sorted(new)[0]
        if current:
            return sorted(current)[0]
        if timeout is not None and (time.time() - start) >= timeout:
            return None
        time.sleep(poll_interval)
