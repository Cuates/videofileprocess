"""
Chapter Injection Pipeline Using mkvmerge with XML Validation and Structured Audit Logging

This script recursively scans a root directory for MKV files and their corresponding chapter XML files.
It validates chapter structure, injects chapters using mkvmerge, and logs all actions to a structured JSON audit file.

Features:
- Validates chapter XMLs for timestamp integrity and overlap
- Injects chapters into MKV files via mkvmerge with full remux
- Logs each operation with UTC and local timestamps, duration in seconds and human-readable format
- Writes each audit entry immediately to disk under a root-level "execution" block
- Finalizes execution metadata with end time, total duration, and summary counts
- Displays real-time progress and prints a summary report

Requirements:
- Python 3.8+
- Install progress bar dependency: `pip install alive-progress`
- Install MKVToolNix (https://mkvtoolnix.download/) and ensure `mkvmerge` is available in your system PATH
    or set the environment variable `MKVMERGE_BIN` to its full path

Designed for forensic-grade traceability, operational safety, and human-readable auditability.
"""

import os
import subprocess
import json
import sys
import time
from pathlib import Path
from typing import Generator, Tuple, List, Dict, Any
from datetime import datetime, timezone, timedelta
from xml.etree import ElementTree as ET
from xml.etree.ElementTree import ParseError
from alive_progress import alive_it

# 🔧 Paths and binaries
SCRIPT_DIR: Path = Path(__file__).resolve().parent
ROOT_DIR: Path = Path("/path/to/root")  # ← Replace with your actual media root
MKVMERGE_BIN: str = os.getenv("MKVMERGE_BIN", "mkvmerge")

# 📝 Audit log path
TIMESTAMP: str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
AUDIT_LOG: Path = SCRIPT_DIR / f"mux_audit_log_{TIMESTAMP}.json"

def format_time_delta(td: timedelta) -> str:
    """Formats a timedelta object into a human-readable string."""
    years, remainder = divmod(td.days, 365)
    months, days = divmod(remainder, 30)
    hours, remainder = divmod(td.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    milliseconds = td.microseconds // 1000

    parts: List[str] = []
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
    if seconds > 0 or not parts:
        parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
    if milliseconds > 0:
        parts.append(f"{milliseconds} millisecond{'s' if milliseconds != 1 else ''}")
    return ", ".join(parts)

def initialize_log(start: datetime) -> None:
    """Initializes the audit log with execution metadata."""
    execution_block: Dict[str, Any] = {
        "start_time_utc": start.isoformat(),
        "start_time_local": start.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
        "root_directory": str(ROOT_DIR),
        "results": []
    }
    AUDIT_LOG.write_text(json.dumps({"execution": execution_block}, indent=2), encoding="utf-8")

def append_audit(entry: Dict[str, Any], duration: float) -> None:
    """Appends a structured entry to the audit log file immediately."""
    utc_now: str = datetime.now(timezone.utc).isoformat()
    local_stamp: str = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    entry["timestamp_utc"] = utc_now
    entry["timestamp_local"] = local_stamp
    entry["duration_seconds"] = round(duration, 2)
    entry["duration_human"] = format_time_delta(timedelta(seconds=duration))

    try:
        existing: Dict[str, Any] = json.loads(AUDIT_LOG.read_text(encoding="utf-8"))
        existing["execution"]["results"].append(entry)
        AUDIT_LOG.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        print(f"🚫 Failed to append audit entry: {exc}")

def finalize_log(end: datetime) -> None:
    """Finalizes the audit log with end time, duration, and summary counts."""
    try:
        existing: Dict[str, Any] = json.loads(AUDIT_LOG.read_text(encoding="utf-8"))
        start = datetime.fromisoformat(existing["execution"]["start_time_utc"])
        results: List[Dict[str, Any]] = existing["execution"]["results"]

        summary: Dict[str, int] = {
            "successfully_muxed": sum(1 for e in results if e.get("status") == "muxed"),
            "failed": sum(1 for e in results if e.get("status") == "mkvmerge_failed"),
            "skipped": sum(1 for e in results if e.get("status") == "skipped"),
            "invalid_chapter": sum(1 for e in results if e.get("status") == "invalid_chapter_xml")
        }

        execution_block: Dict[str, Any] = {
            "start_time_utc": existing["execution"]["start_time_utc"],
            "start_time_local": existing["execution"]["start_time_local"],
            "end_time_utc": end.isoformat(),
            "end_time_local": end.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
            "execution_time_seconds": round((end - start).total_seconds(), 3),
            "execution_time_human": format_time_delta(end - start),
            "summary": summary,
            "root_directory": existing["execution"]["root_directory"],
            "results": results
        }

        AUDIT_LOG.write_text(json.dumps({"execution": execution_block}, indent=2), encoding="utf-8")
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError) as exc:
        print(f"🚫 Failed to finalize execution block: {exc}")

