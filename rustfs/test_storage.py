
import os
import boto3
from botocore.config import Config

s3 = boto3.client(
    "s3",
    endpoint_url=os.environ["S3_ENDPOINT"],
    aws_access_key_id=os.environ["S3_ACCESS_KEY"],
    aws_secret_access_key=os.environ["S3_SECRET_KEY"],
    region_name="us-east-1",
    config=Config(
        s3={"addressing_style": "path"}
    )
)

# Upload file
s3.upload_file(
    "test.txt",
    "queue",
    "test.txt"
)

print("Upload successful!")

# Download file
s3.download_file(
    "queue",
    "test.txt",
    "downloaded.txt"
)

print("Download successful!")

# Verify contents
with open("downloaded.txt") as f:
    print(f.read())

