"""
Media Inspector CLI Tool

Recursively scans a root directory for movie-like media files, extracts rich metadata using FFProbe,
displays progress with scoped spinners, and writes structured output to a timestamped JSON file
saved next to this script.

Dependencies:
    - Python 3.10+
    - Typer CLI framework: `pip install typer`
    - alive-progress for spinner feedback: `pip install alive-progress`
    - FFmpeg (includes FFProbe): https://ffmpeg.org/download.html

FFProbe Requirements:
    - FFProbe must be installed and accessible via system PATH.
    - To verify, run `ffprobe -version` in your terminal.

Metadata Coverage:
    - Audio, video, subtitle, and attachment streams
    - Format-level metadata
    - Chapters and stream tags
    - Language, codec, disposition, and embedded resources

Note:
    - Only movie-like formats are scanned: .mkv, .mp4, .mov, .avi, .ogm, .wmv
    - Video streams flagged as cover art (attached_pic == 1) are excluded from results
"""

from collections import defaultdict
import subprocess
import json
from pathlib import Path
from shutil import which
from datetime import datetime, timezone, timedelta
from time import perf_counter
import time
from logging.handlers import RotatingFileHandler
from typing import List, Optional, Tuple, Any
from dataclasses import dataclass
import logging
from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.live import Live
from rich.align import Align
import typer

log_path = Path(__file__).resolve().parent / "media_inspection.log"

# Create a rotating file handler
log_handler = RotatingFileHandler(
    log_path,
    maxBytes=1_000_000,       # ~1MB per log file
    backupCount=3,            # Keep up to 3 old logs
    encoding="utf-8"          # Ensure UTF-8 encoding
)

# Define log format
formatter = logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log_handler.setFormatter(formatter)

# Configure root logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(log_handler)

console = Console()

@dataclass
class RenderInput:
    root_path: Path
    processed_files: List[Path]
    metadata_map: dict[Path, dict[str, Any]]
    duration_map: Optional[dict[Path, float]] = None
    current_file: Optional[Path] = None
    errors: Optional[List[str]] = None
    include_all_folders: bool = False

@dataclass
class FolderSummary:
    path: Path
    depth: int
    ok: int
    pend: int
    err: int
    has_subfolders: bool

    @property
    def total(self) -> int:
        return self.ok + self.pend + self.err

@dataclass
class TreeRenderContext:
    errors: set[str]
    duration_map: dict[Path, float]
    current_file: Optional[Path]
    folder_tree: dict[Path, List[Path]]
    subfolder_map: dict[Path, List[Path]]
    metadata_map: dict[Path, dict[str, Any]]
    include_all_folders: bool = False  # Optional flag if needed

