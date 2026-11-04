
import os
import json
import redis

import boto3
from botocore.config import Config

from pathlib import Path

def download_song(object_name, destination):
    s3.download_file(
        INPUT_BUCKET,
        object_name,
        str(destination)
    )

    print(f"Downloaded {object_name}", flush=True)

S3_ENDPOINT = os.getenv(
    "S3_ENDPOINT",
    "http://localhost:9000"
)

S3_ACCESS_KEY = os.environ["S3_ACCESS_KEY"]
S3_SECRET_KEY = os.environ["S3_SECRET_KEY"]

INPUT_BUCKET = "queue"
OUTPUT_BUCKET = "output"

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

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

QUEUE_NAME = "toWorkers"

redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", "6379")),
    db=0,
    decode_responses=True,
    socket_connect_timeout=10,
    socket_timeout=None
)

redis_client.ping()

print("Worker connected to Redis", flush=True)
print("Waiting for jobs...", flush=True)

while True:
    message = redis_client.blpop(
        "toWorkers",
        timeout=5
    )

    if message is None:
        print("Waiting for jobs...", flush=True)
        continue

    print("Received:", message[1], flush=True)
