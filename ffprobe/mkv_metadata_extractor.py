"""
Extract MKV metadata using ffprobe and output structured JSON.

This script recursively searches a given root directory for `.mkv` files,
extracts detailed metadata using `ffprobe`, and outputs a timestamped JSON
file containing grouped track information, chapters (if available), and
execution metadata.

──────────────────────────────────────────────────────────────────────────────
📦 Required Packages:
    - Python 3.8+
    - ffprobe (part of FFmpeg suite, must be installed and available in PATH)

──────────────────────────────────────────────────────────────────────────────
🧑‍💻 Usage:
    python extract_mkv_metadata.py /path/to/root_directory

──────────────────────────────────────────────────────────────────────────────
⚙️ Arguments:
    root_dir (str)
        The root directory to recursively search for `.mkv` files.

──────────────────────────────────────────────────────────────────────────────
🧪 Examples:
    # Extract metadata from all MKV files under /media/movies
    python extract_mkv_metadata.py /media/movies

    # On Windows
    python extract_mkv_metadata.py "\\path\\to\\media_folder"

──────────────────────────────────────────────────────────────────────────────
📤 Output:
    A JSON file named like:
        <sanitized_root_dir>_YYYYMMDD_HHMMSS.json

    Example:
        media_folder_20250816_115700.json

    The file contains:
        {
            "metadata": {
                "start_time": "...",
                "end_time": "...",
                "execution_time_seconds": ...,
                "execution_time_formatted": "...",
                "root_directory": "..."
            },
            "results": {
                "<file_path>": {
                    "Tracks": {
                        "Videos": [...],
                        "Audios": [...],
                        "Subtitles": [...]
                    },
                    "Chapters": [...]
                },
                ...
            }
        }

──────────────────────────────────────────────────────────────────────────────
📝 Notes:
    - ffprobe must be installed and accessible via the system PATH.
    - This script does not modify or move any media files.
    - Track metadata is grouped and serialized using nested dataclasses
        to ensure lint compliance and maintainable structure.
    - If ffprobe fails on a file, the error is captured in the output.
"""

import argparse
import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple
import shutil

# ----------------------------- Logging Setup -----------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ----------------------------- Dataclasses -----------------------------

@dataclass
class TrackProperties:
    """
    Technical properties of a media track.
    """
    codec_info: str
    specs: Dict[str, Any]
    metadata: Dict[str, Any]  # disposition, codec_id, etc.

@dataclass
class TrackInfo:
    """
    Metadata for a single media track.
    """
    codec: str
    display: Dict[str, str | bool]  # character_set, language, name, etc.
    properties: TrackProperties

@dataclass
class TrackCollection:
    """
    Grouped media tracks by type.
    """
    videos: List[TrackInfo]
    audios: List[TrackInfo]
    subtitles: List[TrackInfo]

@dataclass
class ChapterInfo:
    """
    Represents a single chapter entry extracted from a media file.

    Attributes:
        id (int): Unique chapter identifier.
        start_time (float): Start time of the chapter in seconds.
        end_time (float): End time of the chapter in seconds.
        title (str): Optional title of the chapter.
    """
    id: int
    start_time: float
    end_time: float
    title: str = ""

    def to_dict(self) -> dict[str, int | float | str]:
        """
        Convert ChapterInfo to a JSON-serializable dictionary.

        Returns:
            dict[str, int | float | str]: Dictionary representation of the chapter.
        """
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "title": self.title
        }

