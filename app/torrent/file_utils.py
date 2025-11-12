"""Utility functions for torrent file handling."""

import re


def is_video_file(filename: str) -> bool:
    """Check if a file is a video file based on extension.

    Args:
        filename: Filename to check

    Returns:
        True if file has video extension
    """
    video_extensions = {
        ".mp4",
        ".mkv",
        ".avi",
        ".mov",
        ".wmv",
        ".flv",
        ".m4v",
        ".mpg",
        ".mpeg",
        ".webm",
        ".ts",
    }

    filename_lower = filename.lower()
    return any(filename_lower.endswith(ext) for ext in video_extensions)


def parse_episode_info(filename: str) -> tuple[str, str] | None:
    """Parse season and episode information from filename.

    Args:
        filename: Filename to parse

    Returns:
        Dictionary with 'season' and 'episode' as strings, or None if not found

    Examples:
        "Show.S01E05.mkv" -> {"season": "1", "episode": "5"}
        "Show.1x03.mp4" -> {"season": "1", "episode": "3"}
        "Show.Season.2.Episode.4.avi" -> {"season": "2", "episode": "4"}
    """
    # Remove file extension for cleaner parsing
    name = filename.rsplit(".", 1)[0]

    # Pattern 1: S01E02, s01e02, S1E2
    pattern1 = re.search(r"[Ss](\d+)[Ee](\d+)", name)
    if pattern1:
        return (str(pattern1.group(1)), str(pattern1.group(2)))

    # Pattern 2: 1x02, 1X02
    pattern2 = re.search(r"(\d+)[xX](\d+)", name)
    if pattern2:
        return (str(pattern2.group(1)), str(pattern2.group(2)))

    # Pattern 3: Season 1 Episode 2, season 1 episode 2
    pattern3 = re.search(r"[Ss]eason\s*(\d+).*[Ee]pisode\s*(\d+)", name, re.IGNORECASE)
    if pattern3:
        return (str(pattern3.group(1)), str(pattern3.group(2)))

    return None


def get_largest_file(files: list[dict]) -> dict | None:
    """Get the largest file from a list of files.

    Args:
        files: List of file dictionaries with 'size' key

    Returns:
        The file dictionary with the largest size, or None if empty
    """
    if not files:
        return None

    return max(files, key=lambda f: f.get("size", 0))


def format_file_size(bytes: int) -> str:
    """Format file size in bytes to human-readable format.

    Args:
        bytes: Size in bytes

    Returns:
        Formatted string (e.g., "1.5 GB", "700 MB")
    """
    if bytes < 1024:
        return f"{bytes} B"
    elif bytes < 1024**2:
        return f"{bytes / 1024:.1f} KB"
    elif bytes < 1024**3:
        return f"{bytes / (1024**2):.1f} MB"
    elif bytes < 1024**4:
        return f"{bytes / (1024**3):.2f} GB"
    else:
        return f"{bytes / (1024**4):.2f} TB"
