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
    python script_name.py [--root ROOT_DIR] [--output OUTPUT_FILE]
                          [--types FILE_TYPES...] [--exclude PATTERNS...]

Example:
    python script_name.py --root /path/to/search --types .xml .xsd
                          --exclude "*temp*" "*backup*"

This command does the following:
    - Searches for files in /path/to/search and its subdirectories
    - Looks for files with .xml and .xsd extensions
    - Excludes any files or directories matching the patterns *temp* or *backup*

For more information, use the --help option:
    python script_name.py --help
"""

import argparse
import fnmatch
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, TypedDict

from tqdm import tqdm

class FileResult(TypedDict):
    """Represents the result of a file search in a single directory."""
    matching_files: List[str]

class DirectoryResult(TypedDict):
    """Represents the result of a file search in a directory and its subdirectories."""
    matching_files: List[str]
    subdirectories: Dict[str, 'DirectoryResult']

class Metadata(TypedDict):
    """Represents metadata about the file search process."""
    start_time: str
    end_time: str
    execution_time_seconds: float
    execution_time_formatted: str
    root_directory: str
    file_types_searched: List[str]
    exclusion_patterns: List[str]
    total_directories_processed: int
    total_matching_files: int

class OutputData(TypedDict):
    """Represents the complete output data structure."""
    metadata: Metadata
    results: DirectoryResult

@dataclass
class SearchConfig:
    """Configuration for the file search process."""
    start_time: float
    start_datetime: datetime
    end_datetime: datetime
    root_dir: Path
    args: argparse.Namespace
    directory_count: int
    file_count: int

class FileSearcher:
    """
    A class to search for files of specified types in a directory structure.
    """

    def __init__(self, root_dir: Path, file_types: List[str], exclude_patterns: List[str]):
        """
        Initialize the FileSearcher.

        Args:
            root_dir (Path): The root directory to start the search from.
            file_types (List[str]): List of file extensions to search for.
            exclude_patterns (List[str]): List of patterns to exclude from the search.
        """
        self.root_dir = root_dir
        self.file_types = file_types
        self.exclude_patterns = exclude_patterns
        self.results: DirectoryResult = {"matching_files": [], "subdirectories": {}}
        self.directory_count = 0
        self.file_count = 0

    def search(self) -> None:
        """
        Perform the file search and populate the results.
        """
        total_dirs = sum(1 for _ in self.root_dir.rglob('*') if _.is_dir()) + 1
        with tqdm(total=total_dirs, desc="Processing directories", unit="dir") as pbar:
            self._search_directory(self.root_dir, self.results)
            pbar.update(total_dirs)  # Update progress bar to 100%

    def _search_directory(self, directory: Path, current_result: DirectoryResult) -> bool:
        """
        Recursively search a directory and its subdirectories for matching files.

        Args:
            directory (Path): The directory to search.
            current_result (DirectoryResult): The current result dictionary to populate.

        Returns:
            bool: True if this directory or any subdirectory contains matching files, False otherwise.
        """
        self.directory_count += 1
        has_matching_files = False

        for path in directory.iterdir():
            if path.is_dir():
                if any(fnmatch.fnmatch(path.name, pattern) for pattern in self.exclude_patterns):
                    continue
                subdir_result: DirectoryResult = {"matching_files": [], "subdirectories": {}}
                if self._search_directory(path, subdir_result):
                    current_result["subdirectories"][path.name] = subdir_result
                    has_matching_files = True
            elif path.is_file():
                if any(path.suffix.lower() == ext.lower() for ext in self.file_types) and \
                   not any(fnmatch.fnmatch(path.name, pattern) for pattern in self.exclude_patterns):
                    current_result["matching_files"].append(path.name)
                    self.file_count += 1
                    has_matching_files = True

        return has_matching_files

    def get_summary(self) -> Dict[str, int]:
        """
        Get a summary of the search results.

        Returns:
            Dict[str, int]: A dictionary containing the number of directories processed and files found.
        """
        return {
            "directories_processed": self.directory_count,
            "matching_files_found": self.file_count
        }

class MetadataCreator:
    """
    A class to create metadata for the file search results.
    """

    @staticmethod
    def create(config: SearchConfig) -> Metadata:
        """
        Create metadata for the file search results.

        Args:
            config (SearchConfig): The search configuration and results.

        Returns:
            Metadata: A dictionary containing the metadata.
        """
        execution_time = time.time() - config.start_time
        execution_timedelta = timedelta(seconds=execution_time)
        return {
            "start_time": config.start_datetime.isoformat(),
            "end_time": config.end_datetime.isoformat(),
            "execution_time_seconds": execution_time,
            "execution_time_formatted": MetadataCreator.format_time_delta(execution_timedelta),
            "root_directory": str(config.root_dir),
            "file_types_searched": config.args.types,
            "exclusion_patterns": config.args.exclude,
            "total_directories_processed": config.directory_count,
            "total_matching_files": config.file_count
        }

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

class JSONWriter:
    """
    A class to write the search results to a JSON file.
    """

    @staticmethod
    def clean_results(results: DirectoryResult) -> DirectoryResult:
        """
        Remove empty subdirectories and matching_files lists from the results.

        Args:
            results (DirectoryResult): The results to clean.

        Returns:
            DirectoryResult: The cleaned results.
        """
        cleaned: DirectoryResult = {}
        if results["matching_files"]:
            cleaned["matching_files"] = results["matching_files"]
        if results["subdirectories"]:
            cleaned["subdirectories"] = {}
            for subdir, subdir_results in results["subdirectories"].items():
                cleaned_subdir = JSONWriter.clean_results(subdir_results)
                if cleaned_subdir:
                    cleaned["subdirectories"][subdir] = cleaned_subdir
        return cleaned

    @staticmethod
    def write(output: OutputData, root_dir: Path, output_file: Optional[Path]) -> None:
        """
        Write the search results to a JSON file.

        Args:
            output (OutputData): The data to write to the JSON file.
            root_dir (Path): The root directory of the search.
            output_file (Optional[Path]): The path to the output file. If None, a default name will be generated.
        """
        script_dir = Path(__file__).parent.resolve()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        root_name = root_dir.name
        json_filename = output_file or script_dir / f"{root_name}_{timestamp}.json"

        # Clean the results before writing
        cleaned_results = JSONWriter.clean_results(output["results"])
        cleaned_output = {
            "metadata": output["metadata"],
            "results": cleaned_results
        }

        with json_filename.open('w', encoding='utf-8') as json_file:
            json.dump(cleaned_output, json_file, indent=2, ensure_ascii=False)
        # logging.info("File structure has been written to %s", json_filename)
        print(f"File structure has been written to {json_filename}")

class XMLFileFinder:
    """
    Main class to orchestrate the XML file finding process.
    """

    def __init__(self):
        """
        Initialize the XMLFileFinder.
        """
        self.args = self.parse_arguments()
        self.setup_logging()

    @staticmethod
    def parse_arguments() -> argparse.Namespace:
        """
        Parse command-line arguments.

        Returns:
            argparse.Namespace: The parsed command-line arguments.
        """
        parser = argparse.ArgumentParser(description="Find XML files and output structure to JSON.")
        parser.add_argument("--root", default=Path.cwd(), type=Path, help="Root directory to search (default: current directory)")
        parser.add_argument("--output", type=Path, help="Output JSON file name (default: auto-generated with timestamp)")
        parser.add_argument("--types", nargs="+", default=[".xml"], help="File types to search for (default: .xml)")
        parser.add_argument("--exclude", nargs="+", default=[], help="Patterns to exclude")
        return parser.parse_args()

    @staticmethod
    def setup_logging() -> None:
        """
        Set up basic logging configuration.
        """
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    def run(self) -> None:
        """
        Run the XML file finding process.
        """
        start_time = time.time()
        start_datetime = datetime.now()
        print(f"Script started at: {start_datetime.strftime('%Y-%m-%d %H:%M:%S')}")

        try:
            root_dir = self.args.root.resolve()

            if not root_dir.exists():
                raise FileNotFoundError(f"The specified root directory does not exist: {root_dir}")

            if not root_dir.is_dir():
                raise NotADirectoryError(f"The specified path is not a directory: {root_dir}")

            # logging.info("Searching for files in: %s", root_dir)
            print(f"Searching for files in: {root_dir}")

            searcher = FileSearcher(root_dir, self.args.types, self.args.exclude)
            searcher.search()
            summary = searcher.get_summary()

            # logging.info("Search completed. Summary: %s", summary)
            print(f"Search completed. Summary: {summary}")

            end_datetime = datetime.now()
            search_config = SearchConfig(
                start_time=start_time,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                root_dir=root_dir,
                args=self.args,
                directory_count=summary["directories_processed"],
                file_count=summary["matching_files_found"]
            )

            metadata = MetadataCreator.create(search_config)
            output: OutputData = {"metadata": metadata, "results": searcher.results}

            JSONWriter.write(output, root_dir, self.args.output)

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
            raise
        finally:
            end_datetime = datetime.now()
            print(f"Script ended at: {end_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Total execution time: {MetadataCreator.format_time_delta(end_datetime - start_datetime)}")

if __name__ == "__main__":
    finder = XMLFileFinder()
    finder.run()
