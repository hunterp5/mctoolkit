# This file is part of MolManager.
# Copyright (C) 2026 Hunter Picard
#
# MolManager is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MolManager is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.

"""Process resident memory (RSS) helpers for the status bar."""

from __future__ import annotations

import sys


def format_memory_bytes(num_bytes: int) -> str:
    """Human-readable size using binary prefixes (KiB, MiB, GiB)."""
    n = max(0, int(num_bytes))
    if n < 1024:
        return f"{n} B"
    units = ("KiB", "MiB", "GiB", "TiB")
    value = float(n)
    for unit in units:
        value /= 1024.0
        if value < 1024.0 or unit == units[-1]:
            if unit == "KiB":
                return f"{value:.0f} {unit}"
            return f"{value:.1f} {unit}"
    return f"{value:.1f} TiB"


def current_process_rss_bytes() -> int | None:
    """Return this process's resident set size in bytes, or None if unavailable."""
    if sys.platform == "win32":
        return _rss_windows()
    if sys.platform == "darwin":
        return _rss_macos()
    return _rss_linux()


def available_physical_bytes() -> int | None:
    """Bytes of physical RAM the OS can still hand out, or None when unknown."""
    if sys.platform == "win32":
        return _available_windows()
    if sys.platform == "darwin":
        return _available_macos()
    return _available_linux()


def application_memory_bytes() -> int | None:
    """Resident memory of this process plus its children.

    Render workers, Uni-pKa, and Qt WebEngine are separate processes. The status
    bar sums them so a busy tool is visible, not only the GUI working set.
    """
    own = current_process_rss_bytes()
    try:
        import psutil
    except ImportError:
        return own
    try:
        proc = psutil.Process()
        total = int(proc.memory_info().rss)
        for child in proc.children(recursive=True):
            try:
                total += int(child.memory_info().rss)
            except (psutil.Error, OSError):
                continue
        return total
    except (psutil.Error, OSError):
        return own


def format_process_memory_status() -> str | None:
    """Short status-bar text, e.g. ``Mem: 1.2 GiB``, or None when RSS is unknown."""
    rss = application_memory_bytes()
    if rss is None:
        return None
    return f"Mem: {format_memory_bytes(rss)}"


def _rss_windows() -> int | None:
    import ctypes
    from ctypes import wintypes

    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    get_process_memory_info = psapi.GetProcessMemoryInfo
    get_process_memory_info.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
        wintypes.DWORD,
    ]
    get_process_memory_info.restype = wintypes.BOOL

    counters = PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(counters)
    process = kernel32.GetCurrentProcess()
    if not get_process_memory_info(process, ctypes.byref(counters), counters.cb):
        return None
    return int(counters.WorkingSetSize)


def _available_windows() -> int | None:
    import ctypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    avail = int(status.ullAvailPhys)
    return avail if avail > 0 else None


def _available_linux() -> int | None:
    try:
        with open("/proc/meminfo", encoding="ascii", errors="replace") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return int(parts[1]) * 1024
    except OSError:
        return None
    return None


def _available_macos() -> int | None:
    # Host statistics need a Mach VM call that is easy to get wrong. Callers fall back
    # to a CPU cap when this is unknown.
    return None


def _rss_linux() -> int | None:
    try:
        with open("/proc/self/status", encoding="ascii", errors="replace") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return int(parts[1]) * 1024
    except OSError:
        return None
    return None


def _rss_macos() -> int | None:
    import ctypes
    import ctypes.util

    libc_path = ctypes.util.find_library("c")
    if not libc_path:
        return None
    libc = ctypes.CDLL(libc_path)

    mach_task_self = libc.mach_task_self
    mach_task_self.restype = ctypes.c_uint

    task_info = libc.task_info
    task_info.argtypes = [
        ctypes.c_uint,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint),
    ]
    task_info.restype = ctypes.c_int

    MACH_TASK_BASIC_INFO = 20

    class mach_task_basic_info(ctypes.Structure):
        _fields_ = [
            ("suspend_count", ctypes.c_uint),
            ("virtual_size", ctypes.c_ulonglong),
            ("resident_size", ctypes.c_ulonglong),
            ("user_time", ctypes.c_ulonglong * 2),
            ("system_time", ctypes.c_ulonglong * 2),
            ("policy", ctypes.c_int),
        ]

    info = mach_task_basic_info()
    count = ctypes.c_uint(ctypes.sizeof(info) // ctypes.sizeof(ctypes.c_uint))
    err = task_info(
        mach_task_self(),
        MACH_TASK_BASIC_INFO,
        ctypes.byref(info),
        ctypes.byref(count),
    )
    if err != 0:
        return None
    return int(info.resident_size)
