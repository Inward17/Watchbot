import yt_dlp
import concurrent.futures
import os
import base64
import tempfile
import requests
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")

def extract_frames(video_url: str, num_frames: int = 3) -> list:
    """Download a few frames from a YouTube video and return as bytes list."""
    frames = []
    with tempfile.TemporaryDirectory() as tmpdir:
        ydl_opts = {
            "format": "worst[ext=mp4]/worst",  # lowest quality = fastest download
            "outtmpl": os.path.join(tmpdir, "video.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])

            # Find downloaded file
            video_file = next(
                (os.path.join(tmpdir, f) for f in os.listdir(tmpdir) if f.startswith("video")),
                None
            )
            if not video_file:
                return []

            # Extract frames using PIL + seeking
            from PIL import Image
            import subprocess

            # Use ffmpeg via yt-dlp's bundled tools to extract frames
            file_size = os.path.getsize(video_file)
            duration_guess = max(5, file_size // 100000)  # rough estimate

            for i in range(num_frames):
                timestamp = (i + 1) * duration_guess // (num_frames + 1)
                frame_path = os.path.join(tmpdir, f"frame_{i}.jpg")
                cmd = [
                    "ffmpeg", "-ss", str(timestamp), "-i", video_file,
                    "-frames:v", "1", "-q:v", "2", frame_path, "-y", "-loglevel", "quiet"
                ]
                result = subprocess.run(cmd, capture_output=True)
                if result.returncode == 0 and os.path.exists(frame_path):
                    with open(frame_path, "rb") as f:
                        frames.append(f.read())

        except Exception as e:
            print(f"Frame extraction error: {e}")

    return frames

def identify_movie_from_frames(frames: list) -> str:
    """Send frames to vision AI and identify movie/show."""
    if not frames:
        return "UNKNOWN"

    content = []
    for frame_bytes in frames:
        img_data = base64.b64encode(frame_bytes).decode()
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{img_data}"}
        })

    content.append({
        "type": "text",
        "text": "These are frames from a video. Identify the movie or TV series shown. Look for visual cues like actors, scenes, settings, text overlays, or any recognizable content. Reply with ONLY the movie/series name. If you cannot identify it, reply UNKNOWN."
    })

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "google/gemma-3-12b-it:free",
                "messages": [{"role": "user", "content": content}]
            },
            timeout=30
        )
        return response.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"Vision API error: {e}")
        return "UNKNOWN"


def extract_frames_with_timeout(video_url: str, num_frames: int = 3, timeout: int = 20) -> list:
    """Run extract_frames with a hard timeout to prevent bot hangs on long videos."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(extract_frames, video_url, num_frames)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            print(f"Frame extraction timed out after {timeout}s")
            return []
        except Exception as e:
            print(f"Frame extraction error: {e}")
            return []