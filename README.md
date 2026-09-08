# High-Performance Telegram Media Downloader CLI (`tg-downloader`)

A production-ready, high-throughput command-line application in Python (3.11+) architected to download restricted and unrestricted media from Telegram channels, groups, topics, and direct post links at maximum network speed.

Built with native cryptographic hardware acceleration (`cryptg`), parallel MTProto connection pooling, zero-copy direct-to-disk streaming via byte offsets, persistent foreign Data Center (DC) authorization storage, and partial download resumption.

---

## Key Capabilities & Architectural Highlights

- **Universal Telegram Media Resolution:**
  - **Public Post Links:** `https://t.me/<channel>/<id>`, message ranges (`https://t.me/<channel>/100-110`).
  - **Private & Restricted Channel Links:** `https://t.me/c/<channel_id>/<id>`, automatically handling Telegram's internal `-100` supergroup ID mapping (e.g. `c/1234567890/42` $\to$ `-1001234567890`) and session cache hydration.
  - **Topic / Forum Threads:** `https://t.me/c/<channel_id>/<topic_id>/<id>`, `https://t.me/<channel>/<topic_id>/<id>`, and topic-level scraping with `--topic`.
  - **Full Channel & Chat Scraping:** Comprehensive scraping of channels, groups, and direct chats with rich filtering (media types, file extensions, date ranges, file sizes, message ID boundaries, text search, limit, and reverse order).
  - **Restricted Content Access:** Downloads restricted media (`noforwards` flag) directly over MTProto without client-side forward or save limitations.

- **High-Throughput Parallel Engine:**
  - **Multi-Connection Pooling:** Connects multiple parallel `MTProtoSender` worker connections directly to the file's target Data Center (DC), bypassing single-connection MTProto bottlenecks and saturating available bandwidth.
  - **512 KB Chunk Fetching:** Requests maximum MTProto chunk sizes (524,288 bytes) pipelined across parallel asynchronous workers.
  - **Zero-Copy Disk Streaming:** Chunks are written directly to disk at exact byte offsets using asynchronous `os.pwrite`. Memory never buffers entire files; RAM usage remains flat ($<50\text{ MB}$) even for multi-gigabyte files.

- **Persistent DC Authorization & Rate-Limit Resilience:**
  - **Persistent Foreign DC Auth Keys (`engine/dc_storage.py`):** Caches exported authorization keys for foreign Data Centers in `<session>.dc_keys.json` with strict file permissions (`0600`). Reuses active connections across downloads to completely prevent repetitive `ExportAuthorization` FloodWait penalties.
  - **Visual Cooldown & Auto-Wait:** When Telegram enforces rate limits, an animated visual countdown displays remaining cooldown time and resumes downloads automatically.
  - **FileReference Refreshing:** Transparently detects `FileReferenceExpiredError` during long-running batch jobs, re-fetching fresh message references and retrying chunk transfers without interruption.

- **Resumption, State Safety & Deduplication:**
  - **Chunk-Verified Resumption:** Partially downloaded transfers save `.part` files alongside `.part.meta` bitmaps, resuming interrupted downloads from the exact verified chunk boundary.
  - **Atomic Finalization:** Destination files are only created after total byte size is validated against metadata, performing an atomic `os.replace` rename.
  - **Intelligent Collision Resolution & Deduplication:** Checks existing files against expected byte sizes and `.part.meta` IDs before downloading to avoid duplicate transfers. Renames collided files cleanly (`filename (1).ext`), while `dedup` utilities detect duplicates via rapid head/tail SHA-256 fingerprinting.
  - **Cross-Platform Filename Sanitization:** Cleans illegal characters (`<>:"/\|?*`), protects against Windows reserved device names (`CON`, `PRN`, `AUX`, `NUL`), truncates excessive lengths, and prevents file collisions.

- **Developer Toolchain & Hardware Acceleration:**
  - **Rust-Powered Toolchain:** Managed strictly with `uv`, linted and formatted via `ruff`, and statically type checked via `ty`.
  - **Hardware Acceleration:** Uses native C-accelerated AES-IGE encryption (`cryptg`) achieving $>200\text{ MB/s}$ cryptographic throughput.

---

## System Architecture

