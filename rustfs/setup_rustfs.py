
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

existing_buckets = {
    bucket["Name"]
    for bucket in s3.list_buckets()["Buckets"]
}

for bucket_name in ["queue", "output"]:
    if bucket_name not in existing_buckets:
        s3.create_bucket(Bucket=bucket_name)
        print(f"Created bucket: {bucket_name}")
    else:
        print(f"Bucket already exists: {bucket_name}")

print("RustFS setup complete!")

