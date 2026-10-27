import yt_dlp
import asyncio
import logging
import os
import subprocess
import tempfile
from app.vision import ask_vision

logger = logging.getLogger(__name__)


def extract_frames(video_url: str, num_frames: int = 3) -> list:
    """Download a video at lowest quality and return a few evenly spaced frames as JPEG bytes."""
    frames = []
    with tempfile.TemporaryDirectory() as tmpdir:
        ydl_opts = {
            "format": "worst[ext=mp4]/worst",  # lowest quality = fastest download
            "outtmpl": os.path.join(tmpdir, "video.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 10,
            "max_filesize": 50 * 1024 * 1024,  # skip huge videos instead of downloading forever
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=True)

            video_file = next(
                (os.path.join(tmpdir, f) for f in os.listdir(tmpdir) if f.startswith("video")),
                None
            )
            if not video_file:
                return []

            duration = info.get("duration") or 10
            for i in range(num_frames):
                timestamp = duration * (i + 1) / (num_frames + 1)
                frame_path = os.path.join(tmpdir, f"frame_{i}.jpg")
                cmd = [
                    "ffmpeg", "-ss", f"{timestamp:.2f}", "-i", video_file,
                    "-frames:v", "1", "-q:v", "2", frame_path, "-y", "-loglevel", "quiet"
                ]
                result = subprocess.run(cmd, capture_output=True, timeout=15)
                if result.returncode == 0 and os.path.exists(frame_path):
                    with open(frame_path, "rb") as f:
                        frames.append(f.read())

        except Exception:
            logger.exception("Frame extraction failed for %s", video_url)

    return frames


def identify_movie_from_frames(frames: list) -> str:
    """Send frames to vision AI and identify movie/show."""
    if not frames:
        return "UNKNOWN"
    return ask_vision(
        frames,
        "These are frames from a video. Identify the movie or TV series shown. Look for visual cues like actors, scenes, settings, text overlays, or any recognizable content. Reply with ONLY the movie/series name. If you cannot identify it, reply UNKNOWN."
    )


async def extract_frames_with_timeout(video_url: str, num_frames: int = 3, timeout: int = 20) -> list:
    """Run extract_frames off the event loop and stop waiting after `timeout` seconds."""
    # ponytail: threads can't be killed; a timed-out download finishes in the background,
    # bounded by socket_timeout and max_filesize
    try:
        return await asyncio.wait_for(asyncio.to_thread(extract_frames, video_url, num_frames), timeout)
    except asyncio.TimeoutError:
        logger.warning("Frame extraction timed out after %ss: %s", timeout, video_url)
        return []