```
tg_downloader/
├── cli.py                  # Typer CLI application, commands, options, and entrypoint
├── config.py               # Pydantic Settings & environment discovery
├── core/
│   ├── auth.py             # Interactive auth lifecycle (Phone, Code, 2FA password)
│   ├── client.py           # TelegramClient factory and session handling
│   ├── errors.py           # Custom exception hierarchy
│   ├── resolver.py         # Universal link & target resolver (-100 mapping)
│   └── scraper.py          # Channel scraping engine with customizable filters
├── engine/
│   ├── dc_storage.py       # Persistent on-disk storage for exported MTProto DC auth keys
│   ├── file_writer.py      # Async direct-to-disk chunk writer (os.pwrite)
│   ├── parallel.py         # High-throughput MTProto parallel chunk downloader
│   ├── pool.py             # Multi-connection MTProto sender pool & visual cooldown
│   ├── resilience.py       # FloodWait backoff & FileReferenceExpired refresh
│   └── state.py            # .part and .part.meta resumption state manager
├── ui/
│   └── progress.py         # Rich multi-bar progress UI & batch summaries
└── utils/
    ├── crypto.py           # Native cryptg acceleration diagnostics & benchmark
    ├── dedup.py            # Fast file deduplication and redundant partial file cleanup
    ├── filename.py         # Cross-platform filename sanitization & collision safety
    ├── formatting.py       # Byte, speed, duration, and size formatting utilities
    └── media.py            # Telegram media classification & naming
```

---

## Quickstart & Installation

### 1. Requirements
- **Python:** 3.11 or higher (Python 3.12 recommended)
- **`uv` Package Manager:** Fast Python package and venv manager.
  - Install via official script: `curl -LsSf https://astral.sh/uv/install.sh | sh` (or `pip install uv`)
- **`make` Build Utility:** (Optional, but recommended for simplified shortcut commands):
  - **Debian / Ubuntu:** `sudo apt install make` (or `sudo apt install build-essential`)
  - **Fedora / RHEL:** `sudo dnf install make`
  - **Arch Linux:** `sudo pacman -S make`
  - **macOS:** `xcode-select --install` or `brew install make`
  - **Windows:** `winget install GnuWin32.Make` or `choco install make` (or use the direct `uv` onboarding commands below)

---

### 2. Onboarding Options

#### Option A: Rapid Onboarding with `Makefile` (Recommended)
If `make` is installed on your system:
```bash
# 1. Create venv and install dependencies in editable mode
make install

# 2. Verify environment and native cryptographic hardware acceleration
make doctor

# 3. Run full test suite
make test

# 4. Run quality gate verification (ruff format + ruff check + ty check)
make check
```

#### Option B: Direct Onboarding with `uv` (No `make` required)
If you prefer not to install or use `make`:
```bash
# 1. Create a Python 3.12 virtual environment
uv venv --python 3.12 .venv

# 2. Install package in editable mode with development dependencies
uv pip install -e ".[dev]"

# 3. Verify environment and native cryptographic hardware acceleration
uv run tg-downloader doctor

# 4. Run test suite
uv run pytest -v tests/

# 5. Run static analysis and lint quality gate
uv run ruff check .
uv run ty check
```

---

## Telegram Credentials Configuration

