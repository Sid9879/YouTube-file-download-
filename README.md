# Authorized Audio-to-MP3 (Render)

A small browser-based service that converts audio from YouTube URLs to MP3 **only for content you own or are authorized to download**.

It does not bypass DRM, private access controls, or paid restrictions. Use must comply with applicable law and the source platform's terms.

## Deploy to Render

1. Create a GitHub repository and upload all files in this project.
2. In Render, choose **New + → Blueprint** and connect the repository.
3. Render reads `render.yaml` and builds the Docker image.
4. Open the service URL after deployment.

You can also create a Render Web Service manually and choose **Docker** as the runtime.

## Use in browser

Open the service homepage, paste a supported YouTube URL, check the authorization box, and press **Download MP3**. The browser receives the MP3 as an attachment.

Direct endpoint format:

`https://YOUR-SERVICE.onrender.com/download?url=ENCODED_VIDEO_URL&authorized=true`

URL-encode the video URL when constructing the query string.

## Limits and operational notes

- Default maximum source duration: 2 hours (`MAX_DURATION_SECONDS`).
- Default maximum converted file size: 300 MB (`MAX_FILE_MB`).
- Two simultaneous conversions per running instance; further requests receive HTTP 429.
- Files are stored in a temporary directory and deleted after the response.
- This uses local temporary storage, not persistent storage.
- A Render instance restart or request timeout can interrupt a long conversion.
- For a public deployment, add authentication, stronger distributed rate limiting, usage quotas, and monitoring. Do not expose an unrestricted public downloader.
- YouTube extraction behavior can change; keep `yt-dlp` updated.

## Local run

Requires Python 3.12+, FFmpeg, and Deno.

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`.
