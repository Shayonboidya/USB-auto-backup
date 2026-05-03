"""Windows‑compatible USB detection utilities.

The original Linux version used pyudev; on Windows we instead poll for newly mounted
removable drives (e.g. "E:\\", "F:\\"). This simple approach works without extra
native extensions and is sufficient for a background daemon.
"""

import os
import time
from typing import Optional, Set


def list_removable_drives() -> Set[str]:
    """Return a set of currently mounted removable drive letters.

    The function checks every alphabetic drive letter (A‑Z) and includes it if the
    path exists and is a directory. This heuristic skips the typical system drive
    (C:\\) and returns any additional drives – which on most Windows machines are
    USB sticks, external HDDs, or network mounts.

    NOTE: For a more accurate detection of *removable* drives only, one could call
    ``ctypes.windll.kernel32.GetDriveTypeW`` and keep only drives where the
    return value is 2 (DRIVE_REMOVABLE) or 3 (DRIVE_FIXED) for external HDDs.
    The current implementation is intentionally simple and can be refined later.
    """
    drives = set()
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        path = f"{letter}:\\"
        if os.path.isdir(path):
            # Exclude the primary system drive (commonly C:\)
            if letter.upper() != "C":
                drives.add(path)
    return drives


# Keep old name as an alias for backward compatibility
_list_removable_drives = list_removable_drives


def wait_for_new_usb(poll_interval: float = 1.0, timeout: Optional[int] = None) -> Optional[str]:
    """Block until a previously‑absent removable drive appears.

    Args:
        poll_interval: Seconds to wait between each poll.
        timeout: Optional maximum number of seconds to wait. ``None`` means wait
            indefinitely.

    Returns:
        The path of the newly detected USB drive (e.g. "E:\\") or ``None`` if a
        timeout occurs.
    """
    known = list_removable_drives()
    start = time.time()
    while True:
        current = list_removable_drives()
        new = current - known
        if new:
            # Return the first new drive (sorted for deterministic order)
            return sorted(new)[0]
        if timeout is not None and (time.time() - start) >= timeout:
            return None
        time.sleep(poll_interval)


def wait_for_any_usb(poll_interval: float = 1.0, timeout: Optional[int] = None) -> Optional[str]:
    """Return a currently present removable drive, or wait until one appears.

    Unlike ``wait_for_new_usb``, this function also returns a drive that is
    already present when the call is made (i.e. the *known* set is initialised
    as empty).

    This is useful for the daemon start‑up, when a USB stick may already be
    plugged in.
    """
    # Start with an empty known set so that any existing drive is considered "new"
    known: Set[str] = set()
    start = time.time()
    while True:
        current = list_removable_drives()
        new = current - known
        if new:
            return sorted(new)[0]
        # If there is at least one drive but we haven't "seen" it yet,
        # treat the first one as the target.
        if current:
            return sorted(current)[0]
        if timeout is not None and (time.time() - start) >= timeout:
            return None
        time.sleep(poll_interval)