Telegram API credentials can be obtained for free from [my.telegram.org/apps](https://my.telegram.org/apps).

Configure your credentials using any of the following methods:

### Option A: Environment Variables (`.env`)
Copy the example environment file:
```bash
cp .env.example .env
```
Edit `.env` with your credentials and preferences:
```env
# Required Telegram API Credentials
TG_API_ID=1234567
TG_API_HASH=0123456789abcdef0123456789abcdef

# Optional Account & Session Configuration
TG_PHONE=+1234567890
TG_SESSION_NAME=tg_downloader
TG_SESSION_DIR=~/.tg_downloader

# Performance & Engine Defaults
TG_DOWNLOAD_DIR=./downloads
TG_MAX_CONNECTIONS=4
TG_CHUNK_SIZE_KB=512
TG_MAX_CONCURRENT_FILES=1
```

### Option B: CLI Flags
Pass `--api-id` and `--api-hash` directly to commands (e.g. `tg-downloader login --api-id ... --api-hash ...`).

---

## CLI Usage Guide

Commands can be invoked directly via `tg-downloader` (or `uv run tg-downloader`), or via the onboarding `Makefile`:
```bash
tg-downloader <command> [options]
# Or using the Makefile runner:
make run ARGS="<command> [options]"
```

---

### 1. Interactive Authentication

#### Log in:
```bash
tg-downloader login
```
Prompts for your phone number, login code (sent via Telegram app or SMS), and 2FA password (masked) if enabled.

To manage multiple accounts or separate profiles, pass `--session-name`:
```bash
tg-downloader login --session-name work_account
```

#### Check authenticated profile:
```bash
tg-downloader whoami
# Or check a specific profile:
tg-downloader whoami --session-name work_account
```

#### Log out and purge session:
```bash
tg-downloader logout
# Or log out of a specific profile:
tg-downloader logout --session-name work_account
```

---

### 2. Diagnostics & Hardware Acceleration (`doctor`)
```bash
tg-downloader doctor
```
Example Output:
```
╭──────────────────────────────────────────────────────────────────────────────╮
│                     Hardware & Cryptographic Diagnostics                     │
│ ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓ │
│ ┃ Component                  ┃ Status / Detail                             ┃ │
│ ┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩ │
│ │ Platform                   │ Linux-7.2.3-1-cachyos-x86_64-with-glibc2.44 │ │
│ │ Python Version             │ 3.12.14                                     │ │
│ │ Native Cryptg Acceleration │ Installed & Available                       │ │
│ │ Active AES Backend         │ cryptg (Native C Acceleration)              │ │
│ │ Hardware Acceleration      │ Active                                      │ │
│ │ AES-IGE Benchmark Speed    │ 235.75 MB/s                                 │ │
│ │ Max MTProto Chunk Size     │ 512 KB (Maximum API Throughput)             │ │
│ └────────────────────────────┴─────────────────────────────────────────────┘ │
╰──────────────────────────────────────────────────────────────────────────────╯
```

---

### 3. Downloading Media

#### A. Single Public Post Link:
```bash
tg-downloader download https://t.me/durov/123 -o ./downloads -c 8
```

#### B. Private Channel Post Link (with `-100` supergroup mapping):
```bash
tg-downloader download https://t.me/c/1234567890/456 -o ./downloads -c 4
```

#### C. Post ID Range:
```bash
tg-downloader download https://t.me/c/1234567890/100-120 -o ./downloads
```

#### D. Full Channel Scraping with Media Type & Extension Filters:
```bash
# Download only videos and PDFs from a channel or group:
tg-downloader download @channelname -t video -t pdf -o ./downloads

# Filter by exact file extensions (comma-separated or multiple flags):
tg-downloader download @channelname -e mp4,pdf,mkv -o ./downloads

# Supported media types: all, video, photo, document, audio, voice, animation, sticker
```

#### E. Forum Groups & Topic / Sub-Group Scraping:
Forum supergroups with topics are automatically detected:
```bash
# Download all videos and PDFs across all topics/sub-groups directly from the group link:
tg-downloader download https://t.me/c/3419616253 -t video -t pdf -o ./downloads

# Filter for a specific topic by name or ID:
tg-downloader download https://t.me/c/3419616253 --topic 'Machine Learning' -t video -t pdf
tg-downloader download https://t.me/c/3419616253 --topic 3

# Or directly provide a topic URL:
tg-downloader download https://t.me/c/3419616253/3 -t video -t pdf
```

#### F. Structural Folder Organization (`--organize-by`):
Organize downloaded files automatically into cleanly structured folders:
```bash
# Default ('auto'): creates '<Group Name>/<Topic Name>/<filename>' for forum groups
tg-downloader download https://t.me/c/3419616253 -t video -t pdf --organize-by auto

# Save directly into topic sub-folders ('<Topic Name>/<filename>'):
tg-downloader download https://t.me/c/3419616253 -t video -t pdf --organize-by topic

# Explicit '<Chat Name>/<Topic Name>/' structure:
tg-downloader download https://t.me/c/3419616253 --organize-by chat/topic

# Organize by chat name ('<Chat Name>/<filename>'):
tg-downloader download @channelname --organize-by chat

# Organize by media type ('downloads/video/', 'downloads/pdf/'):
tg-downloader download @channelname --organize-by type

# Organize by date ('downloads/2024-03-15/'):
tg-downloader download @channelname --organize-by date

# Flat layout without sub-folders:
tg-downloader download @channelname --organize-by flat
```

#### G. Advanced Scraping: Limits, Search, Date & Size Filters:
```bash
# Scrape the first 25 items matching caption search 'lecture':
tg-downloader download @channelname -q "lecture" -n 25

# Filter by creation date and size boundaries:
tg-downloader download @channelname --start-date 2024-01-01 --end-date 2024-12-31 --min-size 10MB --max-size 1GB

# Scrape oldest messages first within specific message ID boundaries:
tg-downloader download @channelname --min-id 100 --max-id 5000 --reverse
```

#### H. Rate-Limit Handling & Visual Cooldown:
By default, `tg-downloader` monitors FloodWait exceptions and waits automatically with an animated countdown timer.
```bash
# Control rate-limit auto-waiting behavior and timeout:
tg-downloader download @channelname --auto-wait --max-flood-wait 1800

# Disable auto-wait (raise immediately on rate limits):
tg-downloader download @channelname --no-auto-wait
```

#### I. Overwriting vs. Intelligent Resumption:
```bash
# By default, files matching expected byte sizes are verified and skipped:
tg-downloader download @channelname -o ./downloads

# Force re-download and overwrite existing files:
tg-downloader download @channelname -o ./downloads --overwrite

# Interrupted downloads resume from verified chunk boundaries via .part and .part.meta:
tg-downloader download https://t.me/c/3419616253/3/23 -o ./downloads
```

---

## CLI Command & Options Reference

### Commands Summary

| Command | Description |
| :--- | :--- |
| `login` | Authenticate interactively (phone, SMS/app code, 2FA password). |
| `logout` | Log out from Telegram and securely delete the local session file. |
| `whoami` | Display active user profile, user ID, phone, and connected Data Center. |
| `doctor` | Run environment and cryptographic hardware acceleration diagnostics. |
| `download` | Download unrestricted and restricted media from posts, channels, or chats. |

### `download` Options Reference

| Option / Flag | Short | Default | Description |
| :--- | :---: | :---: | :--- |
| `target` *(argument)* | | *required* | Telegram URL, post range, channel username (`@channel`), or peer ID. |
| `--output-dir` | `-o` | `./downloads` | Destination directory for downloaded media. |
| `--connections` | `-c` | `4` | Parallel MTProto sender connections (1 to 16). |
| `--limit` | `-n` | `None` | Maximum number of media items to download. |
| `--media-type` | `-t` | `None` | Filter by type: `all`, `video`, `photo`, `document`, `audio`, `voice`, `animation`, `sticker`. |
| `--extension` | `-e` | `None` | Filter by extension (e.g. `-e mp4,pdf,mkv` or multiple `-e` flags). |
| `--topic` | | `None` | Filter by topic ID (e.g. `3`) or topic title query (e.g. `'Machine Learning'`). |
| `--search` | `-q` | `None` | Text search filter for message captions. |
| `--start-date` | | `None` | Messages on or after date (`YYYY-MM-DD`). |
| `--end-date` | | `None` | Messages on or before date (`YYYY-MM-DD`). |
| `--min-size` | | `None` | Minimum file size (e.g. `10MB`, `500KB`). |
| `--max-size` | | `None` | Maximum file size (e.g. `1GB`). |
| `--min-id` | | `None` | Minimum Telegram message ID boundary. |
| `--max-id` | | `None` | Maximum Telegram message ID boundary. |
| `--reverse` | | `False` | Scrape oldest messages first. |
| `--overwrite` | | `False` | Overwrite existing files instead of skipping completed files. |
| `--organize-by` | | `auto` | Folder structure: `auto`, `flat`, `chat`, `topic`, `chat/topic`, `type`, `date`. |
| `--auto-wait` / `--no-auto-wait` | | `True` | Automatically wait with visual countdown when Telegram rate-limits. |
| `--max-flood-wait` | | `3600` | Maximum seconds to auto-wait on Telegram rate limit. |
| `--session-name` | | `tg_downloader` | Custom session profile name to use. |
| `--verbose` | `-v` | `False` | Enable verbose debug logging. |

---

## Verification Pipeline & Quality Gates

Run the composite verification pipeline:
```bash
make check
```
Runs:
1. `ruff format --check .` (zero formatting drift)
2. `ruff check .` (zero lint warnings/errors)
3. `ty check` (zero type diagnostics)

Run pytest test suite:
```bash
make test
```

Format code:
```bash
make format
```

Lint and apply auto-fixes:
```bash
make lint
```

Run type checking directly:
```bash
make typecheck
```

Clean temporary files and build artifacts:
```bash
make clean
```