@dataclass
class FileMetadata:
    """
    Metadata for an MKV file.
    """
    tracks: TrackCollection
    chapters: List[ChapterInfo]

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert FileMetadata to a dictionary for serialization.

        Returns:
            Dict[str, Any]: Dictionary representation of metadata.
        """
        def serialize_track(track: TrackInfo) -> Dict[str, Any]:
            """
            Convert a TrackInfo object into a dictionary suitable for JSON serialization.

            Args:
                track (TrackInfo): The track metadata to serialize.

            Returns:
                Dict[str, Any]: A dictionary containing codec, type, tags, and technical properties.
            """
            properties = {
                **track.properties.metadata,
                "codec_info": track.properties.codec_info,
            }

            # ✅ Only include specs for audio and video
            track_type = track.display.get("type", "")
            if track_type in ("audio", "video"):
                properties.update(track.properties.specs)

            output = {
                "Codec": track.codec,
                "Default_track": track.display.get("default_track", False),
                "Forced_display": track.display.get("forced_display", False),
                "Language": track.display.get("language", ""),
                "Name": track.display.get("name", ""),
                "Properties": properties,
                "Type": track_type
            }

            return output

        return {
            "videos": [serialize_track(t) for t in self.tracks.videos],
            "audios": [serialize_track(t) for t in self.tracks.audios],
            "subtitles": [serialize_track(t) for t in self.tracks.subtitles],
            "chapters": [chapter.to_dict() for chapter in self.chapters]
        }

class MKVMetadataExtractor:
    """
    Extracts structured metadata from MKV files using ffprobe.

    This class is initialized with a root directory and stores results
    keyed by file path after extraction.
    """

    def __init__(self, root_dir: Path):
        """
        Initialize the extractor with a root directory.

        Args:
            root_dir (Path): Directory to search for MKV files.

        Raises:
            NotADirectoryError: If the provided path is not a directory.
        """
        if not root_dir.is_dir():
            raise NotADirectoryError(f"{root_dir} is not a valid directory.")
        self.root_dir = root_dir
        self.results: Dict[Path, FileMetadata] = {}

    def extract_metadata(self) -> None:
        """
        Recursively extract metadata from all MKV files in the root directory.

        Populates self.results with metadata keyed by file path.
        """
        for file_path in self.root_dir.rglob("*.mkv"):
            try:
                metadata = self.extract_file_metadata(file_path)
                self.results[file_path] = metadata
            except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError, OSError) as e:
                print(f"Error processing {file_path}: {type(e).__name__} - {e}")

    def extract_file_metadata(self, file_path: Path) -> FileMetadata:
        """
        Extract metadata from a single MKV file using ffprobe.

        Args:
            file_path (Path): Path to the MKV file.

        Returns:
            FileMetadata: Parsed metadata for the given file.

        Raises:
            RuntimeError: If ffprobe fails or returns invalid output.
            FileNotFoundError: If the file does not exist.
            json.JSONDecodeError: If ffprobe returns malformed JSON.
        """
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format:stream",
            "-show_chapters",
            "-of", "json",
            str(file_path)
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True)
        except subprocess.CalledProcessError as e:
            logger.error("ffprobe failed for file: %s", file_path)
            logger.error("stderr: %s", e.stderr.strip())
            raise RuntimeError(f"ffprobe failed for {file_path}") from e

        if not result.stdout:
            logger.error("ffprobe returned no output for file: %s", file_path)
            raise RuntimeError(f"No output from ffprobe for file: {file_path}")

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse ffprobe output for file: %s", file_path)
            logger.error("JSONDecodeError: %s", str(e))
            logger.debug("Raw ffprobe output:\n%s", result.stdout)
            raise
        videos, audios, subtitles = [], [], []

        for stream in data.get("streams", []):
            track = self._build_track_info(stream)
            track_type = track.display.get("type", "")
            if track_type == "video":
                videos.append(track)
            elif track_type == "audio":
                audios.append(track)
            elif track_type == "subtitle":
                subtitles.append(track)

        chapters = []
        for chapter in data.get("chapters", []):
            title = chapter.get("tags", {}).get("title", "")
            chapters.append(
                ChapterInfo(
                    id=int(chapter.get("id", 0)),
                    start_time=float(chapter.get("start_time", 0.0)),
                    end_time=float(chapter.get("end_time", 0.0)),
                    title=title
                )
            )

        return FileMetadata(
            tracks=TrackCollection(videos, audios, subtitles),
            chapters=chapters
        )

    def _build_track_info(self, stream: Dict[str, Any]) -> TrackInfo:
        """
        Construct a TrackInfo object from a single ffprobe stream dictionary.

        Args:
            stream (Dict[str, Any]): ffprobe stream data.

        Returns:
            TrackInfo: Structured track metadata.
        """
        raw_tags = stream.get("tags", {})

        raw_tags_with_defaults = dict(raw_tags)
        raw_tags_with_defaults["language"] = raw_tags.get("language", "und") or "und"
        raw_tags_with_defaults["title"] = raw_tags.get("title", "") or ""

        disposition = stream.get("disposition", {})

        metadata = {
            "default_track": disposition.get("default", 0) == 1,
            "enabled_track": disposition.get("enabled", 1) == 1,
            "forced_track": disposition.get("forced", 0) == 1,
            "language": raw_tags.get("language", "und"),
            "number": stream.get("index", -1),
            "tag_duration": raw_tags.get("DURATION", ""),
            "track_name": raw_tags.get("title", "")
        }

        if stream.get("codec_type") == "subtitle":
            encoding = raw_tags.get("ENCODING")
            if encoding:
                metadata["encoding"] = encoding
            metadata["text_subtitles"] = True

        display = {
            "default_track": metadata["default_track"],
            "forced_display": metadata["forced_track"],
            "language": metadata["language"],
            "name": metadata["track_name"],
            "type": stream.get("codec_type", "unknown")
        }

        return TrackInfo(
            codec=stream.get("codec_name", "unknown"),
            display=display,
            properties=TrackProperties(
                codec_info=stream.get("codec_long_name", ""),
                specs=self._parse_track_specs(stream),
                metadata=metadata
            )
        )

    def _parse_track_tags(self, tags: Dict[str, str]) -> Dict[str, str]:
        """
        Extract relevant tags from the raw tag dictionary, ensuring 'language' and 'title' are always present.

        Args:
            tags (Dict[str, str]): Raw tags from ffprobe.

        Returns:
            Dict[str, str]: Filtered and normalized tags with defaults.
        """
        normalized = {key.lower(): value for key, value in tags.items()}
        return {
            "language": normalized.get("language", "und") or "und",
            "title": normalized.get("title", "") or ""
        }

    def _parse_track_specs(self, stream: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract technical specs from a stream dictionary.

        Args:
            stream (Dict[str, Any]): ffprobe stream data.

        Returns:
            Dict[str, Any]: Dictionary of extracted specs.
        """
        specs = {}
        if stream.get("codec_type") == "video":
            width = stream.get("width")
            height = stream.get("height")
            if width and height:
                specs["resolution"] = self._format_resolution(width, height)
            specs["frame_rate"] = stream.get("r_frame_rate")

            # ✅ Add display_dimensions from tags if available
            tags = stream.get("tags", {})
            display_dims = tags.get("DISPLAYDIMENSIONS")
            pixel_dims = tags.get("PIXELDIMENSIONS")

            if display_dims:
                specs["display_dimensions"] = display_dims
            if pixel_dims:
                specs["pixel_dimensions"] = pixel_dims

        elif stream.get("codec_type") == "audio":
            specs["channels"] = stream.get("channels")
            specs["sample_rate"] = stream.get("sample_rate")

        return specs

    def _format_resolution(self, width: int, height: int) -> str:
        """
        Format resolution as a string.

        Args:
            width (int): Width in pixels.
            height (int): Height in pixels.

        Returns:
            str: Formatted resolution string.
        """
        return f"{width}x{height}"

