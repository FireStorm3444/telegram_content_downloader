"""Tests for sequential course renamer, title cleaner, and duplicate cleanup."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from telethon.tl import types

from tg_downloader.core.renamer import ChannelRenamer
from tg_downloader.utils.title_cleaner import (
    clean_title,
    extract_lecture_tag,
    extract_title_from_caption,
    format_sequence_name,
    is_truncated_title,
)


def test_clean_title() -> None:
    raw = "@BIJzLI_Module_2_by_Anjali_Lecture_14B_：_Percentage_change_Prac_@itzAnandXD"
    cleaned = clean_title(raw)
    assert "@" not in cleaned
    assert "itzAnandXD" not in cleaned
    assert "BIJzLI" not in cleaned
    assert "Lecture_14B" in cleaned or "Lecture 14B" in cleaned

    html_raw = "Lecture_1_Speed_Time_&amp;_Distance"
    assert clean_title(html_raw) == "Lecture 1 Speed Time & Distance"


def test_is_truncated_title() -> None:
    assert is_truncated_title("@BIJZLI_Aptitude_Lectures_Annotated_Notes_Lectu") is True
    assert is_truncated_title("@BIJZLI_Aptitude_Lectures_Annotated_Notes_Lectu (14).pdf") is True
    assert is_truncated_title("012_Verbal_Aptitude_English_Grammar_Part_1.mp4") is False
    assert is_truncated_title("Lecture_14B_Percentage_Change.pdf") is False


def test_extract_lecture_tag() -> None:
    assert extract_lecture_tag("Module 2 Lecture 14B Practice") == "Module_2_Lecture_14B"
    assert extract_lecture_tag("Lecture_23_Adversarial_Search") == "Lecture_23"
    assert extract_lecture_tag("Introductory Session") is None


def test_format_sequence_name() -> None:
    name_video = format_sequence_name(1, "Verbal Aptitude Part 1", ".mp4", prefix_digits=3)
    assert name_video == "001_Verbal Aptitude Part 1.mp4"

    name_notes = format_sequence_name(
        1, "Verbal Aptitude Part 1", ".pdf", prefix_digits=3, is_notes=True
    )
    assert "Notes" in name_notes
    assert name_notes.endswith(".pdf")


def test_format_sequence_name_prevents_double_extension() -> None:
    res = format_sequence_name(140, "Lecture 14 Gradient Descent.mp4", ".mp4")
    assert res == "140_Lecture 14 Gradient Descent.mp4"
    assert not res.endswith(".mp4.mp4")


def test_extract_title_from_caption() -> None:
    caption_ml = """——— ✦ 1030 ✦ ———

• Introduction to Machine Learning

• Lecture 0   Intro to the Course

• Machine Learning

GATE CSE + DA Complete Course 2026

OWNER : @VAIRNXX❤️"""
    assert extract_title_from_caption(caption_ml) == "Lecture 0 Intro to the Course"

    caption_notes = """——— ✦ 1032 ✦ ———

• Introduction to Machine Learning

• Annotated Notes Lecture 1 Introduction Machine Learning in Layman Terms

• Machine Learning

GATE CSE + DA Complete Course 2026

OWNER : @VAIRNXX❤️"""
    assert (
        extract_title_from_caption(caption_notes)
        == "Annotated Notes Lecture 1 Introduction Machine Learning in Layman Terms"
    )


def test_find_topic_directories(tmp_path: Path) -> None:
    client = MagicMock()
    renamer = ChannelRenamer(client)

    course_dir = tmp_path / "Goclasses Gate DA"
    topic_dir = course_dir / "Aptitude"
    topic_dir.mkdir(parents=True)

    topics_map = {10: "Aptitude", 20: "Machine Learning"}

    # Test searching from root tmp_path
    found = renamer.find_topic_directories(
        base_dir=tmp_path,
        channel_title="Goclasses Gate DA",
        topics_map=topics_map,
        is_forum=True,
    )
    assert len(found) == 1
    assert found[0][0] == 10
    assert found[0][1] == "Aptitude"
    assert found[0][2] == topic_dir


@pytest.mark.asyncio
async def test_create_plan_and_apply(tmp_path: Path) -> None:
    topic_dir = tmp_path / "Aptitude"
    topic_dir.mkdir()

    # Create dummy local files
    video_file = topic_dir / "random_video.mp4"
    video_file.write_bytes(b"VIDEO_CONTENT_12345")
    video_size = video_file.stat().st_size

    notes_file = topic_dir / "@BIJZLI_Aptitude_Notes_Lectu (1).pdf"
    notes_file.write_bytes(b"NOTES_CONTENT_67890")
    notes_size = notes_file.stat().st_size

    # Duplicate of notes file
    dup_notes = topic_dir / "@BIJZLI_Aptitude_Notes_Lectu (2).pdf"
    dup_notes.write_bytes(b"NOTES_CONTENT_67890")

    # Mock Telegram messages
    client = MagicMock()

    # Message 1: Video
    msg1 = MagicMock(spec=types.Message)
    msg1.id = 101
    msg1.message = "Lecture 1: Introduction to Grammar"
    doc1 = MagicMock(spec=types.Document)
    doc1.size = video_size
    doc1.mime_type = "video/mp4"
    doc1.attributes = [types.DocumentAttributeFilename("lecture1.mp4")]
    media1 = MagicMock(spec=types.MessageMediaDocument)
    media1.document = doc1
    msg1.media = media1

    # Message 2: Notes (truncated name)
    msg2 = MagicMock(spec=types.Message)
    msg2.id = 102
    msg2.message = ""  # empty caption
    doc2 = MagicMock(spec=types.Document)
    doc2.size = notes_size
    doc2.mime_type = "application/pdf"
    doc2.attributes = [types.DocumentAttributeFilename("@BIJZLI_Aptitude_Notes_Lectu.pdf")]
    media2 = MagicMock(spec=types.MessageMediaDocument)
    media2.document = doc2
    msg2.media = media2

    async def _mock_iter_messages(*args, **kwargs):
        for m in [msg1, msg2]:
            yield m

    client.iter_messages = _mock_iter_messages

    renamer = ChannelRenamer(client)
    plan = await renamer.create_plan_for_topic(
        entity=MagicMock(),
        topic_id=1,
        topic_name="Aptitude",
        topic_dir=topic_dir,
        prefix_digits=3,
        purge_duplicates=True,
    )

    # 2 active candidates + 1 duplicate candidate
    assert len(plan.candidates) == 3

    video_cand = next(c for c in plan.candidates if c.local_path == video_file)
    assert video_cand.new_name.startswith("001_")
    assert "Introduction" in video_cand.new_name or "Grammar" in video_cand.new_name
    assert video_cand.new_name.endswith(".mp4")

    notes_cand = next(c for c in plan.candidates if c.local_path == notes_file)
    assert notes_cand.new_name.startswith("001_")
    assert "Notes" in notes_cand.new_name
    assert notes_cand.new_name.endswith(".pdf")

    dup_cand = next(c for c in plan.candidates if c.is_duplicate)
    assert dup_cand.local_path == dup_notes

    # Execute apply plan
    renamed, purged = ChannelRenamer.apply_plan(plan, purge_duplicates=True)
    assert renamed == 2
    assert purged == 1
    assert not dup_notes.exists()
    assert (topic_dir / video_cand.new_name).exists()
    assert (topic_dir / notes_cand.new_name).exists()
