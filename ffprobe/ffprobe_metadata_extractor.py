"""
Media Inspector CLI Tool

Recursively scans a root directory for media files, extracts rich metadata using FFProbe,
displays progress with scoped spinners, and writes structured output to a timestamped JSON file.

Features:
- 🎬 Supports .mkv, .mp4, .mov, .avi, .ogm, .wmv formats
- 🔍 Extracts audio, video, subtitle, chapter, and attachment metadata
- 📊 Displays real-time progress with emotional feedback
- 📁 Renders folder trees with status icons and durations
- 📝 Outputs structured JSON with timestamps and summaries

Requirements:
- Python 3.10+
- FFmpeg (includes FFProbe): https://ffmpeg.org/download.html
-- FFmpeg (FFProbe must be in system PATH)
- Typer CLI framework (`pip install typer`)
- rich (`pip install rich`)

FFProbe Requirements:
    - FFProbe must be installed and accessible via system PATH.
    - To verify, run `ffprobe -version` in your terminal.
"""
from collections import defaultdict
import subprocess
import json
from pathlib import Path
# from shutil import which
from datetime import datetime, timezone, timedelta
from time import perf_counter
# import time
from logging.handlers import RotatingFileHandler
from os import PathLike
from typing import List, Dict, Optional, Tuple, Union, Any
from dataclasses import dataclass
import logging
from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.live import Live
from rich.align import Align
import typer

# If script is run in an environment without __file__ (e.g., interactive shell), fallback to current working directory
script_dir = Path(__file__).resolve().parent if '__file__' in globals() else Path.cwd()
log_path = script_dir / "media_inspection.log"

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

MEDIA_EXTENSIONS = [".mkv", ".mp4", ".mov", ".avi", ".ogm", ".wmv"]

@dataclass
class RenderInput:
    """
    Input payload for rendering the media tree panel.

    Attributes:
        root_path: Root directory being scanned.
        processed_files: List of successfully processed media files.
        metadata_map: Raw metadata per file.
        duration_map: Optional map of durations per file.
        current_file: File currently being processed.
        errors: List of file paths that failed to process.
        include_all_folders: Whether to include all folders in tree rendering.
    """
    root_path: Path
    processed_files: List[Union[str, Path, PathLike]]
    metadata_map: Dict[Union[str, Path, PathLike], Dict[str, Any]]
    duration_map: Optional[Dict[Union[str, Path, PathLike], float]] = None
    current_file: Optional[Union[str, Path, PathLike]] = None
    errors: Optional[List[str]] = None
    include_all_folders: bool = False

@dataclass
class FolderSummary:
    """
    Summary of a folder's inspection status.

    Attributes:
        path: Path to the folder.
        depth: Depth level in the folder tree.
        ok: Count of successfully processed files.
        pend: Count of pending files.
        err: Count of errored files.
        has_subfolders: Whether the folder contains subfolders.
    """
    path: Path
    depth: int
    ok: int
    pend: int
    err: int
    has_subfolders: bool

    @property
    def total(self) -> int:
        """
        Returns the cumulative count of all tracked items.

        Combines successful (`ok`), pending (`pend`), and errored (`err`) entries
        into a single total, offering a quick snapshot of overall progress.

        Returns:
            The sum of ok, pend, and err counts as an integer.
        """
        return self.ok + self.pend + self.err

@dataclass
class TreeRenderContext:
    """
    Context for rendering the folder tree.

    Attributes:
        errors: Set of file paths that failed.
        duration_map: Map of durations per file.
        current_file: File currently being processed.
        folder_tree: Mapping of folders to their files.
        subfolder_map: Mapping of folders to their subfolders.
        metadata_map: Raw metadata per file.
        include_all_folders: Whether to include all folders in rendering.
    """
    errors: set[str]
    duration_map: Dict[Union[str, Path, PathLike], float]
    current_file: Optional[Union[str, Path, PathLike]]
    folder_tree: Dict[Union[str, Path, PathLike], List[Union[str, Path, PathLike]]]
    subfolder_map: Dict[Union[str, Path, PathLike], List[Union[str, Path, PathLike]]]
    metadata_map: Dict[Union[str, Path, PathLike], Dict[str, Any]]
    include_all_folders: bool = False  # Optional flag if needed

