"""Cross-platform filename sanitization and conflict resolution utilities."""

import json
import re
import unicodedata
from pathlib import Path

# Characters forbidden on Windows, Linux, and macOS
FORBIDDEN_CHARS_REGEX = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Reserved device names on Windows
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}


def sanitize_filename(filename: str, replacement: str = "_", max_length: int = 200) -> str:
    """Sanitize a filename for cross-platform filesystem safety.

    - Normalizes unicode (NFC).
    - Strips forbidden characters and control codes.
    - Prevents Windows reserved device names.
    - Truncates excessive lengths while preserving extensions.
    - Strips leading/trailing dots and spaces.
    """
    if not filename:
        return "unnamed_file"

    # Normalize unicode
    cleaned = unicodedata.normalize("NFC", filename)

    # Replace illegal characters
    cleaned = FORBIDDEN_CHARS_REGEX.sub(replacement, cleaned)

    # Strip leading/trailing whitespaces and dots
    cleaned = cleaned.strip(" .")

    if not cleaned:
        return "unnamed_file"

    # Split stem and extension
    dot_idx = cleaned.rfind(".")
    if dot_idx > 0 and dot_idx < len(cleaned) - 1:
        stem = cleaned[:dot_idx].rstrip(" .")
        ext = cleaned[dot_idx:]
    else:
        stem = cleaned
        ext = ""

    # Check for Windows reserved names
    if stem.upper() in WINDOWS_RESERVED_NAMES:
        stem = f"_{stem}"

    # Truncate length if needed
    if len(stem) + len(ext) > max_length:
        max_stem_len = max(1, max_length - len(ext))
        stem = stem[:max_stem_len].rstrip(" .")

    final_name = f"{stem}{ext}"
    return final_name if final_name else "unnamed_file"


def _matches_part_meta(part_path: Path, expected_file_id: str | None, expected_size: int) -> bool:
    """Check whether an existing .part file's metadata matches the target download."""
    meta_path = part_path.with_suffix(part_path.suffix + ".meta")
    if not part_path.exists() or not meta_path.exists():
        return False
    try:
        with open(meta_path, encoding="utf-8") as f:
            data = json.load(f)
        if expected_file_id and str(data.get("file_id")) == str(expected_file_id):
            return True
        if expected_size > 0 and data.get("total_size") == expected_size:
            return True
    except Exception:
        pass
    return False


def resolve_target_path(
    dest_dir: Path,
    filename: str,
    expected_size: int = 0,
    file_id: str | None = None,
    overwrite: bool = False,
) -> tuple[Path, bool]:
    """Resolve destination path and determine if the target file was already completed.

    Handles filename collisions across multiple files sharing identical names:
    1. If overwrite is True: returns (dest_dir / filename, False).
    2. Checks base file:
       - Completed if base_path exists and size matches expected_size -> (base_path, True).
       - Resumable if base_path.part exists and metadata matches file_id/size -> (base_path, False).
    3. If base_path exists with a different size, scans numbered collision variants:
       - Completed if candidate exists and size matches expected_size -> (candidate, True).
       - Resumable if candidate.part exists and metadata matches file_id/size -> (candidate, False).
    4. If no matching file exists, returns the first unused variant path -> (new_candidate, False).

    Returns:
        tuple[Path, bool]: (resolved_path, is_already_completed)
    """
    base_path = dest_dir / filename
    if overwrite:
        return base_path, False

    base_part = base_path.with_suffix(base_path.suffix + ".part")

    # If base file does not exist and base .part does not exist
    if not base_path.exists() and not base_part.exists():
        return base_path, False

    # Check base file completed
    if base_path.exists() and expected_size > 0 and base_path.stat().st_size == expected_size:
        return base_path, True

    # Check base file in-progress
    if base_part.exists() and _matches_part_meta(base_part, file_id, expected_size):
        return base_path, False

    # Base file exists with different size: scan numbered variants
    stem = base_path.stem
    ext = base_path.suffix

    variant_pattern = re.compile(rf"^{re.escape(stem)} \((\d+)\){re.escape(ext)}(?:\.part)?$")
    existing_counters: set[int] = set()

    if dest_dir.exists():
        try:
            for p in dest_dir.iterdir():
                m = variant_pattern.match(p.name)
                if m:
                    existing_counters.add(int(m.group(1)))
        except OSError:
            pass

    # Check all existing counters for size or part-meta match
    for c in sorted(existing_counters):
        candidate = dest_dir / f"{stem} ({c}){ext}"
        candidate_part = candidate.with_suffix(candidate.suffix + ".part")

        if candidate.exists() and expected_size > 0 and candidate.stat().st_size == expected_size:
            return candidate, True

        if candidate_part.exists() and _matches_part_meta(candidate_part, file_id, expected_size):
            return candidate, False

    # If no match found, find the lowest unused counter
    free_c = 1
    while free_c in existing_counters:
        free_c += 1

    return dest_dir / f"{stem} ({free_c}){ext}", False


def resolve_unique_path(target_path: Path, overwrite: bool = False) -> Path:
    """Resolve a destination file path, appending a numeric suffix if collision exists and overwrite is False."""
    resolved, _ = resolve_target_path(target_path.parent, target_path.name, overwrite=overwrite)
    return resolved
