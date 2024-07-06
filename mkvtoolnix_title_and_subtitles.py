"""
MKV Processor Script

This script processes MKV and MP4 files by keeping only specified subtitle tracks.
It utilizes the MKVToolNix suite, specifically mkvmerge, to perform these operations.
The script processes all MKV and MP4 files in the specified input directory and saves
the processed files to a sub-directory within the input directory.

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

    process_file(self, file_path):
        Processes an MKV or MP4 file by removing title and non-English subtitles, and saves to output directory.

    process_directory(self):
        Processes all MKV and MP4 files in the input directory.

    run(self):
        Runs the MKVProcessor to process all files in the input directory and track execution time.

Private Methods:
    _get_output_path(self, file_path):
        Generates the output file path based on the input file path.

Usage:
    Modify the MKV_PROCESSOR_CONFIG constants in the main block to match your environment, then run the script.
"""

import subprocess
import os
import glob
from datetime import datetime


class MKVProcessor:
    """
    A class to process MKV and MP4 files by removing titles and non-English subtitles.
    """

    def __init__(self, config):
        """
        Initialize the MKVProcessor with paths and settings.

        Parameters:
        - config (dict): Configuration object containing initialization settings.
        Requires keys: 'mkvmerge_executable', 'input_directory', 'file_extensions',
                        'subtitle_tracks', 'output_extension'.
        """
        self.MKVMERGE_EXECUTABLE = os.path.normpath(config['mkvmerge_executable'])
        self.INPUT_DIRECTORY = os.path.normpath(config['input_directory'])
        self.FILE_EXTENSIONS = config['file_extensions']
        self.SUBTITLE_TRACKS = config['subtitle_tracks']
        self.OUTPUT_EXTENSION = config['output_extension']
        self.output_dir = os.path.join(self.INPUT_DIRECTORY, "processed_files")  # Output directory
        self.successful_files = []
        self.failed_files = []

    def check_executables(self):
        """
        Check if MKVToolNix executables are found at the specified path.

        Returns:
        - bool: True if executables are found, False otherwise.
        """
        if not os.path.isfile(self.MKVMERGE_EXECUTABLE):
            print("Error: MKVToolNix executable not found at the specified path.")
            print(f"mkvmerge path: {self.MKVMERGE_EXECUTABLE}")
            return False
        return True

    def remove_title_keep_english_subs(self, file_path, output_path):
        """
        Remove the title and keep specified subtitle tracks from an MKV file.

        Parameters:
        - file_path (str): Path to the input MKV file.
        - output_path (str): Path to save the processed MKV file.

        Returns:
        - bool: True if successful, False if failed.
        """
        print(f"Processing {os.path.basename(file_path)}...")

        # Build the command to remove title and keep specified subtitle tracks
        command = [self.MKVMERGE_EXECUTABLE, "-o", output_path, "--title", "", "--subtitle-tracks", self.SUBTITLE_TRACKS, file_path]

        try:
            subprocess.run(command, check=True)
            print(f"Removed title and non-English subtitles from {os.path.basename(file_path)}")
            print(f"Saved as {os.path.basename(output_path)}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error processing {os.path.basename(file_path)}: {e}")
            return False

    def process_file(self, file_path):
        """
        Process the MKV file to remove title and non-English subtitles, and save to output directory.

        Parameters:
        - file_path (str): Path to the input MKV file.
        """
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

        # Create output file path
        output_path = os.path.join(self.output_dir, f"{os.path.splitext(os.path.basename(file_path))[0]}{self.OUTPUT_EXTENSION}")

        # Remove non-English subtitles and save to the output directory
        if self.remove_title_keep_english_subs(file_path, output_path):
            self.successful_files.append(os.path.basename(file_path))
        else:
            self.failed_files.append(os.path.basename(file_path))

    def process_directory(self):
        """
        Process all EXT files in the input directory.
        """
        ext_files = []
        for ext in self.FILE_EXTENSIONS:
            ext_files.extend(glob.glob(os.path.join(self.INPUT_DIRECTORY, f"*.{ext}")))

        for ext_file in ext_files:
            self.process_file(ext_file)

    def run(self):
        """
        Run the MKVProcessor to process all files in the input directory and track execution time.
        """
        # Get the start time
        start_time = datetime.now()
        print(f"Script started at: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

        # Check executables
        if self.check_executables():
            # Process the directory
            self.process_directory()

            # Print the summary of processed files
            print("\nSummary of Processed Files:")
            print("Successful files:")
            for file in self.successful_files:
                print(f"  - {file}")
            print("Failed files:")
            for file in self.failed_files:
                print(f"  - {file}")

        else:
            print("Exiting script due to missing executables.")

        # Get the end time
        end_time = datetime.now()
        print(f"Script finished at: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")

        # Calculate and print the execution time
        execution_time = end_time - start_time
        print(f"Total execution time: {str(execution_time)}")

    def _get_output_path(self, file_path):
        """
        Generate the output file path based on the input file path.

        Parameters:
        - file_path (str): Path to the input file.

        Returns:
        - str: Output file path.
        """
        return os.path.join(self.output_dir, os.path.basename(file_path) + self.OUTPUT_EXTENSION)


if __name__ == "__main__":
    # Update these paths and constants accordingly
    MKV_PROCESSOR_CONFIG = {
        'mkvmerge_executable': "</path/to/mkvmerge.exe>",
        'input_directory': "</path/to/input_directory>",  # Replace with your input directory path
        'file_extensions': ['ext_01', 'ext_02'],  # Add or remove file extensions as needed
        'subtitle_tracks': "sub_01,sub_02",  # Subtitle tracks to keep
        'output_extension': "<.output_extension>",  # Output extension for processed files
    }

    processor = MKVProcessor(MKV_PROCESSOR_CONFIG)
    processor.run()