@dataclass
class TraversalState:
    """
    Holds the mutable state during folder traversal and metadata extraction.

    Attributes:
        results (Dict[str, Dict[str, Any]]): Metadata results keyed by filename.
        errors (List[str]): List of file paths that failed to process.
        metadata_map (Dict[Union[str, Path, PathLike], Dict[str, Any]]): Raw metadata per file.
        processed_files (List[Union[str, Path, PathLike]]): Files successfully processed.
        duration_map (Dict[Union[str, Path, PathLike], float]): Duration taken per file.
        last_progress_text (Optional[Text]): Last rendered progress text.
    """
    results: Dict[str, Dict[str, Any]]
    errors: List[str]
    metadata_map: Dict[Union[str, Path, PathLike], Dict[str, Any]]
    processed_files: List[Union[str, Path, PathLike]]
    duration_map: Dict[Union[str, Path, PathLike], float]
    last_progress_text: Optional[Text] = None

@dataclass
class ProcessingContext:
    """
    Encapsulates static configuration and traversal state for the inspection process.

    Attributes:
        root_path: The root directory being scanned.
        files: Sorted list of media files to inspect.
        folder_to_files: Mapping of folders to their contained files.
        live: Rich Live instance for dynamic rendering.
        state: TraversalState object holding mutable inspection data.
    """
    root_path: Path
    files: List[Union[str, Path, PathLike]]
    folder_to_files: Dict[Union[str, Path, PathLike], List[Union[str, Path, PathLike]]]
    live: Live
    state: TraversalState

class TreeRenderer:
    """
    Renders a folder tree with status icons, durations, and emotional feedback.

    Attributes:
        root_path: Root directory of the inspection.
        context: TreeRenderContext containing metadata and traversal state.
    """
    def __init__(self, root_path: Path, context: TreeRenderContext):
        """
        Initializes the TreeRenderer with root path and rendering context.

        Args:
            root_path: Root directory of the inspection.
            context: TreeRenderContext with metadata and traversal state.
        """
        self.root_path = root_path
        self.context = context
        self.error_set = set(context.errors)
        self.duration_map = context.duration_map

    def collect_descendant_files(self, folder: Union[str, Path, PathLike]) -> List[Path]:
        """
        Recursively collects all descendant media files under a folder.

        Args:
            folder: Folder to scan.

        Returns:
            List of media file paths under the folder and its subfolders.
        """
        descendants = []
        stack = [folder]
        while stack:
            current = stack.pop()
            descendants.extend(self.context.folder_tree.get(current, []))
            stack.extend(self.context.subfolder_map.get(current, []))
        return descendants

    def get_file_status(self, file: Path) -> Tuple[str, str]:
        """
        Determines the status icon and style for a file.

        Args:
            file: File to evaluate.

        Returns:
            Tuple of (emoji icon, Rich style string).
        """
        if str(file) in self.error_set:
            return "❌", "bold red"
        if file == self.context.current_file:
            return "🔄", "dim italic"
        return "✅", "bold green"

    def render_file_line(self, file: Path, index: int, total: int, depth: int) -> Text:
        """
        Renders a single line for a media file in the tree.

        Args:
            file: File to render.
            index: Index of the file within its folder.
            total: Total number of files in the folder.
            depth: Depth level in the folder tree.

        Returns:
            Rich Text object representing the file line.
        """
        prefix, style = self.get_file_status(file)
        elapsed = self.duration_map.get(file)
        dur_str = ""
        if elapsed and prefix == "✅":
            td = timedelta(seconds=elapsed)
            dur_str = f" 🕒 {format_time_delta(td)}"

        connector = "└──" if index == total - 1 else "├──"
        indent = "│   " * (depth + 1)
        return Text(f"{indent}{connector} {prefix} {file.name}{dur_str}", style=style)

    def summarize_folder(self, files: List[Union[str, Path, PathLike]]) -> Tuple[int, int, int]:
        """
        Summarizes the status of files in a folder.

        Args:
            files: List of media files in the folder.

        Returns:
            Tuple of (ok, pending, error) counts.
        """
        ok = sum(1 for f in files if str(f) not in self.error_set and f != self.context.current_file)
        err = sum(1 for f in files if str(f) in self.error_set)
        pend = len(files) - ok - err
        return ok, pend, err

    def summarize_descendants(self, folder: Path) -> Tuple[int, int, int, int]:
        """
        Summarizes the status of all descendant files under a folder.

        Args:
            folder: Folder to summarize.

        Returns:
            Tuple of (total, ok, error, pending) counts.
        """
        descendants = self.collect_descendant_files(folder)
        desc_total = len(descendants)
        desc_ok = sum(1 for f in descendants if str(f) not in self.error_set and f != self.context.current_file)
        desc_err = sum(1 for f in descendants if str(f) in self.error_set)
        desc_pend = desc_total - desc_ok - desc_err
        return desc_total, desc_ok, desc_err, desc_pend

    def get_folder_style(self, desc_total: int, desc_ok: int, desc_err: int, desc_pend: int) -> str:
        """
        Determines the Rich style for a folder header based on descendant status.

        Args:
            desc_total: Total descendant files.
            desc_ok: Successfully processed files.
            desc_err: Failed files.
            desc_pend: Pending files.

        Returns:
            Rich style string.
        """
        if desc_total == 0:
            return "grey50"
        if desc_err == desc_total:
            return "bold red"
        if desc_ok > 0 and desc_err > 0:
            return "bold magenta"
        if desc_pend > 0:
            return "bold yellow"
        return "bold green"

    def is_truly_empty(self, folder: Path) -> bool:
        """
        Determines whether a folder is physically empty on disk.

        This includes checking for the absence of any files or subdirectories,
        regardless of media type. Inaccessible folders (due to permissions or
        missing paths) are treated as non-empty to avoid false negatives.

        Args:
            folder: Path to the folder being evaluated.

        Returns:
            True if the folder contains no visible or hidden entries; False otherwise.
        """
        try:
            return not any(folder.iterdir())
        except (PermissionError, FileNotFoundError):
            return False  # Treat inaccessible folders as non-empty

    def render_folder_header(self, summary: FolderSummary) -> Text:
        """
        Renders the header line for a folder in the tree.

        Args:
            summary: FolderSummary object.

        Returns:
            Rich Text object representing the folder header.
        """
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
        elif self.is_truly_empty(summary.path):
            suffix = " — folder is empty"
        else:
            suffix = " — no media files found"

        return Text(
            f"{indent_prefix}📁 {folder_name}{suffix}",
            style=self.get_folder_style(*self.summarize_descendants(summary.path))
        )

    def render_folder(self, folder: Path, depth: int, lines: List[Text]):
        """
        Recursively renders a folder and its contents into tree lines.

        Args:
            folder: Folder to render.
            depth: Depth level in the tree.
            lines: List to append rendered lines to.
        """
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
        """
        Renders the full folder tree starting from the root.

        Returns:
            List of Rich Text lines representing the tree.
        """
        lines: List[Text] = []
        self.render_folder(self.root_path, depth=0, lines=lines)
        return lines