def find_mkv_and_chapters(folder: Path) -> Generator[Tuple[Path, Path], None, None]:
    """Recursively finds MKV files and their matching chapter XML files."""
    for dirpath, _, filenames in os.walk(folder):
        mkv_files: List[str] = [f for f in filenames if f.lower().endswith(".mkv")]
        for mkv in mkv_files:
            mkv_path: Path = Path(dirpath) / mkv
            chapter_path: Path = mkv_path.with_name(f"{mkv_path.stem}_chapters.xml")
            if chapter_path.exists():
                yield mkv_path, chapter_path
            else:
                start: float = time.time()
                append_audit({
                    "file": str(mkv_path),
                    "status": "skipped",
                    "reason": "missing chapter file"
                }, time.time() - start)

def validate_chapter_structure(chapter_path: Path) -> bool:
    """Validates chapter XML structure and detects malformed entries."""
    start: float = time.time()
    try:
        tree: ET.ElementTree = ET.parse(chapter_path)
        root: ET.Element = tree.getroot()
        chapters: List[Tuple[int, int]] = []

        for atom in root.findall(".//ChapterAtom"):
            start_ts: str = atom.findtext("ChapterTimeStart") or ""
            end_ts: str = atom.findtext("ChapterTimeEnd") or ""
            title: str = atom.findtext(".//ChapterDisplay/ChapterString") or ""

            if not start_ts or not end_ts or not title:
                append_audit({
                    "file": str(chapter_path),
                    "status": "invalid_chapter_xml",
                    "reason": "missing start/end/title"
                }, time.time() - start)
                return False

            def to_millis(ts: str) -> int:
                try:
                    h, m, s = ts.split(":")
                    s, ns = s.split(".")
                    return int(h)*3600000 + int(m)*60000 + int(s)*1000 + int(ns[:3])
                except (ValueError, AttributeError, IndexError) as exc:
                    append_audit({
                        "file": str(chapter_path),
                        "status": "invalid_chapter_xml",
                        "reason": f"bad timestamp format: {ts}",
                        "error": str(exc)
                    }, time.time() - start)
                    return -1

            start_ms: int = to_millis(start_ts)
            end_ms: int = to_millis(end_ts)
            if start_ms == -1 or end_ms == -1 or start_ms >= end_ms:
                append_audit({
                    "file": str(chapter_path),
                    "status": "invalid_chapter_xml",
                    "reason": f"invalid timing: {start_ts} → {end_ts}"
                }, time.time() - start)
                return False

            chapters.append((start_ms, end_ms))

        for i in range(1, len(chapters)):
            if chapters[i][0] < chapters[i - 1][1]:
                append_audit({
                    "file": str(chapter_path),
                    "status": "invalid_chapter_xml",
                    "reason": "overlapping chapters"
                }, time.time() - start)
                return False

        return True

    except (FileNotFoundError, ParseError, OSError) as exc:
        append_audit({
            "file": str(chapter_path),
            "status": "invalid_chapter_xml",
            "error": str(exc)
        }, time.time() - start)
        return False

