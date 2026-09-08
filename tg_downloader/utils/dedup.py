"""File deduplication and redundant collision cleanup utilities."""

import hashlib
import logging
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)


def compute_file_hash(path: Path, sample_size: int = 256 * 1024) -> str:
    """Compute a fast content fingerprint using file size, head, and tail samples."""
    size = path.stat().st_size
    hasher = hashlib.sha256()
    hasher.update(str(size).encode("ascii"))

    if size <= sample_size * 2:
        with open(path, "rb") as f:
            hasher.update(f.read())
    else:
        with open(path, "rb") as f:
            hasher.update(f.read(sample_size))
            f.seek(size - sample_size)
            hasher.update(f.read(sample_size))

    return hasher.hexdigest()


def find_duplicate_files(target_dir: Path) -> list[tuple[Path, Path]]:
    """Scan target directory and identify exact duplicate files by size and content hash.

    Returns:
        list[tuple[Path, Path]]: List of (duplicate_to_remove, original_to_keep)
    """
    if not target_dir.exists():
        return []

    # Group all non-part files by size
    size_groups: dict[int, list[Path]] = defaultdict(list)
    for p in target_dir.iterdir():
        if p.is_file() and not p.name.endswith(".part") and not p.name.endswith(".part.meta"):
            size = p.stat().st_size
            if size > 0:
                size_groups[size].append(p)

    duplicates: list[tuple[Path, Path]] = []

    for files in size_groups.values():
        if len(files) < 2:
            continue

        # Group by content hash
        hash_groups: dict[str, list[Path]] = defaultdict(list)
        for f in sorted(files, key=lambda x: (len(x.name), x.name)):
            try:
                h = compute_file_hash(f)
                hash_groups[h].append(f)
            except OSError as err:
                logger.debug("Error hashing %s: %s", f, err)

        for matching_files in hash_groups.values():
            if len(matching_files) > 1:
                # Keep the first one (typically shorter name / lower counter)
                original = matching_files[0]
                for dup in matching_files[1:]:
                    duplicates.append((dup, original))

    return duplicates


def find_redundant_part_files(target_dir: Path) -> list[Path]:
    """Identify .part files whose completed file already exists in the same directory."""
    if not target_dir.exists():
        return []

    redundant: list[Path] = []
    import json

    for p in target_dir.iterdir():
        if p.name.endswith(".part.meta"):
            part_file = p.with_suffix("")  # drops .meta -> .part
            if not part_file.exists():
                redundant.append(p)
                continue

            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
                total_size = data.get("total_size", 0)
                if total_size > 0:
                    # Check if any completed file in target_dir matches this total_size
                    for comp in target_dir.iterdir():
                        if (
                            comp.is_file()
                            and not comp.name.endswith(".part")
                            and not comp.name.endswith(".part.meta")
                            and comp.stat().st_size == total_size
                        ):
                            redundant.append(part_file)
                            redundant.append(p)
                            break
            except Exception:
                pass

    return list(set(redundant))


def purge_duplicates(target_dir: Path, dry_run: bool = False) -> list[Path]:
    """Purge duplicate completed files and redundant partial files from target directory.

    Returns:
        list[Path]: List of deleted file paths.
    """
    dups = find_duplicate_files(target_dir)
    redundant_parts = find_redundant_part_files(target_dir)

    removed: list[Path] = []

    for dup_file, orig_file in dups:
        logger.info("Purging duplicate: %s (original: %s)", dup_file.name, orig_file.name)
        if not dry_run:
            try:
                dup_file.unlink()
                removed.append(dup_file)
            except OSError as e:
                logger.warning("Failed to delete %s: %s", dup_file, e)
        else:
            removed.append(dup_file)

    for part_p in redundant_parts:
        logger.info("Purging redundant part file: %s", part_p.name)
        if not dry_run:
            try:
                if part_p.exists():
                    part_p.unlink()
                    removed.append(part_p)
            except OSError as e:
                logger.warning("Failed to delete %s: %s", part_p, e)
        else:
            removed.append(part_p)

    return removed
