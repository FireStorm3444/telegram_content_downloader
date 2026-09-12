"""Command-Line Interface for the High-Performance Telegram Media Downloader."""

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from telethon.tl import types

from tg_downloader.config import Settings
from tg_downloader.core.auth import AuthManager
from tg_downloader.core.client import create_telegram_client
from tg_downloader.core.errors import TGDownloaderError
from tg_downloader.core.renamer import ChannelRenamer, TopicRenamePlan
from tg_downloader.core.resolver import TargetResolver
from tg_downloader.core.scraper import ChannelScraper, ScrapeFilter
from tg_downloader.engine.parallel import ParallelDownloader
from tg_downloader.engine.resilience import ResilienceManager
from tg_downloader.ui.progress import DownloadUI
from tg_downloader.utils.crypto import get_crypto_diagnostics
from tg_downloader.utils.filename import resolve_target_path, sanitize_filename
from tg_downloader.utils.formatting import format_bytes, format_speed, parse_size_str

app = typer.Typer(
    name="tg-downloader",
    help="High-Performance Telegram Media Downloader CLI using MTProto parallel chunk engine.",
    add_completion=False,
)
console = Console()
logger = logging.getLogger("tg_downloader")


def configure_logging(verbose: bool) -> None:
    """Configure console logging level."""
    log_level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@app.command(name="login")
def login_cmd(
    api_id: Annotated[int | None, typer.Option("--api-id", help="Telegram API ID")] = None,
    api_hash: Annotated[str | None, typer.Option("--api-hash", help="Telegram API Hash")] = None,
    phone: Annotated[str | None, typer.Option("--phone", help="Telegram Phone number")] = None,
    session_name: Annotated[
        str, typer.Option("--session-name", help="Custom session name")
    ] = "tg_downloader",
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Enable verbose debug logs")
    ] = False,
) -> None:
    """Authenticate interactively with Telegram and save the session for future downloads."""
    configure_logging(verbose)
    settings = Settings()
    if api_id:
        settings.api_id = api_id
    if api_hash:
        settings.api_hash = api_hash
    if phone:
        settings.phone = phone
    if session_name:
        settings.session_name = session_name

    async def _run() -> None:
        client = create_telegram_client(settings)
        auth = AuthManager(client, settings, console=console)
        try:
            await auth.ensure_authorized()
        finally:
            await client.disconnect()

    try:
        asyncio.run(_run())
    except TGDownloaderError as e:
        console.print(f"[bold red]Authentication Error:[/] {e}")
        raise typer.Exit(code=1) from e
    except Exception as e:
        console.print(f"[bold red]Unexpected Error:[/] {e}")
        raise typer.Exit(code=1) from e


@app.command(name="logout")
def logout_cmd(
    session_name: Annotated[
        str, typer.Option("--session-name", help="Custom session name")
    ] = "tg_downloader",
) -> None:
    """Log out from Telegram and securely remove the local session file."""
    settings = Settings(session_name=session_name)

    async def _run() -> None:
        if not settings.session_path.exists():
            console.print(
                f"[yellow]Session file not found at {settings.session_path}. Already logged out.[/]"
            )
            return

        client = create_telegram_client(settings)
        auth = AuthManager(client, settings, console=console)
        await auth.logout()

    asyncio.run(_run())


@app.command(name="whoami")
def whoami_cmd(
    session_name: Annotated[
        str, typer.Option("--session-name", help="Custom session name")
    ] = "tg_downloader",
) -> None:
    """Display information about the currently authenticated Telegram user."""
    settings = Settings(session_name=session_name)

    async def _run() -> None:
        if not settings.session_path.exists():
            console.print("[yellow]No session found. Run 'tg-downloader login' to authenticate.[/]")
            raise typer.Exit(code=1)

        client = create_telegram_client(settings)
        auth = AuthManager(client, settings, console=console)
        try:
            user = await auth.get_user_info()
            if not user:
                console.print(
                    "[yellow]Session is unauthorized or expired. Run 'tg-downloader login'.[/]"
                )
                raise typer.Exit(code=1)

            table = Table(title="Telegram Authenticated User Profile", show_header=True)
            table.add_column("Property", style="bold cyan")
            table.add_column("Value", style="green")

            table.add_row(
                "Full Name", f"{user.first_name or ''} {user.last_name or ''}".strip() or "N/A"
            )
            table.add_row("Username", f"@{user.username}" if user.username else "None")
            table.add_row("User ID", str(user.id))
            table.add_row("Phone", f"+{user.phone}" if user.phone else "Hidden")
            connected_dc = str(getattr(client.session, "dc_id", "Unknown"))
            table.add_row("Connected DC", connected_dc)
            table.add_row("Session File", str(settings.session_path))

            console.print(Panel(table, border_style="cyan"))
        finally:
            await client.disconnect()

    asyncio.run(_run())


