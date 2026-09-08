# High-Performance Telegram Media Downloader CLI (`tg-downloader`)

A production-ready, high-throughput command-line application in Python (3.11+) architected to download restricted and unrestricted media from Telegram channels, groups, and direct post links at maximum network speed.

Built with native cryptographic hardware acceleration (`cryptg`), parallel MTProto connection pooling, zero-copy direct-to-disk streaming via byte offsets, and partial download resumption.

---

## Key Capabilities & Architectural Highlights

- **Universal Telegram Media Resolution:**
  - **Public Post Links:** `https://t.me/<channel>/<id>`, message ranges (`https://t.me/<channel>/100-110`).
  - **Private & Restricted Channel Links:** `https://t.me/c/<channel_id>/<id>`, automatically handling Telegram's internal `-100` supergroup ID mapping (e.g. `c/1234567890/42` $\to$ `-1001234567890`) and session cache hydration.
  - **Topic / Forum Threads:** `https://t.me/c/<channel_id>/<topic_id>/<id>` and public topic URLs.
  - **Full Channel & Chat Scraping:** Comprehensive scraping of channels, groups, and direct chats with rich filtering (media types, date ranges, file sizes, message ID boundaries, text search, and reverse order).
  - **Restricted Content Access:** Downloads restricted media (`noforwards` flag) directly over MTProto without client-side forward/save restrictions.

- **High-Throughput Parallel Engine:**
  - **Multi-Connection Pooling:** Connects multiple parallel `MTProtoSender` worker connections directly to the file's target Data Center (DC), bypassing single-connection MTProto bottlenecks and saturating available bandwidth.
  - **512 KB Chunk Fetching:** Requests maximum MTProto chunk sizes (524,288 bytes) pipelined across parallel asynchronous workers.
  - **Zero-Copy Disk Streaming:** Chunks are written directly to disk at exact byte offsets using asynchronous `os.pwrite`. Memory never buffers entire files; RAM usage remains flat ($<50\text{ MB}$) even for multi-gigabyte files.

- **Resumption & State Safety:**
  - **Chunk-Verified Resumption:** Partially downloaded transfers save `.part` files alongside `.part.meta` bitmaps, resuming interrupted downloads from the exact verified chunk boundary.
  - **Atomic Finalization:** Destination files are only created after total byte size is validated against metadata, performing an atomic `os.replace` rename.

- **Protocol Resilience & Edge Cases:**
  - **FloodWait Mitigation:** Automatically sleeps with exponential backoff and randomized jitter on MTProto `FloodWaitError` without process termination.
  - **FileReference Refreshing:** Automatically detects `FileReferenceExpiredError` during long-running batch jobs, re-fetching fresh message references and retrying chunk transfers transparently.
  - **Cross-Platform Filename Sanitization:** Cleans illegal characters (`<>:"/\|?*`), protects against Windows reserved device names (`CON`, `PRN`, `AUX`, `NUL`), truncates excessive lengths, and prevents file collisions.

- **Developer Toolchain & Hardware Acceleration:**
  - **Rust-Powered Toolchain:** Managed strictly with `uv`, linted and formatted via `ruff`, and statically type checked via `ty`.
  - **Hardware Acceleration:** Uses native C-accelerated AES-IGE encryption (`cryptg`) achieving $>200\text{ MB/s}$ cryptographic throughput.

---

## System Architecture

```
tg_downloader/
├── cli.py                  # Typer CLI application, commands, and options
├── config.py               # Pydantic Settings & environment discovery
├── core/
│   ├── auth.py             # Interactive auth lifecycle (Phone, Code, 2FA)
│   ├── client.py           # TelegramClient factory and session handling
│   ├── errors.py           # Custom exception hierarchy
│   ├── resolver.py         # Universal link & target resolver (-100 mapping)
│   └── scraper.py          # Channel scraping engine with customizable filters
├── engine/
│   ├── file_writer.py      # Async direct-to-disk chunk writer (os.pwrite)
│   ├── parallel.py         # High-throughput MTProto parallel chunk downloader
│   ├── pool.py             # Multi-connection MTProto sender pool
│   ├── resilience.py       # FloodWait backoff & FileReferenceExpired refresh
│   └── state.py            # .part and .part.meta resumption state manager
├── ui/
│   └── progress.py         # Rich multi-bar progress UI & batch summaries
└── utils/
    ├── crypto.py           # Native cryptg acceleration diagnostics & benchmark
    ├── filename.py         # Cross-platform filename sanitization & collision safety
    ├── formatting.py       # Byte, speed, and time formatting utilities
    └── media.py            # Telegram media classification & naming
```

