import os
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from starlette.background import BackgroundTask

app = FastAPI(title="Authorized Media Audio Converter")

# Basic in-process protections. For a public production service, add authentication
# and a persistent rate limiter appropriate to your deployment.
_download_lock = threading.BoundedSemaphore(value=2)
MAX_DURATION_SECONDS = int(os.getenv("MAX_DURATION_SECONDS", "7200"))
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "300"))

PAGE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Audio to MP3</title>
  <style>
    *{box-sizing:border-box} body{font-family:system-ui,Arial;background:#f3f5f9;
    margin:0;min-height:100vh;display:grid;place-items:center;color:#182033}
    main{background:white;width:min(92%,560px);padding:30px;border-radius:18px;
    box-shadow:0 12px 40px #18203318}
    h1{margin-top:0} input[type=url]{width:100%;padding:14px;border:1px solid #ccd2df;
    border-radius:9px;font-size:16px;margin:12px 0}
    button{width:100%;padding:14px;border:0;border-radius:9px;background:#2457d6;
    color:white;font-size:16px;font-weight:600;cursor:pointer}
    button:disabled{opacity:.6;cursor:wait}
    label{display:flex;gap:10px;align-items:flex-start;font-size:14px;line-height:1.45;
    margin:12px 0 18px} .muted{color:#667085;font-size:13px;line-height:1.5}
    #status{margin-top:16px;white-space:pre-wrap;font-size:14px}
  </style>
</head>
<body>
<main>
  <h1>Download audio as MP3</h1>
  <p class="muted">Use only with media you own or have explicit permission to download.
  This service does not bypass DRM, private access controls, or paid restrictions.</p>
  <form id="form">
    <input id="url" type="url" placeholder="Paste a supported YouTube URL" required>
    <label><input id="authorized" type="checkbox" required>
      I own this content or have permission to download and convert it.</label>
    <button id="submit" type="submit">Download MP3</button>
  </form>
  <div id="status" role="status"></div>
  <p class="muted">The MP3 is generated temporarily and deleted after the response.</p>
</main>
<script>
const form=document.getElementById('form');
const statusBox=document.getElementById('status');
const button=document.getElementById('submit');
form.addEventListener('submit', async (e)=>{
  e.preventDefault();
  const url=document.getElementById('url').value.trim();
  if(!document.getElementById('authorized').checked) return;
  button.disabled=true; statusBox.textContent='Preparing MP3… please keep this page open.';
  try {
    const response=await fetch('/download?url='+encodeURIComponent(url)+'&authorized=true');
    if(!response.ok){
      let msg='Download failed.';
      try { const data=await response.json(); msg=data.detail||msg; } catch {}
      throw new Error(msg);
    }
    const blob=await response.blob();
    const disposition=response.headers.get('content-disposition')||'';
    const match=disposition.match(/filename="?([^";]+)"?/i);
    const filename=match?match[1]:'audio.mp3';
    const objectUrl=URL.createObjectURL(blob);
    const a=document.createElement('a'); a.href=objectUrl; a.download=filename;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(objectUrl);
    statusBox.textContent='MP3 download started.';
  } catch(err) { statusBox.textContent=err.message; }
  finally { button.disabled=false; }
});
</script>
</body>
</html>
"""

def validate_video_url(raw_url: str) -> str:
    try:
        parsed = urlparse(raw_url.strip())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid URL.")
    host = (parsed.hostname or "").lower().rstrip(".")
    allowed = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com"}
    if parsed.scheme not in {"http", "https"} or host not in allowed:
        raise HTTPException(status_code=400, detail="Only standard YouTube video URLs are supported.")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="URLs containing credentials are not accepted.")
    return raw_url.strip()

def cleanup(path: str):
    shutil.rmtree(path, ignore_errors=True)

@app.get("/", response_class=HTMLResponse)
def home():
    return PAGE

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/download")
def download(
    url: str = Query(..., min_length=10, max_length=2048),
    authorized: bool = Query(False),
):
    if not authorized:
        raise HTTPException(status_code=403, detail="Confirm that you own or are authorized to download this content.")
    url = validate_video_url(url)

    if not _download_lock.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="The server is busy. Please try again shortly.")

    workdir = tempfile.mkdtemp(prefix="audio-job-")
    try:
        output_template = str(Path(workdir) / "%(title).150B.%(ext)s")
        opts = {
            "format": "bestaudio/best",
            "outtmpl": output_template,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "restrictfilenames": True,
            "max_filesize": MAX_FILE_MB * 1024 * 1024,
            "match_filter": yt_dlp.utils.match_filter_func(
                f"duration <= {MAX_DURATION_SECONDS}"
            ),
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }

        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

        mp3_files = list(Path(workdir).glob("*.mp3"))
        if not mp3_files:
            raise RuntimeError("MP3 conversion did not produce an output file.")
        output_file = mp3_files[0]
        if output_file.stat().st_size > MAX_FILE_MB * 1024 * 1024:
            raise HTTPException(status_code=413, detail="The converted audio exceeds the configured size limit.")

        return FileResponse(
            path=str(output_file),
            media_type="audio/mpeg",
            filename=output_file.name,
            background=BackgroundTask(cleanup, workdir),
        )
    except HTTPException:
        cleanup(workdir)
        raise
    except Exception as exc:
        cleanup(workdir)
        # Avoid returning internal server paths or stack traces to clients.
        message = str(exc)
        if "ffmpeg" in message.lower():
            detail = "Audio conversion failed. Check that FFmpeg is installed in the Render container."
        elif "private" in message.lower() or "unavailable" in message.lower():
            detail = "This video is unavailable or cannot be accessed by the server."
        else:
            detail = "Unable to download or convert this video. Check the URL and try again."
        raise HTTPException(status_code=400, detail=detail)
    finally:
        _download_lock.release()