@app.command(name="doctor")
def doctor_cmd() -> None:
    """Run environment and hardware acceleration diagnostics."""
    console.print("[bold cyan]Diagnosing Telegram Downloader Environment...[/]\n")
    diag = get_crypto_diagnostics()

    table = Table(title="Hardware & Cryptographic Diagnostics", show_header=True)
    table.add_column("Component", style="bold cyan")
    table.add_column("Status / Detail", style="white")

    table.add_row("Platform", str(diag["platform"]))
    table.add_row("Python Version", str(diag["python_version"]))
    table.add_row(
        "Native Cryptg Acceleration",
        "[bold green]Installed & Available[/]"
        if diag["cryptg_installed"]
        else "[bold yellow]Not Installed[/]",
    )
    table.add_row("Active AES Backend", str(diag["active_backend"]))
    table.add_row(
        "Hardware Acceleration",
        "[bold green]Active[/]"
        if diag["hardware_accelerated"]
        else "[bold red]Inactive (CPU Bound)[/]",
    )
    bench_speed = diag["benchmark_speed_mb_s"]
    table.add_row(
        "AES-IGE Benchmark Speed",
        f"[bold green]{format_speed(bench_speed * 1024 * 1024)}[/]" if bench_speed > 0 else "N/A",
    )
    table.add_row("Max MTProto Chunk Size", "512 KB (Maximum API Throughput)")

    console.print(Panel(table, border_style="green" if diag["hardware_accelerated"] else "yellow"))