class TreeRenderer:
    def __init__(self, root_path: Path, context: TreeRenderContext):
        self.root_path = root_path
        self.context = context
        self.error_set = set(context.errors)
        self.duration_map = context.duration_map

    def collect_descendant_files(self, folder: Path) -> List[Path]:
        descendants = []
        stack = [folder]
        while stack:
            current = stack.pop()
            descendants.extend(self.context.folder_tree.get(current, []))
            stack.extend(self.context.subfolder_map.get(current, []))
        return descendants

    def get_file_status(self, file: Path) -> tuple[str, str]:
        if str(file) in self.error_set:
            return "❌", "bold red"
        if file == self.context.current_file:
            return "🔄", "dim italic"
        return "✅", "bold green"

    def render_file_line(self, file: Path, index: int, total: int, depth: int) -> Text:
        prefix, style = self.get_file_status(file)
        elapsed = self.duration_map.get(file)
        # dur_str = f" 🕒 {format_duration(elapsed)}" if elapsed and prefix == "✅" else ""
        dur_str = ""
        if elapsed and prefix == "✅":
            td = timedelta(seconds=elapsed)
            dur_str = f" 🕒 {format_time_delta(td)}"

        connector = "└──" if index == total - 1 else "├──"
        indent = "│   " * (depth + 1)
        return Text(f"{indent}{connector} {prefix} {file.name}{dur_str}", style=style)

    def summarize_folder(self, files: List[Path]) -> tuple[int, int, int]:
        ok = sum(1 for f in files if str(f) not in self.error_set and f != self.context.current_file)
        err = sum(1 for f in files if str(f) in self.error_set)
        pend = len(files) - ok - err
        return ok, pend, err

    def summarize_descendants(self, folder: Path) -> tuple[int, int, int, int]:
        descendants = self.collect_descendant_files(folder)
        desc_total = len(descendants)
        desc_ok = sum(1 for f in descendants if str(f) not in self.error_set and f != self.context.current_file)
        desc_err = sum(1 for f in descendants if str(f) in self.error_set)
        desc_pend = desc_total - desc_ok - desc_err
        return desc_total, desc_ok, desc_err, desc_pend

    def get_folder_style(self, desc_total: int, desc_ok: int, desc_err: int, desc_pend: int) -> str:
        if desc_total == 0:
            return "grey50"
        if desc_err == desc_total:
            return "bold red"
        if desc_ok > 0 and desc_err > 0:
            return "bold magenta"
        if desc_pend > 0:
            return "bold yellow"
        return "bold green"

    def render_folder_header(self, summary: FolderSummary) -> Text:
        indent_prefix = "│   " * summary.depth
        # folder_name = summary.path.name if summary.path != self.root_path else self.root_path.name
        folder_name = (
            summary.path.name
            if summary.path != self.root_path or self.root_path.name
            else f"[base path] {self.root_path.drive or self.root_path}"
        )

        if summary.total > 0:
            status = f"{summary.ok} ✅, {summary.pend} 🔄, {summary.err} ❌"
            suffix = f" — {summary.total} files ({status})"
        elif summary.has_subfolders:
            suffix = ""
        else:
            suffix = " — folder is empty"

        return Text(
            f"{indent_prefix}📁 {folder_name}{suffix}",
            style=self.get_folder_style(*self.summarize_descendants(summary.path))
        )

    def render_folder(self, folder: Path, depth: int, lines: List[Text]):
        files = self.context.folder_tree.get(folder, [])
        ok, pend, err = self.summarize_folder(files)
        summary = FolderSummary(
            path=folder,
            depth=depth,
            ok=ok,
            pend=pend,
            err=err,
            has_subfolders=bool(self.context.subfolder_map.get(folder))
        )
        header = self.render_folder_header(summary)

        lines.append(header)
        for i, file in enumerate(sorted(files, key=lambda p: p.name.lower())):
            lines.append(self.render_file_line(file, i, len(files), depth))
        for subfolder in sorted(self.context.subfolder_map.get(folder, []), key=lambda p: str(p).lower()):
            self.render_folder(subfolder, depth + 1, lines)

    def render(self) -> List[Text]:
        lines: List[Text] = []
        self.render_folder(self.root_path, depth=0, lines=lines)
        return lines

def log_success(message: str):
    logging.info("✅ %s", message)

def log_error(message: str):
    logging.error("❌ %s", message)

def log_warning(message: str):
    logging.warning("📛 %s", message)

def log_inspection(message: str):
    logging.info("🔍 %s", message)

def log_action(message: str):
    logging.info("%s", message)

def ffprobe_exists() -> bool:
    """Check if FFProbe is available in system path."""
    return which("ffprobe") is not None

def get_media_files(root: Path, extensions: List[str]) -> List[Path]:
    """Recursively find media files under a root directory."""
    return [p for p in root.rglob("*") if p.suffix.lower() in extensions and p.is_file()]