---

## Quickstart & Installation

### 1. Requirements
- Python 3.11 or higher (Python 3.12 recommended)
- `uv` package manager
- `ruff` linter and formatter
- `ty` static type checker

### 2. Rapid Onboarding with `Makefile`
```bash
# Clone the repository and install dependencies in editable mode
make install

# Verify environment and hardware cryptographic acceleration
make doctor

# Run test suite
make test

# Run quality gate verification (ruff format + ruff check + ty check)
make check
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
Edit `.env` with your credentials:
```env
TG_API_ID=1234567
TG_API_HASH=0123456789abcdef0123456789abcdef
TG_PHONE=+1234567890
```

### Option B: CLI Flags
Pass `--api-id` and `--api-hash` directly to commands.

---

## CLI Usage Guide

### 1. Interactive Authentication

#### Log in:
```bash
make run ARGS="login"
# Or directly with executable:
.venv/bin/tg-downloader login
```
Prompts for phone number, login code (sent via Telegram app or SMS), and 2FA password (masked) if enabled.

#### Check authenticated profile:
```bash
make run ARGS="whoami"
```

#### Log out and purge session:
```bash
make run ARGS="logout"
```

---

### 2. Diagnostics & Hardware Acceleration (`doctor`)
```bash
make run ARGS="doctor"
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
make run ARGS="download https://t.me/durov/123 -o ./downloads -c 8"
```

#### B. Private Channel Post Link (with `-100` supergroup mapping):
```bash
make run ARGS="download https://t.me/c/1234567890/456 -o ./downloads -c 4"
```

#### C. Post ID Range:
```bash
make run ARGS="download https://t.me/c/1234567890/100-120 -o ./downloads"
```

#### D. Full Channel Scraping with Media Type & Extension Filters:
```bash
# Download only videos and PDFs from a channel or group
make run ARGS="download @channelname -t video -t pdf -o ./downloads"

# Filter by exact file extensions:
make run ARGS="download @channelname -e mp4,pdf,mkv -o ./downloads"
```

#### E. Forum Groups & Topic / Sub-Group Scraping:
Forum supergroups with topics are automatically detected:
```bash
# Download all videos and PDFs across all topics/sub-groups directly from the group link:
make run ARGS="download https://t.me/c/3419616253 -t video -t pdf -o ./downloads"

# Filter for a specific topic by name or ID:
make run ARGS="download https://t.me/c/3419616253 --topic 'Machine Learning' -t video -t pdf"
make run ARGS="download https://t.me/c/3419616253 --topic 3"

# Or directly provide a topic URL:
make run ARGS="download https://t.me/c/3419616253/3 -t video -t pdf"
```

#### F. Structural Folder Organization (`--organize-by`):
Organize downloaded files automatically into cleanly structured folders:
```bash
# Default ('auto'): creates '<Group Name>/<Topic Name>/<filename>' for forum groups
make run ARGS="download https://t.me/c/3419616253 -t video -t pdf --organize-by auto"

# Save directly into topic sub-folders ('<Topic Name>/<filename>'):
make run ARGS="download https://t.me/c/3419616253 -t video -t pdf --organize-by topic"

# Explicit '<Chat Name>/<Topic Name>/' structure:
make run ARGS="download https://t.me/c/3419616253 --organize-by chat/topic"

# Organize by media type ('downloads/video/', 'downloads/pdf/'):
make run ARGS="download @channelname --organize-by type"

# Organize by date ('downloads/2024-03-15/'):
make run ARGS="download @channelname --organize-by date"

# Flat layout without sub-folders:
make run ARGS="download @channelname --organize-by flat"
```

#### G. Date and Size Filtering:
```bash
make run ARGS="download @channelname --start-date 2024-01-01 --end-date 2024-12-31 --min-size 10MB --max-size 1GB"
```

#### H. Instant Resumption of Interrupted Downloads:
If a download is interrupted, re-running the command automatically inspects the `.part` and `.part.meta` bitmaps and picks up from the exact verified chunk boundary without re-downloading existing chunks:
```bash
make run ARGS="download https://t.me/c/3419616253/3/23 -o ./downloads"
```


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

Clean build and temporary files:
```bash
make clean
```
