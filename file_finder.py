"""XML File Finder and JSON Output Generator.

This script searches for XML (or other specified) files in a given directory
structure and outputs the results to a JSON file. It supports:
    - Custom file types
    - Exclusion patterns
    - Progress indicator for large directory structures

Required packages:
    - tqdm: For progress bar display

To install required packages:
    pip install tqdm

Usage:
    python file_finder.py [--root ROOT_DIR] [--output OUTPUT_FILE]
                          [--types FILE_TYPES...] [--exclude PATTERNS...]

Example:
    python file_finder.py --root /path/to/search --types .xml .xsd
                          --exclude "*temp*" "*backup*"

This command does the following:
    - Searches for files in /path/to/search and its subdirectories
    - Looks for files with .xml and .xsd extensions
    - Excludes any files or directories matching the patterns *temp* or *backup*

For more information, use the --help option:
    python file_finder.py --help
"""

import argparse
import fnmatch
import json
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional

from tqdm import tqdm

def setup_logging() -> None:
    """Set up basic logging configuration."""
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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

def find_xml_files(root_dir: Path, file_types: List[str], exclude_patterns: List[str]) -> Dict[str, Any]:
    """
    Recursively search for files of specified types in the given directory.

    Args:
        root_dir (Path): The directory to start the search from.
        file_types (List[str]): List of file extensions to search for.
        exclude_patterns (List[str]): List of patterns to exclude from the search.

    Returns:
        Dict[str, Any]: A nested dictionary representing the directory structure and matching files.
    """
    result: Dict[str, Any] = {}
    for path in root_dir.rglob('*'):
        if path.is_dir():
            if any(fnmatch.fnmatch(path.name, pattern) for pattern in exclude_patterns):
                continue
        elif path.is_file():
            if any(path.suffix.lower() == ext.lower() for ext in file_types) and \
               not any(fnmatch.fnmatch(path.name, pattern) for pattern in exclude_patterns):
                relative_path = path.relative_to(root_dir)
                current_level = result
                for part in relative_path.parts[:-1]:
                    if part not in current_level:
                        current_level[part] = {}
                    current_level = current_level[part]
                if 'matching_files' not in current_level:
                    current_level['matching_files'] = []
                current_level['matching_files'].append(path.name)
    return result

def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Find XML files and output structure to JSON.")
    parser.add_argument("--root", default=Path.cwd(), type=Path, help="Root directory to search (default: current directory)")
    parser.add_argument("--output", type=Path, help="Output JSON file name (default: auto-generated with timestamp)")
    parser.add_argument("--types", nargs="+", default=[".xml"], help="File types to search for (default: .xml)")
    parser.add_argument("--exclude", nargs="+", default=[], help="Patterns to exclude")
    return parser.parse_args()

def search_files(root_dir: Path, file_types: List[str], exclude_patterns: List[str]) -> Tuple[Dict[str, Any], int]:
    """Search for files based on given criteria."""
    results: Dict[str, Any] = {}
    directory_count = 0
    total_dirs = sum(1 for _ in root_dir.rglob('*') if _.is_dir())
    with tqdm(total=total_dirs, desc="Processing directories", unit="dir") as pbar:
        for path in root_dir.rglob('*'):
            if path.is_dir():
                directory_count += 1
                dir_results = find_xml_files(path, file_types, exclude_patterns)
                if dir_results:
                    relative_path = path.relative_to(root_dir)
                    current_level = results
                    for part in relative_path.parts:
                        if part not in current_level:
                            current_level[part] = {}
                        current_level = current_level[part]
                    current_level.update(dir_results)
                pbar.update(1)
    return results, directory_count

def create_metadata(start_time: float, start_datetime: datetime, end_datetime: datetime, root_dir: Path, args: argparse.Namespace, directory_count: int) -> Dict[str, Any]:
    """Create metadata for the output."""
    execution_time = time.time() - start_time
    execution_timedelta = timedelta(seconds=execution_time)
    return {
        "start_time": start_datetime.isoformat(),
        "end_time": end_datetime.isoformat(),
        "execution_time_seconds": execution_time,
        "execution_time_formatted": format_time_delta(execution_timedelta),
        "root_directory": str(root_dir),
        "file_types_searched": args.types,
        "exclusion_patterns": args.exclude,
        "total_directories_processed": directory_count
    }

def write_output(output: Dict[str, Any], root_dir: Path, output_file: Optional[Path]) -> None:
    """Write the output to a JSON file in the same directory as the script."""
    script_dir = Path(__file__).parent.resolve()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    root_name = root_dir.name
    json_filename = output_file or script_dir / f"{root_name}_{timestamp}.json"
    with json_filename.open('w', encoding='utf-8') as json_file:
        json.dump(output, json_file, indent=2, ensure_ascii=False)
    # logging.info("File structure has been written to %s", json_filename)
    print(f"File structure has been written to {json_filename}")

def main() -> None:
    """
    Main function to execute the file search and JSON output generation.
    """
    args = parse_arguments()
    setup_logging()

    start_time = time.time()
    start_datetime = datetime.now()
    print(f"Script started at: {start_datetime.strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        root_dir = args.root.resolve()

        # Check if the root directory exists
        if not root_dir.exists():
            raise FileNotFoundError(f"The specified root directory does not exist: {root_dir}")

        if not root_dir.is_dir():
            raise NotADirectoryError(f"The specified path is not a directory: {root_dir}")

        # logging.info("Searching for files in: %s", root_dir)
        print(f"Searching for files in: {root_dir}")

        results, directory_count = search_files(root_dir, args.types, args.exclude)

        metadata = create_metadata(start_time, start_datetime, datetime.now(), root_dir, args, directory_count)
        output = {"metadata": metadata, "results": results}

        write_output(output, root_dir, args.output)

    except FileNotFoundError as e:
        logging.error("File or directory not found: %s", str(e))
    except NotADirectoryError as e:
        logging.error("Not a directory: %s", str(e))
    except PermissionError as e:
        logging.error("Permission denied: %s", str(e))
    except TypeError as e:
        logging.error("Error encoding JSON: %s", str(e))
    except IOError as e:
        logging.error("I/O error occurred: %s", str(e))
    except KeyboardInterrupt:
        logging.info("Script execution interrupted by user.")
    except Exception as e:
        logging.error("An unexpected error occurred: %s", str(e))
        logging.error("Error type: %s", type(e).__name__)
        raise  # Re-raise the exception for debugging purposes
    finally:
        end_datetime = datetime.now()
        print(f"Script ended at: {end_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Total execution time: {format_time_delta(end_datetime - start_datetime)}")
        if 'results' not in locals():
            sys.exit(1)

    sys.exit(0)

if __name__ == "__main__":
    main()
