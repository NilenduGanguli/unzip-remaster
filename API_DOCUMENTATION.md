# Unzip Service API Documentation

This document describes all available endpoints in the Unzip Service application.

## 1. Synchronous ZIP Processing (V1)
**Base Path**: `/api/v1`

These endpoints process zip files sequentially. Extraction and re-uploading are performed serially.

### 1.1 `POST /unzip_upload_doc/{client_id}`
Upload a local zip file, extract its contents, and upload extracted files to Documentum one by one.

*   **Parameters:**
    *   `client_id` (Path): The Client ID associated with this document.
    *   `file` (Form Data): The ZIP file to be processed.
*   **Returns:** JSON object containing the extraction tree structure and metadata.
*   **Example Response:**
    ```json
    {
      "ROOT_DOC_ID": {
        "document_link_id": "09000...",
        "client_id": "123",
        "file_name": "example.zip",
        "zipped_size": 1024,
        "unzipped_size": 2048,
        "tree_struct": {...},
        "files_unzipped": {...}
      }
    }
    ```

### 1.2 `GET /unzip_upload_save_doc/{clientId}/{documentLinkId}`
Fetch an existing ZIP file from Documentum using its ID, extract it, and upload contents back to Documentum.

*   **Parameters:**
    *   `clientId` (Path): The Client ID.
    *   `documentLinkId` (Path): The Documentum ID of the source ZIP file.
*   **Returns:** Same JSON structure as `unzip_upload_doc`.

---

## 2. Parallel ZIP Processing (V1)
**Base Path**: `/api/v1`

These endpoints utilize an external "File Handler Service" via HTTP to distribute or process files in parallel after extraction.

### 2.1 `POST /unzip_upload_doc_parallel/{client_id}`
Upload a local zip file, extract to a shared volume (PVC), and invoke external File Handler.

*   **Parameters:**
    *   `client_id` (Path): The Client ID.
    *   `file` (Form Data): The ZIP file to be processed.
*   **Returns:** JSON object containing results from the parallel processing.

### 2.2 `GET /unzip_upload_save_doc_parallel/{clientId}/{documentLinkId}`
Fetch existing ZIP from Documentum, extract to PVC, and invoke external File Handler.

*   **Parameters:**
    *   `clientId` (Path): The Client ID.
    *   `documentLinkId` (Path): The Documentum ID of the source ZIP file.
*   **Returns:** JSON object containing results.

---

## 3. Asynchronous/Optimized Processing (V2)
**Base Path**: `/api/v2`

These endpoints use Python `asyncio` and concurrent execution logic to optimize throughput. File extraction is offloaded to a process pool, and uploads are performed concurrently.

### 3.1 `POST /unzip_upload_doc/{client_id}`
Optimized direct upload processing.

*   **Parameters:**
    *   `client_id` (Path): The Client ID.
    *   `file` (Form Data): The ZIP file.
*   **Returns:** JSON object containing extraction details.

### 3.2 `GET /unzip_upload_save_doc/{clientId}/{documentLinkId}`
Optimized existing document processing.

*   **Parameters:**
    *   `clientId` (Path): The Client ID.
    *   `documentLinkId` (Path): The Documentum ID of the source ZIP file.
*   **Returns:** JSON object containing extraction details.

---

## 4. Utility Endpoints
**Base Path**: `/api/utils`

Helper endpoints for interacting with external services (Documentum, S3).

### 4.1 `GET /fetch_file_documentum/{documentLinkId}`
Downloads a file from Documentum and streams it back to the client.

*   **Parameters:**
    *   `documentLinkId` (Path): The Documentum ID of the file.
*   **Returns:** Binary file stream (`application/octet-stream`).
*   **Headers:**
    *   `Content-Disposition`: attachment; filename="example.pdf"
    *   `X-Filename`: example.pdf

### 4.2 `POST /upload_file_documentum`
Uploads a raw file directly to Documentum.

*   **Parameters:**
    *   `file` (Form Data): The file to upload.
*   **Returns:**
    ```json
    {
      "documentLinkId": "09000000..."
    }
    ```

### 4.3 `GET /fetch_file_s3/{s3_path}`
Downloads a file from S3 using its full path or key.

*   **Parameters:**
    *   `s3_path` (Path): The S3 path (e.g., `s3://bucket/key` or just `key`). Slashes are allowed.
*   **Returns:** Binary file stream (`application/octet-stream`).

### 4.4 `POST /upload_file_s3`
Uploads a file to the configured S3 bucket.

*   **Parameters:**
    *   `file` (Form Data): The file to upload.
*   **Returns:**
    ```json
    {
      "file_path": "uploads/uuid/filename.ext",
      "s3_path": "s3://bucket/uploads/uuid/filename.ext"
    }
    ```

---

## 5. System Endpoints
**Base Path**: `/`

### 5.1 `GET /health`
*   **Returns**: `{"status": "healthy", ...}`

### 5.2 `GET /info`
*   **Returns**: Application configuration overview (Name, Version, Region, Settings).
