"""Utilities for cleaning promotional watermarks, resolving truncated titles, and formatting filenames."""

import html
import re

from tg_downloader.utils.filename import sanitize_filename

# Regex to match Telegram @channel_names or @usernames (alphanumeric handles)
TELEGRAM_TAG_REGEX = re.compile(r"@[a-zA-Z0-9]+")

# Regex to match URLs
URL_REGEX = re.compile(r"https?://\S+|t\.me/\S+")

# Regex to detect truncated lecture tails (e.g. '_Lectu', '_Lect', '_Notes_Lectu')
TRUNCATED_TAIL_REGEX = re.compile(
    r"(?:_|^)(?:Annotated_)?Notes_Lectu(?:r(?:e)?)?$|(?:_|^)Lectu(?:r)?$", re.IGNORECASE
)

# Regex to detect common lecture/module indicators (e.g. 'Lecture 14B', 'Lecture_23')
LECTURE_PATTERN = re.compile(
    r"(?:Module[_\s]+(\d+)[_\s]+)?(?:Lecture|Lec)[_\s]+(\d+[A-Za-z]?)", re.IGNORECASE
)


def is_truncated_title(name: str) -> bool:
    """Check if a filename or title ends abruptly due to Telegram's 64-char attribute limit."""
    stem = name.rsplit(".", 1)[0] if "." in name else name
    # Strip trailing numbers like (1), (2)
    clean_stem = re.sub(r"\s*\(\d+\)$", "", stem).strip()
    return bool(TRUNCATED_TAIL_REGEX.search(clean_stem))


def clean_title(raw_title: str, max_length: int = 150) -> str:
    """Clean promotional watermarks, decode HTML entities, and normalize spacing for a title."""
    if not raw_title:
        return "Untitled"

    # Decode HTML entities like &amp; -> &
    text = html.unescape(raw_title)

    # Remove URLs and promotional Telegram tags
    text = URL_REGEX.sub(" ", text)
    text = TELEGRAM_TAG_REGEX.sub(" ", text)

    # Replace special separators (fullwidth colons, pipes, slashes) with dashes
    text = re.sub(r"[\uff1a:|\/\\]+", " - ", text)

    # Normalize underscores and whitespaces to single spaces
    text = re.sub(r"[_\s]+", " ", text).strip(" -_")

    # If title has become empty after stripping tags
    if not text:
        text = "Lecture"

    # Sanitize and truncate to safe filesystem length
    sanitized = sanitize_filename(text, max_length=max_length)
    return sanitized


def extract_title_from_caption(caption: str | None) -> str | None:
    """Extract descriptive course lecture/notes title from Telegram message caption.

    Bypasses automated counter banners ('——— ✦ 1030 ✦ ———'), extracts structured
    bulleted items ('• Lecture 1A ...'), and strips promotional channel footers.
    """
    if not caption or not caption.strip():
        return None

    bullet_lines: list[str] = []
    plain_lines: list[str] = []

    for line in caption.split("\n"):
        clean = line.strip()
        if not clean:
            continue

        # Skip decorative banners, dividers, and bot counters
        if any(token in clean for token in ("✦", "———", "===", "***", "~~~")):
            continue

        # Skip promotional channel footers and external links
        if any(
            token in clean.upper()
            for token in ("OWNER :", "GATE CSE", "COMPLETE COURSE", "BEST WATCHED ON YOUTUBE")
        ):
            continue
        if clean.startswith("http://") or clean.startswith("https://"):
            continue

        # Collect bulleted lines
        if clean.startswith("•") or clean.startswith("-"):
            stripped = clean.lstrip("•- ").strip()
            if stripped and not stripped.lower().startswith("watch video"):
                bullet_lines.append(stripped)
        else:
            plain_lines.append(clean)

    # If structured bullet points exist
    if bullet_lines:
        if len(bullet_lines) >= 2:
            module = bullet_lines[0]
            item = bullet_lines[1]

            # If item is just generic course topic name, use module
            if item.lower() in (
                "machine learning",
                "aptitude",
                "artificial intelligence",
                "python",
                "gate",
            ):
                return clean_title(module)

            # If module is specific (e.g. 'Module 1 - Propositional Logic'), prepend it
            if re.match(r"^Module\s+\d+", module, re.IGNORECASE):
                mod_tag = re.match(r"^(Module\s+\d+)", module, re.IGNORECASE)
                mod_prefix = mod_tag.group(1) if mod_tag else module
                return clean_title(f"{mod_prefix} - {item}")

            # If module is 'Statistics-Summary-Lectures' or 'Quizzes'
            if any(
                keyword in module.lower()
                for keyword in ("statistics", "summary", "quiz", "student notes", "project")
            ):
                return clean_title(f"{module} - {item}")

            # Otherwise, item itself has full lecture title
            return clean_title(item)

        return clean_title(bullet_lines[0])

    # Fallback: use first clean non-banner line
    if plain_lines:
        return clean_title(plain_lines[0])

    return None


def extract_lecture_tag(title: str) -> str | None:
    """Extract and normalize lecture/module tags like 'Lecture_14B' or 'Module_1_Lecture_02'."""
    m = LECTURE_PATTERN.search(title)
    if not m:
        return None

    module_part = f"Module_{m.group(1)}_" if m.group(1) else ""
    lec_num = m.group(2).replace(" ", "_")
    return f"{module_part}Lecture_{lec_num}"


def format_sequence_name(
    seq_index: int,
    base_title: str,
    extension: str,
    prefix_digits: int = 3,
    is_notes: bool = False,
) -> str:
    """Construct a clean, zero-padded, standardized sequential filename."""
    prefix = f"{seq_index:0{prefix_digits}d}"
    clean = clean_title(base_title)

    # Strip any existing leading sequence numbers from clean title (e.g. '012_...')
    clean = re.sub(r"^\d+[\s._-]+", "", clean).strip()

    # Strip extension from clean title if already present (prevents .mp4.mp4)
    ext = extension.lstrip(".")
    if ext and clean.lower().endswith(f".{ext.lower()}"):
        clean = clean[: -(len(ext) + 1)].rstrip(" ._")

    for common_ext in ("mp4", "mkv", "pdf", "webm", "avi", "mov"):
        if clean.lower().endswith(f".{common_ext}"):
            clean = clean[: -(len(common_ext) + 1)].rstrip(" ._")

    # Append _Notes if marked and not already present
    if is_notes and "notes" not in clean.lower():
        clean = f"{clean} - Notes"

    final_name = f"{prefix}_{clean}.{ext}" if ext else f"{prefix}_{clean}"
    return sanitize_filename(final_name)