# ----------------------------- Helper Functions -----------------------------

def parse_arguments() -> argparse.Namespace:
    """
    Parse command-line arguments for the metadata extraction script.

    This function defines and parses the required command-line arguments,
    specifically the root directory to search for MKV files.

    Returns:
        argparse.Namespace: Parsed arguments containing the root directory path.
    """
    parser = argparse.ArgumentParser(description="Extract metadata from MKV files.")
    parser.add_argument("root_dir", type=str, help="Root directory to search for MKV files")
    return parser.parse_args()

def sanitize_filename(name: str) -> str:
    """
    Sanitize a string to be safe for use as a filename.

    This function replaces any character that is not alphanumeric, a dash,
    or an underscore with an underscore. It ensures compatibility across
    operating systems and avoids issues with special characters.

    Args:
        name (str): The original filename or directory name.

    Returns:
        str: A sanitized version of the input string suitable for use in file names.
    """
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name)

def sort_dict(item: Any) -> Any:
    """
    Recursively sort dictionary keys for consistent JSON output.

    This function traverses nested dictionaries and lists, sorting all
    dictionary keys alphabetically (case-insensitive). It preserves the
    structure of the input while ensuring deterministic ordering.

    Args:
        item (Any): A dictionary, list, or primitive value.

    Returns:
        Any: A sorted version of the input with dictionaries ordered by key.
    """
    if isinstance(item, dict):
        return {
            k: sort_dict(v)
            for k, v in sorted(item.items(), key=lambda x: str(x[0]).lower())
        }
    if isinstance(item, list):
        return [sort_dict(v) for v in item]
    return item

