# CLAUDE.md - icloud_photos_downloader

## Project overview

Command-line tool to download iCloud photos. Python 3.10-3.13.

## Architecture

4-layer design:
1. **CLI/Config** (`src/icloudpd/cli.py`, `config.py`) - argparse, GlobalConfig/UserConfig dataclasses
2. **Core orchestration** (`src/icloudpd/base.py`) - main sync loop in `core_single_run()`
3. **iCloud API client** (`src/pyicloud_ipd/`) - auth, session, CloudKit photos service
4. **Functional utilities** (`src/foundation/`) - compose, curry, map_, filter_

Entry point: `icloudpd` CLI -> `icloudpd.cli:cli()` -> `icloudpd.base.run_with_configs()`

### Key files

| File | Purpose |
|------|---------|
| `src/icloudpd/base.py` | Core sync loop, download orchestration (~1200 lines) |
| `src/icloudpd/cli.py` | Argument parsing, config construction |
| `src/icloudpd/config.py` | GlobalConfig, UserConfig dataclasses |
| `src/icloudpd/download.py` | File download with retries, resume, checksums |
| `src/icloudpd/album_cache.py` | Album membership cache (`.albums/*.json`) |
| `src/icloudpd/xmp_sidecar.py` | XMP sidecar generation (metadata, albums) |
| `src/icloudpd/authentication.py` | 2FA/2SA handling |
| `src/icloudpd/autodelete.py` | Deletion strategies |
| `src/icloudpd/log_level.py` | LogLevel enum, TRACE level (5) |
| `src/pyicloud_ipd/base.py` | PyiCloudService (auth, session management) |
| `src/pyicloud_ipd/services/photos.py` | PhotosService, PhotoLibrary, PhotoAlbum, PhotoAsset |
| `src/pyicloud_ipd/session.py` | HTTP session, cookies, request tracing |

### Design patterns

- Functional programming style (compose, curry, partial from `foundation.core`)
- No database - sync state derived from filesystem (file existence + size)
- Callback-based design for filename builders, password/MFA providers
- Multi-user support (sequential processing, shared thread pool)

### Asset identity

- `PhotoAsset.id` - master record name (e.g. `AY2Uh8KJVniOxTh8vb5vfqkm2fgS`)
- `PhotoAsset.asset_id` - CPLAsset record name / UUID (e.g. `0E454CB9-42BC-413B-8BB2-4A20F4B54FE1`)
- Album membership and XMP `dc:identifier` use `asset_id` for consistency

### Album system

- `PhotoLibrary.albums` property enumerates albums via CloudKit API
- Recursive subfolder traversal for nested album hierarchies (albumType=3)
- `PhotoAlbum.uuid` and `.record_change_tag` used for cache invalidation
- Album membership cached in `.albums/<name>.json` to avoid re-fetching
- Subfolder structure cached in `.albums/<path>/.meta.json`

## Development

### Setup

```sh
scripts/install_deps   # install in editable mode with dev deps
```

### Commands

```sh
scripts/test           # run pytest with coverage
scripts/lint           # ruff lint
scripts/format         # ruff format
scripts/build          # build Python wheel
```

Alternatively run tests directly:

```sh
.venv/bin/pytest tests/                        # full suite
.venv/bin/pytest tests/test_album_cache.py -v  # specific file
```

### Testing

- 24 test files in `tests/`
- Uses vcrpy for HTTP recording, pytest, freezegun for time mocking
- 100% test coverage expected for new code
- Test cassettes contain cached iCloud API responses (never use private photos)

### Code style

- Formatted with ruff
- No lint errors (`scripts/lint`)
- Changelog: update `## Unreleased` section in `CHANGELOG.md`
- Reference docs: `docs/reference.md` for CLI parameters
