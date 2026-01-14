#!/usr/bin/env python3
"""
MinIO setup script for integration tests.

Creates test buckets and uploads sample data files (parquet, csv, json).

Usage:
    python tests/fixtures/setup_minio.py

Requirements:
    pip install boto3 pandas pyarrow

Environment:
    Uses localhost:9100 by default (mapped from docker container)
"""

import io
import json
import sys
from pathlib import Path

# Check for required dependencies
try:
    import boto3
    from botocore.client import Config
except ImportError:
    print("ERROR: boto3 is required. Install with: pip install boto3")
    sys.exit(1)

try:
    import pandas as pd
except ImportError:
    print("ERROR: pandas is required. Install with: pip install pandas")
    sys.exit(1)

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:
    print("WARNING: pyarrow not found, parquet files won't be created. Install with: pip install pyarrow")
    pa = None
    pq = None


# MinIO configuration
MINIO_ENDPOINT = "http://localhost:9100"
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin"

# Test buckets
BUCKETS = [
    "test-data",
    "analytics",
    "raw-events",
]


def get_s3_client():
    """Create S3 client configured for MinIO."""
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
    )


def create_buckets(s3):
    """Create test buckets."""
    existing = {b["Name"] for b in s3.list_buckets().get("Buckets", [])}

    for bucket in BUCKETS:
        if bucket not in existing:
            s3.create_bucket(Bucket=bucket)
            print(f"Created bucket: {bucket}")
        else:
            print(f"Bucket exists: {bucket}")


def create_sample_dataframes():
    """Create sample DataFrames for test data."""

    # Sales data
    sales_df = pd.DataFrame({
        "order_id": [1001, 1002, 1003, 1004, 1005, 1006, 1007, 1008],
        "customer_id": [101, 102, 101, 103, 104, 102, 105, 101],
        "product": ["Widget A", "Widget B", "Gadget X", "Widget A", "Service Y", "Gadget X", "Widget B", "Service Y"],
        "quantity": [2, 1, 3, 1, 1, 2, 4, 2],
        "unit_price": [29.99, 49.99, 15.00, 29.99, 199.99, 15.00, 49.99, 199.99],
        "order_date": pd.to_datetime([
            "2024-01-15", "2024-01-16", "2024-01-17", "2024-01-18",
            "2024-01-19", "2024-01-20", "2024-01-21", "2024-01-22"
        ]),
        "region": ["North", "South", "North", "East", "West", "South", "North", "East"],
    })
    sales_df["total"] = sales_df["quantity"] * sales_df["unit_price"]

    # Events data (for time-series queries)
    events_df = pd.DataFrame({
        "event_id": list(range(1, 21)),
        "event_type": ["click", "view", "purchase", "view", "click"] * 4,
        "user_id": [f"user_{i % 5 + 1}" for i in range(20)],
        "page": ["/home", "/products", "/checkout", "/products", "/cart"] * 4,
        "timestamp": pd.date_range("2024-06-01", periods=20, freq="H"),
        "device": ["mobile", "desktop", "mobile", "tablet", "desktop"] * 4,
        "session_duration_sec": [30, 120, 45, 90, 60, 150, 25, 180, 40, 75] * 2,
    })

    # Metrics data (numeric heavy)
    metrics_df = pd.DataFrame({
        "metric_name": ["cpu_usage", "memory_usage", "disk_io", "network_rx", "network_tx"] * 10,
        "host": [f"server-{i % 3 + 1}" for i in range(50)],
        "value": [45.2, 72.1, 1024, 5000, 3200] * 10,
        "timestamp": pd.date_range("2024-06-01", periods=50, freq="5min"),
        "datacenter": ["us-east", "us-west", "eu-west"] * 16 + ["us-east", "us-west"],
    })

    return {
        "sales": sales_df,
        "events": events_df,
        "metrics": metrics_df,
    }


def upload_parquet(s3, bucket: str, key: str, df: pd.DataFrame):
    """Upload DataFrame as parquet file."""
    if pq is None:
        print(f"  Skipping parquet (pyarrow not installed): {key}")
        return

    buffer = io.BytesIO()
    table = pa.Table.from_pandas(df)
    pq.write_table(table, buffer)
    buffer.seek(0)

    s3.put_object(Bucket=bucket, Key=key, Body=buffer.getvalue())
    print(f"  Uploaded: s3://{bucket}/{key}")


def upload_csv(s3, bucket: str, key: str, df: pd.DataFrame):
    """Upload DataFrame as CSV file."""
    buffer = io.StringIO()
    df.to_csv(buffer, index=False)

    s3.put_object(Bucket=bucket, Key=key, Body=buffer.getvalue().encode())
    print(f"  Uploaded: s3://{bucket}/{key}")


def upload_json(s3, bucket: str, key: str, df: pd.DataFrame):
    """Upload DataFrame as JSON lines file."""
    buffer = io.StringIO()
    df.to_json(buffer, orient="records", lines=True, date_format="iso")

    s3.put_object(Bucket=bucket, Key=key, Body=buffer.getvalue().encode())
    print(f"  Uploaded: s3://{bucket}/{key}")


def setup_test_data(s3):
    """Upload test data to MinIO buckets."""
    dfs = create_sample_dataframes()

    print("\nUploading test data to 'test-data' bucket...")

    # Parquet files (primary format)
    for name, df in dfs.items():
        upload_parquet(s3, "test-data", f"parquet/{name}.parquet", df)

    # CSV files
    for name, df in dfs.items():
        upload_csv(s3, "test-data", f"csv/{name}.csv", df)

    # JSON lines files
    for name, df in dfs.items():
        upload_json(s3, "test-data", f"json/{name}.jsonl", df)

    print("\nUploading analytics data...")
    upload_parquet(s3, "analytics", "processed/sales_summary.parquet", dfs["sales"])
    upload_parquet(s3, "analytics", "processed/event_counts.parquet", dfs["events"])

    print("\nUploading raw events...")
    upload_json(s3, "raw-events", "2024/06/01/events.jsonl", dfs["events"])


def main():
    print("=" * 60)
    print("MinIO Test Data Setup")
    print("=" * 60)
    print(f"\nEndpoint: {MINIO_ENDPOINT}")

    try:
        s3 = get_s3_client()

        # Test connection
        s3.list_buckets()
        print("Connected to MinIO successfully\n")

    except Exception as e:
        print(f"\nERROR: Cannot connect to MinIO at {MINIO_ENDPOINT}")
        print(f"       {e}")
        print("\nMake sure the docker container is running:")
        print("  docker compose -f docker-compose.sql-tests.yml up -d")
        sys.exit(1)

    print("Creating buckets...")
    create_buckets(s3)

    print("\nUploading test data...")
    setup_test_data(s3)

    print("\n" + "=" * 60)
    print("Setup complete!")
    print("=" * 60)
    print("\nTest data is available at:")
    print(f"  - s3://test-data/parquet/*.parquet")
    print(f"  - s3://test-data/csv/*.csv")
    print(f"  - s3://test-data/json/*.jsonl")
    print(f"  - s3://analytics/processed/*.parquet")
    print(f"  - s3://raw-events/2024/06/01/events.jsonl")
    print("\nMinIO Console: http://localhost:9101")
    print("  Username: minioadmin")
    print("  Password: minioadmin")


if __name__ == "__main__":
    main()
