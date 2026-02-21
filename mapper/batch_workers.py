import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent / "logs"


# Gets available memory in bytes so we can avoid overloading low-resource systems.
def _available_memory_bytes():
    if os.name == "nt":
        try:
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
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullAvailPhys)
        except Exception:
            return None
        return None

    if hasattr(os, "sysconf"):
        try:
            page_size = os.sysconf("SC_PAGE_SIZE")
            avail_pages = os.sysconf("SC_AVPHYS_PAGES")
            return int(page_size * avail_pages)
        except Exception:
            return None
    return None


# Chooses a safe worker count and falls back to one-at-a-time when resources are limited.
def resolve_worker_count(domain_count, requested_workers, max_workers):
    if domain_count <= 1:
        return 1

    cpu_count = os.cpu_count() or 1
    safe_cpu_cap = max(1, min(max_workers, cpu_count // 2 if cpu_count > 2 else 1))
    mem_bytes = _available_memory_bytes()
    mem_cap = max_workers
    if mem_bytes is not None:
        mem_gb = mem_bytes / (1024 ** 3)
        if mem_gb < 1.5:
            mem_cap = 1
        elif mem_gb < 3:
            mem_cap = min(mem_cap, 2)
        elif mem_gb < 6:
            mem_cap = min(mem_cap, 3)

    safe_cap = max(1, min(domain_count, safe_cpu_cap, mem_cap))
    if requested_workers and requested_workers > 0:
        return max(1, min(requested_workers, safe_cap))
    return safe_cap


# Decides whether the batch should run in the background based on selected mode.
def should_run_in_background(mode, domain_count):
    if mode == "background":
        return True
    if mode == "foreground":
        return False
    return domain_count > 1


# Builds the background command that re-runs mapper in foreground batch mode.
def build_background_command(
    script_path,
    domains,
    requested_workers,
    max_workers,
    include_subdomains,
    output_path,
):
    cmd = [
        sys.executable,
        str(script_path),
        "--run-batch",
        "--mode",
        "foreground",
        "--workers",
        str(requested_workers),
        "--max-workers",
        str(max_workers),
        "--output",
        str(output_path),
    ]
    if not include_subdomains:
        cmd.append("--no-subdomains")
    cmd.extend(domains)
    return cmd


# Starts a detached mapper process and writes output to a log file.
def launch_background(
    script_path,
    domains,
    requested_workers,
    max_workers,
    include_subdomains,
    output_path,
    log_file="",
):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    resolved_log = Path(log_file) if log_file else LOG_DIR / f"mapper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    cmd = build_background_command(
        script_path=script_path,
        domains=domains,
        requested_workers=requested_workers,
        max_workers=max_workers,
        include_subdomains=include_subdomains,
        output_path=output_path,
    )

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

    with open(resolved_log, "a", encoding="utf-8") as log_handle:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            cwd=str(script_path.parent),
            close_fds=True,
            creationflags=creationflags,
        )

    return process.pid, resolved_log
