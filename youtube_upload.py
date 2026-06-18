"""
YouTube upload using YouTube Data API v3
Handles OAuth2 flow and video upload with metadata
"""

import os
import json
import pickle
import subprocess
import sys
from pathlib import Path


SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_FILE = "token.pickle"
CLIENT_SECRETS_FILE = os.environ.get("YOUTUBE_CLIENT_SECRETS", "client_secrets.json")


def ensure_google_libs():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        print("  Installing Google API libraries...")
        subprocess.check_call([
            sys.executable, "-m", "pip", "install",
            "google-auth-oauthlib", "google-api-python-client", "-q"
        ])


def get_authenticated_service():
    """Get authenticated YouTube service, using cached token if available."""
    ensure_google_libs()
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    import google.oauth2.credentials

    credentials = None

    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            credentials = pickle.load(f)

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            if not os.path.exists(CLIENT_SECRETS_FILE):
                raise FileNotFoundError(
                    f"YouTube client secrets not found at '{CLIENT_SECRETS_FILE}'. "
                    "See README.md for setup instructions."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRETS_FILE, SCOPES
            )
            credentials = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(credentials, f)

    return build("youtube", "v3", credentials=credentials)


def upload_to_youtube(
    video_path: str,
    title: str,
    description: str,
    tags: list = None,
    category_id: str = "27",  # 27 = Education
    privacy: str = "public",
) -> str:
    """
    Upload video to YouTube.
    
    Returns the video URL.
    """
    from googleapiclient.http import MediaFileUpload
    import googleapiclient.errors

    youtube = get_authenticated_service()

    body = {
        "snippet": {
            "title": title[:100],  # YouTube title limit
            "description": description[:5000],
            "tags": (tags or [])[:500],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=1024 * 1024 * 10,  # 10MB chunks
    )

    request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=media,
    )

    print("  Uploading (this may take a few minutes)...")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            print(f"  Upload progress: {pct}%", end="\r")

    video_id = response["id"]
    url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"\n  ✓ Uploaded: {url}")
    return url


if __name__ == "__main__":
    import sys
    video_path = sys.argv[1] if len(sys.argv) > 1 else "output/final_video.mp4"
    url = upload_to_youtube(
        video_path=video_path,
        title="Test Upload",
        description="Test description",
        tags=["cars", "education"],
        privacy="private",  # safe default for testing
    )
    print(url)
