"""
MKV Processor Script

This script processes MKV and MP4 files by retaining only specified subtitle tracks.
It uses the MKVToolNix suite, particularly mkvmerge, to execute these operations.
The script processes all MKV and MP4 files in the specified input directories and
saves the processed files to a sub-directory within each input directory.

Classes:
    MKVProcessor: A class that handles the processing of MKV and MP4 files.

Functions:
    rgb_color(r, g, b, text): Generates ANSI escape sequences for RGB-like color formatting in terminal output.

Usage:
    Modify the MKV_PROCESSOR_CONFIG constants in the main block to match your environment, then run the script.
    python mkv_processor.py

Requirements:
    Ensure that MKVToolNix is installed and the mkvmerge executable path is correctly set in the configuration.

Notes for Windows Users:
    If you encounter a warning about pip scripts not being on PATH, consider adding the directory to PATH
    or use --no-warn-script-location to suppress the warning.
"""

import json
import pathlib
import subprocess
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from tqdm import tqdm  # Progress bar

def rgb_color(r, g, b, text):
    """
    Generate ANSI escape sequences for RGB-like color formatting in terminal output.

    Parameters:
        r (int): Red component (0-255).
        g (int): Green component (0-255).
        b (int): Blue component (0-255).
        text (str): Text to be colored.

    Returns:
        str: ANSI escape sequence for colored text.
    """
    return f"\033[38;2;{r};{g};{b}m{text}\033[0m"

def setup_logging(script_filename, script_directory):
    """
    Setup logging configuration with log rotation.

    Parameters:
        script_filename (str): The name of the script file.
        script_directory (pathlib.Path): The directory where the script is located.
    """
    log_file = script_directory / f"{script_filename}.log"
    handler = RotatingFileHandler(log_file, maxBytes=10**6, backupCount=5)  # 1MB per file, 5 backups
    logging.basicConfig(handlers=[handler], level=logging.INFO,
                        format='%(asctime)s - %(levelname)s - %(message)s')

