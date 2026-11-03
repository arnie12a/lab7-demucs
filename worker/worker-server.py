
import os
import sys
import json
import time
import redis
import boto3
import requests
import subprocess

from pathlib import Path
from tempfile import TemporaryDirectory
from botocore.config import Config


# ----------------------------------
# 1. Configuration
# ----------------------------------

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://localhost:9000")
S3_ACCESS_KEY = os.environ["S3_ACCESS_KEY"]
S3_SECRET_KEY = os.environ["S3_SECRET_KEY"]

INPUT_BUCKET = os.getenv("INPUT_BUCKET", "queue")
OUTPUT_BUCKET = os.getenv("OUTPUT_BUCKET", "output")

QUEUE_NAME = "toWorkers"


# ----------------------------------
# 2. Connect to Redis
# ----------------------------------

redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=0,
    decode_responses=True,
    socket_connect_timeout=10,
    socket_timeout=None
)

redis_client.ping()
print("Worker connected to Redis", flush=True)


# ----------------------------------
# 3. Connect to RustFS
# ----------------------------------

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

print("RustFS client configured", flush=True)


# ----------------------------------
# 4. Logging
# ----------------------------------

def log_info(message):
    print(message, flush=True)

    try:
        redis_client.lpush("logging", message)
    except redis.RedisError as error:
        print(f"Logging failed: {error}", flush=True)


# ----------------------------------
# 5. Download song from RustFS
# ----------------------------------

def download_song(object_name, destination):
    log_info(f"Downloading {object_name}")

    s3.download_file(
        INPUT_BUCKET,
        object_name,
        str(destination)
    )

    log_info(f"Downloaded {object_name}")


# ----------------------------------
# 6. Run Demucs
# ----------------------------------

def separate_song(input_path, output_dir):
    log_info("Starting Demucs separation")

    command = [
        sys.executable,
        "-m",
        "demucs.separate",
        "--mp3",
        "--out",
        str(output_dir),
        str(input_path)
    ]

    subprocess.run(command, check=True)

    log_info("Demucs separation completed")


# ----------------------------------
# 7. Upload separated tracks
# ----------------------------------

def upload_tracks(song_id, output_dir):
    parts = ["bass", "drums", "vocals", "other"]

    for part in parts:
        matches = list(
            Path(output_dir).glob(
                f"*/{song_id}/{part}.mp3"
            )
        )

        if len(matches) != 1:
            raise RuntimeError(
                f"Expected one {part}.mp3, "
                f"found {len(matches)}"
            )

        output_file = matches[0]
        object_name = f"{song_id}-{part}.mp3"

        s3.upload_file(
            str(output_file),
            OUTPUT_BUCKET,
            object_name,
            ExtraArgs={"ContentType": "audio/mpeg"}
        )

        log_info(f"Uploaded {object_name}")


# ----------------------------------
# 8. Optional webhook callback
# ----------------------------------

def send_callback(job):
    callback = job.get("callback")

    if not callback:
        return

    try:
        response = requests.post(
            callback["url"],
            json=callback["data"],
            timeout=10
        )
        response.raise_for_status()
        log_info("Callback sent successfully")

    except (requests.RequestException, KeyError) as error:
        log_info(f"Callback failed: {error}")


# ----------------------------------
# 9. Process a complete job
# ----------------------------------

def process_job(job):
    song_id = job["song_id"]
    object_name = job["object_name"]

    # Prevent unexpected filenames/paths
    if not song_id or not all(
        c.isalnum() or c in "-_" for c in song_id
    ):
        raise ValueError("Invalid song_id")

    with TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)

        input_path = temp / f"{song_id}.mp3"
        output_dir = temp / "output"

        # Download original MP3
        download_song(object_name, input_path)

        # Run Demucs
        separate_song(input_path, output_dir)

        # Upload four tracks
        upload_tracks(song_id, output_dir)

    log_info(f"Completed processing {song_id}")

    # Notify callback after successful processing
    send_callback(job)


# ----------------------------------
# 10. Main worker loop
# ----------------------------------

def main():
    log_info("Worker started. Waiting for jobs...")

    while True:
        try:
            message = redis_client.blpop(
                QUEUE_NAME,
                timeout=5
            )

            if message is None:
                continue

            job = json.loads(message[1])

            log_info(f"Received job: {job.get('song_id')}")

            process_job(job)

        except redis.RedisError as error:
            print(f"Redis error: {error}", flush=True)
            time.sleep(2)

        except Exception as error:
            log_info(f"Worker processing failed: {error}")


if __name__ == "__main__":
    main()

