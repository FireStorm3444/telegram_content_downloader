"""Formatting utilities for sizes, speeds, and times."""

import re


def format_bytes(num_bytes: float | int) -> str:
    """Format bytes into human-readable binary unit representation (KiB, MiB, GiB)."""
    if num_bytes < 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    unit_idx = 0
    while size >= 1024.0 and unit_idx < len(units) - 1:
        size /= 1024.0
        unit_idx += 1
    if unit_idx == 0:
        return f"{int(size)} B"
    return f"{size:.2f} {units[unit_idx]}"


def format_speed(bytes_per_sec: float) -> str:
    """Format byte rate into human-readable speed representation."""
    return f"{format_bytes(bytes_per_sec)}/s"


def format_duration(seconds: float) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    if seconds < 0 or seconds != seconds:  # NaN or negative
        return "--:--"
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def parse_size_str(size_str: str | None) -> int | None:
    """Parse size string like '10MB', '500KB', '1.5GB' into integer bytes."""
    if not size_str:
        return None
    cleaned = size_str.strip().upper()
    match = re.match(r"^([0-9.]+)\s*([KMGT]?B?)$", cleaned)
    if not match:
        raise ValueError(f"Invalid size string: '{size_str}'")

    value_str, unit = match.groups()
    value = float(value_str)
    multipliers = {
        "": 1,
        "B": 1,
        "K": 1024,
        "KB": 1024,
        "M": 1024**2,
        "MB": 1024**2,
        "G": 1024**3,
        "GB": 1024**3,
        "T": 1024**4,
        "TB": 1024**4,
    }
    if unit not in multipliers:
        raise ValueError(f"Unknown size unit: '{unit}' in '{size_str}'")

    return int(value * multipliers[unit])
