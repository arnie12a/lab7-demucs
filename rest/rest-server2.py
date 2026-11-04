
import os
import re
import io
import json
import base64
import binascii
import hashlib

import boto3
import redis

from flask import Flask, request, jsonify, send_file
from botocore.config import Config
from botocore.exceptions import ClientError

app = Flask(__name__)

# Configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://localhost:9000")

INPUT_BUCKET = os.getenv("INPUT_BUCKET", "queue")
OUTPUT_BUCKET = os.getenv("OUTPUT_BUCKET", "output")
QUEUE_NAME = "toWorkers"

# Limit request body to 16 MiB
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    decode_responses=True,
    socket_connect_timeout=10,
    socket_timeout=10
)

s3 = boto3.client(
    "s3",
    endpoint_url=S3_ENDPOINT,
    aws_access_key_id=os.environ["S3_ACCESS_KEY"],
    aws_secret_access_key=os.environ["S3_SECRET_KEY"],
    region_name="us-east-1",
    config=Config(s3={"addressing_style": "path"})
)

TRACKS = {
    "bass.mp3": "bass",
    "base.mp3": "bass",
    "vocals.mp3": "vocals",
    "drums.mp3": "drums",
    "other.mp3": "other"
}


@app.route("/", methods=["GET"])
def home():
    return "<h1>Music Separation Server</h1>", 200


@app.route("/health", methods=["GET"])
def health():
    try:
        redis_client.ping()
        s3.head_bucket(Bucket=INPUT_BUCKET)
        return jsonify({"status": "healthy"}), 200
    except Exception:
        return jsonify({"status": "unhealthy"}), 503


@app.route("/apiv1/separate", methods=["POST"])
def separate():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "Expected JSON object"}), 400

    encoded = data.get("mp3")

    if not isinstance(encoded, str):
        return jsonify({"error": "Missing mp3 field"}), 400

    try:
        mp3_bytes = base64.b64decode(
            encoded,
            validate=True
        )
    except (ValueError, binascii.Error):
        return jsonify({"error": "Invalid Base64 MP3"}), 400

    if not mp3_bytes:
        return jsonify({"error": "Empty MP3"}), 400

    # Hash the original song
    songhash = hashlib.sha256(mp3_bytes).hexdigest()
    object_name = f"{songhash}.mp3"

    # Optional model selection
    model = data.get("model", "htdemucs")

    if model != "htdemucs":
        return jsonify({
            "error": "Only htdemucs is currently supported"
        }), 400

    callback = data.get("callback")

    if callback is not None:
        if (
            not isinstance(callback, dict)
            or not isinstance(callback.get("url"), str)
            or not isinstance(callback.get("data"), dict)
        ):
            return jsonify({"error": "Invalid callback"}), 400

    try:
        # Upload original MP3 to RustFS
        s3.upload_fileobj(
            io.BytesIO(mp3_bytes),
            INPUT_BUCKET,
            object_name,
            ExtraArgs={"ContentType": "audio/mpeg"}
        )

        # Match existing worker's message format
        job = {
            "song_id": songhash,
            "object_name": object_name,
            "callback": callback
        }

        redis_client.lpush(
            QUEUE_NAME,
            json.dumps(job)
        )

        return jsonify({
            "hash": songhash,
            "reason": "Song enqueued for separation"
        }), 200

    except Exception:
        app.logger.exception("Submission failed")
        return jsonify({"error": "Submission failed"}), 500


@app.route("/apiv1/queue/", methods=["GET"])
@app.route("/apiv1/queue", methods=["GET"])
def queue():
    try:
        entries = redis_client.lrange(
            QUEUE_NAME, 0, -1
        )

        songhashes = []

        for entry in entries:
            try:
                job = json.loads(entry)
                songhashes.append(job["song_id"])
            except (ValueError, KeyError, TypeError):
                continue

        return jsonify({"queue": songhashes}), 200

    except redis.RedisError:
        return jsonify({"error": "Redis unavailable"}), 503


def get_track_key(songhash, track):
    if not re.fullmatch(r"[a-f0-9]{64}", songhash):
        return None

    part = TRACKS.get(track)

    if part is None:
        return None

    return f"{songhash}-{part}.mp3"


@app.route(
    "/apiv1/track/<songhash>/<track>",
    methods=["GET"]
)
def get_track(songhash, track):
    key = get_track_key(songhash, track)

    if key is None:
        return jsonify({"error": "Invalid track request"}), 400

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

        if code in ("NoSuchKey", "404", "NotFound"):
            return jsonify({"error": "Track not found"}), 404

        app.logger.exception("Track retrieval failed")
        return jsonify({"error": "Storage error"}), 502


@app.route(
    "/apiv1/remove/<songhash>/<track>",
    methods=["GET", "DELETE"]
)
def remove_track(songhash, track):
    key = get_track_key(songhash, track)

    if key is None:
        return jsonify({"error": "Invalid track request"}), 400

    try:
        s3.head_object(
            Bucket=OUTPUT_BUCKET,
            Key=key
        )

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

        if code in ("NoSuchKey", "404", "NotFound"):
            return jsonify({"error": "Track not found"}), 404

        app.logger.exception("Track removal failed")
        return jsonify({"error": "Storage error"}), 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

