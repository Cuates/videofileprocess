"""
Video Processor Script for FFmpeg-Based Subtitle Filtering and Metadata Removal

This script scans configured directories for video files, filters subtitle streams
based on language, removes title metadata, and either remuxes or reencodes the media
based on configuration. It supports GPU acceleration (CUDA) for reencoding when available.

Features:
- Config-driven input/output behavior
- Subtitle stream filtering by language
- Title metadata removal
- Remux or reencode modes
- GPU acceleration detection
- Structured logging (text + JSON)
- CPU load-aware processing
- Modular, auditable design

Dependencies:
- Python 3.8+
- Required Python libraries:
    - json
    - logging
    - subprocess
    - time
    - sys
    - shutil
    - pathlib
    - datetime
    - typing
    - psutil (install via `pip install psutil`)
- Required system tools:
    - ffmpeg
    - ffprobe
    - nvidia-smi (optional, for GPU detection)

Usage:
    Configure the JSON file with required keys and run the script.
"""
import json
import logging
import subprocess
import time
import sys
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Union
from logging.handlers import RotatingFileHandler
from enum import Enum
from dataclasses import dataclass
import psutil

class ConversionMode(Enum):
    """
    Enum representing the mode of video processing.

    Options:
        REMUX: Stream copy without reencoding.
        REENCODE: Full reencoding of video stream.
    """
    REMUX = "remux"
    REENCODE = "reencode"

class EncoderType(Enum):
    """
    Enum representing supported video encoder types.

    Options:
        LIBX264: CPU-based H.264 encoding.
        LIBX265: CPU-based H.265 encoding.
        H264_NVENC: NVIDIA GPU-based H.264 encoding.
        HEVC_NVENC: NVIDIA GPU-based H.265 encoding.
    """
    LIBX264 = "libx264"
    LIBX265 = "libx265"
    H264_NVENC = "h264_nvenc"
    HEVC_NVENC = "hevc_nvenc"

class PixelFormat(Enum):
    """
    Enum representing common pixel formats.

    Options:
        YUV420P: Standard 8-bit 4:2:0 planar YUV.
        YUV420P10LE: 10-bit 4:2:0 planar YUV, little-endian.
        P010LE: 10-bit 4:2:0 NVENC-compatible pixel format, little-endian.
    """
    YUV420P = "yuv420p"
    YUV420P10LE = "yuv420p10le"
    P010LE = "p010le"

class PresetLibxSpeed(Enum):
    """
    Enum representing libx264 preset speeds and compression tradeoffs.

    Options range from ULTRAFAST (fastest, worst compression)
    to VERYSLOW (slowest, best compression).
    """
    ULTRAFAST = "ultrafast" # Speed fastest, Compression worst
    SUPERFAST = "superfast" # Speed very fastest, Compression poor
    VERYFAST = "veryfast" # Speed fast, Compression decent
    FASTER = "faster" # Speed medium, Compression better
    FAST = "fast" # Speed slower, Compression good
    MEDIUM = "medium" # Speed slow, Compression great
    SLOW = "slow" # Speed very slow, Compression excellent
    SLOWER = "slower" # Speed very slow, Compression excellent
    VERYSLOW = "veryslow" # Speed slowest, Compression best

class PresetNvencSpeed(Enum):
    """
    Enum representing NVIDIA NVENC preset speeds and quality levels.

    Options range from P1 (fastest, lowest quality)
    to P7 (slowest, highest quality).
    """
    P1 = "p1" # Quality lowest, Speed fastest
    P2 = "p2" # Quality lower, Speed very fast
    P3 = "p3" # Quality low, Speed fast
    P4 = "p4" # Quality medium, Speed balanced
    P5 = "p5" # Quality good, Speed slower
    P6 = "p6" # Quality better, Speed very slow
    P7 = "p7" # Quality best, Speed slowest

class ConfigKey(Enum):
    """
    Enum representing keys expected in the configuration JSON file.

    Keys:
        INPUT_DIRECTORIES: List of directories to scan for video files.
        FILE_EXTENSIONS: List of file extensions to include.
        SUBTITLE_TRACKS: List of subtitle languages to retain.
        OUTPUT_EXTENSION: Extension for output files.
        CONVERSION_MODE: Processing mode (remux or reencode).
    """
    INPUT_DIRECTORIES = "input_directories"
    FILE_EXTENSIONS = "file_extensions"
    SUBTITLE_TRACKS =  "subtitle_tracks"
    OUTPUT_EXTENSION = "output_extension"
    CONVERSION_MODE = "conversion_mode"
    VIDEO_CODEC = "video_codec"
    AUDIO_CODEC = "audio_codec"
    SUBTITLE_CODEC = "subtitle_codec"
    PRESET = "preset"