def mux_chapters_with_mkvmerge(mkv_path: Path, chapter_path: Path) -> None:
    """Injects chapters into MKV using mkvmerge and logs duration."""
    if not validate_chapter_structure(chapter_path):
        return

    temp_output: Path = mkv_path.with_name(f"{mkv_path.stem}_with_chapters.mkv")
    cmd: List[str] = [MKVMERGE_BIN, "-o", str(temp_output), "--chapters", str(chapter_path), str(mkv_path)]

    start: float = time.time()
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        mkv_path.unlink()
        chapter_path.unlink()
        temp_output.rename(mkv_path)

        append_audit({
            "file": str(mkv_path),
            "status": "muxed",
            "tool": "mkvmerge"
        }, time.time() - start)

    except subprocess.CalledProcessError as exc:
        if temp_output.exists():
            temp_output.unlink()

        error_msg = exc.stderr.strip() or exc.stdout.strip() or "No error message returned by mkvmerge"

        append_audit({
            "file": str(mkv_path),
            "status": "mkvmerge_failed",
            "error": error_msg
        }, time.time() - start)

def print_summary() -> None:
    """Prints a summary report of muxing results for the current run."""
    try:
        log_text: str = AUDIT_LOG.read_text(encoding="utf-8")
        current_run: Dict[str, Any] = json.loads(log_text)
        results: List[Dict[str, Any]] = current_run.get("execution", {}).get("results", [])
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        print(f"🚫 Failed to read audit log: {exc}")
        return

    muxed = [e for e in results if e.get("status") == "muxed"]
    failed = [e for e in results if e.get("status") == "mkvmerge_failed"]
    skipped = [e for e in results if e.get("status") == "skipped"]
    invalid = [e for e in results if e.get("status") == "invalid_chapter_xml"]

    print("\n📊 Summary Report")
    print(f"{'✅ Successfully muxed:':<25} {len(muxed)} file(s)")
    print(f"{'❌ Failed:':<25} {len(failed)} file(s)")
    print(f"{'⚠️  Skipped:':<27} {len(skipped)} file(s)")
    print(f"{'🧪 Invalid Chapter:':<25} {len(invalid)} file(s)")

    if muxed:
        print("\n✅ Files Successfully Muxed:")
        for e in muxed:
            print(f" - {e['file']} (Duration => {e['duration_human']})")

    if failed:
        print("\n🔍 Files that Failed:")
        for e in failed:
            reason = e.get("error", "unknown error")
            print(f" - {e['file']} (Reason => {reason}, Duration => {e['duration_human']})")

    if invalid:
        print("\n🧪 Invalid Chapter Files:")
        for e in invalid:
            reason = e.get("reason", e.get("error", "unknown issue"))
            print(f" - {e['file']} (Reason => {reason}, Duration => {e['duration_human']})")

    # if skipped:
    #     print("\n⚠️ Skipped Files:")
    #     for e in skipped:
    #         print(f" - {e['file']} (Reason => {e['reason']}, Duration => {e['duration_human']})")

def main() -> None:
    """Main entry point. Tracks execution time and prints summary."""
    start_time: datetime = datetime.now(timezone.utc)
    initialize_log(start_time)

    pairs: List[Tuple[Path, Path]] = list(find_mkv_and_chapters(ROOT_DIR))
    for mkv_path, chapter_path in alive_it(pairs, title="Processing media files"):
        sys.stdout.write(f"\r🎬 Processing: {mkv_path.name}\n")
        sys.stdout.flush()
        mux_chapters_with_mkvmerge(mkv_path, chapter_path)

    end_time: datetime = datetime.now(timezone.utc)
    finalize_log(end_time)
    print_summary()

if __name__ == "__main__":
    main()
