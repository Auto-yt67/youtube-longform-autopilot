"""
YouTube upload with thumbnail, optimal scheduling, and full metadata.
"""

import os
import json
import pickle
import subprocess
import sys
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.force-ssl"]
TOKEN_FILE = "token.pickle"
CLIENT_SECRETS_FILE = os.environ.get("YOUTUBE_CLIENT_SECRETS", "client_secrets.json")

def ensure_google_libs():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install",
            "google-auth-oauthlib", "google-api-python-client", "-q"])

def get_authenticated_service():
    ensure_google_libs()
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    credentials = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            credentials = pickle.load(f)

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            if not os.path.exists(CLIENT_SECRETS_FILE):
                raise FileNotFoundError(f"client_secrets.json not found.")
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
            credentials = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(credentials, f)

    return build("youtube", "v3", credentials=credentials)

def upload_thumbnail(youtube, video_id: str, thumbnail_path: str):
    """Upload thumbnail to YouTube video."""
    try:
        from googleapiclient.http import MediaFileUpload
        media = MediaFileUpload(thumbnail_path, mimetype="image/png")
        youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
        print(f"  ✓ Thumbnail uploaded")
    except Exception as e:
        print(f"  ✗ Thumbnail upload failed: {e}")

def upload_to_youtube(
    video_path: str,
    title: str,
    description: str,
    tags: list = None,
    thumbnail_path: str = None,
    publish_settings: dict = None,
    category_id: str = "2",  # 2 = Autos & Vehicles
) -> str:
    from googleapiclient.http import MediaFileUpload

    youtube = get_authenticated_service()

    # Default: post publicly now
    if publish_settings is None:
        publish_settings = {"privacyStatus": "public", "publishAt": None}

    status_body = {"privacyStatus": publish_settings["privacyStatus"],
                   "selfDeclaredMadeForKids": False}
    
    if publish_settings.get("publishAt"):
        status_body["publishAt"] = publish_settings["publishAt"]

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": (tags or [])[:500],
            "categoryId": category_id,
            "defaultLanguage": "en",
        },
        "status": status_body,
    }

    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True,
                            chunksize=1024 * 1024 * 10)

    request = youtube.videos().insert(part=",".join(body.keys()), body=body,
                                       media_body=media)

    print("  Uploading video...")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  Upload: {int(status.progress() * 100)}%", end="\r")

    video_id = response["id"]
    print(f"\n  ✓ Video uploaded: https://www.youtube.com/watch?v={video_id}")

    # Upload thumbnail
    if thumbnail_path and os.path.exists(thumbnail_path):
        upload_thumbnail(youtube, video_id, thumbnail_path)

    return f"https://www.youtube.com/watch?v={video_id}"


if __name__ == "__main__":
    # Auth test only
    youtube = get_authenticated_service()
    print("✓ YouTube auth successful")
