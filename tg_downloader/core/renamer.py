"""Channel and forum sequential renamer engine for downloaded Telegram media."""

import contextlib
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from telethon import TelegramClient
from telethon.tl import types

from tg_downloader.core.scraper import ChannelScraper
from tg_downloader.utils.dedup import find_duplicate_files
from tg_downloader.utils.filename import sanitize_filename
from tg_downloader.utils.media import get_media_filename, get_media_size, get_media_type
from tg_downloader.utils.title_cleaner import (
    clean_title,
    extract_title_from_caption,
    format_sequence_name,
    is_truncated_title,
)

logger = logging.getLogger(__name__)


@dataclass
class RenameCandidate:
    """Represents a proposed file renaming operation."""

    local_path: Path
    new_name: str
    file_size: int
    topic_name: str
    message_id: int | None
    is_duplicate: bool = False
    duplicate_of: Path | None = None
    reason: str = ""


@dataclass
class TopicRenamePlan:
    """Execution plan for reorganizing and renaming files within a topic or folder."""

    topic_name: str
    topic_dir: Path
    candidates: list[RenameCandidate] = field(default_factory=list)
    unmatched_files: list[Path] = field(default_factory=list)
    duplicate_pairs: list[tuple[Path, Path]] = field(default_factory=list)


class ChannelRenamer:
    """Orchestrates scanning local files, matching against Telegram topic history, and applying renames."""

    def __init__(self, client: TelegramClient) -> None:
        self.client = client
        self.scraper = ChannelScraper(client)

    def find_topic_directories(
        self,
        base_dir: Path,
        channel_title: str,
        topics_map: dict[int, str],
        is_forum: bool,
    ) -> list[tuple[int | None, str, Path]]:
        """Identify corresponding directories on disk for channel topics.

        Returns:
            list[tuple[topic_id, topic_title, directory_path]]
        """
        results: list[tuple[int | None, str, Path]] = []
        clean_chat = sanitize_filename(channel_title)

        if not is_forum:
            # Single channel folder
            cand_paths = [
                base_dir / clean_chat,
                base_dir,
            ]
            for p in cand_paths:
                if p.exists() and p.is_dir():
                    results.append((None, channel_title, p))
                    break
            return results

        # Forum supergroup: search per topic
        for topic_id, topic_title in topics_map.items():
            clean_topic = sanitize_filename(topic_title)
            candidates = [
                base_dir / clean_topic,
                base_dir / clean_chat / clean_topic,
                base_dir,  # in case base_dir is already the topic folder
            ]
            for cand in candidates:
                if (
                    cand.exists()
                    and cand.is_dir()
                    and (
                        cand.name.lower() == clean_topic.lower()
                        or cand == base_dir / clean_topic
                        or cand == base_dir / clean_chat / clean_topic
                    )
                ):
                    results.append((topic_id, topic_title, cand))
                    break

        return results

    async def create_plan_for_topic(
        self,
        entity: Any,
        topic_id: int | None,
        topic_name: str,
        topic_dir: Path,
        prefix_digits: int = 3,
        purge_duplicates: bool = True,
    ) -> TopicRenamePlan:
        """Scan local files in topic_dir, fetch Telegram topic messages, and create rename plan."""
        plan = TopicRenamePlan(topic_name=topic_name, topic_dir=topic_dir)

        if not topic_dir.exists():
            return plan

        # Step 1: Detect duplicate files using content fingerprints
        dup_pairs = find_duplicate_files(topic_dir)
        plan.duplicate_pairs = dup_pairs
        duplicate_files = {dup for dup, _ in dup_pairs}

        # Step 2: Index non-duplicate local media files by byte size
        files_by_size: dict[int, list[Path]] = defaultdict(list)
        all_local_files: list[Path] = []

        for p in topic_dir.iterdir():
            if not p.is_file():
                continue
            if p.name.endswith(".part") or p.name.endswith(".part.meta"):
                continue

            all_local_files.append(p)
            if p in duplicate_files:
                continue

            size = p.stat().st_size
            if size > 0:
                files_by_size[size].append(p)

        # Sort paths within each size bucket by length and name for determinism
        for s in files_by_size:
            files_by_size[s].sort(key=lambda x: (len(x.name), x.name))

        # Step 3: Fetch topic messages from Telegram in chronological order
        kwargs: dict[str, Any] = {"reverse": True}
        if topic_id is not None:
            kwargs["reply_to"] = topic_id

        matched_paths: set[Path] = set()
        seq_counter = 1
        last_video_title: str | None = None
        last_video_seq: int | None = None

        async for msg in self.client.iter_messages(entity, **kwargs):
            if not isinstance(msg, types.Message) or not msg.media:
                continue

            size = get_media_size(msg)
            m_type = get_media_type(msg)
            if size <= 0 or not m_type:
                continue

            # Check if this message's media matches an existing local file
            if size not in files_by_size or not files_by_size[size]:
                continue

            local_file = files_by_size[size].pop(0)
            matched_paths.add(local_file)

            # Determine human-readable title from caption or file attributes
            caption = (msg.message or "").strip()
            caption_title = extract_title_from_caption(caption)

            # Check document attribute filename
            attr_filename: str | None = None
            if isinstance(msg.media, types.MessageMediaDocument) and isinstance(
                msg.media.document, types.Document
            ):
                for attr in msg.media.document.attributes:
                    if isinstance(attr, types.DocumentAttributeFilename):
                        attr_filename = attr.file_name

            raw_fallback = attr_filename or get_media_filename(msg)
            raw_fallback_stem = (
                raw_fallback.rsplit(".", 1)[0] if "." in raw_fallback else raw_fallback
            )
            is_truncated = is_truncated_title(raw_fallback)

            is_video = m_type == "video"
            is_notes = m_type in ("pdf", "document")

            if is_video:
                # Video file: prioritize caption title if available, else cleaned filename
                if caption_title:
                    item_title = caption_title
                    reason = "Matched video with syllabus caption"
                else:
                    item_title = clean_title(raw_fallback_stem)
                    reason = "Matched video from chronological syllabus"

                last_video_title = item_title
                last_video_seq = seq_counter
                target_seq = seq_counter
                seq_counter += 1

                new_name = format_sequence_name(
                    seq_index=target_seq,
                    base_title=item_title,
                    extension=local_file.suffix,
                    prefix_digits=prefix_digits,
                    is_notes=False,
                )

            elif is_notes:
                # Notes/PDF file: check caption title first, then paired lecture, then attribute
                if caption_title:
                    item_title = caption_title
                    target_seq = seq_counter
                    seq_counter += 1
                    reason = "Matched notes with syllabus caption"
                elif is_truncated and last_video_title and last_video_seq is not None:
                    # Inherit title and sequence from paired lecture video
                    item_title = last_video_title
                    target_seq = last_video_seq
                    reason = f"Inherited lecture title from video (Seq {target_seq})"
                else:
                    # Non-truncated or standalone document
                    item_title = clean_title(raw_fallback_stem)
                    target_seq = seq_counter
                    seq_counter += 1
                    reason = "Matched standalone document"

                new_name = format_sequence_name(
                    seq_index=target_seq,
                    base_title=item_title,
                    extension=local_file.suffix,
                    prefix_digits=prefix_digits,
                    is_notes=True,
                )

            else:
                # Other media (photos, audio)
                item_title = caption_title if caption_title else clean_title(raw_fallback_stem)
                target_seq = seq_counter
                seq_counter += 1
                new_name = format_sequence_name(
                    seq_index=target_seq,
                    base_title=item_title,
                    extension=local_file.suffix,
                    prefix_digits=prefix_digits,
                    is_notes=False,
                )
                reason = f"Matched {m_type} media"

            plan.candidates.append(
                RenameCandidate(
                    local_path=local_file,
                    new_name=new_name,
                    file_size=size,
                    topic_name=topic_name,
                    message_id=msg.id,
                    reason=reason,
                )
            )

        # Step 4: Record duplicate candidates
        for dup, orig in dup_pairs:
            plan.candidates.append(
                RenameCandidate(
                    local_path=dup,
                    new_name="<PURGE_DUPLICATE>",
                    file_size=dup.stat().st_size if dup.exists() else 0,
                    topic_name=topic_name,
                    message_id=None,
                    is_duplicate=True,
                    duplicate_of=orig,
                    reason=f"Redundant duplicate copy of {orig.name}",
                )
            )

        # Step 5: Record unmatched files
        for f in all_local_files:
            if f not in matched_paths and f not in duplicate_files:
                plan.unmatched_files.append(f)

        return plan

    @staticmethod
    def apply_plan(plan: TopicRenamePlan, purge_duplicates: bool = True) -> tuple[int, int]:
        """Execute proposed rename operations and duplicate purges safely.

        Returns:
            tuple[renamed_count, purged_count]
        """
        renamed_count = 0
        purged_count = 0

        # Step A: Purge duplicates
        if purge_duplicates:
            for cand in plan.candidates:
                if cand.is_duplicate and cand.local_path.exists():
                    try:
                        cand.local_path.unlink()
                        purged_count += 1
                        logger.info("Purged duplicate: %s", cand.local_path.name)
                    except OSError as e:
                        logger.warning("Failed to delete duplicate %s: %s", cand.local_path, e)

        # Step B: Perform two-pass rename to avoid collision conflicts
        active_candidates = [
            c for c in plan.candidates if not c.is_duplicate and c.local_path.exists()
        ]
        temp_renames: list[tuple[Path, Path, Path]] = []

        # Pass 1: rename to temporary names if target already exists with different inode
        for idx, cand in enumerate(active_candidates):
            target_path = plan.topic_dir / cand.new_name
            if target_path == cand.local_path:
                continue

            temp_path = plan.topic_dir / f".tmp_rename_{idx}_{cand.local_path.name}"
            try:
                cand.local_path.rename(temp_path)
                temp_renames.append((temp_path, target_path, cand.local_path))
            except OSError as e:
                logger.error("Failed temporary rename of %s: %s", cand.local_path, e)

        # Pass 2: rename from temporary names to final target names
        for temp_path, target_path, original_path in temp_renames:
            try:
                temp_path.rename(target_path)
                renamed_count += 1
                logger.info("Renamed: %s -> %s", original_path.name, target_path.name)
            except OSError as e:
                logger.error("Failed final rename %s -> %s: %s", temp_path, target_path, e)
                # Attempt rollback to original name
                if temp_path.exists():
                    with contextlib.suppress(OSError):
                        temp_path.rename(original_path)

        return renamed_count, purged_count
