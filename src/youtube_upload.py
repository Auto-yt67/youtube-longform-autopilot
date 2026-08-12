"""
YouTube upload with thumbnail, optimal scheduling, and full metadata.

Adapted for CI/automated runs: reads client_secrets.json and the cached
OAuth token from environment variables (set as GitHub Actions secrets)
instead of interactively prompting for login every run.

IMPORTANT - one-time manual step required (this cannot be automated,
since Google's OAuth consent screen needs a human to click "Allow"):
  1. Run this script locally once:
       export YOUTUBE_CLIENT_SECRETS_PATH=../client_secrets.json
       python youtube_upload.py --auth-only
  2. It opens a browser, you log in and approve access
  3. It writes token.pickle locally
  4. base64-encode token.pickle and store it as the GH secret YOUTUBE_TOKEN_PICKLE_B64
  5. Store your client_secrets.json content (raw JSON or base64, either works)
     as the GH secret YOUTUBE_CLIENT_SECRETS
After that, the pipeline refreshes the token automatically forever (Google
refresh tokens don't expire unless revoked).

Note: YOUTUBE_CLIENT_SECRETS_PATH (local override, points to a file) and
YOUTUBE_CLIENT_SECRETS (CI secret, holds the file's actual JSON content) are
intentionally different variable names - they must never collide, or the CI
secret's JSON content gets misinterpreted as a filesystem path.
"""

import os
import json
import base64
import pickle
import re
import subprocess
import sys
import argparse
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.force-ssl"]
TOKEN_FILE = Path("token.pickle")
# Fixed local path where client secrets always end up on disk, whether they
# arrived as a CI secret (materialized below) or were placed here manually.
# YOUTUBE_CLIENT_SECRETS_PATH is a separate, distinctly-named override for
# local runs only - it must never collide with YOUTUBE_CLIENT_SECRETS, which
# in CI holds the actual secret *content* (raw JSON), not a path.
CLIENT_SECRETS_FILE = Path(os.environ.get("YOUTUBE_CLIENT_SECRETS_PATH", "client_secrets.json"))


def _clean_base64(raw: str) -> str:
    """
    Strip anything that isn't a valid base64 character. Copy-pasting a long
    base64 string through different clipboard tools/editors can introduce
    stray invisible characters (BOMs, smart-formatting artifacts) that
    base64.b64decode rejects outright since it requires pure ASCII. This
    keeps only the actual base64 alphabet, so a single injected character
    doesn't take down the whole decode.
    """
    return re.sub(r"[^A-Za-z0-9+/=]", "", raw)


def _maybe_b64_decode(raw: str) -> bytes:
    """Accept either raw JSON text or base64-encoded content, whichever was stored."""
    raw = raw.strip()
    if raw.startswith("{"):
        return raw.encode("utf-8")
    try:
        return base64.b64decode(_clean_base64(raw))
    except Exception:
        return raw.encode("utf-8")


def _materialize_ci_secrets():
    """In CI, secrets arrive as env vars - write them to disk once.
    Handles both raw-JSON and base64-encoded secret values."""
    client_secrets_raw = os.environ.get("YOUTUBE_CLIENT_SECRETS") or os.environ.get("YOUTUBE_CLIENT_SECRETS_B64")
    if client_secrets_raw and not CLIENT_SECRETS_FILE.exists():
        CLIENT_SECRETS_FILE.write_bytes(_maybe_b64_decode(client_secrets_raw))

    token_raw = os.environ.get("YOUTUBE_TOKEN_PICKLE_B64") or os.environ.get("YOUTUBE_TOKEN_B64")
    if token_raw and not TOKEN_FILE.exists():
        TOKEN_FILE.write_bytes(base64.b64decode(_clean_base64(token_raw.strip())))


def ensure_google_libs():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow  # noqa
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install",
            "google-auth-oauthlib", "google-api-python-client", "-q"])


def get_authenticated_service():
    ensure_google_libs()
    _materialize_ci_secrets()
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    credentials = None
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, "rb") as f:
            credentials = pickle.load(f)

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            if not CLIENT_SECRETS_FILE.exists():
                raise FileNotFoundError("client_secrets.json not found - see module docstring.")
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS_FILE), SCOPES)
            credentials = flow.run_local_server(port=0)  # only works when run locally by a human
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(credentials, f)

    return build("youtube", "v3", credentials=credentials)


def upload_thumbnail(youtube, video_id: str, thumbnail_path: str):
    try:
        from googleapiclient.http import MediaFileUpload
        media = MediaFileUpload(thumbnail_path, mimetype="image/png")
        youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
        print("  \u2713 Thumbnail uploaded")
    except Exception as e:
        print(f"  \u2717 Thumbnail upload failed: {e}")


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
    request = youtube.videos().insert(part=",".join(body.keys()), body=body, media_body=media)

    print("  Uploading video...")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  Upload: {int(status.progress() * 100)}%", end="\r")

    video_id = response["id"]
    print(f"\n  \u2713 Video uploaded: https://www.youtube.com/watch?v={video_id}")

    if thumbnail_path and os.path.exists(thumbnail_path):
        upload_thumbnail(youtube, video_id, thumbnail_path)

    return f"https://www.youtube.com/watch?v={video_id}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--auth-only", action="store_true",
                        help="Run the one-time interactive login and write token.pickle")
    args = parser.parse_args()

    youtube = get_authenticated_service()
    print("\u2713 YouTube auth successful")
    if args.auth_only:
        print(f"token.pickle written. base64-encode it for the YOUTUBE_TOKEN_B64 secret:")
        print(f"  base64 -w0 {TOKEN_FILE} > token_b64.txt")
