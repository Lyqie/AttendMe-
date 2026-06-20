"""
Screen capture module for AttendMe.

Captures screenshots via mss (fast, cross-platform) and retrieves
active window information via Windows API (ctypes).
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from io import BytesIO
from pathlib import Path

import mss
import mss.windows
from PIL import Image


# ── Windows API helpers ──────────────────────────────────────────────────────

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_psapi = ctypes.windll.psapi


def get_active_window_title() -> str:
    """Return the title text of the currently focused (foreground) window."""
    hwnd = _user32.GetForegroundWindow()
    length = _user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def get_active_process_name() -> str:
    """Return the executable name (e.g. 'chrome.exe') of the foreground process."""
    hwnd = _user32.GetForegroundWindow()
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    process_handle = _kernel32.OpenProcess(0x0400 | 0x0010, False, pid.value)
    if not process_handle:
        return ""

    name_buf = ctypes.create_unicode_buffer(260)
    size = wintypes.DWORD(ctypes.sizeof(name_buf))
    success = _psapi.GetModuleBaseNameW(process_handle, None, name_buf, size)
    _kernel32.CloseHandle(process_handle)

    return name_buf.value if success else ""


# ── Screen capture ────────────────────────────────────────────────────────────

class ScreenCapture:
    """Captures screen content using mss for speed."""

    def __init__(self, monitor_index: int = 0, max_dimension: int = 1024,
                 quality: int = 75):
        self._monitor_index = monitor_index
        self._max_dim = max_dimension
        self._quality = quality
        self._sct = mss.mss()

    @property
    def monitor_count(self) -> int:
        return len(self._sct.monitors) - 1  # monitor[0] is "all monitors"

    def capture(self) -> Image.Image:
        """Capture the specified monitor and return a resized PIL Image."""
        monitor = self._sct.monitors[self._monitor_index + 1]  # 1-indexed
        sct_img = self._sct.grab(monitor)
        pil_img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

        # Resize to keep inference fast while retaining readability
        w, h = pil_img.size
        if max(w, h) > self._max_dim:
            scale = self._max_dim / max(w, h)
            pil_img = pil_img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        return pil_img

    def capture_to_base64(self) -> str:
        """Capture screen and return as a base64-encoded JPEG string."""
        import base64
        img = self.capture()
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=self._quality)
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    def get_active_window_info(self) -> tuple[str, str]:
        """Return (process_name, window_title) of the foreground window."""
        return get_active_process_name(), get_active_window_title()
