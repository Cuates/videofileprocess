"""
MKV Subtitle Extractor and Converter (SRT → ASS)

This script scans one or more folders for MKV files, extracts SubRip (SRT) subtitle tracks,
and converts them to Advanced SubStation Alpha (ASS) format using a custom style.

Features:
- ✅ Cross-platform: Windows, macOS, Linux
- ✅ Audit-friendly: filenames include track metadata
- ✅ UTF-8 safe: handles multilingual subtitles
- ✅ Modular and extensible: supports multiple folders
- ✅ Summary report: tracks conversions and failures
- ✅ Rotating log file and JSON output for audit traceability

Requirements:
- Python 3.7+
- Install dependencies:
    pip install pysubs2

- Install MKVToolNix and ensure `mkvmerge` and `mkvextract` are in your system PATH:
    https://mkvtoolnix.download/

Usage:
1. Set `MKV_FOLDERS` to one or more folders containing `.mkv` files.
2. Run the script:
    python mkv_subtitle_converter.py
3. Extracted `.srt` and converted `.ass` files will appear in the same folder as each MKV file.
4. Logs and JSON summaries will be saved in the script directory.

Filename format includes:
    - MKV base name
    - Track ID
    - Language code
    - Sanitized track name
    - Default/forced flags

Example:
    MyMovie_track2_eng_Signs_and_Songs_default0_forced1.ass
"""

from pathlib import Path
from typing import List, Dict, Set
from datetime import datetime
import subprocess
import json
import re
import shutil
import sys
from logging.handlers import RotatingFileHandler
from collections import defaultdict
import logging
import pysubs2
from pysubs2 import SSAStyle

SCRIPT_DIR = Path(__file__).resolve().parent if '__file__' in globals() else Path.cwd()

LOG_FILE = SCRIPT_DIR / "conversion.log"

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

SUCCESS_JSON = SCRIPT_DIR / f"converted_files_{TIMESTAMP}.json"
FAILURE_JSON = SCRIPT_DIR / f"failed_files_{TIMESTAMP}.json"

log_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=5_000_000,       # ~1MB per log file
    backupCount=5,            # Keep up to 3 old logs
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

# === CONFIG ===
STYLE_NAME: str = "CustomTrebuchet"
FONT_NAME: str = "Trebuchet MS"
FONT_SIZE: int = 20
OUTLINE: float = 1.0
SHADOW: float = 1.0

MKV_FOLDERS: List[Path] = [
    Path("D:/winshare/Project/Python_Projects/mkv_subtitle_extractor_converter/test"),
]

# === SUMMARY TRACKING ===
summary: Dict[str, int] = {
    "folders_processed": 0,
    "files_processed": 0,
    "files_converted": 0
}

folders_with_failures: Set[str] = set()
folders_with_converted_files: Set[str] = set()
conversion_log: Dict[str, List[str]] = defaultdict(list)
failure_log: Dict[str, List[str]] = defaultdict(list)

def log_success(message: str) -> None:
    """Logs a success message with ✅ prefix."""
    logging.info("✅ %s", message)

def log_error(message: str) -> None:
    """Logs an error message with ❌ prefix."""
    logging.error("❌ %s", message)

def log_warning(message: str) -> None:
    """Logs a warning message with 📛 prefix."""
    logging.warning("📛 %s", message)

def log_inspection(message: str) -> None:
    """Logs an inspection message with 🔍 prefix."""
    logging.info("🔍 %s", message)

def check_tool_installed(tool_name: str) -> bool:
    """
    Check if a tool is available in the system PATH.

    Args:
        tool_name: Name of the tool (e.g., 'mkvmerge')

    Returns:
        True if found, False otherwise
    """
    return shutil.which(tool_name) is not None

