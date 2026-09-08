"""Rich multi-bar progress UI for real-time file speeds, ETAs, and batch progress."""

import time

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    Task,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table
from rich.text import Text

from tg_downloader.utils.formatting import format_bytes, format_duration, format_speed


class SmartDownloadColumn(DownloadColumn):
    """Custom download column formatting files count for batch tasks and bytes for file tasks."""

    def render(self, task: Task) -> Text:
        if task.fields.get("is_batch"):
            return Text(
                f"{int(task.completed)}/{int(task.total or 0)} files",
                style="progress.download",
            )
        return super().render(task)


class SmartTransferSpeedColumn(TransferSpeedColumn):
    """Custom speed column hiding throughput for batch tasks."""

    def render(self, task: Task) -> Text:
        if task.fields.get("is_batch"):
            return Text("")
        return super().render(task)


class SmartTimeRemainingColumn(TimeRemainingColumn):
    """Custom ETA column hiding remaining time for batch tasks."""

    def render(self, task: Task) -> Text:
        if task.fields.get("is_batch"):
            return Text("")
        return super().render(task)


class DownloadUI:
    """Manages multi-bar visual progress tracking and formatted batch summaries."""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()
        self.progress = Progress(
            SpinnerColumn(spinner_name="dots"),
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(bar_width=30, complete_style="green", finished_style="bold green"),
            TaskProgressColumn(text_format="[bold cyan]{task.percentage:>5.1f}%"),
            SmartDownloadColumn(),
            SmartTransferSpeedColumn(),
            SmartTimeRemainingColumn(),
            console=self.console,
            transient=False,
        )
        self._batch_task: TaskID | None = None
        self._current_file_task: TaskID | None = None
        self._total_bytes_downloaded = 0
        self._files_downloaded = 0
        self._files_skipped = 0
        self._files_failed = 0
        self._total_files = 0
        self._is_group = False
        self._start_time = 0.0

    def start_batch(
        self,
        total_files: int,
        title: str = "Batch Download",
        is_group: bool | None = None,
    ) -> None:
        """Initialize and start the batch progress tracking session."""
        self._start_time = time.perf_counter()
        self._total_bytes_downloaded = 0
        self._files_downloaded = 0
        self._files_skipped = 0
        self._files_failed = 0
        self._total_files = total_files
        self._is_group = (total_files > 1) if is_group is None else is_group

        self.progress.start()
        if self._is_group:
            self._batch_task = self.progress.add_task(
                f"[bold yellow]{title}",
                total=total_files,
                completed=0,
                is_batch=True,
            )
        else:
            self._batch_task = None

    def start_file(self, filename: str, total_bytes: int) -> None:
        """Add a progress task for an individual downloading file."""
        display_name = filename if len(filename) <= 30 else f"{filename[:27]}..."
        self._current_file_task = self.progress.add_task(
            f"[white]{display_name}",
            total=total_bytes,
            completed=0,
            is_batch=False,
        )

    def update_file_progress(self, current_bytes: int, total_bytes: int) -> None:
        """Update downloaded byte progress on the active file bar."""
        if self._current_file_task is not None:
            self.progress.update(
                self._current_file_task,
                completed=current_bytes,
                total=total_bytes,
            )

    def complete_file(self, filename: str, file_bytes: int, skipped: bool = False) -> None:
        """Mark the active file as complete or skipped and update batch counter."""
        if self._current_file_task is not None:
            self.progress.update(
                self._current_file_task,
                completed=file_bytes,
                visible=False,
            )
            self.progress.remove_task(self._current_file_task)
            self._current_file_task = None

        if skipped:
            self._files_skipped += 1
        else:
            self._files_downloaded += 1
            self._total_bytes_downloaded += file_bytes

        if self._batch_task is not None:
            self.progress.advance(self._batch_task, 1)

        progress_suffix = ""
        if self._is_group and self._total_files > 0:
            processed = self._files_downloaded + self._files_skipped + self._files_failed
            pct = (processed / self._total_files) * 100.0
            progress_suffix = f" [bold cyan][{processed}/{self._total_files} - {pct:.1f}%][/]"

        if skipped:
            self.console.print(
                f"[yellow]↷ Skipped:[/] {filename} (already exists){progress_suffix}"
            )
        else:
            self.console.print(
                f"[green]✓ Downloaded:[/] {filename} [dim]({format_bytes(file_bytes)})[/]{progress_suffix}"
            )

    def fail_file(self, filename: str, error_message: str) -> None:
        """Record a failed file transfer and advance batch progress."""
        if self._current_file_task is not None:
            self.progress.remove_task(self._current_file_task)
            self._current_file_task = None

        self._files_failed += 1

        if self._batch_task is not None:
            self.progress.advance(self._batch_task, 1)

        progress_suffix = ""
        if self._is_group and self._total_files > 0:
            processed = self._files_downloaded + self._files_skipped + self._files_failed
            pct = (processed / self._total_files) * 100.0
            progress_suffix = f" [bold cyan][{processed}/{self._total_files} - {pct:.1f}%][/]"

        self.console.print(
            f"[red]✗ Failed:[/] {filename} - [dim]{error_message}[/]{progress_suffix}"
        )

    def finish_batch(self) -> None:
        """Stop progress bars and render final summary statistics table."""
        self.progress.stop()
        elapsed = max(0.001, time.perf_counter() - self._start_time)
        avg_speed = self._total_bytes_downloaded / elapsed

        title = "Download Batch Summary" if self._is_group else "Download Summary"
        table = Table(title=title, show_header=True, header_style="bold cyan")
        table.add_column("Metric", style="bold")
        table.add_column("Value", style="green")

        total_processed = self._files_downloaded + self._files_skipped + self._files_failed
        if self._is_group and self._total_files > 0:
            pct = (self._files_downloaded / self._total_files) * 100.0
            table.add_row("Total Files in Group", str(self._total_files))
            table.add_row(
                "Files Processed",
                f"{total_processed}/{self._total_files}",
            )
            table.add_row(
                "Files Downloaded",
                f"[bold green]{self._files_downloaded}/{self._total_files} ({pct:.1f}%)[/]",
            )
        else:
            table.add_row("Total Files Processed", str(total_processed))
            table.add_row("Files Downloaded", f"[bold green]{self._files_downloaded}[/]")

        table.add_row("Files Skipped", f"[yellow]{self._files_skipped}[/]")
        table.add_row(
            "Files Failed", f"[red]{self._files_failed}[/]" if self._files_failed > 0 else "0"
        )
        table.add_row("Total Data Downloaded", format_bytes(self._total_bytes_downloaded))
        table.add_row("Total Elapsed Time", format_duration(elapsed))
        table.add_row("Average Throughput", format_speed(avg_speed))

        self.console.print()
        self.console.print(Panel(table, border_style="cyan"))
