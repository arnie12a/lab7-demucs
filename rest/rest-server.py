
import os
import re
import io
import json
import time
import base64
import binascii
import hashlib
import threading
from pathlib import Path

import boto3
import redis

from flask import Flask, request, jsonify, send_file
from botocore.config import Config
from botocore.exceptions import ClientError


# ==========================================
# 1. FLASK CONFIGURATION
# ==========================================

app = Flask(__name__)

app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

S3_ENDPOINT = os.getenv(
    "S3_ENDPOINT",
    "http://localhost:9000"
)

S3_ACCESS_KEY = os.environ["S3_ACCESS_KEY"]
S3_SECRET_KEY = os.environ["S3_SECRET_KEY"]

INPUT_BUCKET = os.getenv("INPUT_BUCKET", "queue")
OUTPUT_BUCKET = os.getenv("OUTPUT_BUCKET", "output")

QUEUE_NAME = "toWorkers"

# Local output directory
OUTPUT_DIR = Path(
    os.getenv(
        "LOCAL_OUTPUT_DIR",
        str(Path.home() / "lab7-demucs" / "output")
    )
)

TRACK_NAMES = ["bass", "drums", "vocals", "other"]

# Maximum time to wait for Demucs
MAX_WAIT_SECONDS = 600
POLL_INTERVAL = 5


# ==========================================
# 2. REDIS CONNECTION
# ==========================================

redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=0,
    decode_responses=True,
    socket_connect_timeout=10,
    socket_timeout=10
)


# ==========================================
# 3. RUSTFS CONNECTION
# ==========================================

s3 = boto3.client(
    "s3",
    endpoint_url=S3_ENDPOINT,
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
    region_name="us-east-1",
    config=Config(
        s3={"addressing_style": "path"}
    )
)


# ==========================================
# 4. TRACK HELPERS
# ==========================================

TRACKS = {
    "bass.mp3": "bass",
    "base.mp3": "bass",
    "drums.mp3": "drums",
    "vocals.mp3": "vocals",
    "other.mp3": "other"
}


def get_track_key(songhash, track):
    """
    Convert REST track name to RustFS object key.
    """

    if not re.fullmatch(r"[a-f0-9]{64}", songhash):
        return None

    part = TRACKS.get(track)

    if part is None:
        return None

    return f"{songhash}-{part}.mp3"


def get_output_folder(songhash, filename=None):
    """
    Choose a safe local output directory.
    """

    if filename:
        folder_name = Path(filename).stem

        if not re.fullmatch(
            r"[A-Za-z0-9_-]{1,100}",
            folder_name
        ):
            folder_name = songhash
    else:
        folder_name = songhash

    return OUTPUT_DIR / folder_name


# ==========================================
# 5. AUTOMATIC TRACK DOWNLOADING
# ==========================================

def save_completed_tracks(songhash, filename=None):
    """
    Wait for Demucs output in RustFS and
    save all four tracks to the local folder.
    """

    output_folder = get_output_folder(
        songhash,
        filename
    )

    output_folder.mkdir(
        parents=True,
        exist_ok=True
    )

    print(
        f"Waiting for Demucs output: {songhash}",
        flush=True
    )

    deadline = time.monotonic() + MAX_WAIT_SECONDS

    remaining = set(TRACK_NAMES)

    while remaining and time.monotonic() < deadline:

        for track in list(remaining):

            object_name = f"{songhash}-{track}.mp3"

            destination = (
                output_folder / f"{track}.mp3"
            )

            temp_file = (
                output_folder / f"{track}.mp3.part"
            )

            try:
                # Check if worker has uploaded the track
                s3.head_object(
                    Bucket=OUTPUT_BUCKET,
                    Key=object_name
                )

                # Download the track
                s3.download_file(
                    OUTPUT_BUCKET,
                    object_name,
                    str(temp_file)
                )

                # Rename after complete download
                temp_file.replace(destination)

                print(
                    f"Saved: {destination}",
                    flush=True
                )

                remaining.remove(track)

            except ClientError as error:

                code = error.response["Error"]["Code"]

                if code in (
                    "404",
                    "NoSuchKey",
                    "NotFound"
                ):
                    continue

                print(
                    f"RustFS error: {error}",
                    flush=True
                )

            except Exception as error:
                print(
                    f"Download error for {track}: {error}",
                    flush=True
                )

        if remaining:
            time.sleep(POLL_INTERVAL)

    if remaining:
        print(
            f"Timed out waiting for: "
            f"{sorted(remaining)}",
            flush=True
        )
    else:
        print(
            f"All four tracks saved to {output_folder}",
            flush=True
        )


# ==========================================
# 6. HOME AND HEALTH ENDPOINTS
# ==========================================

@app.route("/", methods=["GET"])
def home():
    return (
        "<h1>Music Separation Server</h1>"
        "<p>Use a valid API endpoint.</p>"
    ), 200


@app.route("/health", methods=["GET"])
def health():
    try:
        redis_client.ping()
        s3.head_bucket(Bucket=INPUT_BUCKET)

        return jsonify({
            "status": "healthy"
        }), 200

    except Exception:
        return jsonify({
            "status": "unhealthy"
        }), 503


# ==========================================
# 7. POST /apiv1/separate
# ==========================================