def verify_tools() -> None:
    """
    Verify that mkvmerge and mkvextract are installed and available in PATH.
    Logs and exits the script if any are missing.
    """
    missing = [tool for tool in ["mkvmerge", "mkvextract"] if not check_tool_installed(tool)]
    if missing:
        print(f"❌ Missing tools: {', '.join(missing)}")
        log_error(f"❌ Missing tools: {', '.join(missing)}")
        print("Please install MKVToolNix and ensure the tools are in your system PATH.")
        log_error("Please install MKVToolNix and ensure the tools are in your system PATH.")
        sys.exit(1)

def sanitize_filename(name: str) -> str:
    """
    Sanitize a string for safe use in filenames.

    Args:
        name: Original track name

    Returns:
        A sanitized string safe for use in filenames.
    """
    return re.sub(r'[^\w\-_. ]', '_', name)

def get_srt_tracks(mkv_path: Path) -> List[Dict[str, object]]:
    """
    Parse MKV metadata and return a list of SRT subtitle tracks.

    Args:
        mkv_path: Path to the MKV file

    Returns:
        A list of dictionaries containing track metadata.
    """
    metadata = subprocess.check_output(["mkvmerge", "-J", str(mkv_path)], text=True, encoding="utf-8")
    info = json.loads(metadata)
    tracks = []
    base = mkv_path.stem
    for track in info.get("tracks", []):
        if track["type"] == "subtitles" and "SubRip" in track["codec"]:
            tid = track["id"]
            lang = track["properties"].get("language", "und")
            name = track["properties"].get("track_name", "unnamed")
            default = track["properties"].get("default_track", False)
            forced = track["properties"].get("forced_track", False)
            safe_name = sanitize_filename(name)
            filename = (
                f"{base}_track{tid}_{safe_name}"
                f"_default{int(default)}_forced{int(forced)}.{lang}.srt"
            )
            tracks.append({
                "id": tid,
                "filename": filename,
                "language": lang,
                "name": name,
                "default": default,
                "forced": forced
            })
    return tracks

def extract_srt_tracks(mkv_path: Path, output_dir: Path) -> List[Path]:
    """
    Extract SRT subtitle tracks from an MKV file using mkvextract.

    Args:
        mkv_path: Path to the MKV file
        output_dir: Directory to save extracted SRT files

    Returns:
        A list of paths to the extracted SRT files.
    """
    extracted_files: List[Path] = []
    for track in get_srt_tracks(mkv_path):
        output_path = output_dir / track["filename"]
        cmd = ["mkvextract", "tracks", str(mkv_path), f"{track['id']}:{str(output_path)}"]
        try:
            log_inspection(f"Command: {' '.join(cmd)}")
            subprocess.run(cmd, check=True)
            extracted_files.append(output_path)
            print(f"📥 Extracted: {output_path}")
            log_inspection(f"Extracted: {output_path}")
            print(f"     ↳ Language: {track['language']}, Name: {track['name']}, Default: {track['default']}, Forced: {track['forced']}")
            log_inspection(f"     ↳ Language: {track['language']}, Name: {track['name']}, Default: {track['default']}, Forced: {track['forced']}")
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to extract track {track['id']}: {e}")
            log_error(f"Failed to extract track {track['id']}: {e}")
    return extracted_files

def convert_srt_to_ass(input_path: Path, output_path: Path) -> None:
    """
    Convert an SRT file to ASS format using pysubs2 and apply custom styling.

    Args:
        input_path: Path to the input SRT file
        output_path: Path to the output ASS file
    """
    try:
        subs = pysubs2.load(str(input_path), encoding="utf-8")

        style = SSAStyle(
            fontname=FONT_NAME,
            fontsize=FONT_SIZE,
            outline=OUTLINE,
            shadow=SHADOW,
        )
        style.name = STYLE_NAME

        subs.styles[STYLE_NAME] = style
        for line in subs:
            line.style = STYLE_NAME

        subs.save(str(output_path), encoding="utf-8")
        print(f"🎯 Converted: {input_path} → {output_path}")
        log_success(f"Converted: {input_path} → {output_path}")

    except (UnicodeDecodeError, IOError, ValueError) as e:
        print(f"❌ Error converting {input_path}: {e}")
        log_error(f"Error converting {input_path}: {e}")