def probe_file(file_path: Path) -> Optional[dict[str, Any]]:
    """Run FFProbe on a media file and return parsed metadata."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                "-show_chapters",
                "-show_entries", "stream_tags:format_tags:chapter_tags",
                str(file_path)
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True
        )
        raw_data = json.loads(result.stdout)

        # Filter out cover art streams
        filtered_streams = [
            s for s in raw_data.get("streams", [])
            if not (s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic") == 1)
        ]
        raw_data["streams"] = filtered_streams
        return raw_data

    except subprocess.CalledProcessError:
        log_error(f"FFProbe failed for file: {file_path}")
        return None

@staticmethod
def format_time_delta(td: timedelta) -> str:
    years, remainder = divmod(td.days, 365)
    months, days = divmod(remainder, 30)
    hours, remainder = divmod(td.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    milliseconds = td.microseconds // 1000

    parts = []
    if years: parts.append(f"{years} year{'s' if years > 1 else ''}")
    if months: parts.append(f"{months} month{'s' if months > 1 else ''}")
    if days: parts.append(f"{days} day{'s' if days > 1 else ''}")
    if hours: parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
    if minutes: parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")

    no_larger_units = all(x == 0 for x in (years, months, days, hours, minutes))
    if seconds or no_larger_units:
        parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
    if milliseconds:
        parts.append(f"{milliseconds} millisecond{'s' if milliseconds != 1 else ''}")

    return ", ".join(parts)

def format_duration(seconds: float) -> str:
    try:
        hours, remainder = divmod(int(seconds), 3600)
        minutes, secs = divmod(remainder, 60)
        millis = int((seconds - int(seconds)) * 1000)
        return f"{hours}:{minutes:02}:{secs:02}.{millis:03}"
    except (ValueError, TypeError):
        return "Unknown"

def print_summary(success_count: int, error_files: List[str], timestamp: str) -> None:
    """Print a timestamped summary of the processing results."""
    print("\n✅ Inspection complete")
    print(f"🕒 Timestamp: {timestamp}")
    print(f"📁 Files processed: {success_count + len(error_files)}")
    print(f"🟢 Successes: {success_count}")
    print(f"🔴 Failures: {len(error_files)}")

    if error_files:
        print("🔍 Files with errors:")
        for f in error_files:
            print(f"  - {f}")

def build_folder_tree(processed_files: List[Path]) -> dict[Path, List[Path]]:
    folder_tree = defaultdict(list)
    for file in processed_files:
        folder_tree[file.parent].append(file)
    return folder_tree

def build_folder_to_files(files: List[Path]) -> dict[Path, List[Path]]:
    folder_map: dict[Path, List[Path]] = defaultdict(list)
    for file in files:
        folder_map[file.parent].append(file)
    return folder_map

def resolve_all_folders(root_path: Path, processed_files: List[Path], include_all: bool) -> set[Path]:
    if include_all:
        all_folders = set(p for p in root_path.rglob("*") if p.is_dir())
        all_folders.add(root_path)
    else:
        all_folders = set()
        for file in processed_files:
            folder = file.parent
            while folder != root_path:
                all_folders.add(folder)
                folder = folder.parent
            all_folders.add(root_path)
    return all_folders

def map_subfolders(sorted_folders: List[Path], root_path: Path) -> dict[Path, List[Path]]:
    subfolder_map = defaultdict(list)
    for folder in sorted_folders:
        parent = folder.parent if folder != root_path else None
        if parent and parent in sorted_folders:
            subfolder_map[parent].append(folder)
    return subfolder_map

def render_tree(
    root_path: Path,
    folder_tree: dict[Path, List[Path]],
    subfolder_map: dict[Path, List[Path]],
    metadata_map: dict[Path, dict[str, Any]],
    context: TreeRenderContext
) -> List[Text]:
    # Merge context with tree data
    full_context = TreeRenderContext(
        errors=context.errors,
        duration_map=context.duration_map,
        current_file=context.current_file,
        folder_tree=folder_tree,
        subfolder_map=subfolder_map,
        metadata_map=metadata_map,
        include_all_folders=getattr(context, "include_all_folders", False)
    )
    return TreeRenderer(root_path, full_context).render()

def build_tree_lines(
    root_path: Path,
    processed_files: List[Path],
    metadata_map: dict[Path, dict[str, Any]],
    context: TreeRenderContext
) -> List[Text]:
    folder_tree = build_folder_tree(processed_files)
    all_folders = resolve_all_folders(root_path, processed_files, context.include_all_folders)
    sorted_folders = sorted(all_folders, key=lambda p: (len(p.relative_to(root_path).parts), str(p)))
    subfolder_map = map_subfolders(sorted_folders, root_path)

    return render_tree(
        root_path=root_path,
        folder_tree=folder_tree,
        subfolder_map=subfolder_map,
        metadata_map=metadata_map,
        context=context
    )

def build_render_context(inputs: RenderInput) -> TreeRenderContext:
    folder_tree = build_folder_tree(inputs.processed_files)
    all_folders = resolve_all_folders(inputs.root_path, inputs.processed_files, inputs.include_all_folders)
    sorted_folders = sorted(all_folders, key=lambda p: (len(p.relative_to(inputs.root_path).parts), str(p)))
    subfolder_map = map_subfolders(sorted_folders, inputs.root_path)

    return TreeRenderContext(
        errors=set(inputs.errors or []),
        duration_map=inputs.duration_map or {},
        current_file=inputs.current_file,
        folder_tree=folder_tree,
        subfolder_map=subfolder_map,
        metadata_map=inputs.metadata_map,
        include_all_folders=inputs.include_all_folders
    )

def render_panel(inputs: RenderInput, progress_text: Optional[Text] = None) -> Panel:
    context = build_render_context(inputs)
    tree_lines = TreeRenderer(inputs.root_path, context).render()

    combined = Text()

    # ⏳ Progress line (e.g. "Inspecting media files [2/2] 100%")
    if progress_text:
        combined.append(progress_text)
        combined.append("\n")

    # 🔧 Working on line (e.g. "Working on: video2.mp4")
    if inputs.current_file:
        working_line = Text(f"🔧 Working on: {inputs.current_file.name}", style="bold yellow")
        combined.append(working_line)
        combined.append("\n")

    for line in tree_lines:
        combined.append(line.copy().append("\n"))

    term_width = console.size.width
    max_width = max(min(term_width - 6, 140), 60)

    return Panel.fit(
        Align.left(combined),
        title="📁 Media Files",
        border_style="green",
        width=max_width
    )

def build_summary_panel(results: List[dict[str, Any]], errors: List[str], total_duration: float, start_local: datetime, end_local: datetime) -> Panel:
    start_timestamp = start_local.strftime("%Y-%m-%d %H:%M:%S %Z")
    end_timestamp = end_local.strftime("%Y-%m-%d %H:%M:%S %Z")
    total_execution_duration = end_local - start_local
    summary_text = Text()
    summary_text.append(
        f"✅ Inspection complete in {format_time_delta(timedelta(seconds=total_duration))}\n",
        style="bold green"
    )
    summary_text.append(f"📄 Total files processed: {len(results)}\n")
    summary_text.append(f"📛 Files with errors: {len(errors)}\n")
    summary_text.append(f"⏰ Started at: {start_timestamp}\n")
    summary_text.append(f"⌚ Completed at: {end_timestamp}\n")
    summary_text.append(f"⌛ Total execution time: {format_time_delta(total_execution_duration)}")

    term_width = console.size.width
    summary_width = max(min(term_width - 6, 100), 60)

    log_action(f"Final Summary => Files processed: {len(results)}, Errors: {len(errors)}")

    return Panel.fit(
        Align.center(summary_text, vertical="middle"),
        title="📊 Summary",
        border_style="bright_blue",
        width=summary_width
    )

def process_files(root_path: Path, files: List[Path]) -> Tuple[List[dict[str, Any]], List[str]]:
    # results: List[dict[str, Any]] = []
    results: dict[str, dict[str, Any]] = {}
    errors: List[str] = []
    metadata_map: dict[Path, dict[str, Any]] = {}
    processed_files: List[Path] = []
    duration_map: dict[Path, float] = {}
    total_duration = 0.0

    console.print(f"\n🎬 Found {len(files)} media files. Beginning inspection...\n", style="bold green")
    log_action(f"Found {len(files)} media files. Beginning inspection.")

    # Sort files case-insensitively before rendering
    files = sorted(files, key=lambda p: str(p).lower())

    folder_to_files = build_folder_to_files(files)

    last_progress_text: Optional[Text] = None

    def normalize_language(value: Optional[str]) -> str:
        return value.strip() if value and value.strip() else "und"

    def clean_attachment_metadata(stream: dict[str, Any]) -> dict[str, Any]:
        excluded_keys = {
            "index", "codec_tag_string", "codec_tag", "r_frame_rate", "avg_frame_rate",
            "time_base", "duration_ts", "start_pts", "duration", "extradata_size", "start_time"
        }
        return {k: v for k, v in stream.items() if k not in excluded_keys}

    def group_attachments_by_mimetype(streams: List[dict[str, Any]]) -> dict[str, List[dict[str, Any]]]:
        grouped = defaultdict(list)
        for stream in streams:
            if stream.get("codec_type") == "attachment":
                mimetype = stream.get("tags", {}).get("mimetype") or stream.get("mimetype") or "unknown"
                cleaned = clean_attachment_metadata(stream)
                grouped[mimetype].append(cleaned)
        return dict(grouped)

    def build_stream_entry(stream: dict[str, Any]) -> Optional[dict[str, Any]]:
        type_map = {
            "video": "videos",
            "audio": "audios",
            "subtitle": "subtitles"
        }

        codec_type = stream.get("codec_type")
        if codec_type not in type_map:
            return None

        tags = stream.get("tags", {})
        language = normalize_language(tags.get("language") or stream.get("language"))
        name = tags.get("title") or tags.get("track_name") or ""

        disposition = stream.get("disposition", {})
        default_track = bool(disposition.get("default", 0))
        forced_display = bool(disposition.get("forced", 0))

        tab_duration = stream.get("tag_duration") or tags.get("DURATION")

        width = stream.get("width")
        height = stream.get("height")
        resolution = f"{width}x{height}" if width and height else None

        entry = {
            "Codec": stream.get("codec_name"),
            "Default_track": default_track,
            "Forced_display": forced_display,
            "Language": language,
            "Name": name,
            "Type": codec_type
        }

        if codec_type == "audio":
            entry["Properties"] = {
                "channels": stream.get("channels"),
                "codec_long_name": stream.get("codec_long_name"),
                "index": stream.get("index"),
                "sample_rate": stream.get("sample_rate"),
                "tag_duration": tab_duration
            }

        elif codec_type == "video":
            entry["Properties"] = {
                "resolution": resolution,
                "codec_long_name": stream.get("codec_long_name"),
                "index": stream.get("index"),
                "r_frame_rate": stream.get("r_frame_rate"),
                "tag_duration": tab_duration
            }

        elif codec_type == "subtitle":
            entry["Properties"] = {
                "codec_long_name": stream.get("codec_long_name"),
                "index": stream.get("index"),
                "tag_duration": tab_duration
            }

        return type_map[codec_type], entry

    def categorize_streams(streams: List[dict[str, Any]]) -> dict[str, List[dict[str, Any]]]:
        categories = {"videos": [], "audios": [], "subtitles": []}

        for stream in streams:
            result = build_stream_entry(stream)
            if result:
                category, entry = result
                categories[category].append(entry)

        return categories

    def format_chapters(chapters: List[dict[str, Any]]) -> List[dict[str, Any]]:
        formatted = []
        for chapter in chapters:
            formatted.append({
                "start_time": float(chapter.get("start_time", 0)),
                "end_time": float(chapter.get("end_time", 0)),
                "title": chapter.get("tags", {}).get("title", "")
            })
        return formatted

    def process_single_file(file: Path) -> None:
        log_inspection(f"Probing file: {file.name}")

        nonlocal total_duration, last_progress_text

        start = perf_counter()
        metadata = probe_file(file)
        elapsed = perf_counter() - start
        total_duration += elapsed

        if metadata:
            log_success(f"Metadata extracted from {file.name} in {elapsed:.2f}s")
            streams = metadata.get("streams", [])
            chapters = metadata.get("chapters", [])

            attachments = group_attachments_by_mimetype(streams)
            categorized = categorize_streams(streams)
            chapter_data = format_chapters(chapters)

            results[file.name] = {
                "attachments": attachments,
                "audios": categorized["audios"],
                "chapters": chapter_data,
                "subtitles": categorized["subtitles"],
                "videos": categorized["videos"]
            }
            metadata_map[file] = metadata
            duration_map[file] = elapsed
        else:
            log_error(f"Failed to extract metadata from {file.name}")
            errors.append(str(file))

        processed_files.append(file)

        progress_text = Text(f"Inspecting media files [{len(processed_files)}/{len(files)}] ")
        progress_text.append(f"{int((len(processed_files) / len(files)) * 100)}%", style="bold green")
        last_progress_text = progress_text

        inputs = RenderInput(
            root_path=root_path,
            processed_files=processed_files,
            metadata_map=metadata_map,
            duration_map=duration_map,
            current_file=file,
            errors=errors,
            include_all_folders=False
        )

        live.update(render_panel(inputs, progress_text=last_progress_text))
        # time.sleep(1.0)

    def process_folder(folder: Path):
        if not folder.exists():
            log_warning(f"Skipping nonexistent folder: {folder}")
            return

        if not folder.is_dir():
            log_warning(f"Skipping non-directory path: {folder}")
            return

        nonlocal total_duration

        for file in sorted(folder_to_files.get(folder, []), key=lambda p: p.name.lower()):
            process_single_file(file)

        try:
            sub_folders = [p for p in folder.iterdir() if p.is_dir()]
            for sub in sorted(sub_folders, key=lambda p: p.name.lower()):
                process_folder(sub)
        except (FileNotFoundError, PermissionError) as e:
            log_error(f"Cannot access folder: {folder} — {e}")
            return

    inputs = RenderInput(
        root_path=root_path,
        processed_files=processed_files,
        metadata_map=metadata_map,
        duration_map=duration_map,
        current_file=None,
        errors=errors,
        include_all_folders=False
    )

    with Live(render_panel(inputs), refresh_per_second=10, console=console) as live:
        process_folder(root_path)

        # Final refresh to clear pending status and ensure last file is marked complete
        inputs = RenderInput(
            root_path=root_path,
            processed_files=processed_files,
            metadata_map=metadata_map,
            duration_map=duration_map,
            current_file=None,
            errors=errors,
            include_all_folders=True
        )

        live.update(render_panel(inputs, progress_text=last_progress_text))

    return results, errors, total_duration

def sort_nested(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: sort_nested(obj[k]) for k in sorted(obj)}
    if isinstance(obj, list):
        return [sort_nested(item) for item in obj]
    return obj

def write_output(data: dict[str, Any]) -> Path:
    """Write metadata results to a timestamped JSON file next to this script."""
    script_dir = Path(__file__).resolve().parent
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_file = script_dir / f"media_info_{timestamp}.json"
    with output_file.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    log_action(f"Metadata written to output file: {output_file}")
    return output_file

def run_inspection(root_dir: Path) -> None:
    """Execute the full inspection workflow."""
    if not ffprobe_exists():
        log_error("FFProbe not found in system PATH. Aborting.")
        print("🚫 FFProbe not found. Aborting.")
        return

    start_utc = datetime.now(timezone.utc)
    start_local = datetime.now()
    start_perf = perf_counter()

    log_action(f"==== Started Media Inspection for {root_dir} at {start_local.strftime('%Y-%m-%d %H:%M:%S')} ====")

    extensions = [".mkv", ".mp4", ".mov", ".avi", ".ogm", ".wmv"]

    media_files = get_media_files(root_dir, extensions)
    results, errors, total_duration = process_files(root_dir, media_files)

    end_utc = datetime.now(timezone.utc)
    end_local = datetime.now()
    end_perf = perf_counter()

    output_data: dict[str, Any] = {
        "start_time_utc": start_utc.isoformat(),
        "start_time_local": start_local.isoformat(),
        "end_time_utc": end_utc.isoformat(),
        "end_time_local": end_local.isoformat(),
        "execution_time_seconds": round(end_perf - start_perf, 2),
        "execution_time_human": format_time_delta(end_local - start_local),
        "summary": {
            "total_files": len(media_files),
            "processed_successfully": len(results),
            "failed": len(errors)
        },
        "root_directory": str(root_dir),
        "results": results
    }

    output_data["results"] = sort_nested(output_data["results"])
    final_output = output_data
    write_output(final_output)
    # write_output(output_data) # Write output without printing path

    console.print(build_summary_panel(results, errors, total_duration, start_local, end_local))
    log_action(f"==== Completed Media Inspection at {end_local.strftime('%Y-%m-%d %H:%M:%S')} ====")

if __name__ == "__main__":
    typer.run(run_inspection)