@app.command(name="download")
def download_cmd(
    target: Annotated[
        str, typer.Argument(help="Telegram post link, channel URL, username, or peer ID")
    ],
    output_dir: Annotated[
        Path, typer.Option("--output-dir", "-o", help="Target directory for downloads")
    ] = Path("./downloads"),
    connections: Annotated[
        int, typer.Option("--connections", "-c", min=1, max=16, help="Parallel MTProto connections")
    ] = 4,
    limit: Annotated[
        int | None, typer.Option("--limit", "-n", help="Maximum number of media items to download")
    ] = None,
    media_type: Annotated[
        list[str] | None,
        typer.Option(
            "--media-type",
            "-t",
            help="Media filter: all, video, photo, document, audio, voice, animation, sticker",
        ),
    ] = None,
    extension: Annotated[
        list[str] | None,
        typer.Option(
            "--extension",
            "-e",
            help="Filter by file extension (e.g. pdf, mp4, mkv). Supports multiple -e flags or comma-separated values.",
        ),
    ] = None,
    topic: Annotated[
        str | None,
        typer.Option(
            "--topic",
            help="Filter by topic ID (e.g. 3) or topic title (e.g. 'Machine Learning') in forum supergroups",
        ),
    ] = None,
    min_id: Annotated[int | None, typer.Option("--min-id", help="Minimum message ID")] = None,
    max_id: Annotated[int | None, typer.Option("--max-id", help="Maximum message ID")] = None,
    start_date: Annotated[
        str | None, typer.Option("--start-date", help="Messages on or after date (YYYY-MM-DD)")
    ] = None,
    end_date: Annotated[
        str | None, typer.Option("--end-date", help="Messages on or before date (YYYY-MM-DD)")
    ] = None,
    min_size: Annotated[
        str | None, typer.Option("--min-size", help="Minimum file size (e.g. 10MB, 500KB)")
    ] = None,
    max_size: Annotated[
        str | None, typer.Option("--max-size", help="Maximum file size (e.g. 1GB)")
    ] = None,
    search: Annotated[
        str | None, typer.Option("--search", "-q", help="Text search filter for message captions")
    ] = None,
    reverse: Annotated[
        bool, typer.Option("--reverse", help="Scrape oldest messages first")
    ] = False,
    overwrite: Annotated[
        bool, typer.Option("--overwrite", help="Overwrite existing files instead of skipping")
    ] = False,
    organize_by: Annotated[
        str,
        typer.Option(
            "--organize-by",
            help="Folder structure: auto, flat, chat, topic, chat/topic, type, date [default: auto]",
        ),
    ] = "auto",
    auto_wait: Annotated[
        bool,
        typer.Option(
            "--auto-wait/--no-auto-wait",
            help="Automatically wait with visual countdown when Telegram rate-limits",
        ),
    ] = True,
    max_flood_wait: Annotated[
        int,
        typer.Option(
            "--max-flood-wait",
            help="Maximum seconds to auto-wait on Telegram rate limit",
        ),
    ] = 3600,
    session_name: Annotated[
        str, typer.Option("--session-name", help="Custom session name")
    ] = "tg_downloader",
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Enable verbose debug logging")
    ] = False,
) -> None:
    """Download unrestricted and restricted media from Telegram posts, channels, or chats at maximum speed."""
    configure_logging(verbose)
    settings = Settings(session_name=session_name, max_connections=connections)

    # Parse date filters if provided
    start_dt = datetime.strptime(start_date, "%Y-%m-%d") if start_date else None
    end_dt = datetime.strptime(end_date, "%Y-%m-%d") if end_date else None

    # Parse byte size filters
    min_bytes = parse_size_str(min_size) if min_size else None
    max_bytes = parse_size_str(max_size) if max_size else None

    # Clean media types filter
    m_types: set[str] | None = None
    if media_type:
        m_types = {t.lower() for t in media_type}

    # Clean extension filter
    ext_set: set[str] | None = None
    if extension:
        ext_set = {
            part.strip().lstrip(".").lower()
            for raw in extension
            for part in raw.split(",")
            if part.strip()
        }

    async def _run() -> None:
        client = create_telegram_client(settings)
        auth = AuthManager(client, settings, console=console)

        downloader: ParallelDownloader | None = None
        try:
            await auth.ensure_authorized()

            # Universal resolution of target
            console.print(f"[bold cyan]Resolving target:[/] {target}...")
            resolved = await TargetResolver.resolve(client, target)

            forum_badge = " [bold magenta][Forum Supergroup][/]" if resolved.is_forum else ""
            console.print(
                f"[green]✓ Target Resolved:[/] [bold]{resolved.title}[/]{forum_badge} "
                f"({'@' + resolved.username if resolved.username else f'ID: {resolved.peer_id}'})"
            )

            # Determine topic filter
            target_topic_id: int | None = resolved.topic_id
            target_topic_query: str | None = None
            if topic:
                topic_cleaned = topic.strip()
                if topic_cleaned.isdigit():
                    target_topic_id = int(topic_cleaned)
                else:
                    target_topic_query = topic_cleaned

            if target_topic_id is not None:
                console.print(f"[cyan]Topic Scope:[/] [bold]ID {target_topic_id}[/]")
            elif target_topic_query:
                console.print(f"[cyan]Topic Scope:[/] [bold]'{target_topic_query}'[/]")
            elif resolved.is_forum:
                console.print("[cyan]Topic Scope:[/] [bold]All Topics / Sub-groups[/]")

            downloader = ParallelDownloader(
                client=client,
                max_connections=connections,
                session_path=settings.session_path,
                auto_wait=auto_wait,
                console=console,
                resilience=ResilienceManager(max_flood_sleep=max_flood_wait),
            )
            ui = DownloadUI(console=console)

            # Determine destination subdirectory based on organization strategy
            base_out = output_dir

            def get_dest_folder(
                m_type: str,
                msg_date: datetime | None,
                topic_title: str | None = None,
            ) -> Path:
                chat_folder = sanitize_filename(
                    resolved.title or resolved.username or str(resolved.peer_id)
                )
                clean_topic = sanitize_filename(topic_title or "General")

                if organize_by in ("topic", "subgroup"):
                    folder = base_out / clean_topic
                elif organize_by in ("chat/topic", "chat_topic"):
                    folder = base_out / chat_folder / clean_topic
                elif organize_by == "auto":
                    if resolved.is_forum:
                        folder = base_out / chat_folder / clean_topic
                    else:
                        folder = base_out / chat_folder
                elif organize_by == "chat":
                    folder = base_out / chat_folder
                elif organize_by == "type":
                    folder = base_out / m_type
                elif organize_by == "date":
                    date_str = msg_date.strftime("%Y-%m-%d") if msg_date else "unknown_date"
                    folder = base_out / date_str
                else:  # flat
                    folder = base_out

                folder.mkdir(parents=True, exist_ok=True)
                return folder

            # Mode 1: Single post or specific message ID range
            if resolved.is_post_link and resolved.message_ids:
                total_msgs = len(resolved.message_ids)
                is_group = total_msgs > 1
                ui.start_batch(
                    total_files=total_msgs,
                    title=f"Downloading from {resolved.title}",
                    is_group=is_group,
                )

                messages = await client.get_messages(resolved.entity, ids=resolved.message_ids)
                if not isinstance(messages, list):
                    messages = [messages]

                for msg in messages:
                    if not msg or not msg.media:
                        ui.console.print(
                            f"[dim]Message {getattr(msg, 'id', '?')} has no media. Skipping.[/]"
                        )
                        ui.complete_file(f"msg_{getattr(msg, 'id', '?')}", 0, skipped=True)
                        continue

                    from tg_downloader.utils.media import (
                        get_media_filename,
                        get_media_size,
                        get_media_type,
                    )

                    size = get_media_size(msg)
                    m_type = get_media_type(msg) or "media"
                    fname = get_media_filename(
                        msg, chat_prefix=resolved.username or str(resolved.peer_id)
                    )
                    dest = get_dest_folder(m_type, msg.date)

                    ui.start_file(filename=fname, total_bytes=size)
                    try:
                        res = await downloader.download_media(
                            message=msg,
                            dest_dir=dest,
                            filename_override=fname,
                            overwrite=overwrite,
                            entity=resolved.entity,
                            progress_callback=ui.update_file_progress,
                        )
                        ui.complete_file(filename=fname, file_bytes=size, skipped=res.skipped)
                    except Exception as err:
                        ui.fail_file(filename=fname, error_message=str(err))

                ui.finish_batch()

            # Mode 2: Channel / Chat / Forum Scraping with filters
            else:
                scraper = ChannelScraper(client=client)
                scrape_filter = ScrapeFilter(
                    limit=limit,
                    media_types=m_types,
                    extensions=ext_set,
                    min_id=min_id,
                    max_id=max_id,
                    start_date=start_dt,
                    end_date=end_dt,
                    min_size=min_bytes,
                    max_size=max_bytes,
                    search_query=search,
                    reverse=reverse,
                    topic_id=target_topic_id,
                    topic_query=target_topic_query,
                )

                ui.console.print("[bold cyan]Scanning messages and preparing download queue...[/]")
                items = []
                chat_prefix = resolved.username or str(resolved.peer_id)
                async for item in scraper.scrape(
                    resolved.entity, scrape_filter=scrape_filter, chat_prefix=chat_prefix
                ):
                    items.append(item)

                if not items:
                    console.print("[yellow]No media items found matching the specified filters.[/]")
                    return

                total_items_size = sum(it.file_size for it in items)
                console.print(
                    f"[green]Found {len(items)} matching media items[/] "
                    f"([dim]{format_bytes(total_items_size)} total[/])"
                )

                ui.start_batch(
                    total_files=len(items),
                    title=f"Scraping {resolved.title}",
                    is_group=True,
                )

                for item in items:
                    dest = get_dest_folder(item.media_type, item.date, topic_title=item.topic_title)
                    file_id = getattr(
                        getattr(item.message.media, "document", None),
                        "id",
                        f"msg_{item.message_id}",
                    )

                    # Fast path: check if file or existing collision variant is already completed
                    target_path, is_completed = resolve_target_path(
                        dest_dir=dest,
                        filename=item.file_name,
                        expected_size=item.file_size,
                        file_id=str(file_id),
                        overwrite=overwrite,
                    )

                    if is_completed:
                        ui.start_file(filename=target_path.name, total_bytes=item.file_size)
                        ui.complete_file(
                            filename=target_path.name, file_bytes=item.file_size, skipped=True
                        )
                        continue

                    # If this message was scraped over 1 hour ago, proactively refresh it before downloading
                    # to prevent FileReferenceExpired errors on long multi-hour downloads
                    if time.time() - item.scraped_at > 3600:
                        try:
                            fresh = await client.get_messages(resolved.entity, ids=item.message_id)
                            fresh_msg = fresh[0] if isinstance(fresh, list) else fresh
                            if isinstance(fresh_msg, types.Message) and fresh_msg.media:
                                item.message = fresh_msg
                                item.scraped_at = time.time()
                        except Exception as ref_err:
                            logger.debug(
                                "Proactive refresh failed for %s: %s", item.file_name, ref_err
                            )

                    ui.start_file(filename=item.file_name, total_bytes=item.file_size)
                    try:
                        res = await downloader.download_media(
                            message=item.message,
                            dest_dir=dest,
                            filename_override=item.file_name,
                            overwrite=overwrite,
                            entity=resolved.entity,
                            progress_callback=ui.update_file_progress,
                        )
                        ui.complete_file(
                            filename=item.file_name, file_bytes=item.file_size, skipped=res.skipped
                        )
                    except Exception as err:
                        ui.fail_file(filename=item.file_name, error_message=str(err))

                ui.finish_batch()

        finally:
            if downloader:
                await downloader.close()
            await client.disconnect()

    try:
        asyncio.run(_run())
    except TGDownloaderError as e:
        console.print(f"[bold red]Downloader Error:[/] {e}")
        raise typer.Exit(code=1) from e
    except KeyboardInterrupt:
        console.print("\n[yellow]Download interrupted by user. Partial progress saved (.part).[/]")
        raise typer.Exit(code=130) from None


