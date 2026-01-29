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
      "090000000a000001": {
        "doc_id": "090000000a000001",
        "client_id": "1001198212",
        "file_name": "small_flat.zip",
        "zipped_size": "10240",
        "unzipped_size": "10240",
        "tree_struct": {
          "small_flat.zip": {
            "file_1.txt": {},
            "file_2.txt": {}
          }
        },
        "files_unzipped": {
          "small_flat.zip/file_1.txt": {
            "file_name": "file_1.txt",
            "file_id": "090000000a000002",
            "file_size": "1024"
          },
          "small_flat.zip/file_2.txt": {
            "file_name": "file_2.txt",
            "file_id": "090000000a000003",
            "file_size": "1024"
          }
        }
      }
    }
    ```

### 1.2 `GET /unzip_upload_save_doc/{clientId}/{documentLinkId}`
Fetch an existing ZIP file from Documentum using its ID, extract it, and upload contents back to Documentum.

*   **Parameters:**
    *   `clientId` (Path): The Client ID (e.g., `1001198212`).
    *   `documentLinkId` (Path): The Documentum ID (e.g., `000000000a`).
*   **Returns:** Same JSON structure as `unzip_upload_doc`.
*   **Example Response:**
    ```json
    {
      "000000000a": {
        "doc_id": "000000000a",
        "client_id": "1001198212",
        "file_name": "archive_from_dctm.zip",
        "zipped_size": "5000",
        "unzipped_size": "12000",
        "tree_struct": {
            "archive.zip": {
                "doc.pdf": {}
            }
        },
        "files_unzipped": {
            "archive.zip/doc.pdf": {
                "file_name": "doc.pdf",
                "file_id": "090000000a000099",
                "file_size": "12000"
            }
        }
      }
    }
    ```

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
*   **Example Response:**
    ```json
    {
      "090000000b000001": {
        "doc_id": "090000000b000001",
        "client_id": "1001198212",
        "file_name": "nested.zip",
        "zipped_size": "15000",
        "unzipped_size": "45000",
        "tree_struct": {
          "nested.zip": {
             "folder": {
                "l2.zip": {
                   "level2.txt": {}
                }
             },
             "root.txt": {}
          }
        },
        "files_unzipped": {
           "nested.zip/root.txt": {
              "file_name": "root.txt", 
              "file_id": "090000000b000002", 
              "file_size": "100"
           },
           "nested.zip/folder/l2.zip/level2.txt": {
              "file_name": "level2.txt",
              "file_id": "090000000b000005",
              "file_size": "500"
           }
        }
      }
    }
    ```

### 2.2 `GET /unzip_upload_save_doc_parallel/{clientId}/{documentLinkId}`
Fetch existing ZIP from Documentum, extract to PVC, and invoke external File Handler.

*   **Parameters:**
    *   `clientId` (Path): The Client ID (e.g., `1001198212`).
    *   `documentLinkId` (Path): The Documentum ID (e.g., `000000000b`).
*   **Returns:** JSON object containing results.
*   **Example Response:**
    ```json
    {
      "000000000b": {
        "doc_id": "000000000b",
        "client_id": "1001198212",
        "file_name": "fetched_nested.zip",
        "zipped_size": "2048",
        "unzipped_size": "4096",
        "tree_struct": {
           "fetched_nested.zip": {
               "data.csv": {}
           }
        },
        "files_unzipped": {
           "fetched_nested.zip/data.csv": {
              "file_name": "data.csv",
              "file_id": "090000000b000099",
              "file_size": "4096"
           }
        }
      }
    }
    ```

---

## 3. Asynchronous/Optimized Processing (V2)
**Base Path**: `/api/v2`

These endpoints use Python `asyncio` and concurrent execution logic to optimize throughput. File extraction is offloaded to a process pool, and uploads are performed concurrently.

### 3.1 `POST /unzip_upload_doc/{client_id}`
Optimized direct upload processing.

*   **Parameters:**
    *   `client_id` (Path): The Client ID (e.g., `1001198212`).
    *   `file` (Form Data): The ZIP file.
*   **Returns:** JSON object containing extraction details (same structure as V1).
*   **Example Response:**
    ```json
    {
      "090000000c000001": {
        "doc_id": "090000000c000001",
        "client_id": "1001198212",
        "file_name": "async_upload.zip",
        "zipped_size": "3072",
        "unzipped_size": "6144",
        "tree_struct": {
          "async_upload.zip": {
            "report.pdf": {}
          }
        },
        "files_unzipped": {
           "async_upload.zip/report.pdf": {
              "file_name": "report.pdf",
              "file_id": "090000000c000088",
              "file_size": "6144"
           }
        }
      }
    }
    ```

### 3.2 `GET /unzip_upload_save_doc/{clientId}/{documentLinkId}`
Optimized existing document processing.

*   **Parameters:**
    *   `clientId` (Path): The Client ID (e.g., `1001198212`).
    *   `documentLinkId` (Path): The Documentum ID of the source ZIP file (e.g., `000000000c`).
*   **Returns:** JSON object containing extraction details (same structure as V1).
*   **Example Response:**
    ```json
    {
      "000000000c": {
        "doc_id": "000000000c",
        "client_id": "1001198212",
        "file_name": "async_remote.zip",
        "zipped_size": "4096",
        "unzipped_size": "8192",
        "tree_struct": {
            "async_remote.zip": {
                "log.txt": {}
            }
        },
        "files_unzipped": {
            "async_remote.zip/log.txt": {
                "file_name": "log.txt",
                "file_id": "090000000c000077",
                "file_size": "8192"
            }
        }
      }
    }
    ```

---

## 4. Utility Endpoints
**Base Path**: `/api/utils`

Helper endpoints for interacting with external services (Documentum, S3).

### 4.1 `GET /fetch_file_documentum/{documentLinkId}`
Downloads a file from Documentum and streams it back to the client.

*   **Parameters:**
    *   `documentLinkId` (Path): The Documentum ID of the file (e.g., `090000000a000099`).
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
      "documentLinkId": "090000000a000099"
    }
    ```

### 4.3 `GET /fetch_file_s3/{s3_path}`
Downloads a file from S3 using its full path or key.

*   **Parameters:**
    *   `s3_path` (Path): The S3 path (e.g., `s3://bucket/1001198212/090000000a/doc.pdf`).
*   **Returns:** Binary file stream (`application/octet-stream`).

### 4.4 `POST /upload_file_s3`
Uploads a file to the configured S3 bucket.

*   **Parameters:**
    *   `file` (Form Data): The file to upload.
*   **Returns:**
    ```json
    {
      "file_path": "uploads/uniqid/uploaded.pdf",
      "s3_path": "s3://my-bucket/uploads/uniqid/uploaded.pdf"
    }
    ```

---

## 5. System Endpoints
**Base Path**: `/`

### 5.1 `GET /health`
*   **Returns**: `{"status": "healthy", ...}`

### 5.2 `GET /info`
*   **Returns**: Application configuration overview (Name, Version, Region, Settings).
