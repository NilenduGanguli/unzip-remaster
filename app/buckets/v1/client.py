"""
S3 Bucket Client.
Wrapper around boto3 for interacting with S3-compatible object storage.
Used for caching JSON responses to avoid re-processing.
"""
import boto3
import json
import asyncio
from typing import Dict, Any, Optional
from botocore.exceptions import ClientError
from app.core.v1.config import AppSettings
from app.core.v1.logging import get_logger

logger = get_logger(__name__)
settings = AppSettings()

class S3Client:
    def __init__(self):
        self.bucket_name = settings.S3_BUCKET_NAME
        self.s3 = boto3.client(
            's3',
            endpoint_url=settings.S3_HOST,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY
        )

    async def upload_json(self, key: str, data: Dict[str, Any]) -> str:
        """
        Uploads a dictionary as JSON to S3.
        Returns the S3 URI (s3://bucket/key).
        """
        loop = asyncio.get_running_loop()
        try:
            json_str = json.dumps(data)
            await loop.run_in_executor(
                None,
                lambda: self.s3.put_object(
                    Bucket=self.bucket_name,
                    Key=key,
                    Body=json_str,
                    ContentType='application/json'
                )
            )
            s3_path = f"s3://{self.bucket_name}/{key}"
            await logger.ainfo(f"Uploaded response to {s3_path}")
            return s3_path
        except Exception as e:
            await logger.aerror(f"S3 Upload failed: {e}")
            raise

    async def get_json(self, s3_path: str) -> Optional[Dict[str, Any]]:
        """
        Fetches JSON from S3 given a full s3:// URI or just the Key.
        """
        loop = asyncio.get_running_loop()
        
        # Parse Key from s3:// path if provided
        key = s3_path
        if s3_path.startswith("s3://"):
            # s3://bucket/key -> split by / -> remove first 3 parts (s3:, , bucket)
            parts = s3_path.split("/", 3)
            if len(parts) > 3:
                key = parts[3]
            else:
                await logger.aerror(f"Invalid S3 Path format: {s3_path}")
                return None

        try:
            response = await loop.run_in_executor(
                None,
                lambda: self.s3.get_object(Bucket=self.bucket_name, Key=key)
            )
            content = await loop.run_in_executor(None, lambda: response['Body'].read().decode('utf-8'))
            return json.loads(content)
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                await logger.awarning(f"S3 Key not found: {key}")
                return None
            await logger.aerror(f"S3 Fetch failed: {e}")
            raise
        except Exception as e:
            await logger.aerror(f"S3 Fetch error: {e}")
            raise

    async def upload_file(self, key: str, file_content: bytes, content_type: str = 'application/octet-stream') -> str:
        """
        Uploads raw file content to S3.
        """
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: self.s3.put_object(
                    Bucket=self.bucket_name,
                    Key=key,
                    Body=file_content,
                    ContentType=content_type
                )
            )
            s3_path = f"s3://{self.bucket_name}/{key}"
            await logger.ainfo(f"Uploaded file to {s3_path}")
            return s3_path
        except Exception as e:
            await logger.aerror(f"S3 File Upload failed: {e}")
            raise

    async def get_file(self, s3_path: str):
        """
        Fetches raw file bytes from S3.
        Returns (content_bytes, content_type)
        """
        loop = asyncio.get_running_loop()
        
        # Parse Key
        key = s3_path
        if s3_path.startswith("s3://"):
            parts = s3_path.split("/", 3)
            if len(parts) > 3:
                key = parts[3]
            else:
                raise ValueError(f"Invalid S3 Path format: {s3_path}")

        try:
            response = await loop.run_in_executor(
                None,
                lambda: self.s3.get_object(Bucket=self.bucket_name, Key=key)
            )
            # Read all bytes
            content = await loop.run_in_executor(None, lambda: response['Body'].read())
            content_type = response.get('ContentType', 'application/octet-stream')
            return content, content_type
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                await logger.awarning(f"S3 Key not found: {key}")
                raise FileNotFoundError(f"S3 Key not found: {key}")
            await logger.aerror(f"S3 Fetch failed: {e}")
            raise
        except Exception as e:
            await logger.aerror(f"S3 Fetch error: {e}")
            raise

def get_s3_client() -> S3Client:
    return S3Client()
