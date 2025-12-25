#!/usr/bin/env python3
"""
Integration test for RVBBIT MAP syntax via HTTP API.

This tests the rewriter through the actual SQL API endpoint.
"""

import sys
sys.path.insert(0, 'rvbbit')

from rvbbit.client import RVBBITClient


def test_map_via_http_api():
    """Test RVBBIT MAP through HTTP API."""
    print("=" * 70)
    print("🌐 Testing RVBBIT MAP via HTTP API")
    print("=" * 70)

    try:
        client = RVBBITClient('http://localhost:5001')

        # Test 1: Basic MAP syntax
        print("\n1️⃣ Basic MAP syntax:")
        query = """
            RVBBIT MAP 'traits/extract_brand.yaml'
            USING (
              SELECT * FROM (VALUES
                ('Apple iPhone 15'),
                ('Samsung Galaxy S24')
              ) AS t(product_name)
            )
        """
        print(f"Query: {query[:80]}...")

        df = client.execute(query)
        print(f"\nResult:\n{df}")
        print(f"\nColumns: {list(df.columns)}")

        assert 'product_name' in df.columns
        assert 'result' in df.columns
        assert len(df) == 2

        print("✅ Basic MAP works via HTTP API!")

        # Test 2: With AS alias
        print("\n2️⃣ With AS alias:")
        query = """
            RVBBIT MAP 'traits/extract_brand.yaml' AS brand_info
            USING (
              SELECT * FROM (VALUES ('Test Product')) AS t(product_name)
            )
        """

        df = client.execute(query)
        print(f"Columns: {list(df.columns)}")

        assert 'brand_info' in df.columns
        assert 'result' not in df.columns

        print("✅ AS alias works!")

        print("\n" + "=" * 70)
        print("✅ ALL INTEGRATION TESTS PASSED!")
        print("=" * 70)
        print("\n⚠️  NOTE: If tests fail, make sure:")
        print("   1. Dashboard backend is running (python dashboard/backend/app.py)")
        print("   2. Server has been RESTARTED to load new sql_rewriter.py")

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        print(f"\n⚠️  Make sure:")
        print("   1. Dashboard is running: cd dashboard/backend && python app.py")
        print("   2. Server was restarted after adding sql_rewriter.py")
        return False

    return True


if __name__ == '__main__':
    success = test_map_via_http_api()
    sys.exit(0 if success else 1)
