"""
MKV Processor Script

This script processes MKV and MP4 files by retaining only specified subtitle tracks. 
It uses the MKVToolNix suite, particularly mkvmerge, to execute these operations. 
The script processes all MKV and MP4 files in the specified input directories and saves 
the processed files to a sub-directory within each input directory.

Classes:
    MKVProcessor: A class that handles the processing of MKV and MP4 files.

Functions:
    rgb_color(r, g, b, text): 
        Generates ANSI escape sequences for RGB-like color formatting in terminal output.

Usage:
    Modify the MKV_PROCESSOR_CONFIG constants in the main block to match your environment, then run the script.

    python docker_compose_manager.py

Requirements:
    Ensure that MKVToolNix is installed and the mkvmerge executable path is correctly set in the configuration.
    Update pip if necessary:
    python.exe -m pip install --upgrade pip

Notes for Windows Users:
    If you encounter a warning about pip scripts not being on PATH, consider adding the directory to PATH 
    or use --no-warn-script-location to suppress the warning.
"""

import json
import pathlib
import subprocess
import os
from datetime import datetime

# ANSI color escape sequences for RGB-like colors
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

class MKVProcessor:
    """
    A class to process MKV and MP4 files by removing titles and non-English subtitles.
    This class uses ANSI escape sequences for colored output in the terminal.

    Attributes:
        MKVMERGE_EXECUTABLE (str): Path to the mkvmerge executable.
        INPUT_DIRECTORIES (list): List of directories to process files from.
        FILE_EXTENSIONS (list): List of file extensions to process.
        SUBTITLE_TRACKS (str): Subtitle tracks to keep.
        OUTPUT_EXTENSION (str): Output extension for processed files.
        script_filename (str): Name of the script file used for JSON naming.

    Methods:
        __init__(self, config):
            Initializes the MKVProcessor with paths and settings using a configuration object.

        check_executables(self):
            Checks if MKVToolNix executable is found at the specified path.
            Returns True if executables are found, False otherwise.

        remove_title_keep_english_subs(self, file_path, output_path):
            Removes the title and keeps specified subtitle tracks from an MKV file.
            Returns True if successful, False otherwise.

        process_file(self, file_path, output_dir):
            Processes an MKV or MP4 file by removing the title and non-English subtitles,
            then saves it to the output directory.

        process_directory(self, input_dir):
            Processes all MKV and MP4 files in the input directory.

        run(self):
            Runs the MKVProcessor to process all files in the input directories and tracks execution time.

        _write_or_append_to_json(self, message, is_success=True):
            Writes or appends a message to a JSON file for logging purposes.

    Private Methods:
        _get_output_path(self, file_path, output_dir):
            Generates the output file path based on the input file path.
    """

    def __init__(self, config):
        """
        Initialize the MKVProcessor with paths and settings.

        Parameters:
            config (dict): Configuration object containing initialization settings.
            Requires keys: 'mkvmerge_executable', 'input_directories', 'file_extensions', 'subtitle_tracks', 'output_extension'.
        """
        self.MKVMERGE_EXECUTABLE = os.path.normpath(config['mkvmerge_executable'])
        self.INPUT_DIRECTORIES = [os.path.normpath(d) for d in config['input_directories']]
        self.FILE_EXTENSIONS = config['file_extensions']
        self.SUBTITLE_TRACKS = config['subtitle_tracks']
        self.OUTPUT_EXTENSION = config['output_extension']

        # Get script filename for JSON naming
        self.script_filename = os.path.splitext(os.path.basename(__file__))[0]

    def _write_or_append_to_json(self, message, is_success=True):
        """
        Write or append a message to a JSON file.

        Parameters:
            message (str): A message to write or append.
            is_success (bool): True for success message, False for error message.

        Notes:
            - Creates a JSON file if it doesn't exist or appends to the existing file.
            - Logs messages with timestamps under 'success' or 'error' suffix in filenames.
        """
        # Determine the file name
        file_suffix = "success" if is_success else "error"
        filename = f"{self.script_filename}_{file_suffix}.json"
        filepath = os.path.join(os.path.dirname(__file__), filename)

        # Initialize JSON structure
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Convert Path objects to strings
        new_message = [{"timestamp": current_time, "message": str(message)}]
        root_key = f"{self.script_filename}_{file_suffix}"

        # Read existing data or create a new JSON structure if file doesn't exist
        data = {}
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as file:
                    # Check if the file is not empty
                    if os.path.getsize(filepath) > 0:
                        data = json.load(file)
            except json.JSONDecodeError:
                print(rgb_color(255, 255, 0, f"Warning: JSON file {filename} is corrupted. Starting with an empty file.")) # rgb(255, 255, 0)

        # Update or initialize the JSON structure
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

        # Write data to file
        with open(filepath, 'w', encoding='utf-8') as file:
            json.dump(data, file, indent=4)

    def check_executables(self):
        """
        Check if MKVToolNix executables are found at the specified path.

        Uses ANSI escape sequences for colored output.

        Returns:
            bool: True if executables are found, False otherwise.

        Notes:
            - Prints error messages to the terminal using RGB colors if executables are not found.
            - Logs error details in the JSON error file.
        """
        if not os.path.isfile(self.MKVMERGE_EXECUTABLE):
            print(rgb_color(255, 0, 0, "Error: MKVToolNix executable not found at the specified path.")) # rgb(255, 0, 0)
            print(rgb_color(255, 255, 0, f"mkvmerge path: {self.MKVMERGE_EXECUTABLE}")) # rgb(255, 255, 0)

            error_msg = f"Error: MKVToolNix executable not found at the specified path.\n mkvmerge path: {self.MKVMERGE_EXECUTABLE}"
            self._write_or_append_to_json(error_msg, is_success=False)
            return False
        return True

    def remove_title_keep_english_subs(self, file_path, output_path):
        """
        Remove the title and keep specified subtitle tracks from an MKV file.

        Uses ANSI escape sequences for colored output.

        Parameters:
            file_path (str): Path to the input MKV file.
            output_path (str): Path to save the processed MKV file.

        Returns:
            bool: True if successful, False otherwise.

        Notes:
            - Executes mkvmerge command to process the file.
            - Logs success and error messages to JSON files with timestamps.
            - Prints progress and error messages to the terminal using RGB colors.
        """
        print(rgb_color(71, 111, 232, f"Processing {os.path.basename(file_path)}...")) # rgb(71, 111, 232)

        # Build the command to remove title and keep specified subtitle tracks
        command = [self.MKVMERGE_EXECUTABLE, "-o", output_path, "--title", "", "--subtitle-tracks", self.SUBTITLE_TRACKS, file_path]

        try:
            subprocess.run(command, check=True)
            success_msg_one = f"Removed title and non-English subtitles from {os.path.basename(file_path)}"
            success_msg_two = f"Saved as {os.path.basename(output_path)}"
            print(rgb_color(0, 255, 0, success_msg_one)) # rgb(0, 255, 0)
            print(rgb_color(0, 255, 0, success_msg_two)) # rgb(0, 255, 0)

            success_msg = success_msg_one + "\n" + success_msg_two
            self._write_or_append_to_json(success_msg, is_success=True)
            return True
        except subprocess.CalledProcessError as e:
            error_msg = f"Error processing {os.path.basename(file_path)}: {e}"
            print(rgb_color(255, 0, 0, error_msg)) # rgb(255, 0, 0)
            self._write_or_append_to_json(error_msg, is_success=False)
            return False

    def process_file(self, file_path, output_dir):
        """
        Process an MKV file to remove the title and non-English subtitles, and save it to the output directory.

        Uses ANSI escape sequences for colored output.

        Parameters:
            file_path (str): Path to the input MKV file.
            output_dir (str): Directory to save the processed file.

        Notes:
            - Creates the output directory if it doesn't exist.
            - Generates the output file path using the input file name and output extension.
        """
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # Create output file path
        output_path = os.path.join(output_dir, f"{os.path.splitext(os.path.basename(file_path))[0]}{self.OUTPUT_EXTENSION}")

        self.remove_title_keep_english_subs(file_path, output_path)

    def process_directory(self, input_dir):
        """
        Process all MKV and MP4 files in the input directory.

        Uses ANSI escape sequences for colored output.

        Parameters:
            input_dir (str): Directory to process files from.

        Notes:
            - Searches for files with specified extensions in the input directory.
            - Calls process_file for each file found.
            - Creates a "processed_files" sub-directory to store processed files.
        """
        ext_files = []
        for ext in self.FILE_EXTENSIONS:
            ext_files.extend(list(pathlib.Path(input_dir).glob(f'*.{ext}')))

        output_dir = os.path.join(input_dir, "processed_files")

        for ext_file in ext_files:
            self.process_file(ext_file, output_dir)

    def run(self):
        """
        Run the MKVProcessor to process all files in the input directories and track execution time.

        Uses ANSI escape sequences for colored output.

        Notes:
            - Logs start and finish times with RGB color formatting.
            - Validates the existence of the mkvmerge executable before processing.
            - Iterates over input directories and processes each directory.
            - Skips processing for invalid or missing directories.
            - Logs execution time and instructs users to check JSON logs for details.
        """
        # Get the start time
        start_time = datetime.now()
        print(rgb_color(0, 255, 255, f"Script started at: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")) # rgb(0, 255, 255)

        # Check executables
        if self.check_executables():
            if not self.INPUT_DIRECTORIES:
                print(rgb_color(255, 255, 0, "No directories provided.")) # rgb(255, 255, 0)
            else:
                # Process each directory
                for input_dir in self.INPUT_DIRECTORIES:
                    # Explicitly Check for Empty String: Check if input_dir is an empty string.
                    if input_dir.strip() == "":
                        print(rgb_color(255, 255, 0, "No directory was given.")) # rgb(255, 255, 0)
                        continue

                    # Use os.curdir for Current Directory: Use os.curdir to represent the current directory instead of "." or "./".
                    # Use os.path.normpath() to normalize paths and handle different path separators (\ vs / on Windows vs Unix-like systems).
                    if os.path.normpath(input_dir) == os.path.normpath(os.curdir):
                        print(rgb_color(255, 255, 0, "Current directory (. or ./) specified. Skipping.")) # rgb(255, 255, 0)
                        continue

                    # Existence Check: os.path.isdir(input_dir) checks if input_dir is a valid directory.
                    if not os.path.isdir(input_dir):
                        print(rgb_color(255, 255, 0, f"Directory does not exist: {input_dir}")) # rgb(255, 255, 0)
                        continue

                    print(rgb_color(136, 66, 183, f"Working directory {input_dir}...")) # rgb(136, 66, 183)
                    self.process_directory(input_dir)

            # Print the summary of processed files
            print(rgb_color(255, 255, 0, "\nCheck success and or error file(s) if any were generated")) # rgb(255, 255, 0)

        else:
            print(rgb_color(255, 0, 0, "Exiting script due to missing executables.")) # rgb(255, 0, 0)

        # Get the end time
        end_time = datetime.now()
        print(rgb_color(0, 255, 255, f"Script finished at: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")) # rgb(0, 255, 255)

        # Calculate and print the execution time
        execution_time = end_time - start_time
        print(rgb_color(201, 103, 28, f"Total execution time: {str(execution_time)}")) # rgb(201, 103, 28)

    def _get_output_path(self, file_path, output_dir):
        """
        Generate the output file path based on the input file path.

        Parameters:
            file_path (str): Path to the input file.
            output_dir (str): Directory to save the output file.

        Returns:
            str: Output file path.

        Notes:
            - Combines the output directory with the base name of the input file and output extension.
        """
        return os.path.join(output_dir, os.path.basename(file_path) + self.OUTPUT_EXTENSION)

if __name__ == "__main__":
    # Update these paths and constants accordingly
    MKV_PROCESSOR_CONFIG = {
        'mkvmerge_executable': r"</path/to/mkvmerge.exe>",
        'input_directories': [r"</path/to/input_directory_01>", r"</path/to/input_directory_02>"],  # Replace with your input directory paths
        'file_extensions': ['<ext_01>', '<ext_02>'],  # Add or remove file extensions as needed
        'subtitle_tracks': "<sub_01,sub_02>",  # Subtitle tracks to keep
        'output_extension': "<.output_extension>",  # Output extension for processed files
    }

    processor = MKVProcessor(MKV_PROCESSOR_CONFIG)
    processor.run()
