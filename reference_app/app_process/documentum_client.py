import httpx
from app_process.database import settings
import logging
import mimetypes
import base64
import json

logger = logging.getLogger(__name__)

class DocumentumClient:
    def __init__(self):
        self.upload_url = settings.DOCUMENTUM_UPLOAD_URL
        self.fetch_url = settings.DOCUMENTUM_FETCH_URL
        # Use limits to control connection pooling for high concurrency
        limits = httpx.Limits(max_keepalive_connections=50, max_connections=100)
        
        cert = None
        if settings.USE_CERT:
            if settings.DOCUMENTUM_CERT_PATH and settings.DOCUMENTUM_KEY_PATH:
                logger.info(f"Using client certificate: {settings.DOCUMENTUM_CERT_PATH} with key: {settings.DOCUMENTUM_KEY_PATH}")
                if settings.DOCUMENTUM_KEY_PASSWORD:
                    # Provide cert, key, and password
                    cert = (settings.DOCUMENTUM_CERT_PATH, settings.DOCUMENTUM_KEY_PATH, settings.DOCUMENTUM_KEY_PASSWORD)
                else:
                    cert = (settings.DOCUMENTUM_CERT_PATH, settings.DOCUMENTUM_KEY_PATH)
            else:
                 logger.warning("USE_CERT is true but DOCUMENTUM_CERT_PATH or DOCUMENTUM_KEY_PATH is missing")

        self.client = httpx.AsyncClient(timeout=30.0, limits=limits, cert=cert)

    async def close(self):
        await self.client.aclose()

    async def upload_document(self, file_content: bytes, filename: str, parent_id: str = None) -> str:
        """
        Uploads a document to Documentum (JSON Base64) and returns the document ID.
        """
        try:
            logger.debug(f"Uploading to Documentum: {filename} (Parent: {parent_id})")
            
            encoded_content = base64.b64encode(file_content).decode('utf-8')
            
            payload = {
                "filename": filename,
                "content": encoded_content
            }
            
            response = await self.client.post(self.upload_url, json=payload)
            response.raise_for_status()
            
            data = response.json()
            doc_id = data.get("document_link_id")
            
            logger.debug(f"Documentum upload success. ID: {doc_id}")
            return doc_id

        except httpx.HTTPError as e:
            logger.error(f"Documentum upload failed for {filename}: {str(e)}")
            raise Exception(f"Failed to upload to Documentum: {str(e)}")

    async def fetch_document(self, document_link_id: str):
        """
        Fetch a document from Documentum (JSON Base64).
        Returns (filename, content_bytes)
        """
        logger.info(f"Fetching document from Documentum with documentLinkId: {document_link_id}")
        try:
            payload = {"document_link_id": document_link_id}
            
            response = await self.client.post(self.fetch_url, json=payload)
            response.raise_for_status()
            
            data = response.json()
            if "content" not in data:
                 raise Exception(f"Invalid response: Missing 'content' for {document_link_id}")
            
            base64_content = data["content"]
            if not base64_content:
                 raise Exception(f"Empty content for {document_link_id}")

            filename = data.get("filename") or data.get("file_name") or f"{document_link_id}.zip"
            
            decoded_bytes = base64.b64decode(base64_content)
            logger.info(f"Successfully fetched document, size: {len(decoded_bytes)} bytes")
            
            return filename, decoded_bytes

        except Exception as e:
            logger.error(f"Error fetching document: {e}")
            raise Exception(f"Failed to fetch document: {str(e)}")

# Singleton instance
doc_client = DocumentumClient()

def get_documentum_client() -> DocumentumClient:
    return doc_client
