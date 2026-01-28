# Document Handler Service API Documentation

This guide details the available APIs in the Document Handler Service and provides instructions on how to interact with them, specifically for other containers running within the same Docker network (`unzip-network`).

## Connectivity for Containers

For services running inside the `unzip-network`, you can access the Document Handler Service using its service name and internal port.

*   **Service Name**: `document-handler`
*   **Port**: `8080`
*   **Base URL**: `http://document-handler:8080`

## API Endpoints

### 1. Batch Upload from PVC

Triggers a parallel upload of files that are already present on the shared PVC mounted at `/transfer` in the document-handler container.

*   **Endpoint**: `/upload/pvc/files`
*   **Method**: `POST`
*   **Content-Type**: `application/json`

#### Request Body
A list of file paths relative to the `/transfer` directory.

```json
[
  "subdir/file1.pdf",
  "reports/2023/summary.txt"
]
```

#### Response
A JSON object containing:
- Key-value pairs of `file_path` mapped to the generated `document_link_id` for successful uploads.
- `error`: A list of file paths that failed to upload (optional, present if errors occur).
- `error_log`: A list of verbose error messages corresponding to the failed files (optional, present if errors occur).

```json
{
  "subdir/file1.pdf": "0900000180000123",
  "reports/2023/summary.txt": "0900000180000456",
  "error": [
    "subdir/missing_file.doc"
  ],
  "error_log": [
    "java.lang.RuntimeException: Failed to read file: /transfer/subdir/missing_file.doc"
  ]
}
```

#### Python Example (requests)
```python
import requests

url = "http://document-handler:8080/upload/pvc/files"
payload = ["subdir/file1.pdf", "subdir/file2.txt"]
headers = {"Content-Type": "application/json"}

response = requests.post(url, json=payload)
print(response.json())
```

---

### 2. Stream Upload (Multiple Files)

Upload multiple files directly via HTTP multipart request. The service streams them to Documentum in parallel.

*   **Endpoint**: `/upload/documentum/stream`
*   **Method**: `POST`
*   **Content-Type**: `multipart/form-data`

#### Request Parameters
*   `files`: A list of files to upload.

#### Response
A map of original filenames to their generated `document_link_id`.

```json
{
  "contract.pdf": "0900000180000111",
  "image.png": "0900000180000222"
}
```

#### Python Example (requests)
```python
import requests

url = "http://document-handler:8080/upload/documentum/stream"
files = [
    ('files', ('contract.pdf', open('contract.pdf', 'rb'), 'application/pdf')),
    ('files', ('notes.txt', open('notes.txt', 'rb'), 'text/plain'))
]

response = requests.post(url, files=files)
print(response.json())
```

---

### 3. Single File Upload

Upload a single file via HTTP multipart request.

*   **Endpoint**: `/upload/documentum/file`
*   **Method**: `POST`
*   **Content-Type**: `multipart/form-data`

#### Request Parameters
*   `file`: The file to upload.

#### Response
A JSON object with upload details (defined by `DocumentumUploadResponse`).

```json
{
  "documentLinkId": "0900000180000333",
  "success": true
}
```

#### Python Example (requests)
```python
import requests

url = "http://document-handler:8080/upload/documentum/file"
files = {'file': open('report.docx', 'rb')}

response = requests.post(url, files=files)
print(response.json())
```

---

### 4. Download File

Download a file from Documentum using its ID.

*   **Endpoint**: `/download/documentum`
*   **Method**: `GET`

#### Query Parameters
*   `document_link_id`: The ID of the document to retrieve.

#### Response
The binary content of the file. The `Content-Disposition` header will contain the filename.

#### Python Example (requests)
```python
import requests

url = "http://document-handler:8080/download/documentum"
params = {"document_link_id": "0900000180000123"}

response = requests.get(url, params=params)

if response.status_code == 200:
    with open("downloaded_file.pdf", "wb") as f:
        f.write(response.content)
```
