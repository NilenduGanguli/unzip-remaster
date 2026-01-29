import asyncio
import os
import time
import random
import string
import zipfile
import uuid
import httpx
import statistics
from pathlib import Path
from typing import List, Dict, Callable

# Configuration
BASE_URL = "http://localhost:8080"
TEST_DIR = Path("perf_test/data")
ITERATIONS = 5  # Number of requests per endpoint per file type
CLIENT_ID = "perf_test_client"

# Helper to generate random content
def generate_random_content(size_bytes: int) -> bytes:
    return os.urandom(size_bytes)

def create_dummy_file(path: Path, size_bytes: int):
    with open(path, 'wb') as f:
        f.write(generate_random_content(size_bytes))

# Zip generators
def create_test_zips():
    TEST_DIR.mkdir(parents=True, exist_ok=True)
    
    # 1. Small Flat Zip (10 files, 1KB each)
    small_zip = TEST_DIR / "small_flat.zip"
    if not small_zip.exists():
        print(f"Generating {small_zip}...")
        with zipfile.ZipFile(small_zip, 'w') as zf:
            for i in range(10):
                zf.writestr(f"file_{i}.txt", generate_random_content(1024))

    # 2. Medium Flat Zip (50 files, 10KB each)
    medium_zip = TEST_DIR / "medium_flat.zip"
    if not medium_zip.exists():
        print(f"Generating {medium_zip}...")
        with zipfile.ZipFile(medium_zip, 'w') as zf:
             for i in range(50):
                zf.writestr(f"doc_{i}.txt", generate_random_content(10 * 1024))

    # 3. Large Single Zip (1 file, 5MB)
    large_zip = TEST_DIR / "large_single.zip"
    if not large_zip.exists():
        print(f"Generating {large_zip}...")
        with zipfile.ZipFile(large_zip, 'w') as zf:
            zf.writestr("large_data.bin", generate_random_content(5 * 1024 * 1024))

    # 4. Nested Zip (3 levels)
    nested_zip = TEST_DIR / "nested.zip"
    if not nested_zip.exists():
        print(f"Generating {nested_zip}...")
        
        # Level 3 zip
        l3_path = TEST_DIR / "l3.zip"
        with zipfile.ZipFile(l3_path, 'w') as zf:
            zf.writestr("level3.txt", b"deep data")
        
        # Level 2 zip containing l3
        l2_path = TEST_DIR / "l2.zip"
        with zipfile.ZipFile(l2_path, 'w') as zf:
            zf.write(l3_path, "l3.zip")
            zf.writestr("level2.txt", b"middle data")
        
        # Root zip containing l2
        with zipfile.ZipFile(nested_zip, 'w') as zf:
            zf.write(l2_path, "folder/l2.zip")
            zf.writestr("root.txt", b"root data")
            
        # Cleanup temp
        os.remove(l3_path)
        os.remove(l2_path)

    return [small_zip, medium_zip, large_zip, nested_zip]

# Benchmark Logic
class BenchmarkResult:
    def __init__(self, name: str):
        self.name = name
        self.times: List[float] = []
        self.statuses: List[int] = []
        self.errors: List[str] = []

    def add(self, duration: float, status: int, error: str = None):
        self.times.append(duration)
        self.statuses.append(status)
        if error:
            self.errors.append(error)

    def print_stats(self):
        if not self.times:
            print(f"[{self.name}] No results.")
            return

        avg_t = statistics.mean(self.times)
        max_t = max(self.times)
        min_t = min(self.times)
        median_t = statistics.median(self.times)
        
        success_count = sum(1 for s in self.statuses if 200 <= s < 300)
        total = len(self.statuses)
        success_rate = (success_count / total) * 100

        print(f"{'-'*60}")
        print(f"Results for: {self.name}")
        print(f"  Requests: {total}")
        print(f"  Success Rate: {success_rate:.2f}%")
        print(f"  Avg Time: {avg_t:.4f}s")
        print(f"  Min Time: {min_t:.4f}s")
        print(f"  Max Time: {max_t:.4f}s")
        print(f"  Median  : {median_t:.4f}s")
        if self.errors:
            print(f"  Errors  : {len(self.errors)}")
            # print(f"    Sample: {self.errors[0]}")

