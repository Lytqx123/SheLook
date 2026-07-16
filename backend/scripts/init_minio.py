"""MinIO 初始化脚本 —— 创建存储桶并设置策略。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from minio import Minio
from minio.error import S3Error

from app.config import settings


def init_minio():
    print("=== MinIO 初始化 ===\n")

    endpoint = settings.MINIO_ENDPOINT
    secure = settings.MINIO_SECURE

    print(f"连接 MinIO: {endpoint}")
    client = Minio(
        endpoint,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=secure,
    )

    try:
        client.list_buckets()
        print("✓ MinIO 连接成功")
    except S3Error as e:
        print(f"✗ MinIO 连接失败: {e}")
        return

    # 创建存储桶
    buckets = [
        settings.MINIO_BUCKET,
        settings.MINIO_PRIVATE_BUCKET,
        "raw-images",
        "reference-images",
    ]

    for bucket_name in buckets:
        try:
            found = client.bucket_exists(bucket_name)
            if found:
                print(f"  Bucket '{bucket_name}' 已存在，跳过")
            else:
                client.make_bucket(bucket_name)
                print(f"✓ Bucket '{bucket_name}' 创建成功")
        except S3Error as e:
            print(f"✗ Bucket '{bucket_name}' 创建失败: {e}")

    # 设置 public-read 策略
    bucket_name = settings.MINIO_BUCKET
    public_policy = f"""
{{
    "Version": "2012-10-17",
    "Statement": [
        {{
            "Effect": "Allow",
            "Principal": {{"AWS": ["*"]}},
            "Action": ["s3:GetObject"],
            "Resource": ["arn:aws:s3:::{bucket_name}/*"]
        }}
    ]
}}
"""
    try:
        client.set_bucket_policy(settings.MINIO_BUCKET, public_policy)
        print(f"✓ Bucket '{settings.MINIO_BUCKET}' 策略设置为 public-read")
    except S3Error as e:
        print(f"! Bucket 策略设置警告: {e}")

    print("\n=== MinIO 初始化完成 ===")


if __name__ == "__main__":
    init_minio()