@app.command(name="rename")
def rename_cmd(
    target: Annotated[
        str,
        typer.Argument(help="Telegram channel URL, forum supergroup link, username, or peer ID"),
    ],
    dir: Annotated[
        Path,
        typer.Option(
            "--dir",
            "-d",
            help="Root downloads directory or course folder containing downloaded files",
        ),
    ] = Path("./downloads"),
    topic: Annotated[
        str | None,
        typer.Option(
            "--topic",
            help="Filter renaming to a specific topic ID or title query in forum supergroups",
        ),
    ] = None,
    digits: Annotated[
        int,
        typer.Option(
            "--digits",
            min=2,
            max=6,
            help="Number of digits for zero-padded sequence prefix (e.g. 3 -> 001)",
        ),
    ] = 3,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Preview proposed renames and duplicates without modifying files on disk",
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Automatically execute renames without interactive confirmation prompt",
        ),
    ] = False,
    purge_duplicates: Annotated[
        bool,
        typer.Option(
            "--purge-duplicates/--keep-duplicates",
            help="Automatically remove redundant duplicate copies of files",
        ),
    ] = True,
    session_name: Annotated[
        str, typer.Option("--session-name", help="Custom session name")
    ] = "tg_downloader",
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Enable verbose debug logging")
    ] = False,
) -> None:
    """Reorganize and rename previously downloaded files in syllabus/chronological order."""
    configure_logging(verbose)
    settings = Settings(session_name=session_name)

    async def _run() -> None:
        client = create_telegram_client(settings)
        auth = AuthManager(client, settings, console=console)

        try:
            await auth.ensure_authorized()

            console.print(f"[bold cyan]Resolving channel target:[/] {target}...")
            resolved = await TargetResolver.resolve(client, target)

            forum_badge = " [bold magenta][Forum Supergroup][/]" if resolved.is_forum else ""
            console.print(
                f"[green]✓ Target Resolved:[/] [bold]{resolved.title}[/]{forum_badge} "
                f"({'@' + resolved.username if resolved.username else f'ID: {resolved.peer_id}'})"
            )

            renamer = ChannelRenamer(client)
            topics_map: dict[int, str] = {}
            if resolved.is_forum:
                topics_map = await renamer.scraper.get_forum_topics(resolved.entity)

            # Filter topics if specified by user
            if topic:
                topic_cleaned = topic.strip()
                filtered_topics: dict[int, str] = {}
                for t_id, t_title in topics_map.items():
                    if (topic_cleaned.isdigit() and t_id == int(topic_cleaned)) or (
                        topic_cleaned.lower() in t_title.lower()
                    ):
                        filtered_topics[t_id] = t_title
                topics_map = filtered_topics

            matched_dirs = renamer.find_topic_directories(
                base_dir=dir,
                channel_title=resolved.title,
                topics_map=topics_map,
                is_forum=resolved.is_forum,
            )

            if not matched_dirs:
                console.print(
                    f"[yellow]No matching local directories found under '{dir}'.[/]\n"
                    "Ensure your downloaded course directory or topic folder is specified via --dir."
                )
                return

            console.print(f"[cyan]Found {len(matched_dirs)} matching local topic directories.[/]\n")

            plans: list[TopicRenamePlan] = []
            total_candidates = 0
            total_duplicates = 0

            for topic_id, topic_title, topic_path in matched_dirs:
                with console.status(
                    f"[bold cyan]Scanning and matching files for '{topic_title}'..."
                ):
                    plan = await renamer.create_plan_for_topic(
                        entity=resolved.entity,
                        topic_id=topic_id,
                        topic_name=topic_title,
                        topic_dir=topic_path,
                        prefix_digits=digits,
                        purge_duplicates=purge_duplicates,
                    )
                plans.append(plan)

                # Render table for this topic
                table = Table(
                    title=f"Rename Plan: {topic_title} ({topic_path})",
                    show_header=True,
                    header_style="bold cyan",
                    expand=True,
                )
                table.add_column("Original Filename", style="dim", overflow="fold", ratio=4)
                table.add_column("Size", justify="right", style="magenta", no_wrap=True)
                table.add_column(
                    "Proposed New Filename", style="bold green", overflow="fold", ratio=5
                )
                table.add_column("Status / Action", style="white", ratio=3)

                topic_active_cands = 0
                topic_dups = 0

                for cand in plan.candidates:
                    size_str = format_bytes(cand.file_size)
                    if cand.is_duplicate:
                        orig_name = cand.duplicate_of.name if cand.duplicate_of else "original"
                        table.add_row(
                            cand.local_path.name,
                            size_str,
                            "[strike red]PURGE DUPLICATE[/]",
                            f"[red]Duplicate of {orig_name}[/]",
                        )
                        topic_dups += 1
                    else:
                        table.add_row(
                            cand.local_path.name,
                            size_str,
                            cand.new_name,
                            f"[green]{cand.reason}[/]",
                        )
                        topic_active_cands += 1

                console.print(table)
                total_candidates += topic_active_cands
                total_duplicates += topic_dups

                if plan.unmatched_files:
                    console.print(
                        f"[yellow]ℹ {len(plan.unmatched_files)} local files were not matched "
                        "and will remain unchanged.[/]"
                    )
                console.print()

            if total_candidates == 0 and total_duplicates == 0:
                console.print("[yellow]No files required renaming or duplicate cleanup.[/]")
                return

            summary_text = (
                f"Total: {total_candidates} files to rename, {total_duplicates} duplicates to purge"
            )
            console.print(Panel(summary_text, style="bold cyan"))

            if dry_run:
                console.print(
                    "[yellow]Dry-run mode active. No changes have been applied to disk.[/]"
                )
                return

            if not yes:
                from rich.prompt import Confirm

                confirmed = Confirm.ask(
                    "Proceed with renaming and reorganizing these files?", default=False
                )
                if not confirmed:
                    console.print("[yellow]Operation cancelled by user. No files were modified.[/]")
                    return

            # Apply all plans
            grand_renamed = 0
            grand_purged = 0
            for plan in plans:
                r_cnt, p_cnt = ChannelRenamer.apply_plan(plan, purge_duplicates=purge_duplicates)
                grand_renamed += r_cnt
                grand_purged += p_cnt

            console.print(
                f"[bold green]✓ Successfully renamed {grand_renamed} files and purged "
                f"{grand_purged} duplicates![/]"
            )

        finally:
            await client.disconnect()

    try:
        asyncio.run(_run())
    except TGDownloaderError as e:
        console.print(f"[bold red]Rename Error:[/] {e}")
        raise typer.Exit(code=1) from e
    except KeyboardInterrupt:
        console.print("\n[yellow]Rename operation interrupted by user.[/]")
        raise typer.Exit(code=130) from None


def main() -> None:
    """CLI application entrypoint."""
    app()


if __name__ == "__main__":
    main()