@app.route("/apiv1/separate", methods=["POST"])
def separate():

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "error": "Expected JSON object"
        }), 400

    encoded = data.get("mp3")

    if not isinstance(encoded, str):
        return jsonify({
            "error": "Missing mp3 field"
        }), 400

    try:
        mp3_bytes = base64.b64decode(
            encoded,
            validate=True
        )

    except (ValueError, binascii.Error):
        return jsonify({
            "error": "Invalid Base64 MP3"
        }), 400

    if not mp3_bytes:
        return jsonify({
            "error": "Empty MP3"
        }), 400

    # Generate unique identifier
    songhash = hashlib.sha256(
        mp3_bytes
    ).hexdigest()

    object_name = f"{songhash}.mp3"

    model = data.get("model", "htdemucs")

    if model != "htdemucs":
        return jsonify({
            "error": "Only htdemucs is supported"
        }), 400

    callback = data.get("callback")

    if callback is not None:

        if (
            not isinstance(callback, dict)
            or not isinstance(
                callback.get("url"), str
            )
            or not isinstance(
                callback.get("data"), dict
            )
        ):
            return jsonify({
                "error": "Invalid callback"
            }), 400

    filename = data.get("filename")

    if not isinstance(filename, str):
        filename = None

    try:
        # Upload original MP3 to RustFS
        s3.upload_fileobj(
            io.BytesIO(mp3_bytes),
            INPUT_BUCKET,
            object_name,
            ExtraArgs={
                "ContentType": "audio/mpeg"
            }
        )

        # Job format expected by existing worker
        job = {
            "song_id": songhash,
            "object_name": object_name,
            "callback": callback
        }

        # Submit processing request to Redis
        redis_client.lpush(
            QUEUE_NAME,
            json.dumps(job)
        )

        # Start background download task
        threading.Thread(
            target=save_completed_tracks,
            args=(songhash, filename),
            daemon=True
        ).start()

        return jsonify({
            "hash": songhash,
            "reason": "Song enqueued for separation"
        }), 200

    except Exception:
        app.logger.exception(
            "Failed to submit song"
        )

        return jsonify({
            "error": "Submission failed"
        }), 500


# ==========================================
# 8. GET /apiv1/queue/
# ==========================================

@app.route("/apiv1/queue/", methods=["GET"])
@app.route("/apiv1/queue", methods=["GET"])
def queue():

    try:
        entries = redis_client.lrange(
            QUEUE_NAME,
            0,
            -1
        )

        hashes = []

        for entry in entries:
            try:
                job = json.loads(entry)
                hashes.append(job["song_id"])

            except (
                ValueError,
                KeyError,
                TypeError
            ):
                continue

        return jsonify({
            "queue": hashes
        }), 200

    except redis.RedisError:
        return jsonify({
            "error": "Redis unavailable"
        }), 503


# ==========================================
# 9. GET /apiv1/track/<hash>/<track>
# ==========================================

@app.route(
    "/apiv1/track/<songhash>/<track>",
    methods=["GET"]
)
def get_track(songhash, track):

    key = get_track_key(songhash, track)

    if key is None:
        return jsonify({
            "error": "Invalid track request"
        }), 400

    try:
        response = s3.get_object(
            Bucket=OUTPUT_BUCKET,
            Key=key
        )

        audio = response["Body"].read()
        response["Body"].close()

        return send_file(
            io.BytesIO(audio),
            mimetype="audio/mpeg",
            as_attachment=True,
            download_name=track
        )

    except ClientError as error:

        code = error.response["Error"]["Code"]

        if code in (
            "NoSuchKey",
            "404",
            "NotFound"
        ):
            return jsonify({
                "error": "Track not found"
            }), 404

        return jsonify({
            "error": "Storage error"
        }), 502


# ==========================================
# 10. REMOVE /apiv1/remove/<hash>/<track>
# ==========================================

@app.route(
    "/apiv1/remove/<songhash>/<track>",
    methods=["GET", "DELETE"]
)
def remove_track(songhash, track):

    key = get_track_key(songhash, track)

    if key is None:
        return jsonify({
            "error": "Invalid track request"
        }), 400

    try:
        # Verify track exists
        s3.head_object(
            Bucket=OUTPUT_BUCKET,
            Key=key
        )

        # Remove from RustFS
        s3.delete_object(
            Bucket=OUTPUT_BUCKET,
            Key=key
        )

        return jsonify({
            "hash": songhash,
            "track": track,
            "reason": "Track removed"
        }), 200

    except ClientError as error:

        code = error.response["Error"]["Code"]

        if code in (
            "NoSuchKey",
            "404",
            "NotFound"
        ):
            return jsonify({
                "error": "Track not found"
            }), 404

        return jsonify({
            "error": "Storage error"
        }), 502


# ==========================================
# 11. START FLASK SERVER
# ==========================================

if __name__ == "__main__":

    print("Starting Music Separation REST API")

    print(f"Redis: {REDIS_HOST}:{REDIS_PORT}")
    print(f"RustFS: {S3_ENDPOINT}")
    print(f"Output directory: {OUTPUT_DIR}")

    app.run(
        host="0.0.0.0",
        port=5000,
        threaded=True
    )

