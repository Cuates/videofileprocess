"""
Subdirectory Lister

This script lists unique subdirectories of directories that start with specified letters.
It can search from a given path or the current directory by default.
Only the unique paths of subdirectories are written to the output file.

The script includes error handling to manage issues such as permission errors,
file I/O errors, and unexpected exceptions. It also provides timing information,
displaying the start time, end time, and total execution time of the script.

Features:
- Searches for directories starting with specified letters
- Writes unique subdirectory paths to an output file
- Handles permission errors and other OS-related errors
- Provides detailed execution timing information
- Uses efficient directory traversal with pathlib
- Implements human-readable time formatting for execution duration
- Ensures no duplicate subdirectory paths in the output
- Sorts the output for improved readability

Usage examples:
1. Basic usage (search for 'P' and 'S' in current directory, output to default file):
    python list_subdirectories.py P S

2. Specify a search path and output file:
    python list_subdirectories.py A B C -p /path/to/search -o my_results.txt

3. Search for 'X' and 'Y' in current directory with a custom output file:
    python list_subdirectories.py X Y -o xy_subdirectories.txt

Note: The script will attempt to continue execution even if errors are encountered
with individual directories, reporting these errors to the console.
"""

from pathlib import Path
import argparse
import sys
import logging
import time
from datetime import datetime, timedelta
from typing import List, Set

def write_subdirectories(root: Path, unique_subdirs: Set[str]) -> None:
    """
    Add subdirectories of the given root to the set of unique subdirectories.

    This function attempts to add all subdirectories of the given root directory
    to the set of unique subdirectories. It handles potential permission errors
    and other OS errors, logging them as they occur without halting the entire process.

    Args:
    root (Path): The root directory to search for subdirectories.
    unique_subdirs (Set[str]): The set to store unique subdirectory paths.

    Raises:
    PermissionError: If there's a permission issue accessing the directory.
    OSError: For other OS-related errors during file operations.
    """
    try:
        for subdir in root.rglob('*'):
            if subdir.is_dir() and subdir != root:
                unique_subdirs.add(str(subdir))
    except PermissionError:
        logging.error("Permission denied accessing %s", root)
    except OSError as e:
        logging.error("OS error occurred processing directory %s: %s", root, str(e))

def process_directory(root: Path, letters: List[str], unique_subdirs: Set[str]) -> None:
    """
    Process a directory if it starts with one of the given letters.

    This function checks if the given directory starts with any of the specified letters.
    If it does, it calls write_subdirectories to add its subdirectories to the set of
    unique subdirectories.

    Args:
    root (Path): The directory to process.
    letters (List[str]): The list of starting letters to check against.
    unique_subdirs (Set[str]): The set to store unique subdirectory paths.
    """
    if root.is_dir() and any(root.name.lower().startswith(letter) for letter in letters):
        write_subdirectories(root, unique_subdirs)

def list_subdirectories(letters: List[str], search_path: Path = Path('.'), output_file: Path = Path('subdirectory_list.txt')) -> None:
    """
    List unique subdirectories of directories starting with the specified letters.

    This function walks through the directory tree from the given search path,
    identifies directories starting with any of the specified letters,
    collects unique paths of their subdirectories, and writes them to the output file.

    Args:
    letters (List[str]): The starting letters to search for in parent directory names.
    search_path (Path): The path to start the search from. Defaults to current directory.
    output_file (Path): The name of the file to write the results to.

    Raises:
    OSError: For OS-related errors during file operations, including IOError and PermissionError.
    """
    letters = [letter.lower() for letter in letters]
    unique_subdirs: Set[str] = set()
    try:
        for root in search_path.rglob('*'):
            process_directory(root, letters, unique_subdirs)

        with output_file.open('w', encoding='utf-8') as f:
            for subdir in sorted(unique_subdirs):
                f.write(f"{subdir}\n")
    except PermissionError:
        logging.error("Permission denied accessing %s", search_path)
    except OSError as e:
        logging.error("OS error occurred: %s", str(e))

def format_time_delta(td: timedelta) -> str:
    """
    Format a timedelta object into a human-readable string.

    This function takes a timedelta object and returns a string representation
    breaking it down into years, months, days, hours, minutes, seconds, and milliseconds.
    It only includes non-zero values in the output, except for very small time deltas
    where at least seconds will always be shown.

    The function uses approximate values for years (365 days) and months (30 days)
    for simplicity in calculation.

    Args:
    td (timedelta): The timedelta object to format.

    Returns:
    str: A human-readable string representation of the time delta.

    Example:
    >>> format_time_delta(timedelta(days=400, seconds=3661, microseconds=200000))
    '1 year, 1 month, 5 days, 1 hour, 1 minute, 1 second, 200 milliseconds'
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

    # Check if no larger units are present
    no_larger_units = all(x == 0 for x in (years, months, days, hours, minutes))
    if seconds > 0 or no_larger_units:
        parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
    if milliseconds > 0:
        parts.append(f"{milliseconds} millisecond{'s' if milliseconds != 1 else ''}")

    return ", ".join(parts)

def main() -> None:
    """
    Main function to handle command-line arguments and execute the subdirectory listing.

    This function sets up argument parsing, processes the command-line inputs,
    calls the list_subdirectories function with the provided arguments, and
    handles the overall execution flow of the script. It also measures and
    reports the execution time of the script.

    The function uses argparse for command-line argument parsing, allowing for
    flexible and user-friendly input. It handles potential errors in argument
    parsing and during script execution, ensuring graceful exit in case of issues.

    Command-line Arguments:
    letters: One or more letters to search for (positional, required)
    -p, --path: Path to search in (optional, default: current directory)
    -o, --output: Output file name (optional, default: subdirectory_list.txt)

    The function also provides timing information, displaying the start time,
    end time, and total execution time of the script in a human-readable format.

    Raises:
    SystemExit: If there's an error in argument parsing or during script execution.
    """
    start_time = time.time()
    start_datetime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"Script started at: {start_datetime}")

    parser = argparse.ArgumentParser(description="List unique subdirectories of directories starting with specified letters.")
    parser.add_argument('letters', nargs='+', help="Starting letters to search for in parent directory names")
    parser.add_argument('-p', '--path', type=Path, default=Path('.'), help="Path to search in (default: current directory)")
    parser.add_argument('-o', '--output', type=Path, default=Path('subdirectory_list.txt'), help="Output file name (default: subdirectory_list.txt)")

    try:
        args = parser.parse_args()
    except argparse.ArgumentError as e:
        logging.error("Error parsing arguments: %s", str(e))
        sys.exit(1)

    try:
        list_subdirectories(args.letters, args.path, args.output)
        print(f"Results have been written to {args.output}")
    except OSError as e:
        logging.error("An error occurred during execution: %s", str(e))
        sys.exit(1)

    end_time = time.time()
    end_datetime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    execution_time = timedelta(seconds=end_time - start_time)

    print(f"Script ended at: {end_datetime}")
    print(f"Total execution time: {format_time_delta(execution_time)}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR, format='%(levelname)s: %(message)s')
    main()
