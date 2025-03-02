"""
MKV Metadata Extractor

This script extracts specific metadata from MKV files in a given directory and its subdirectories
using MKVMerge. It outputs the results to a JSON file in the same directory as the script
and provides console logging. The output JSON is sorted alphanumerically in a case-insensitive manner.

Required packages:
- pathlib
- tqdm
- logging
- argparse
- json
- datetime
- subprocess

Usage:
    python mkv_metadata_extractor_full.py <root_directory>

Arguments:
    root_directory : str
        The path to the directory containing MKV files to process.

Options:
    -h, --help
        Show this help message and exit.

Examples:
    # Extract metadata from MKV files in the '/home/user/videos' directory:
    python mkv_metadata_extractor_full.py /home/user/videos

    # Show help message:
    python mkv_metadata_extractor_full.py --help

Output:
    The script will create a JSON file in the same directory as the script,
    named '<root_directory_name>_YYYYMMDD_HHMMSS.json', containing the extracted metadata.
    Spaces in the root directory name are replaced with underscores.

Note:
    Ensure you have MKVToolNix installed and set the MKVMERGE_PATH variable
    to the correct location of the mkvmerge executable on your system.
"""

import argparse
import json
import logging
import sys
import subprocess
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Union, TypedDict, Any

from tqdm import tqdm

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Set the path to mkvmerge executable here
MKVMERGE_PATH = Path("/path/to/mkvmerge")  # Modify this path as needed

class TrackInfo(TypedDict):
    """
    TypedDict for storing track information.

    Attributes:
        Codec (str): The codec of the track.
        Type (str): The type of the track (video, audio, subtitles).
        Language (str): The language of the track.
        Name (str): The name of the track.
        Default_track (bool): Whether this is the default track.
        Forced_display (bool): Whether this track is forced to display.
        Character_set (str): The character set of the track.
        Properties (Dict[str, Union[str, bool, int, float]]): Additional properties of the track.
    """
    Codec: str
    Type: str
    Language: str
    Name: str
    Default_track: bool
    Forced_display: bool
    Character_set: str
    Properties: Dict[str, Union[str, bool, int, float]]

class ChapterInfo(TypedDict):
    """
    TypedDict for storing chapter information.

    Attributes:
        Name (str): The name of the chapter.
        Start_time (str): The start time of the chapter.
        End_time (str): The end time of the chapter.
        Language (str): The language of the chapter.
    """
    Name: str
    Start_time: str
    End_time: str
    Language: str

class FileMetadata(TypedDict):
    """
    TypedDict for storing file metadata.

    Attributes:
        videos (List[TrackInfo]): List of video track information.
        audios (List[TrackInfo]): List of audio track information.
        subtitles (List[TrackInfo]): List of subtitle track information.
        chapters (List[ChapterInfo]): List of chapter information.
        error (str): Error message if metadata extraction failed.
    """
    videos: List[TrackInfo]
    audios: List[TrackInfo]
    subtitles: List[TrackInfo]
    chapters: List[ChapterInfo]
    error: str

