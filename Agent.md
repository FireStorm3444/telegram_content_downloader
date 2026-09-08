# Autonomous Agent Guidelines & Engineering Rules (`Agent.md`)

This document establishes the binding engineering standards, architectural boundaries, code-authoring instructions, and operational protocols for any autonomous AI agent (including Antigravity, Claude, Cursor, and Copilot) operating on the `tg-downloader` codebase.

All autonomous agents MUST strictly adhere to these rules without exception.

---

## 1. Core Principles & Non-Negotiable Rules

### Rule 1: Always Validate Code with Quality Gate (`make check`)
- **Requirement:** Every single code modification MUST be validated by running:
  ```bash
  make check
  ```
  *(Equivalent to: `ruff format --check . && ruff check . && ty check`)*
- **Zero Diagnostics Policy:** The quality gate must pass with **0 formatting issues, 0 lint warnings, and 0 static type diagnostics**.
- **Rule of Execution:** Never conclude a task or present a solution to the user if `make check` returns a non-zero exit code. If formatting errors exist, run `make format`. If lint errors exist, run `make lint`. If type diagnostics remain, resolve them explicitly.

### Rule 2: Always Run and Pass the Test Suite (`make test`)
- **Requirement:** Every code change MUST be tested with:
  ```bash
  make test
  ```
  *(Equivalent to: `pytest -v tests/`)*
- **Test Invariant:** All unit and integration testcases (53+ testcases across `tests/`) must pass cleanly.
- **Coverage Preservation:** Never delete, skip (`@pytest.mark.skip`), or weaken existing test assertions to make tests pass.
- **New Feature / Bugfix TDD:** Whenever implementing a new CLI option, algorithm change, or bugfix, companion unit tests MUST be added in `tests/` covering both success paths and edge cases (e.g. rate limits, network drops, malformed data).

### Rule 3: Strict Static Typing & Type Narrowing
- **Type Annotations Required:** All new functions, methods, parameters, and return types MUST have explicit type annotations compatible with Python 3.11+ / 3.12 (`int | None`, `list[str]`, `dict[str, Any]`, etc.).
- **No Untyped Any Leaks:** Minimize the use of `Any`. Prefer specific dataclasses, Pydantic models, or Telethon types (`types.Message`, `types.Channel`, `types.Chat`).
- **Explicit Type Narrowing:** When handling optional types (`T | None`), always narrow types before indexing or attribute access (e.g., using `assert var is not None` or `if var is not None:`) to ensure `ty check` succeeds with zero diagnostics.

### Rule 4: MTProto Protocol & Network Discipline
- **Connection Pooling & DC Key Persistence:** Never instantiate standalone or uncontrolled `TelegramClient` or `MTProtoSender` connections. Always utilize `MTProtoSenderPool` and `DCKeyStorage`.
- **Persistent Foreign DC Keys:** All foreign DC worker authorization keys MUST be loaded and saved via `DCKeyStorage` (`<session>.dc_keys.json`) with strict `0o600` permissions to avoid `ExportAuthorization` FloodWait penalties.
- **FloodWait & Resilience Handling:** Never swallow or terminate ungracefully on MTProto `FloodWaitError` or `FileReferenceExpiredError`. Always route requests through `ResilienceManager`, and honor the user's `--auto-wait` and `--max-flood-wait` settings.
- **Chunk Alignment:** Always request MTProto chunks aligned to 512 KB (`524,288` bytes) or 128 KB boundaries. Never issue unaligned chunk offset requests.

### Rule 5: Zero-Copy Disk Streaming & RAM Discipline
- **Flat Memory Invariant:** Memory footprint must stay flat ($<50\text{ MB}$) regardless of whether downloading a 5 MB photo or a 50 GB video.
- **Direct-to-Disk `os.pwrite`:** Never read, buffer, or accumulate entire media files into memory (`bytes`). Chunks must be written directly to disk at designated byte offsets asynchronously using `AsyncFileWriter`.
- **Resumption Bitmaps:** Always maintain `.part` and `.part.meta` chunk bitmaps during transfers. Only finalize the file via atomic `os.replace` after total file size is verified.

### Rule 6: Code Style & File System Safety
- **PEP 8 & Ruff Standard:** Line length is 100 characters. Double quotes for strings. Import sorting managed by Ruff (`I`).
- **Cross-Platform Path & Filename Safety:** Always sanitize user-provided filenames using `sanitize_filename` and resolve duplicates using `resolve_target_path`. Ensure protection against Windows reserved names (`CON`, `PRN`, `AUX`, `NUL`) and forbidden filesystem characters (`<>:"/\|?*`).
- **No Dead Code or Console Spills:** Avoid raw `print()` statements in core engine modules. Use structured logging (`logger.debug`, `logger.info`, `logger.warning`) in library code and `rich.console.Console` exclusively in `tg_downloader/ui/` or `tg_downloader/cli.py`.

### Rule 7: Documentation Integrity & Sync
- **Maintain Docs in Lockstep:** If modifying CLI arguments, environment variables, or architecture, immediately update `README.md` and inline docstrings.
- **Preserve Existing Comments:** Do not delete comments or docstrings unrelated to your changes.

---

## 2. Codebase Architecture & Boundaries

Keep architectural boundaries clean and strictly separated:

| Module Directory | Allowed Responsibilities | Forbidden Responsibilities |
| :--- | :--- | :--- |
| `tg_downloader/cli.py` | Typer CLI commands, CLI options/arguments, Rich output orchestration. | Raw MTProto socket calls, direct disk byte writes. |
| `tg_downloader/config.py` | Pydantic `BaseSettings`, environment loading, directory resolution. | Network calls, CLI logic. |
| `tg_downloader/core/` | Client instantiation, interactive auth flow, link/target entity resolution, scraping filters. | Direct-to-disk chunk pwrite, connection pool socket logic. |
| `tg_downloader/engine/` | MTProto multi-connection pooling, DC key persistence, parallel chunk fetching, byte-offset file writing, `.part.meta` state management, FloodWait/FileReference resilience. | UI rendering, CLI flag definitions. |
| `tg_downloader/ui/` | Rich progress bars, smart columns, animated cooldown timers, batch summaries. | MTProto network calls, file downloads. |
| `tg_downloader/utils/` | Reusable utilities: cryptographic diagnostics (`crypto.py`), file deduplication (`dedup.py`), filename sanitization (`filename.py`), byte/speed/duration formatting (`formatting.py`), media classification (`media.py`). | Application state management, CLI commands. |

---

## 3. Standard Agent Workflow Checklist

When assigned a task, every autonomous agent should follow this cycle:

1. **Understand & Inspect:**
   - Locate target files using `find_by_name` or `grep_search`.
   - Read existing implementation and tests using `view_file`.
2. **Implement Changes:**
   - Make minimal, surgical modifications preserving code style.
   - Maintain strict typing and docstrings.
3. **Verify Quality Gates:**
   - Run `make check` (or `uv run ruff check . && uv run ty check`).
   - If any lint or format error occurs: fix with `make format` or `make lint` and re-check.
4. **Verify Tests:**
   - Run `make test` (or `uv run pytest -v tests/`).
   - If new behavior was introduced, add corresponding test cases in `tests/test_<feature>.py`.
5. **Review Git Diff:**
   - Run `git status` and `git diff` to confirm no unwanted files, caches, or debug statements remain.
6. **Update Documentation:**
   - If CLI flags, settings, or architectural components changed, update `README.md`.