class MKVProcessor:
    """
    A class to process MKV and MP4 files by removing titles and non-English subtitles.

    Attributes:
        mkvmerge_executable (pathlib.Path): Path to the mkvmerge executable.
        input_directories (list): List of directories to process files from.
        file_extensions (list): List of file extensions to process.
        subtitle_tracks (str): Subtitle tracks to keep.
        output_extension (str): Output extension for processed files.
        script_directory (pathlib.Path): Directory where the script is located.
        script_filename (str): Name of the script file used for JSON naming.
    """

    def __init__(self, config):
        """
        Initialize the MKVProcessor with paths and settings.

        Parameters:
            config (dict): Configuration object containing initialization settings.
                Requires keys: 'mkvmerge_executable', 'input_directories',
                'file_extensions', 'subtitle_tracks', 'output_extension'.
        """
        self.mkvmerge_executable = pathlib.Path(config['mkvmerge_executable'])
        self.input_directories = [pathlib.Path(d) for d in config['input_directories']]
        self.file_extensions = config['file_extensions']
        self.subtitle_tracks = config['subtitle_tracks']
        self.output_extension = config['output_extension']

        # Get the full path of the script
        script_path = pathlib.Path(__file__).resolve()
        self.script_directory = script_path.parent
        self.script_filename = script_path.stem

        setup_logging(self.script_filename, self.script_directory)

    @staticmethod
    def load_config(config_path):
        """
        Load configuration from a JSON file.

        Parameters:
            config_path (str): Path to the JSON configuration file.

        Returns:
            dict: Configuration data loaded from the file.
        """
        try:
            with open(config_path, 'r', encoding='utf-8') as file:
                return json.load(file)
        except FileNotFoundError as fnf_error:
            logging.error("Configuration file not found: %s", config_path)
            raise fnf_error
        except json.JSONDecodeError:
            logging.error("Error decoding JSON from the configuration file: %s", config_path)
            raise

    def _write_or_append_to_json(self, message, is_success=True):
        """
        Write or append a message to a JSON file.

        Parameters:
            message (str): A message to write or append.
            is_success (bool): True for success message, False for error message.
        """
        file_suffix = "success" if is_success else "error"
        filename = f"{self.script_filename}_{file_suffix}.json"
        filepath = self.script_directory / filename

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_message = [{"timestamp": current_time, "message": str(message)}]
        root_key = f"{self.script_filename}_{file_suffix}"

        data = {}
        if filepath.exists():
            try:
                with open(filepath, 'r', encoding='utf-8') as file:
                    if filepath.stat().st_size > 0:
                        data = json.load(file)
            except json.JSONDecodeError:
                logging.warning("JSON file %s is corrupted. Starting with an empty file.", filename)

        if root_key in data:
            data[root_key]["updated_date"] = current_time
            data[root_key]["messages"].extend(new_message)
            data[root_key]["count"] = len(data[root_key]["messages"])
        else:
            data[root_key] = {
                "created_date": current_time,
                "updated_date": current_time,
                "count": len(new_message),
                "messages": new_message
            }

        try:
            with open(filepath, 'w', encoding='utf-8') as file:
                json.dump(data, file, indent=4)
        except IOError as io_error:
            logging.error("Failed to write to JSON file %s: %s", filename, io_error)

    def check_executables(self):
        """
        Check if MKVToolNix executables are found at the specified path.

        Returns:
            bool: True if executables are found, False otherwise.
        """
        if not self.mkvmerge_executable.is_file():
            logging.error("MKVToolNix executable not found at the specified path.")
            logging.error("mkvmerge path: %s", self.mkvmerge_executable)
            self._write_or_append_to_json("MKVToolNix executable not found.", is_success=False)
            return False
        return True

    def remove_title_keep_english_subs(self, file_path, output_path):
        """
        Remove the title and keep specified subtitle tracks from an MKV file.

        Parameters:
            file_path (str): Path to the input MKV file.
            output_path (str): Path to save the processed MKV file.

        Returns:
            bool: True if successful, False otherwise.
        """
        logging.info("Processing %s...", file_path.name)

        command = [
            str(self.mkvmerge_executable), "-o", str(output_path), "--title", "",
            "--subtitle-tracks", self.subtitle_tracks, str(file_path)
        ]

        try:
            subprocess.run(command, check=True)
            logging.info("Removed title and non-English subtitles from %s", file_path.name)
            logging.info("Saved as %s", output_path.name)
            self._write_or_append_to_json(f"Processed {file_path.name}", is_success=True)
            return True
        except subprocess.CalledProcessError as subproc_error:
            logging.error("Error processing %s: %s", file_path.name, subproc_error)
            self._write_or_append_to_json(f"Error processing {file_path.name}: {subproc_error}", is_success=False)
            return False

    def process_file(self, file_path, output_dir):
        """
        Process an MKV file to remove the title and non-English subtitles, and save it to the output directory.

        Parameters:
            file_path (str): Path to the input MKV file.
            output_dir (str): Directory to save the processed file.
        """
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{file_path.stem}{self.output_extension}"
            self.remove_title_keep_english_subs(file_path, output_path)
        except (OSError, IOError) as os_error:
            logging.error("Error processing file %s: %s", file_path, os_error)
            self._write_or_append_to_json(f"Error processing file {file_path}: {os_error}", is_success=False)

    def process_directory(self, input_dir):
        """
        Process all MKV and MP4 files in the input directory.

        Parameters:
            input_dir (str): Directory to process files from.
        """
        try:
            ext_files = [file for ext in self.file_extensions for file in input_dir.glob(f'*.{ext}')]
            output_dir = input_dir / "processed_files"
            for ext_file in tqdm(ext_files, desc=f"Processing directory {input_dir}"):
                self.process_file(ext_file, output_dir)
        except (OSError, IOError) as os_error:
            logging.error("Error processing directory %s: %s", input_dir, os_error)
            self._write_or_append_to_json(f"Error processing directory {input_dir}: {os_error}", is_success=False)

    def run(self):
        """
        Run the MKVProcessor to process all files in the input directories and track execution time.
        """
        start_time = datetime.now()
        logging.info("Script started at: %s", start_time.strftime('%Y-%m-%d %H:%M:%S'))

        if self.check_executables():
            if not self.input_directories:
                logging.warning("No directories provided.")
            else:
                for input_dir in self.input_directories:
                    if input_dir == pathlib.Path('.'):
                        logging.warning("Current directory (.) specified. Skipping.")
                        continue
                    if not input_dir.is_dir():
                        logging.warning("Directory does not exist: %s", input_dir)
                        continue
                    logging.info("Working directory %s...", input_dir)
                    self.process_directory(input_dir)

            logging.info("Check success and or error file(s) if any were generated")
        else:
            logging.error("Exiting script due to missing executables.")

        end_time = datetime.now()
        logging.info("Script finished at: %s", end_time.strftime('%Y-%m-%d %H:%M:%S'))
        execution_time = end_time - start_time
        logging.info("Total execution time: %s", str(execution_time))

    def _get_output_path(self, file_path, output_dir):
        """
        Generate the output file path based on the input file path.

        Parameters:
            file_path (str): Path to the input file.
            output_dir (str): Directory to save the output file.

        Returns:
            str: Output file path.
        """
        return output_dir / f"{file_path.stem}{self.output_extension}"


if __name__ == "__main__":
    CONFIG_PATH = '/path/to/mkvtoolnix_title_and_subtitles_config.json'  # Path to your configuration file
    try:
        CONFIG = MKVProcessor.load_config(CONFIG_PATH)
        processor = MKVProcessor(CONFIG)
        processor.run()
    except (FileNotFoundError, json.JSONDecodeError) as main_error:
        logging.error("An error occurred during execution: %s", main_error)