def log_success(message: str):
    """Logs a success message with ✅ prefix."""
    logging.info("✅ %s", message)

def log_error(message: str):
    """Logs an error message with ❌ prefix."""
    logging.error("❌ %s", message)

def log_warning(message: str):
    """Logs a warning message with 📛 prefix."""
    logging.warning("📛 %s", message)

def log_inspection(message: str):
    """Logs an inspection message with 🔍 prefix."""
    logging.info("🔍 %s", message)

def log_action(message: str):
    """Logs a generic action message."""
    logging.info("%s", message)

def ffprobe_exists() -> bool:
    """
    Checks whether FFProbe is available in the system PATH.

    Returns:
        True if FFProbe is found and executable, False otherwise.
    """
    try:
        subprocess.run(
            ["ffprobe", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            encoding="utf-8"
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False

def get_media_files(root: Union[str, Path, PathLike], extensions: List[str]) -> List[Path]:
    """Recursively find media files under a root directory."""
    return [p for p in root.rglob("*") if p.suffix.lower() in extensions and p.is_file()]

def probe_file(file_path: Union[str, Path, PathLike]) -> Optional[Dict[str, Any]]:
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

def format_time_delta(td: timedelta) -> str:
    """
    Formats a time duration in seconds into HH:MM:SS string.

    Args:
        seconds: Duration in seconds.

    Returns:
        A formatted string representing the duration.
    """
    years, remainder = divmod(td.days, 365)
    months, days = divmod(remainder, 30)
    hours, remainder = divmod(td.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    milliseconds = td.microseconds // 1000

    parts = []
    if years:
        parts.append(f"{years} year{'s' if years > 1 else ''}")
    if months:
        parts.append(f"{months} month{'s' if months > 1 else ''}")
    if days:
        parts.append(f"{days} day{'s' if days > 1 else ''}")
    if hours:
        parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
    if minutes:
        parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")

    no_larger_units = all(x == 0 for x in (years, months, days, hours, minutes))
    if seconds or no_larger_units:
        parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
    if milliseconds:
        parts.append(f"{milliseconds} millisecond{'s' if milliseconds != 1 else ''}")

    return ", ".join(parts)

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

def build_folder_tree(processed_files: List[Union[str, Path, PathLike]]) -> Dict[Path, List[Path]]:
    """
    Builds a mapping of folders to their contained media files.

    Args:
        processed_files: List of media files that were successfully processed.

    Returns:
        Dictionary mapping each folder path to a list of its media files.
    """
    folder_tree = defaultdict(list)
    for file in processed_files:
        folder_tree[file.parent].append(file)
    return folder_tree

def build_folder_to_files(files: List[Union[str, Path, PathLike]]) -> Dict[Path, List[Path]]:
    """
    Groups media files by their parent folders.

    Args:
        files: List of media file paths.

    Returns:
        Dictionary mapping folder paths to lists of files within them.
    """
    folder_map: Dict[Union[str, Path, PathLike], List[Union[str, Path, PathLike]]] = defaultdict(list)
    for file in files:
        folder_map[file.parent].append(file)
    return folder_map

def resolve_all_folders(root_path: Path, processed_files: List[Union[str, Path, PathLike]], include_all: bool) -> set[Path]:
    """
    Resolves all folders to be included in the tree rendering.

    Args:
        root_path: Root directory of the inspection.
        processed_files: List of successfully processed media files.
        include_all: Whether to include all folders under root, even if empty.

    Returns:
        Set of folder paths to include in the tree.
    """
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

def map_subfolders(sorted_folders: List[Union[str, Path, PathLike]], root_path: Union[str, Path, PathLike]) -> Dict[Path, List[Path]]:
    """
    Builds a mapping of folders to their direct subfolders.

    Args:
        sorted_folders: List of all folders sorted by depth and name.
        root_path: Root directory of the inspection.

    Returns:
        Dictionary mapping each folder to its subfolders.
    """
    subfolder_map = defaultdict(list)
    for folder in sorted_folders:
        parent = folder.parent if folder != root_path else None
        if parent and parent in sorted_folders:
            subfolder_map[parent].append(folder)
    return subfolder_map

def render_tree(
    root_path: Path,
    folder_tree: Dict[Union[str, Path, PathLike], List[Union[str, Path, PathLike]]],
    subfolder_map: Dict[Union[str, Path, PathLike], List[Union[str, Path, PathLike]]],
    metadata_map: Dict[Union[str, Path, PathLike], Dict[str, Any]],
    context: TreeRenderContext
) -> List[Text]:
    """
    Renders the full folder tree using the provided context and mappings.

    Args:
        root_path: Root directory of the inspection.
        folder_tree: Mapping of folders to their media files.
        subfolder_map: Mapping of folders to their subfolders.
        metadata_map: Raw metadata per file.
        context: TreeRenderContext containing traversal state.

    Returns:
        List of Rich Text lines representing the rendered tree.
    """
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
    processed_files: List[Union[str, Path, PathLike]],
    metadata_map: Dict[Union[str, Path, PathLike], Dict[str, Any]],
    context: TreeRenderContext
) -> List[Text]:
    """
    Constructs tree lines for rendering based on processed files and context.

    Args:
        root_path: Root directory of the inspection.
        processed_files: List of successfully processed media files.
        metadata_map: Raw metadata per file.
        context: TreeRenderContext containing traversal state.

    Returns:
        List of Rich Text lines representing the folder tree.
    """
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
    """
    Converts RenderInput into a TreeRenderContext for tree rendering.

    Args:
        inputs: RenderInput containing metadata, durations, and file state.

    Returns:
        TreeRenderContext with folder mappings and traversal state.
    """
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
    """
    Builds a Rich panel combining progress text and folder tree rendering.

    Args:
        inputs: RenderInput containing metadata and traversal state.
        progress_text: Optional progress line to display at the top.

    Returns:
        Rich Panel object with tree and progress information.
    """
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

def build_summary_panel(results: List[Dict[str, Any]], errors: List[str], total_duration: float, start_local: datetime, end_local: datetime) -> Panel:
    """
    Builds a Rich summary panel displaying inspection results and timing details.

    Args:
        results: List of metadata dictionaries for successfully processed files.
        errors: List of file paths (as strings) that failed to process.
        total_duration: Total duration spent inspecting files, in seconds.
        start_local: Local timestamp when inspection started.
        end_local: Local timestamp when inspection completed.

    Returns:
        A Rich Panel object summarizing the inspection with:
            - Total files processed
            - Number of errors
            - Start and end timestamps
            - Total execution time
            - Emotional closure via icons and styled text
    """
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

def normalize_language(value: Optional[str]) -> str:
    """
    Normalizes a language string by stripping whitespace and defaulting to 'und'.

    Args:
        value: Language value from metadata (may be None or empty).

    Returns:
        A cleaned language code string, or 'und' if undefined.
    """
    return value.strip() if value and value.strip() else "und"

def clean_attachment_metadata(stream: Dict[str, Any]) -> Dict[str, Any]:
    """
    Removes extraneous keys from an attachment stream for cleaner output.

    Args:
        stream: Raw attachment stream dictionary from FFProbe.

    Returns:
        A filtered dictionary with only relevant metadata.
    """
    excluded_keys = {
        "index", "codec_tag_string", "codec_tag", "r_frame_rate", "avg_frame_rate",
        "time_base", "duration_ts", "start_pts", "duration", "extradata_size", "start_time"
    }
    return {k: v for k, v in stream.items() if k not in excluded_keys}

def group_attachments_by_mimetype(streams: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Groups attachment streams by their MIME type.

    Args:
        streams: List of FFProbe stream dictionaries.

    Returns:
        Dictionary mapping MIME types to lists of cleaned attachment metadata.
    """
    grouped = defaultdict(list)
    for stream in streams:
        if stream.get("codec_type") == "attachment":
            mimetype = stream.get("tags", {}).get("mimetype") or stream.get("mimetype") or "unknown"
            cleaned = clean_attachment_metadata(stream)
            grouped[mimetype].append(cleaned)
    return dict(grouped)

def build_stream_entry(stream: Dict[str, Any]) -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    Builds a structured metadata entry for a single stream.

    Args:
        stream: Raw stream dictionary from FFProbe.

    Returns:
        A tuple of (category name, structured entry), or None if stream type is unsupported.
    """
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

    tag_duration = stream.get("tag_duration") or tags.get("DURATION")

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
            "tag_duration": tag_duration
        }

    elif codec_type == "video":
        entry["Properties"] = {
            "resolution": resolution,
            "codec_long_name": stream.get("codec_long_name"),
            "index": stream.get("index"),
            "r_frame_rate": stream.get("r_frame_rate"),
            "tag_duration": tag_duration
        }

    elif codec_type == "subtitle":
        entry["Properties"] = {
            "codec_long_name": stream.get("codec_long_name"),
            "index": stream.get("index"),
            "tag_duration": tag_duration
        }

    return type_map[codec_type], entry

def categorize_streams(streams: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Categorizes media streams into videos, audios, and subtitles.

    Args:
        streams: List of FFProbe stream dictionaries.

    Returns:
        Dictionary with categorized lists of structured stream entries.
    """
    categories = {"videos": [], "audios": [], "subtitles": []}

    for stream in streams:
        result = build_stream_entry(stream)
        if result:
            category, entry = result
            categories[category].append(entry)

    return categories

def format_chapters(chapters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Formats chapter metadata into a simplified structure.

    Args:
        chapters: List of chapter dictionaries from FFProbe.

    Returns:
        List of formatted chapter entries with start/end times and titles.
    """
    formatted = []
    for chapter in chapters:
        formatted.append({
            "start_time": float(chapter.get("start_time", 0)),
            "end_time": float(chapter.get("end_time", 0)),
            "title": chapter.get("tags", {}).get("title", "")
        })
    return formatted

def update_progress_panel(file: Path, context: ProcessingContext) -> None:
    """
    Updates the live Rich panel with current progress and file status.

    Args:
        file: The file currently being processed.
        context: The current processing context.
    """
    progress_text = Text(f"Inspecting media files [{len(context.state.processed_files)}/{len(context.files)}] ")
    progress_text.append(f"{int((len(context.state.processed_files) / len(context.files)) * 100)}%", style="bold green")
    context.state.last_progress_text = progress_text

    inputs = RenderInput(
        root_path=context.root_path,
        processed_files=context.state.processed_files,
        metadata_map=context.state.metadata_map,
        duration_map=context.state.duration_map,
        current_file=file,
        errors=context.state.errors,
        include_all_folders=False
    )
    context.live.update(render_panel(inputs, progress_text=progress_text))
    # time.sleep(1.0)

def extract_metadata(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transforms raw FFProbe metadata into structured categories.

    Args:
        raw_data: Raw metadata dictionary from FFProbe.

    Returns:
        A dictionary containing categorized metadata:
            - attachments
            - audios
            - subtitles
            - videos
            - chapters
    """
    streams = raw_data.get("streams", [])
    chapters = raw_data.get("chapters", [])

    attachments = group_attachments_by_mimetype(streams)
    categorized = categorize_streams(streams)
    chapter_data = format_chapters(chapters)

    return {
        "attachments": attachments,
        "audios": categorized["audios"],
        "chapters": chapter_data,
        "subtitles": categorized["subtitles"],
        "videos": categorized["videos"]
    }

def process_single_file(file: Union[str, Path, PathLike], context: ProcessingContext) -> float:
    """
    Extracts metadata from a single media file and updates the processing context.

    Args:
        file: Path to the media file.
        context: The current processing context.

    Returns:
        Duration taken to process the file (in seconds).
    """
    log_inspection(f"Probing file: {file.name}")
    start = perf_counter()
    metadata = probe_file(file)
    elapsed = perf_counter() - start

    if metadata:
        context.state.results[file.name] = extract_metadata(metadata)
        context.state.metadata_map[file] = metadata
        context.state.duration_map[file] = elapsed
        log_success(f"Metadata extracted from {file.name} in {elapsed:.2f}s")
    else:
        context.state.errors.append(str(file))
        log_error(f"Failed to extract metadata from {file.name}")

    context.state.processed_files.append(file)
    update_progress_panel(file, context)
    return elapsed

def prepare_inspection(files: List[Union[str, Path, PathLike]]) -> Tuple[Dict[Path, List[Path]], List[Path]]:
    """
    Organizes files by their parent folders and sorts them for inspection.

    Args:
        files (List[Union[str, Path, PathLike]]): List of media file paths.

    Returns:
        tuple: A dictionary mapping folders to their files,
            and a sorted list of all files.
    """
    sorted_files = sorted(files, key=lambda p: str(p).lower())
    folder_to_files = build_folder_to_files(sorted_files)
    return folder_to_files, sorted_files

def process_files(root_path: Path, files: List[Union[str, Path, PathLike]]) -> Tuple[List[Dict[str, Any]], List[str], float]:
    """
    Processes a list of media files under a given root path.

    Initializes the processing context, traverses the folder structure,
    extracts metadata for each file, and returns results, errors, and total duration.

    Args:
        root_path (Path): The root directory for traversal.
        files (List[Union[str, Path, PathLike]]): List of media files to inspect.

    Returns:
        tuple: A tuple containing:
            - List of metadata dictionaries for successfully processed files
            - List of file paths (as strings) that failed to process
            - Total duration of the inspection in seconds
    """
    folder_to_files, sorted_files = prepare_inspection(files)

    state = TraversalState(
        results={},
        errors=[],
        metadata_map={},
        processed_files=[],
        duration_map={},
        last_progress_text=None
    )

    context = ProcessingContext(
        root_path=root_path,
        files=sorted_files,
        folder_to_files=folder_to_files,
        live=None,
        state=state
    )

    console.print(f"\n🎬 Found {len(files)} media files. Beginning inspection...\n", style="bold green")
    log_action(f"Found {len(files)} media files. Beginning inspection.")

    def inspect_folder(context: ProcessingContext) -> float:
        """
        Recursively traverses folders and processes each media file.

        Args:
            context: The current processing context.

        Returns:
            Total duration of all file inspections.
        """
        total_duration = 0.0

        def process_folder(folder: Path):
            """
            Recursively processes media files within a folder and its sub_folders.

            Updates the total inspection duration and logs any inaccessible folders.

            Args:
                folder: Path to the folder to process.
            """
            nonlocal total_duration

            if not folder.exists() or not folder.is_dir():
                log_warning(f"Skipped: {folder} (missing or not a folder)")
                return

            for file in sorted(context.folder_to_files.get(folder, []), key=lambda p: p.name.lower()):
                total_duration += process_single_file(file, context)

            try:
                sub_folders = [p for p in folder.iterdir() if p.is_dir()]
            except (FileNotFoundError, PermissionError) as e:
                log_error(f"Cannot access folder: {folder} — {e}")
                return

            for sub in sorted(sub_folders, key=lambda p: p.name.lower()):
                process_folder(sub)

        process_folder(context.root_path)
        return total_duration

    def finalize_inspection(context: ProcessingContext) -> None:
        """
        Renders the final summary panel after all files have been processed.

        Args:
            context: The current processing context.
        """
        inputs = RenderInput(
            root_path=context.root_path,
            processed_files=context.state.processed_files,
            metadata_map=context.state.metadata_map,
            duration_map=context.state.duration_map,
            current_file=None,
            errors=context.state.errors,
            include_all_folders=True
        )
        context.live.update(render_panel(inputs, progress_text=context.state.last_progress_text))

    inputs = RenderInput(
        root_path=root_path,
        processed_files=context.state.processed_files,
        metadata_map=context.state.metadata_map,
        duration_map=context.state.duration_map,
        current_file=None,
        errors=context.state.errors,
        include_all_folders=False
    )

    total_duration = 0.0

    if console.is_terminal:
        with Live(render_panel(inputs), refresh_per_second=10, console=console) as live:
            context.live = live
            total_duration = inspect_folder(context)
            finalize_inspection(context)
    else:
        log_warning("Live rendering disabled: non-TTY environment detected.")

    return context.state.results, context.state.errors, total_duration

def sort_nested(obj: Any) -> Any:
    """
    Recursively sorts dictionaries and lists for consistent output formatting.

    Args:
        obj: Arbitrary nested structure (dict, list, or primitive).

    Returns:
        Sorted version of the input structure.
    """
    if isinstance(obj, dict):
        return {k: sort_nested(obj[k]) for k in sorted(obj)}
    if isinstance(obj, list):
        return [sort_nested(item) for item in obj]
    return obj

def write_output(data: Dict[str, Any], output_dir: Optional[Union[str, Path, PathLike]] = None) -> Path:
    """
    Writes metadata results to a timestamped JSON file in the script directory.

    Args:
        data: Final metadata dictionary to serialize.

    Returns:
        Path to the written output file.
    """
    output_dir = output_dir or script_dir
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"media_info_{timestamp}.json"
    with output_file.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    log_action(f"Metadata written to output file: {output_file}")
    return output_file

def normalize_path(p: str) -> Path:
    """
    Converts a user-provided path string into a fully resolved, absolute Path object.

    This function expands any tilde (~) to the user's home directory and resolves
    symbolic links and relative segments to produce a scroll-safe, canonical path.

    Args:
        p: A string representing a file or folder path. May include user shortcuts or relative segments.

    Returns:
        A fully expanded and resolved Path object, suitable for traversal, inspection, or display.
    """
    return Path(p).expanduser().resolve()

def run_inspection(root_dir: str) -> None:
    """
    Executes the full inspection workflow from start to finish.

    Verifies FFProbe availability, scans for media files, extracts metadata,
    renders progress and summary panels, and writes output to disk.

    Args:
        root_dir: Root directory to scan for media files.
    """
    root_path = normalize_path(root_dir)

    if not ffprobe_exists():
        log_error("FFProbe not found in system PATH. Aborting.")
        print("🚫 FFProbe not found. Aborting.")
        return

    start_utc = datetime.now(timezone.utc)
    start_local = datetime.now()
    start_perf = perf_counter()

    log_action(f"==== Started Media Inspection for {root_path} at {start_local.strftime('%Y-%m-%d %H:%M:%S')} ====")

    media_files = get_media_files(root_path, MEDIA_EXTENSIONS)
    results, errors, total_duration = process_files(root_path, media_files)

    end_utc = datetime.now(timezone.utc)
    end_local = datetime.now()
    end_perf = perf_counter()

    output_data: Dict[str, Any] = {
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
        "root_directory": str(root_path),
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