def format_time_delta(td: timedelta) -> str:
    """
    Format a timedelta object into a human-readable string.

    This function breaks down a timedelta into years, months, days, hours,
    minutes, seconds, and milliseconds. It returns a comma-separated string
    describing the duration in natural language.

    Args:
        td (timedelta): The time difference to format.

    Returns:
        str: A human-readable string representing the duration.
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
    if seconds or not parts:
        parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
    if milliseconds:
        parts.append(f"{milliseconds} millisecond{'s' if milliseconds != 1 else ''}")

    return ", ".join(parts)

def check_executables() -> Tuple[bool, str]:
    """
    Checks if required tools (FFmpeg, FFprobe) are available in system PATH.

    Returns:
        Tuple[bool, str]: A tuple where the first element is True if all tools are available,
                        and the second is an error message or empty string.
    """
    required_tools = ["ffmpeg", "ffprobe"]
    missing_tools = []

    for tool in required_tools:
        if shutil.which(tool) is None:
            logging.error("%s is not installed or not found in system PATH.", tool)
            missing_tools.append(tool)

    if missing_tools:
        error_msg = f"Missing required tools: {', '.join(missing_tools)}"
        return False, error_msg

    return True, ""

# ----------------------------- Main Function -----------------------------

def main() -> None:
    """
    Orchestrate the metadata extraction workflow.

    This function coordinates the entire process:
    - Parses command-line arguments to determine the root directory.
    - Validates the directory and logs the start time.
    - Initializes the metadata extractor and processes all MKV files.
    - Measures execution time and formats it for reporting.
    - Serializes and sorts the results into a structured JSON output.
    - Saves the output to a timestamped file in the script directory.
    - Logs completion and performance metrics.

    Exits:
        The script exits with status code 1 if the root directory is invalid.
    """
    args = parse_arguments()
    root_dir = Path(args.root_dir)

    success, message = check_executables()
    if not success:
        logger.error("Executable check failed: %s", message)
        sys.exit(1)

    if not root_dir.is_dir():
        logger.error("Invalid directory: %s", root_dir)
        sys.exit(1)

    start_time = datetime.now()
    logger.info("Script started at: %s", start_time)
    logger.info("Searching for files in: %s", root_dir)

    extractor = MKVMetadataExtractor(root_dir)
    extractor.extract_metadata()

    end_time = datetime.now()
    execution_time = end_time - start_time
    execution_time_seconds = execution_time.total_seconds()
    execution_time_formatted = format_time_delta(execution_time)

    output = {
        "metadata": {
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "execution_time_seconds": execution_time_seconds,
            "execution_time_formatted": execution_time_formatted,
            "root_directory": str(root_dir)
        },
        "results": {path.name: metadata.to_dict() for path, metadata in extractor.results.items()}
    }

    sorted_output = sort_dict(output)
    root_dir_name = sanitize_filename(root_dir.name) or "output"
    output_file_name = f"{root_dir_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    script_dir = Path(sys.argv[0]).resolve().parent
    output_file = script_dir / output_file_name

    with output_file.open("w", encoding="utf-8") as f:
        json.dump(sorted_output, f, indent=2)

    logger.info("File structure has been written to: %s", output_file)
    logger.info("Script ended at: %s", end_time)
    logger.info("Total execution time: %s", execution_time_formatted)

# ----------------------------- Entry Point -----------------------------

if __name__ == "__main__":
    main()