class MKVMetadataExtractor:
    """Class for extracting metadata from MKV files using MKVMerge."""

    def __init__(self, root_dir: Path):
        """
        Initialize the MKVMetadataExtractor.

        Args:
            root_dir (Path): The root directory to search for MKV files.
        """
        self.root_dir = root_dir
        self.results: Dict[str, Union[Dict, FileMetadata]] = {}

    def extract_metadata(self) -> None:
        """
        Extract metadata from all MKV files in the root directory and subdirectories.

        This method processes all MKV files found in the root directory and its subdirectories,
        extracting metadata for each file and storing it in the results dictionary.
        """
        for file_path in tqdm(sorted(self.root_dir.rglob("*.mkv")), desc="Processing MKV files"):
            try:
                file_metadata = self._extract_file_metadata(file_path)
                self._add_to_results(file_path, file_metadata)
            except subprocess.CalledProcessError as e:
                error_msg = f"mkvmerge command failed: {str(e)}"
                logger.error("%s: %s", file_path, error_msg)
                self._add_to_results(file_path, {"error": error_msg})
            except json.JSONDecodeError as e:
                error_msg = f"Error decoding JSON: {str(e)}"
                logger.error("%s: %s", file_path, error_msg)
                self._add_to_results(file_path, {"error": error_msg})
            except ValueError as e:
                error_msg = str(e)
                logger.error("%s: %s", file_path, error_msg)
                self._add_to_results(file_path, {"error": error_msg})
            except PermissionError as e:
                error_msg = f"Permission error: {str(e)}"
                logger.error("%s: %s", file_path, error_msg)
                self._add_to_results(file_path, {"error": error_msg})
            except OSError as e:
                error_msg = f"OS error: {str(e)}"
                logger.error("%s: %s", file_path, error_msg)
                self._add_to_results(file_path, {"error": error_msg})
            except Exception as e:
                error_msg = f"Unexpected error: {str(e)}"
                logger.critical("%s: %s", file_path, error_msg)
                self._add_to_results(file_path, {"error": error_msg})
                # Re-raise the exception to allow for proper handling at a higher level
                raise

    def _extract_file_metadata(self, file_path: Path) -> FileMetadata:
        """
        Extract metadata from a single MKV file using MKVMerge.

        Args:
            file_path (Path): The path to the MKV file.

        Returns:
            FileMetadata: The extracted metadata for the file.
        """
        cmd = [str(MKVMERGE_PATH), '-J', str(file_path)]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', check=True)
            if not result.stdout:
                raise ValueError(f"mkvmerge produced no output for file: {file_path}")
            metadata = json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            error_msg = f"mkvmerge command failed: {e}\nStderr: {e.stderr}"
            logger.error("%s: %s", file_path, error_msg)
            return {"error": error_msg}
        except json.JSONDecodeError as e:
            error_msg = f"Failed to parse mkvmerge output as JSON: {e}"
            logger.error("%s: %s", file_path, error_msg)
            return {"error": error_msg}
        except ValueError as e:
            error_msg = str(e)
            logger.error("%s: %s", file_path, error_msg)
            return {"error": error_msg}

        processed_metadata: FileMetadata = {
            "videos": [],
            "audios": [],
            "subtitles": [],
            "chapters": []
        }

        for track in metadata.get('tracks', []):
            track_info = self._extract_track_info(track)
            if track['type'] == 'video':
                processed_metadata["videos"].append(track_info)
            elif track['type'] == 'audio':
                processed_metadata["audios"].append(track_info)
            elif track['type'] == 'subtitles':
                processed_metadata["subtitles"].append(track_info)

        if 'chapters' in metadata:
            processed_metadata["chapters"] = [self._extract_chapter_info(chapter) for chapter in metadata['chapters']]

        return processed_metadata

    def _extract_track_info(self, track: Dict[str, Union[str, Dict[str, Union[str, bool, int, float]]]]) -> TrackInfo:
        """
        Extract information from a track.

        Args:
            track (Dict[str, Any]): The track data from MKVMerge output.

        Returns:
            TrackInfo: The extracted track information.
        """
        properties = track.get('properties', {})
        return TrackInfo(
            Codec=track.get('codec', ''),
            Type=track.get('type', ''),
            Language=properties.get('language', ''),
            Name=properties.get('track_name', ''),
            Default_track=properties.get('default_track', False),
            Forced_display=properties.get('forced_track', False),
            Character_set=properties.get('encoding', ''),
            Properties=properties
        )

    def _extract_chapter_info(self, chapter: Dict[str, Union[str, int]]) -> ChapterInfo:
        """
        Extract information from chapters.

        Args:
            chapters (List[Dict[str, Any]]): The chapters data from MKVMerge output.

        Returns:
            List[ChapterInfo]: The extracted chapter information.
        """
        return ChapterInfo(
            Name=chapter.get('name', ''),
            Start_time=str(chapter.get('timestamp', '')),
            End_time=str(chapter.get('end_timestamp', '')),
            Language=chapter.get('language', '')
        )

    @staticmethod
    def format_time_delta(td: timedelta) -> str:
        """
        Format a timedelta object into a human-readable string.

        Args:
            td (timedelta): The timedelta object to format.

        Returns:
            str: A human-readable string representation of the time delta.
        """
        years, remainder = divmod(td.days, 365)
        months, days = divmod(remainder, 30)
        hours, remainder = divmod(td.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        milliseconds = td.microseconds // 1000

        parts = []
        if years > 0:
            parts.append(f"{years} year{'s' if years > 1 else ''}")
        if months > 0:
            parts.append(f"{months} month{'s' if months > 1 else ''}")
        if days > 0:
            parts.append(f"{days} day{'s' if days > 1 else ''}")
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")

        no_larger_units = all(x == 0 for x in (years, months, days, hours, minutes))
        if seconds > 0 or no_larger_units:
            parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
        if milliseconds > 0:
            parts.append(f"{milliseconds} millisecond{'s' if milliseconds != 1 else ''}")

        return ", ".join(parts)

    def _add_to_results(self, file_path: Path, metadata: FileMetadata) -> None:
        """
        Add extracted metadata to the results dictionary.

        Args:
            file_path (Path): The path of the processed file.
            metadata (FileMetadata): The extracted metadata for the file.
        """
        current_dict = self.results
        for part in file_path.relative_to(self.root_dir).parts[:-1]:
            current_dict = current_dict.setdefault(part, {})
        current_dict[file_path.name] = metadata

def sort_dict(item: Any) -> Any:
    """
    Recursively sort dictionary keys in a case-insensitive manner.

    Args:
        item (Any): The item to sort (can be a dict, list, or any other type).

    Returns:
        Any: The sorted item.
    """
    if isinstance(item, dict):
        return {k: sort_dict(v) for k, v in sorted(item.items(), key=lambda x: x[0].lower())}
    if isinstance(item, list):
        return [sort_dict(i) for i in item]
    return item

def parse_arguments() -> argparse.Namespace:
    """
    Parse command-line arguments.

    Returns:
        argparse.Namespace: The parsed arguments.
    """
    parser = argparse.ArgumentParser(description="Extract metadata from MKV files.")
    parser.add_argument("root_dir", type=str, help="Root directory to search for MKV files")
    return parser.parse_args()

def sanitize_filename(name: str) -> str:
    """
    Sanitize the filename by replacing spaces with underscores and removing invalid characters.

    Args:
        name (str): The original filename.

    Returns:
        str: The sanitized filename.
    """
    # Replace spaces with underscores
    name = name.replace(' ', '_')
    # Remove any characters that aren't alphanumeric, underscore, or hyphen
    name = re.sub(r'[^\w\-]', '', name)
    return name

def main() -> None:
    """
    Main function to run the script.

    This function orchestrates the entire process of extracting metadata from MKV files,
    including argument parsing, metadata extraction, and output generation.
    """
    if not MKVMERGE_PATH.is_file():
        logger.error("mkvmerge executable not found at the specified path: %s", MKVMERGE_PATH)
        logger.error("Please ensure MKVToolNix is installed and the MKVMERGE_PATH is set correctly.")
        sys.exit(1)

    args = parse_arguments()
    root_dir = Path(args.root_dir)

    start_time = datetime.now()
    logger.info("Script started at: %s", start_time)
    logger.info("Searching for files in: %s", root_dir)
    logger.info("Using mkvmerge from: %s", MKVMERGE_PATH)

    extractor = MKVMetadataExtractor(root_dir)
    extractor.extract_metadata()

    end_time = datetime.now()
    execution_time: timedelta = end_time - start_time
    execution_time_seconds: float = execution_time.total_seconds()
    execution_time_formatted: str = MKVMetadataExtractor.format_time_delta(execution_time)

    output: Dict[str, Union[Dict[str, Union[str, float]], Dict[str, Union[Dict, FileMetadata]]]] = {
        "metadata": {
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "execution_time_seconds": execution_time_seconds,
            "execution_time_formatted": execution_time_formatted,
            "root_directory": str(root_dir),
            "mkvmerge_path": str(MKVMERGE_PATH)
        },
        "results": extractor.results
    }

    # Sort the output dictionary
    sorted_output = sort_dict(output)

    # Get base name of root directory, sanitize it, and construct output file name with date and time
    root_dir_name = sanitize_filename(root_dir.name) or "output"
    output_file_name = f"{root_dir_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    # Get the directory of the script and save output there
    script_dir = Path(sys.argv[0]).resolve().parent
    output_file = script_dir / output_file_name

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(sorted_output, f, indent=2)

    logger.info("File structure has been written to: %s", output_file)
    logger.info("Script ended at: %s", end_time)
    logger.info("Total execution time: %s", execution_time_formatted)

if __name__ == "__main__":
    main()