async def run_benchmark(
    client: httpx.AsyncClient, 
    label: str, 
    endpoint_template: str, 
    method: str, 
    files: List[Path]
) -> BenchmarkResult:
    result = BenchmarkResult(label)
    
    print(f"\nRunning benchmark: {label} (Method: {method})")
    
    for file_path in files:
        print(f"  Testing with file: {file_path.name}")
        for i in range(ITERATIONS):
            # Unique ID to avoid cache hits during performance testing (unless testing cache)
            # We want to test PROCESSING speed, so we use unique IDs.
            unique_client_id = f"{CLIENT_ID}_{uuid.uuid4().hex[:8]}"
            
            start_time = time.time()
            try:
                if method == "POST_UPLOAD":
                    # Direct Upload Endpoint
                    url = endpoint_template.format(client_id=unique_client_id)
                    with open(file_path, "rb") as f:
                        response = await client.post(
                            url, 
                            files={"file": (file_path.name, f, "application/zip")},
                            timeout=60.0 # extended timeout for large files
                        )
                
                elif method == "GET_SAVE_DOC":
                    # Existing Doc Endpoint - Needs Pre-upload
                    # 1. Upload to Documentum via Utils
                    upload_url = f"{BASE_URL}/api/utils/upload_file_documentum"
                    with open(file_path, "rb") as f:
                        up_resp = await client.post(upload_url, files={"file": (file_path.name, f, "application/zip")})
                    
                    if up_resp.status_code != 200:
                         result.add(0, up_resp.status_code, f"Setup Upload Failed: {up_resp.text}")
                         continue
                         
                    doc_id = up_resp.json()["documentLinkId"]
                    
                    # 2. Call the actual Endpoint
                    # Reset timer to measure ONLY the processing endpoint
                    start_time = time.time() 
                    url = endpoint_template.format(client_id=unique_client_id, doc_id=doc_id)
                    response = await client.get(url, timeout=60.0)

                duration = time.time() - start_time
                result.add(duration, response.status_code)
                
                if response.status_code != 200:
                    print(f"    Request failed: {response.text[:100]}")

            except Exception as e:
                duration = time.time() - start_time
                result.add(duration, 0, str(e))
                print(f"    Error: {e}")

    return result

async def main():
    print("=== Generating Test Data ===")
    zips = create_test_zips()
    
    results = []
    
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # Check System
        try:
            resp = await client.get("/health")
            if resp.status_code != 200:
                print("System is not healthy. Aborting.")
                return
            print("System is UP.")
        except Exception:
            print("Could not connect to localhost:8080. Ensure app is running.")
            return

        # --- 1. Synchronous Benchmarks ---
        res_sync_direct = await run_benchmark(
            client, 
            "Sync Direct Upload", 
            "/api/v1/unzip_upload_doc/{client_id}", 
            "POST_UPLOAD", 
            zips
        )
        results.append(res_sync_direct)

        res_sync_saved = await run_benchmark(
            client,
            "Sync Save Doc",
            "/api/v1/unzip_upload_save_doc/{client_id}/{doc_id}",
            "GET_SAVE_DOC",
            zips
        )
        results.append(res_sync_saved)

        # --- 2. Asynchronous Benchmarks ---
        res_async_direct = await run_benchmark(
            client,
            "Async Direct Upload",
            "/api/v2/unzip_upload_doc/{client_id}",
            "POST_UPLOAD",
            zips
        )
        results.append(res_async_direct)

        res_async_saved = await run_benchmark(
            client,
            "Async Save Doc",
            "/api/v2/unzip_upload_save_doc/{client_id}/{doc_id}",
            "GET_SAVE_DOC",
            zips
        )
        results.append(res_async_saved)

        # --- 3. Parallel Benchmarks ---
        # Note: These rely on File Handler Service. Results may vary if not running.
        res_parallel_direct = await run_benchmark(
            client,
            "Parallel Direct Upload",
            "/api/v1/unzip_upload_doc_parallel/{client_id}",
            "POST_UPLOAD",
            zips
        )
        results.append(res_parallel_direct)

        res_parallel_saved = await run_benchmark(
            client,
            "Parallel Save Doc",
            "/api/v1/unzip_upload_save_doc_parallel/{client_id}/{doc_id}",
            "GET_SAVE_DOC",
            zips
        )
        results.append(res_parallel_saved)

    print("\n\n" + "="*60)
    print("FINAL PERFOMANCE SUMMARY")
    print("="*60)
    
    # Headers
    print(f"{'Endpoint':<25} | {'Avg (s)':<10} | {'Max (s)':<10} | {'95% (s)':<10} | {'Success':<8}")
    print("-" * 75)

    for r in results:
        if not r.times:
            print(f"{r.name:<25} | {'N/A':<10} | {'N/A':<10} | {'N/A':<10} | 0%")
            continue
            
        avg = statistics.mean(r.times)
        mx = max(r.times)
        
        # P95
        sorted_times = sorted(r.times)
        idx = int(len(sorted_times) * 0.95)
        p95 = sorted_times[idx] if idx < len(sorted_times) else mx
        
        success = (sum(1 for s in r.statuses if 200 <= s < 300) / len(r.statuses)) * 100
        
        print(f"{r.name:<25} | {avg:<10.4f} | {mx:<10.4f} | {p95:<10.4f} | {success:.0f}%")

if __name__ == "__main__":
    asyncio.run(main())
