"""
MKV Processor Script

This script processes MKV and MP4 files by keeping only specified subtitle tracks.
It utilizes the MKVToolNix suite, specifically mkvmerge, to perform these operations.
The script processes all MKV and MP4 files in the specified input directories and saves
the processed files to a sub-directory within each input directory.

Classes:
    MKVProcessor: Handles processing of MKV and MP4 files.

Methods:
    __init__(self, config):
        Initializes the MKVProcessor with paths and settings using a configuration object.

    check_executables(self):
        Checks if MKVToolNix executable is found at the specified path.
        Returns True if executables are found, False otherwise.

    remove_title_keep_english_subs(self, file_path, output_path):
        Removes the title and keeps specified subtitle tracks from an MKV file.

    process_file(self, file_path, output_dir):
        Processes an MKV or MP4 file by removing title and non-English subtitles, and saves to output directory.

    process_directory(self, input_dir):
        Processes all MKV and MP4 files in the input directory.

    run(self):
        Runs the MKVProcessor to process all files in the input directories and track execution time.

Private Methods:
    _get_output_path(self, file_path, output_dir):
        Generates the output file path based on the input file path.

Usage:
    Modify the MKV_PROCESSOR_CONFIG constants in the main block to match your environment, then run the script.

    python docker_compose_manager.py

Pip:
    Make sure your pip is updated
    python.exe -m pip install --upgrade pip

Windows:
    If warning on a Windows machine perform the following
    WARNING: The scripts pip.exe, pip3.12.exe and pip3.exe are installed in 'C:\\Users\\<user_name>\\AppData\\Roaming\\Python\\Python312\\Scripts' which is not on PATH.
    Consider adding this directory to PATH or, if you prefer to suppress this warning, use --no-warn-script-location.
"""

import pathlib
import subprocess
import os
from datetime import datetime

# ANSI color escape sequences for RGB-like colors
def rgb_color(r, g, b, text):
    """
    Generate ANSI escape sequences for RGB-like color formatting in terminal output.

    Parameters:
    - r (int): Red component (0-255).
    - g (int): Green component (0-255).
    - b (int): Blue component (0-255).
    - text (str): Text to be colored.

    Returns:
    - str: ANSI escape sequence for colored text.
    """
    return f"\033[38;2;{r};{g};{b}m{text}\033[0m"

class MKVProcessor:
    """
    A class to process MKV and MP4 files by removing titles and non-English subtitles.
    This class uses ANSI escape sequences for colored output in the terminal.

    Attributes:
    - MKVMERGE_EXECUTABLE (str): Path to the mkvmerge executable.
    - INPUT_DIRECTORIES (list): List of directories to process files from.
    - FILE_EXTENSIONS (list): List of file extensions to process.
    - SUBTITLE_TRACKS (str): Subtitle tracks to keep.
    - OUTPUT_EXTENSION (str): Output extension for processed files.
    - successful_files (list): List of successfully processed files.
    - failed_files (list): List of files that failed to process.
    """

    def __init__(self, config):
        """
        Initialize the MKVProcessor with paths and settings.

        Parameters:
        - config (dict): Configuration object containing initialization settings.
        Requires keys: 'mkvmerge_executable', 'input_directories', 'file_extensions',
                        'subtitle_tracks', 'output_extension'.
        """
        self.MKVMERGE_EXECUTABLE = os.path.normpath(config['mkvmerge_executable'])
        self.INPUT_DIRECTORIES = [os.path.normpath(d) for d in config['input_directories']]
        self.FILE_EXTENSIONS = config['file_extensions']
        self.SUBTITLE_TRACKS = config['subtitle_tracks']
        self.OUTPUT_EXTENSION = config['output_extension']
        self.successful_files = []
        self.failed_files = []

    def check_executables(self):
        """
        Check if MKVToolNix executables are found at the specified path.

        Uses ANSI escape sequences for colored output.

        Returns:
        - bool: True if executables are found, False otherwise.
        """
        if not os.path.isfile(self.MKVMERGE_EXECUTABLE):
            print(rgb_color(255, 0, 0, "Error: MKVToolNix executable not found at the specified path.")) # rgb(255, 0, 0)
            print(rgb_color(255, 255, 0, f"mkvmerge path: {self.MKVMERGE_EXECUTABLE}")) # rgb(255, 255, 0)
            return False
        return True

    def remove_title_keep_english_subs(self, file_path, output_path):
        """
        Remove the title and keep specified subtitle tracks from an MKV file.

        Uses ANSI escape sequences for colored output.

        Parameters:
        - file_path (str): Path to the input MKV file.
        - output_path (str): Path to save the processed MKV file.

        Returns:
        - bool: True if successful, False if failed.
        """
        print(rgb_color(71, 111, 232, f"Processing {os.path.basename(file_path)}...")) # rgb(71, 111, 232)

        # Build the command to remove title and keep specified subtitle tracks
        command = [self.MKVMERGE_EXECUTABLE, "-o", output_path, "--title", "", "--subtitle-tracks", self.SUBTITLE_TRACKS, file_path]

        try:
            subprocess.run(command, check=True)
            print(rgb_color(0, 255, 0, f"Removed title and non-English subtitles from {os.path.basename(file_path)}")) # rgb(0, 255, 0)
            print(rgb_color(0, 255, 0, f"Saved as {os.path.basename(output_path)}")) # rgb(0, 255, 0)
            return True
        except subprocess.CalledProcessError as e:
            print(rgb_color(255, 0, 0, f"Error processing {os.path.basename(file_path)}: {e}")) # rgb(255, 0, 0)
            return False

    def process_file(self, file_path, output_dir):
        """
        Process the MKV file to remove title and non-English subtitles, and save to output directory.

        Uses ANSI escape sequences for colored output.

        Parameters:
        - file_path (str): Path to the input MKV file.
        - output_dir (str): Directory to save the processed file.
        """
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # Create output file path
        output_path = os.path.join(output_dir, f"{os.path.splitext(os.path.basename(file_path))[0]}{self.OUTPUT_EXTENSION}")

        # Remove non-English subtitles and save to the output directory
        if self.remove_title_keep_english_subs(file_path, output_path):
            self.successful_files.append(file_path)
        else:
            self.failed_files.append(file_path)

    def process_directory(self, input_dir):
        """
        Process all MKV and MP4 files in the input directory.

        Uses ANSI escape sequences for colored output.

        Parameters:
        - input_dir (str): Directory to process files from.
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
        """
        # Get the start time
        start_time = datetime.now()
        print(rgb_color(0, 255, 255, f"Script started at: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")) # rgb(0, 255, 255)

        # Check executables
        if self.check_executables():
            # Process each directory
            for input_dir in self.INPUT_DIRECTORIES:
                print(rgb_color(136, 66, 183, f"Working directory {input_dir}...")) # rgb(136, 66, 183)
                self.process_directory(input_dir)

            # Print the summary of processed files
            print(rgb_color(255, 255, 0, "\nSummary of Processed Files:")) # rgb(255, 255, 0)
            print(rgb_color(0, 255, 0, "Successful files:")) # rgb(0, 255, 0)
            for file in self.successful_files:
                print(rgb_color(0, 255, 0, f"  - {file}")) # rgb(0, 255, 0)
            print(rgb_color(255, 0, 0, "Failed files:")) # rgb(255, 0, 0)
            for file in self.failed_files:
                print(rgb_color(255, 0, 0, f"  - {file}")) # rgb(255, 0, 0)

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
        - file_path (str): Path to the input file.
        - output_dir (str): Directory to save the output file.

        Returns:
        - str: Output file path.
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
