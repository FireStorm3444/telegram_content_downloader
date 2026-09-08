"""Tests for DownloadUI progress tracking and columns."""

import io

from rich.console import Console
from rich.progress import Progress, TaskProgressColumn

from tg_downloader.ui.progress import (
    DownloadUI,
    SmartDownloadColumn,
    SmartTimeRemainingColumn,
    SmartTransferSpeedColumn,
)


def test_smart_columns_rendering() -> None:
    """Test custom columns behavior for batch vs individual file tasks."""
    dl_col = SmartDownloadColumn()
    speed_col = SmartTransferSpeedColumn()
    time_col = SmartTimeRemainingColumn()
    pct_col = TaskProgressColumn(text_format="[bold cyan]{task.percentage:>5.1f}%")

    progress = Progress(dl_col, speed_col, time_col, pct_col)

    # Batch task
    batch_task_id = progress.add_task("Batch", total=10, completed=3, is_batch=True)
    batch_task = progress._tasks[batch_task_id]

    rendered_dl = dl_col.render(batch_task).plain
    assert rendered_dl == "3/10 files"
    assert speed_col.render(batch_task).plain == ""
    assert time_col.render(batch_task).plain == ""
    assert pct_col.render(batch_task).plain == " 30.0%"

    # File task
    file_task_id = progress.add_task(
        "File", total=100_000_000, completed=45_200_000, is_batch=False
    )
    file_task = progress._tasks[file_task_id]

    assert "MB" in dl_col.render(file_task).plain
    assert pct_col.render(file_task).plain == " 45.2%"


def test_download_ui_single_file() -> None:
    """Test DownloadUI when downloading a single file (not a group)."""
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, color_system=None)
    ui = DownloadUI(console=console)

    ui.start_batch(total_files=1, title="Single Post", is_group=False)
    assert ui._is_group is False
    assert ui._batch_task is None

    ui.start_file("test_video.mp4", 1000)
    assert ui._current_file_task is not None
    task = ui.progress._tasks[ui._current_file_task]
    assert task.total == 1000
    assert task.completed == 0

    # Update file progress to 50%
    ui.update_file_progress(500, 1000)
    assert task.percentage == 50.0

    ui.complete_file("test_video.mp4", 1000)
    assert ui._current_file_task is None
    assert ui._files_downloaded == 1

    ui.finish_batch()

    output = buf.getvalue()
    assert "✓ Downloaded: test_video.mp4" in output
    # Ensure no group progress badge for single file
    assert "[1/1 -" not in output
    assert "Download Summary" in output


def test_download_ui_group_progress() -> None:
    """Test DownloadUI when downloading a group with multiple files."""
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, color_system=None)
    ui = DownloadUI(console=console)

    ui.start_batch(total_files=4, title="Scraping Channel", is_group=True)
    assert ui._is_group is True
    assert ui._batch_task is not None
    batch_task = ui.progress._tasks[ui._batch_task]
    assert batch_task.total == 4
    assert batch_task.completed == 0

    # File 1: Downloaded
    ui.start_file("file1.mp4", 1000)
    ui.update_file_progress(750, 1000)
    assert ui._current_file_task is not None
    task1 = ui.progress._tasks[ui._current_file_task]
    assert task1.percentage == 75.0
    ui.complete_file("file1.mp4", 1000)

    assert batch_task.completed == 1
    assert batch_task.percentage == 25.0

    # File 2: Skipped
    ui.start_file("file2.mp4", 2000)
    ui.complete_file("file2.mp4", 2000, skipped=True)
    assert batch_task.completed == 2
    assert batch_task.percentage == 50.0

    # File 3: Failed
    ui.start_file("file3.mp4", 3000)
    ui.fail_file("file3.mp4", "Connection dropped")
    assert batch_task.completed == 3
    assert batch_task.percentage == 75.0

    # File 4: Downloaded
    ui.start_file("file4.mp4", 4000)
    ui.complete_file("file4.mp4", 4000)
    assert batch_task.completed == 4
    assert batch_task.percentage == 100.0

    ui.finish_batch()

    output = buf.getvalue()
    # Verify group progress badges in logs
    assert "✓ Downloaded: file1.mp4" in output
    assert "[1/4 - 25.0%]" in output
    assert "↷ Skipped: file2.mp4" in output
    assert "[2/4 - 50.0%]" in output
    assert "✗ Failed: file3.mp4" in output
    assert "[3/4 - 75.0%]" in output
    assert "✓ Downloaded: file4.mp4" in output
    assert "[4/4 - 100.0%]" in output

    # Verify batch summary table contents
    assert "Download Batch Summary" in output
    assert "Total Files in Group" in output
    assert "2/4 (50.0%)" in output


def test_download_ui_is_group_default() -> None:
    """Test default inference of is_group flag from total_files."""
    ui1 = DownloadUI()
    ui1.start_batch(total_files=5)
    assert ui1._is_group is True
    assert ui1._batch_task is not None
    ui1.finish_batch()

    ui2 = DownloadUI()
    ui2.start_batch(total_files=1)
    assert ui2._is_group is False
    assert ui2._batch_task is None
    ui2.finish_batch()