PROCESSED_FILES_DIR = "processed_files"

CONFIG_PATH: str = '/path/to/ffmpeg_title_and_subtitles_config.json'

@dataclass(frozen=True)
class ScriptMeta:
    """
    Immutable container for metadata about the executing script.

    Attributes:
        path (Path): Absolute path to the script file.
        directory (Path): Directory containing the script.
        filename (str): Stem name of the script file, without extension.

    This class is used to group script-level metadata for logging,
    audit trails, and path resolution. It is frozen to ensure
    consistency and prevent accidental mutation.
    """
    path: Path
    directory: Path
    filename: str

@dataclass
class ConfigBundle:
    """
    Structured container for validated configuration parameters
    used in media processing workflows.

    Attributes:
        input_dirs (List[Path]): List of directories to scan for input media files.
        file_exts (List[str]): Allowed file extensions for input media (e.g., ['.mkv', '.mp4']).
        subtitle_langs (List[str]): Desired subtitle languages to retain (e.g., ['eng', 'spa']).
        output_ext (str): Target file extension for output media (e.g., '.mkv').
        mode (ConversionMode): Processing mode (e.g., REMUX, CONVERT) as defined by the enum.

    This class encapsulates config-derived values for traceability,
    validation, and centralized access throughout the pipeline.
    """
    input_dirs: List[Path]
    file_exts: List[str]
    subtitle_langs: List[str]
    output_ext: str
    mode: ConversionMode