def process_mkv_file(mkv_path: Path, folder_process: Path) -> None:
    """
    Process a single MKV file: extract SRT tracks and convert them to ASS.
    Updates summary counters and logs results.

    Args:
        mkv_path: Path to the MKV file
        folder_process: Folder currently being processed
    """
    output_dir = mkv_path.parent
    srt_files = extract_srt_tracks(mkv_path, output_dir)
    summary["files_processed"] += 1

    for srt_file in srt_files:
        ass_file = srt_file.with_suffix(".ass")
        try:
            convert_srt_to_ass(srt_file, ass_file)
            summary["files_converted"] += 1
            folders_with_converted_files.add(str(folder_process))
            conversion_log[str(folder_process)].append(str(ass_file.name))
        except (UnicodeDecodeError, IOError, ValueError) as e:
            folders_with_failures.add(str(folder_process))
            failure_log[str(folder_process)].append(str(srt_file.name))
            print(f"❌ Conversion failed for {srt_file}: {e}")
            log_error(f"Conversion failed for {srt_file}: {e}")

def main() -> None:
    """
    Main execution loop.
    Processes all folders in MKV_FOLDERS, logs progress, and writes summary JSON files.
    """
    log_inspection("Starting conversion script")
    verify_tools()
    for folder in MKV_FOLDERS:
        if not folder.exists():
            print(f"❌ MKV folder not found: {folder}")
            log_error(f"MKV folder not found: {folder}")
            continue

        summary["folders_processed"] += 1
        for mkv_file in folder.glob("*.mkv"):
            print(f"\n🔍 Processing: {mkv_file}")
            log_inspection(f"Processing: {mkv_file}")
            process_mkv_file(mkv_file, folder)

    print("\n📋 Summary Report")
    log_inspection("Summary Report")
    print(f"✅ Folders processed: {summary['folders_processed']}")
    log_inspection(f"Folders processed: {summary['folders_processed']}")
    print(f"📦 MKV files processed: {summary['files_processed']}")
    log_inspection(f"MKV files processed: {summary['files_processed']}")
    print(f"🎯 Files converted to ASS: {summary['files_converted']}")
    log_inspection(f"Files converted to ASS: {summary['files_converted']}")

    if folders_with_converted_files:
        # print("\n📁 Folders with converted files:")
        log_success("Folders with converted files:")
        for folder in sorted(folders_with_converted_files):
            # print(f"  - {folder}")
            log_success(f"  - {folder}")
            for fname in conversion_log[folder]:
                # print(f"     ↳ {fname}")
                log_success(f"     ↳ {fname}")

    if folders_with_failures:
        # print("\n⚠️ Folders with conversion failures:")
        log_error("Folders with conversion failures:")
        for folder in sorted(folders_with_failures):
            # print(f"  - {folder}")
            log_error(f"  - {folder}")
            for fname in failure_log[folder]:
                # print(f"     ↳ {fname}")
                log_error(f"     ↳ {fname}")

    # Save converted files
    with SUCCESS_JSON.open("w", encoding="utf-8") as f:
        json.dump(dict(conversion_log), f, indent=2, ensure_ascii=False)

    if folders_with_converted_files:
        log_inspection(f"Converted files saved to {SUCCESS_JSON}")

    # Save failed files
    with FAILURE_JSON.open("w", encoding="utf-8") as f:
        json.dump(dict(failure_log), f, indent=2, ensure_ascii=False)

    if folders_with_failures:
        log_inspection(f"Failed files saved to {FAILURE_JSON}")

    log_inspection("Conversion script completed")

if __name__ == "__main__":
    main()