class VideoProcessor:
    """
    Core class for scanning, processing, and converting video files.

    Responsibilities:
    - Load and validate configuration
    - Detect GPU availability
    - Filter subtitle streams
    - Remove title metadata
    - Build and execute FFmpeg commands
    - Log results to text and JSON
    - Handle CPU load and system readiness
    """
    def __init__(self, config_path: Path) -> None:
        """
        Initializes the VideoProcessor with configuration and logging setup.

        Args:
            config_path (Path): Path to the JSON configuration file.
        """
        self.meta = ScriptMeta(
            path=Path(__file__).resolve(),
            directory=Path(__file__).resolve().parent,
            filename=Path(__file__).resolve().stem
        )

        self.setup_logging()

        config: Dict[str, Union[str, List[str]]] = self.load_config(config_path)
        mode_str: str = config.get(ConfigKey.CONVERSION_MODE.value, "").lower()
        try:
            config[ConfigKey.CONVERSION_MODE.value] = ConversionMode(mode_str)
        except ValueError as exc:
            raise ValueError(
                f"Invalid conversion_mode: '{mode_str}'. Must be one of {[m.value for m in ConversionMode]}"
            ) from exc

        self.config: Dict[str, Union[str, List[str]]] = config
        self.config_bundle = ConfigBundle(
            input_dirs=[Path(d) for d in config.get(ConfigKey.INPUT_DIRECTORIES.value, [])],
            file_exts=config.get(ConfigKey.FILE_EXTENSIONS.value, []),
            subtitle_langs=config.get(ConfigKey.SUBTITLE_TRACKS.value, []),
            output_ext=config.get(ConfigKey.OUTPUT_EXTENSION.value, ".mkv"),
            mode=config.get(ConfigKey.CONVERSION_MODE.value, ConversionMode.REMUX)
        )
        self.use_gpu: bool = self.has_nvidia_gpu()
        self.remux_failures: List[str] = []
        self.reencode_failures: List[str] = []

    @staticmethod
    def load_config(config_path: str) -> Dict[str, Union[str, List[str]]]:
        """
        Loads and validates the configuration JSON file.

        Args:
            config_path (str): Path to the configuration file.

        Returns:
            Dict[str, Union[str, List[str]]]: Parsed and validated configuration dictionary.

        Raises:
            FileNotFoundError: If the config file is missing.
            ValueError: If the config is invalid or missing required keys.
            TypeError: If config values are of incorrect types.
        """
        try:
            with open(config_path, 'r', encoding='utf-8') as file:
                config = json.load(file)

            required_keys = {
                ConfigKey.INPUT_DIRECTORIES.value: list,
                ConfigKey.FILE_EXTENSIONS.value: list,
                ConfigKey.SUBTITLE_TRACKS.value: (str, list),
                ConfigKey.OUTPUT_EXTENSION.value: str,
                ConfigKey.CONVERSION_MODE.value: str
            }

            for key, expected_type in required_keys.items():
                if key not in config:
                    raise ValueError(f"Missing required config key: '{key}'")
                if not isinstance(config[key], expected_type):
                    raise TypeError(f"Config key '{key}' must be of type {expected_type}, got {type(config[key])}")

            if isinstance(config[ConfigKey.SUBTITLE_TRACKS.value], str):
                config[ConfigKey.SUBTITLE_TRACKS.value] = [lang.strip() for lang in config[ConfigKey.SUBTITLE_TRACKS.value].split(",") if lang.strip()]

            if config[ConfigKey.CONVERSION_MODE.value] not in {ConversionMode.REMUX.value, ConversionMode.REENCODE.value}:
                raise ValueError(f"{ConfigKey.CONVERSION_MODE.value} must be either '{ConversionMode.REMUX.value}' or '{ConversionMode.REENCODE.value}'")

            if not config[ConfigKey.OUTPUT_EXTENSION.value].startswith("."):
                raise ValueError("output_extension must start with a '.'")

            return config

        except FileNotFoundError as fnf_error:
            logging.error("Configuration file not found: %s", config_path)
            raise FileNotFoundError(f"Configuration file not found: {config_path}") from fnf_error

        except json.JSONDecodeError as json_error:
            logging.error("Error decoding JSON from the configuration file: %s", config_path)
            raise ValueError(f"Invalid JSON in config file: {config_path}") from json_error

        except (ValueError, TypeError) as validation_error:
            logging.error("Configuration validation failed: %s", str(validation_error))
            raise ValueError(f"Configuration validation error: {validation_error}") from validation_error

    def setup_logging(self) -> None:
        """
        Sets up rotating file and console logging for the script.
        """
        log_file = self.meta.directory / f"{self.meta.filename}.log"
        handler = RotatingFileHandler(log_file, maxBytes=10**6, backupCount=5)
        logging.basicConfig(
            handlers=[handler, logging.StreamHandler(sys.stdout)],
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )

    def has_nvidia_gpu(self) -> bool:
        """
        Detects if an NVIDIA GPU is available and CUDA is supported by FFmpeg.

        Returns:
            bool: True if GPU with CUDA support is available, False otherwise.
        """
        try:
            subprocess.run(["nvidia-smi"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            result = subprocess.run(["ffmpeg", "-hwaccels"], capture_output=True, text=True, check=False)
            return "cuda" in result.stdout.lower()
        except subprocess.SubprocessError as e:
            logging.warning("Subprocess error during GPU detection: %s", e)
            return False
        except OSError as e:
            logging.warning("OS error during GPU detection: %s", e)
            return False

    def get_matching_subtitle_maps(self, video_file: Path) -> List[str]:
        """
        Extracts subtitle stream indices matching configured languages.

        Args:
            video_file (Path): Path to the input video file.

        Returns:
            List[str]: List of FFmpeg stream map strings for matching subtitle tracks.
        """
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-select_streams", "s",
                    "-show_entries", "stream=index:stream_tags=language",
                    "-of", "csv=p=0", str(video_file)
                ],
                capture_output=True, text=True, check=False
            )

            allowed_langs = {lang.strip().lower() for lang in self.config_bundle.subtitle_langs}
            maps = []

            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split(",")
                if len(parts) == 2:
                    index, lang = parts
                    lang = lang.strip().lower()
                elif len(parts) == 1:
                    index = parts[0].strip()
                    lang = "und"  # ✅ Treat missing language as undetermined
                else:
                    continue  # Unexpected format

                if lang in allowed_langs:
                    maps.append(f"0:{index}")
                # else:
                #     print(f"Excluded subtitle stream {index} ({lang})")

            return maps

        except subprocess.SubprocessError as e:
            logging.warning("ffprobe subprocess error on %s: %s", video_file.name, e)
            return []
        except OSError as e:
            logging.warning("OS error while running ffprobe on %s: %s", video_file.name, e)
            return []

    def wait_for_cpu(self, threshold: int = 50) -> None:
        """
        Waits until CPU usage drops below a threshold before processing.

        Args:
            threshold (int): CPU usage percentage threshold.
        """
        while psutil.cpu_percent(interval=1) > threshold:
            logging.info("CPU busy, waiting...")
            time.sleep(5)

    def get_output_path(self, video_file: Path) -> Path:
        """
        Constructs the output path for the processed video file.

        Args:
            video_file (Path): Path to the input video file.

        Returns:
            Path: Path to the output file in the 'processed_files' subdirectory.
        """
        output_dir = video_file.parent / PROCESSED_FILES_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir / f"{video_file.stem}{self.config_bundle.output_ext}"

    def mkvmerge_remove_title_keep_english_subs(self, video_file: Path, output_path: Path) -> None:
        """
        Remove the title and keep specified subtitle tracks from an MKV file using mkvmerge.

        Parameters:
            video_file (Path): Input video file path.
            output_file (Path): Output video file path.
        """
        logging.info("Attempting %s mkvmerge fallback for %s...", ConversionMode.REMUX.value, video_file.name)

        subtitle_tracks = self.config_bundle.subtitle_langs
        if isinstance(subtitle_tracks, list):
            subtitle_tracks = ",".join(subtitle_tracks)

        command = [
            "mkvmerge", "-o", str(output_path), "--title", "",
            "--subtitle-tracks", subtitle_tracks, str(video_file)
        ]

        try:
            subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            # Validate output file
            if output_path.exists() and output_path.stat().st_size > 0:
                logging.info("Removed title and non-English subtitles from %s", video_file.name)
                logging.info("Saved as %s", output_path.name)
                self.write_or_append_to_json(f"Processed {video_file.name}", is_success=True)
            else:
                raise RuntimeError("mkvmerge produced empty or missing output file.")

        except (subprocess.CalledProcessError, RuntimeError) as subproc_error:
            stderr_output = subproc_error.stderr.strip() if hasattr(subproc_error, "stderr") and subproc_error.stderr else ""
            stdout_output = subproc_error.stdout.strip() if hasattr(subproc_error, "stdout") and subproc_error.stdout else ""

            if stderr_output:
                error_output = stderr_output
            elif stdout_output:
                error_output = f"(No stderr) stdout says: {stdout_output}"
            else:
                error_output = "No stderr or stdout captured. Silent failure."

            # error_output = subproc_error.stderr.strip() if subproc_error.stderr else "No stderr captured"
            logging.error("Error processing mkvmerge failed on %s", video_file.name)
            error_msg = f"Error processing mkvmerge failed on {video_file.name}: {error_output}"
            self.write_or_append_to_json(f"Command => {command}", is_success=False)
            self.write_or_append_to_json(error_msg, is_success=False)

    def build_subtitle_flags(self, subtitle_maps: List[str]) -> List[str]:
        """
        Builds FFmpeg flags for subtitle stream mapping.

        Args:
            subtitle_maps (List[str]): List of subtitle stream map strings.

        Returns:
            List[str]: FFmpeg command flags for subtitle mapping.
        """
        flags = []
        for map_str in subtitle_maps:
            flags += ["-map", map_str]
        if subtitle_maps:
            flags += ["-c:s", "copy"]
        else:
            logging.info("No matching subtitle streams found.")
        return flags

    def build_metadata_flags(self, title: str) -> List[str]:
        """
        Builds FFmpeg flags to remove or overwrite title metadata.

        Args:
            title (str): Original title (ignored in current implementation).

        Returns:
            List[str]: FFmpeg metadata flags.
        """
        # Remove title metadata by setting it to an empty string
        title = ''
        return ["-metadata", f"title={title}"]

    def _build_remux_codec_flags(self, mode_config: dict) -> List[str]:
        """
        Generates FFmpeg codec flags for remuxing mode based on configuration.

        This method constructs stream copy directives for video, audio, and subtitle streams,
        using values from the provided configuration. If no explicit codec is defined, it defaults
    to 'copy', preserving the original encoding without reprocessing.

        Args:
            mode_config (dict): Dictionary containing codec preferences for remuxing.

        Returns:
            List[str]: A list of FFmpeg flags for stream copy operations.
        """
        return [
            "-c:v", mode_config.get(ConfigKey.VIDEO_CODEC.value, "copy"),
            "-c:a", mode_config.get(ConfigKey.AUDIO_CODEC.value, "copy"),
            "-c:s", mode_config.get(ConfigKey.SUBTITLE_CODEC.value, "copy")
        ]

    def _build_reencode_codec_flags(self, video_file: Path, mode_config: dict) -> List[str]:
        """
        Constructs FFmpeg codec flags for reencoding mode based on configuration and input file characteristics.

        This method selects the appropriate video codec (GPU or CPU), preset, and quality parameters (CRF or bitrate)
        depending on the encoder type. It also appends audio and subtitle codec flags. If bitrate is not explicitly
        defined for GPU encoding, it is dynamically resolved based on the input video's height.

        Args:
            video_file (Path): Path to the input video file, used for bitrate resolution if needed.
            mode_config (dict): Dictionary containing codec configuration values such as video/audio/subtitle codec,
                                preset, CRF, and bitrate.

        Returns:
            List[str]: A list of FFmpeg command-line flags for codec configuration.

        Logs:
            Logs the selected video codec and dynamically resolved bitrate if applicable.
        """
        flags = []
        video_codec = EncoderType.HEVC_NVENC.value if self.use_gpu else mode_config.get(ConfigKey.VIDEO_CODEC.value, EncoderType.LIBX265.value)
        preset = self.resolve_preset(video_codec, mode_config.get(ConfigKey.PRESET.value, PresetLibxSpeed.MEDIUM.value))
        audio_codec = mode_config.get(ConfigKey.AUDIO_CODEC.value, "copy")
        subtitle_codec = mode_config.get(ConfigKey.SUBTITLE_CODEC.value, "copy")

        flags += ["-c:v", video_codec]

        logging.info("Using video codec for reencoding: %s", video_codec)

        if video_codec in [EncoderType.LIBX264.value, EncoderType.LIBX265.value]:
            crf = str(mode_config.get("crf", 18))
            flags += ["-crf", crf, "-preset", preset]
        elif video_codec == EncoderType.HEVC_NVENC.value:
            bitrate = mode_config.get("bitrate")
            if not bitrate:
                height = self.get_video_height(video_file)
                bitrate = self.resolve_bitrate(height)
                # try:
                #     height = self.get_video_height(video_file)
                #     bitrate = self.resolve_bitrate(height)
                # except (KeyError, IndexError, TypeError, ValueError, RuntimeError) as err:
                #     logging.error("Could not determine video height for %s: %s", video_file.name, err)
                #     self.write_or_append_to_json(f"Height detection failed for {video_file.name}: {err}", is_success=False)
                #     return []

            flags += ["-b:v", bitrate, "-preset", preset]

        flags += ["-c:a", audio_codec, "-c:s", subtitle_codec]
        return flags

    def build_ffmpeg_command(
        self,
        video_file: Path,
        output_file: Path,
        subtitle_maps: List[str],
        title: str
    ) -> List[str]:
        """
        Constructs the full FFmpeg command for processing a video file.

        Args:
            video_file (Path): Path to the input video file.
            output_file (Path): Path to the output video file.
            subtitle_maps (List[str]): Subtitle stream mappings.
            title (str): Title metadata to remove or overwrite.

        Returns:
            List[str]: FFmpeg command as a list of arguments.
        """
        cmd = ["ffmpeg", "-y"]

        # ✅ GPU acceleration
        if self.config_bundle.mode == ConversionMode.REENCODE:
            if self.use_gpu:
                logging.info("Using GPU acceleration for reencoding")
                cmd += ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
            else:
                logging.info("No GPU detected, using CPU for reencoding")
        elif self.config_bundle.mode == ConversionMode.REMUX:
            logging.info("Skipping GPU acceleration for remuxing (stream copy only)")

        cmd += ["-i", str(video_file)]

        # Preserve chapters
        cmd += ["-map_chapters", "0"]

        # Preserve metadata
        cmd += ["-map_metadata", "0"]

        # ✅ Stream mapping, with actual video stream (no cover art attachment as video stream included), and optional attachments as the script will error out if there are no attachments present
        cmd += ["-map", "0:V", "-map", "0:a", "-map", "0:t?"]
        for sub_map in subtitle_maps:
            cmd += ["-map", sub_map]

        mode_config = self.config.get(self.config_bundle.mode.value, {})

        # ✅ Codec settings
        if self.config_bundle.mode == ConversionMode.REMUX:
            cmd += self._build_remux_codec_flags(mode_config)

        elif self.config_bundle.mode == ConversionMode.REENCODE:
            pix_fmt = self.get_pixel_format(video_file)
            is_10bit = "10" in pix_fmt or "p010" in pix_fmt

            if is_10bit:
                pixel_format = PixelFormat.P010LE.value if self.use_gpu else PixelFormat.YUV420P10LE.value
                cmd += ["-pix_fmt", pixel_format]

            cmd += self._build_reencode_codec_flags(video_file, mode_config)

        else:
            raise ValueError(f"Unsupported conversion_mode: {self.config_bundle.mode}")

        # ✅ Metadata
        cmd += self.build_metadata_flags(title)
        cmd += [str(output_file)]

        return cmd

    def run_ffmpeg(self, cmd: List[str], video_file: Path, output_file: Path) -> None:
        """
        Executes the FFmpeg command and logs success or error.

        Args:
            cmd (List[str]): FFmpeg command arguments.
            video_file (Path): Input video file path.
            output_file (Path): Output video file path.
        """
        logging.info("Processing %s...", video_file.name)

        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            logging.info("Removed title and non-English subtitles from %s", video_file.name)
            logging.info("Saved as %s", output_file.name)
            self.write_or_append_to_json(f"Processed {video_file.name}", is_success=True)

        except subprocess.CalledProcessError as exc:
            error_output = exc.stderr.strip() if exc.stderr else "No stderr captured"
            logging.error("Error processing FFmpeg failed on %s", video_file.name)
            error_msg = f"Error processing FFmpeg failed on {video_file.name}: {error_output}"
            self.write_or_append_to_json(f"Command => {cmd}", is_success=False)
            self.write_or_append_to_json(error_msg, is_success=False)
            self.cleanup_failed_output(output_file)

            # 🔁 Fallback only if conversion_mode is remux
            if self.config_bundle.mode == ConversionMode.REMUX:
                self.mkvmerge_remove_title_keep_english_subs(video_file, output_file)

                # Check if mkvmerge succeeded by verifying output file
                if not output_file.exists() or output_file.stat().st_size == 0:
                    self.remux_failures.append(video_file.name)

            elif self.config_bundle.mode == ConversionMode.REENCODE:
                self.reencode_failures.append(video_file.name)

    def write_or_append_to_json(self, message: str, is_success: bool = True) -> None:
        """
        Writes a structured log entry to a JSON file for success or error.

        Args:
            message (str): Log message.
            is_success (bool): True for success log, False for error log.
        """
        file_suffix: str = "success" if is_success else "error"
        filename: str = f"{self.meta.filename}_{file_suffix}.json"
        filepath: Path = self.meta.directory / filename
        current_time: str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_entry: Dict[str, str] = {"timestamp": current_time, "message": str(message)}
        root_key: str = f"{self.meta.filename}_{file_suffix}"

        data: Dict[str, Any] = self._load_json_file(filepath)

        if root_key in data:
            data[root_key]["updated_date"] = current_time
            data[root_key]["messages"].append(new_entry)
            data[root_key]["count"] = len(data[root_key]["messages"])
        else:
            data[root_key] = {
                "created_date": current_time,
                "updated_date": current_time,
                "count": 1,
                "messages": [new_entry]
            }

        self._write_json_file(filepath, data)

    def _load_json_file(self, filepath: Path) -> Dict[str, Any]:
        """
        Loads JSON data from a file, returns empty dict if missing or corrupted.

        Args:
            filepath (Path): Path to the JSON file.

        Returns:
            Dict[str, Any]: Parsed JSON data or empty dictionary.
        """
        if not filepath.exists() or filepath.stat().st_size == 0:
            return {}

        try:
            with open(filepath, 'r', encoding='utf-8') as file:
                return json.load(file)
        except json.JSONDecodeError as exc:
            logging.warning("JSON file %s is corrupted. Starting with an empty file.", filepath.name)
            raise ValueError(f"Corrupted JSON file: {filepath.name}") from exc
        except OSError as exc:
            logging.error("Error reading JSON file %s: %s", filepath.name, exc)
            raise RuntimeError(f"Failed to read JSON file: {filepath.name}") from exc

    def _write_json_file(self, filepath: Path, data: Dict[str, Any]) -> None:
        """
        Writes JSON data to a file, overwriting existing content.

        Args:
            filepath (Path): Path to the JSON file.
            data (Dict[str, Any]): Data to write.
        """
        try:
            with open(filepath, 'w', encoding='utf-8') as file:
                json.dump(data, file, indent=4)
        except OSError as exc:
            logging.error("Failed to write to JSON file %s: %s", filepath.name, exc)
            raise RuntimeError(f"Failed to write to JSON file: {filepath.name}") from exc

    def process_video(self, video_file: Path) -> None:
        """
        Processes a single video file: waits for CPU, filters subtitles,
        builds FFmpeg command, and executes it.

        Args:
            video_file (Path): Path to the video file.
        """
        try:
            self.wait_for_cpu()
            subtitle_maps = self.get_matching_subtitle_maps(video_file)
            output_file = self.get_output_path(video_file)
            title = video_file.stem
            cmd = self.build_ffmpeg_command(video_file, output_file, subtitle_maps, title)
            self.run_ffmpeg(cmd, video_file, output_file)
        except (OSError, IOError, RuntimeError) as os_error:
            logging.error("Error processing file %s: %s", video_file.name, os_error)
            self.write_or_append_to_json(f"Error processing file {video_file.name}: {os_error}", is_success=False)

    def scan_and_process(self) -> None:
        """
        Scans configured directories for video files and processes each one.
        Logs execution time and handles errors gracefully.
        """
        start_time: datetime = datetime.now()
        logging.info("Script started at: %s", start_time.strftime('%Y-%m-%d %H:%M:%S'))

        if self.check_executables():
            if not self.config_bundle.input_dirs:
                logging.warning("No directories provided.")
            else:
                for input_dir in self.config_bundle.input_dirs:
                    if input_dir == Path('.'):
                        logging.warning("Current directory (.) specified. Skipping.")
                        continue

                    if not input_dir.exists():
                        logging.warning("Input directory does not exist: %s", input_dir)
                        continue

                    try:
                        logging.info("Working directory %s...", input_dir)

                        ext_files: List[Path] = [
                            file for ext in self.config_bundle.file_exts for file in input_dir.glob(f"*.{ext}")
                        ]

                        for video_file in ext_files:
                            self.process_video(video_file)

                    except (OSError, IOError) as os_error:
                        logging.error("Error processing directory %s: %s", input_dir, os_error)
                        self.write_or_append_to_json(
                            f"Error processing directory {input_dir}: {os_error}",
                            is_success=False
                        )
                # logging.info("Check success and or error file(s) if any were generated")
                self.summarize_failures()
        else:
            logging.error("Exiting script due to missing executables.")

        end_time: datetime = datetime.now()
        logging.info("Script finished at: %s", end_time.strftime('%Y-%m-%d %H:%M:%S'))
        execution_time: timedelta = end_time - start_time
        logging.info("Total execution time: %s", self.format_time_delta(execution_time))

    def check_executables(self) -> bool:
        """
        Checks if required tools (FFmpeg, FFprobe, mkvmerge) are available in system PATH.

        Returns:
            bool: True if all tools are available, False otherwise.
        """
        required_tools = {
            "ffmpeg": "FFmpeg",
            "ffprobe": "FFprobe",
            "mkvmerge": "MKVToolNix (mkvmerge)"
        }

        missing_tools = []
        for exe, label in required_tools.items():
            if shutil.which(exe) is None:
                logging.error("%s is not installed or not found in system PATH.", label)
                missing_tools.append(label)

        if missing_tools:
            error_msg = f"Missing required tools: {', '.join(missing_tools)}"
            self.write_or_append_to_json(error_msg, is_success=False)
            return False

        return True

    def get_video_height(self, input_path: Path) -> int:
        """
        Retrieves the height of the video stream using FFprobe.

        Args:
            input_path (Path): Path to the input video file.

        Returns:
            int: Height of the video stream in pixels.
        """
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=height",
            "-of", "json", input_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        try:
            data = json.loads(result.stdout)
            if "streams" not in data or not data["streams"]:
                self.reencode_failures.append(input_path.name)
                raise RuntimeError("No video stream found")
            height = data["streams"][0].get("height")
            if height is None:
                self.reencode_failures.append(input_path.name)
                raise RuntimeError("Height not found in video stream")
            return height
        except json.JSONDecodeError as exc:
            self.reencode_failures.append(input_path.name)
            raise RuntimeError(f"Invalid JSON from ffprobe: {exc}") from exc
        # data = json.loads(result.stdout)
        # return data["streams"][0]["height"]

    def get_pixel_format(self, input_path: Path) -> str:
        """
        Extracts the pixel format of the primary video stream from a media file using ffprobe.

        This method runs ffprobe as a subprocess to query the pixel format (e.g., 'yuv420p', 'yuv420p10le', 'p010le')
        of the first video stream in the specified media file. The result is used to determine bit depth and guide
        codec selection during reencoding.

        Args:
            input_path (Path): Path to the input media file.

        Returns:
            str: The pixel format string reported by ffprobe.

        Logs:
            Logs the detected pixel format for traceability and audit purposes.
        """
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=pix_fmt",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(input_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        pix_fmt = result.stdout.strip()
        # logging.info("Detected pixel format for %s: %s", input_path.name, pix_fmt)
        if pix_fmt:
            logging.info("Detected pixel format for %s: %s", input_path.name, pix_fmt)
        else:
            logging.error("No pixel format detected for %s", input_path.name)

        return pix_fmt

    def resolve_bitrate(self, height: int) -> str:
        """
        Resolves a recommended bitrate based on video height.

        Args:
            height (int): Height of the video in pixels.

        Returns:
            str: Bitrate string suitable for FFmpeg (e.g., '8M').
        """
        if height <= 720:
            return "5M"
        if height <= 1080:
            return "8M"
        if height <= 2160:
            return "15M"
        return "30M"

    def resolve_preset(self, codec: str, preset: str) -> str:
        """
        Resolves the appropriate preset for the given codec.

        Args:
            codec (str): Video codec name.
            preset (str): Desired preset name.

        Returns:
            str: Resolved preset string for FFmpeg.
        """
        nvenc_presets = {
            PresetLibxSpeed.ULTRAFAST.value: PresetNvencSpeed.P1.value,
            PresetLibxSpeed.VERYFAST.value: PresetNvencSpeed.P2.value,
            PresetLibxSpeed.FASTER.value: PresetNvencSpeed.P4.value,
            PresetLibxSpeed.FAST.value: PresetNvencSpeed.P3.value,
            PresetLibxSpeed.MEDIUM.value: PresetNvencSpeed.P4.value,
            PresetLibxSpeed.SLOW.value: PresetNvencSpeed.P5.value,
            PresetLibxSpeed.SLOWER.value: PresetNvencSpeed.P6.value,
            PresetLibxSpeed.VERYSLOW.value: PresetNvencSpeed.P7.value
        }
        if codec == EncoderType.HEVC_NVENC.value:
            return nvenc_presets.get(preset, PresetLibxSpeed.FASTER.value)
        return preset  # libx264 or others

    def summarize_failures(self) -> None:
        """
        Summarizes media files that failed processing and logs results.

        This method reports:
        - Remux failures: files that failed both FFmpeg and mkvmerge
        - Reencode failures: files that failed FFmpeg reencode (no fallback)

        It logs the failures to console and appends summary entries to the audit JSON.
        """
        if self.remux_failures and self.config_bundle.mode == ConversionMode.REMUX:
            msg = ', '.join(self.remux_failures)
            logging.error("Remux failures (FFmpeg + mkvmerge) (count => %s):", len(self.remux_failures))
            for name in self.remux_failures:
                logging.error(" * %s", name)

        if self.reencode_failures and self.config_bundle.mode == ConversionMode.REENCODE:
            msg = ', '.join(self.reencode_failures)
            logging.error("Reencode failures (count => %s):", len(self.reencode_failures))
            for name in self.reencode_failures:
                logging.error(" * %s", name)

        if not self.remux_failures and self.config_bundle.mode == ConversionMode.REMUX:
            msg = f"All {ConversionMode.REMUX.value} media files processed successfully."
            logging.info(msg)

        if not self.reencode_failures and self.config_bundle.mode == ConversionMode.REENCODE:
            msg = f"All {ConversionMode.REENCODE.value} media files processed successfully."
            logging.info(msg)

    def cleanup_failed_output(self, output_path: Path) -> None:
        """
        Deletes a failed output media file and its parent folder if empty.

        This function is used after a failed FFmpeg or mkvmerge operation to:
        - Remove the output file if it exists
        - Remove the parent folder if it becomes empty after file deletion

        Parameters:
            output_path (Path): The full path to the failed output media file.
        """
        if output_path.exists():
            try:
                output_path.unlink()
                logging.info("Deleted failed output file: %s", output_path.name)
            except (OSError, PermissionError) as file_error:
                logging.warning("Could not delete file %s: %s", output_path.name, file_error)

        parent = output_path.parent
        if parent.exists() and not any(parent.iterdir()):
            try:
                parent.rmdir()
                logging.info("Deleted empty folder: %s", parent)
            except (OSError, PermissionError) as folder_error:
                logging.warning("Could not delete folder %s: %s", parent, folder_error)

    @staticmethod
    def format_time_delta(td: timedelta) -> str:
        """
        Formats a timedelta object into a human-readable string.

        Args:
            td (timedelta): Time delta to format.

        Returns:
            str: Human-readable duration string.
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

if __name__ == "__main__":
    try:
        processor = VideoProcessor(Path(CONFIG_PATH))
        processor.scan_and_process()
    except (ValueError, TypeError, FileNotFoundError, json.JSONDecodeError, RuntimeError) as exc:
        logging.critical("An error occurred during execution: [%s] %s", type(exc).__name__, exc)
