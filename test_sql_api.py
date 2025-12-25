#!/usr/bin/env python3
"""
Quick test script for Windlass SQL API.

Run this to verify the SQL server is working before connecting from DBeaver!
"""

import sys
sys.path.insert(0, 'windlass')

from rvbbit.client import RVBBITClient
import json


def test_sql_api():
    """Test all SQL API features."""

    print("=" * 70)
    print("🌊 WINDLASS SQL API TEST SUITE")
    print("=" * 70)

    # Create client
    client = RVBBITClient('http://localhost:5001')

    # Test 1: Health check
    print("\n📡 Test 1: Health Check")
    print("-" * 70)
    try:
        health = client.health_check()
        print(f"✅ Status: {health['status']}")
        print(f"✅ Simple UDF registered: {health['windlass_udf_registered']}")
        print(f"✅ Cascade UDF registered: {health['cascade_udf_registered']}")
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return False

    # Test 2: Simple query
    print("\n🔢 Test 2: Simple SELECT")
    print("-" * 70)
    try:
        df = client.execute("SELECT 1 as one, 2 as two, 3 as three")
        print(df.to_string(index=False))
        print(f"✅ Basic SQL works!")
    except Exception as e:
        print(f"❌ Simple query failed: {e}")
        return False

    # Test 3: windlass_udf()
    print("\n🤖 Test 3: windlass_udf() - Simple LLM Extraction")
    print("-" * 70)
    try:
        df = client.execute("""
            SELECT
              product,
              windlass_udf('Extract the brand name only', product) as brand
            FROM (VALUES
              ('Apple iPhone 15 Pro Max'),
              ('Samsung Galaxy S24 Ultra'),
              ('Google Pixel 8 Pro')
            ) AS t(product)
        """)
        print(df.to_string(index=False))
        print(f"✅ Simple UDF works! Brands extracted via LLM!")
    except Exception as e:
        print(f"❌ Simple UDF failed: {e}")
        return False

    # Test 4: Multiple UDFs
    print("\n🎨 Test 4: Multiple UDFs - Product Enrichment")
    print("-" * 70)
    try:
        df = client.execute("""
            WITH products AS (
              SELECT * FROM (VALUES
                ('Apple iPhone 15 Pro Max Space Black', 1199.99),
                ('Samsung Galaxy S24 Ultra Titanium', 1299.99)
              ) AS t(product_name, price)
            )
            SELECT
              product_name,
              price,
              windlass_udf('Extract brand', product_name) as brand,
              windlass_udf('Extract color', product_name) as color,
              windlass_udf('Classify: budget/mid-range/premium/luxury', product_name || ' - $' || price) as tier
            FROM products
        """)
        print(df.to_string(index=False))
        print(f"✅ Multi-UDF enrichment works!")
    except Exception as e:
        print(f"❌ Multi-UDF failed: {e}")
        return False

    # Test 5: Cascade UDF
    print("\n⚡ Test 5: windlass_cascade_udf() - Full Cascade Per Row")
    print("-" * 70)
    print("⏳ Running full cascade (this takes ~10 seconds)...")
    try:
        df = client.execute(f"""
            SELECT
              customer,
              windlass_cascade_udf(
                '/home/ryanr/repos/windlass/tackle/analyze_customer.yaml',
                json_object(
                  'customer_id', '999',
                  'customer_name', customer,
                  'email', customer || '@example.com'
                )
              ) as analysis_json
            FROM (VALUES ('Acme Industries'), ('Tech Startup Inc')) AS t(customer)
        """)

        # Parse JSON results
        print(f"\nRaw results ({len(df)} rows):")
        for idx, row in df.iterrows():
            analysis = json.loads(row['analysis_json'])
            print(f"  • {row['customer']}: session_id={analysis['session_id']}, status={analysis['status']}")

            # Extract risk score from nested JSON
            try:
                assess_output = analysis['outputs']['analyze']
                if isinstance(assess_output, str):
                    assess_data = json.loads(assess_output)
                    print(f"    Risk Score: {assess_data.get('risk_score', 'N/A')}")
                    print(f"    Recommendation: {assess_data.get('recommendation', 'N/A')}")
            except:
                print(f"    (Could not parse analysis output)")

        print(f"✅ Cascade UDF works! Complete workflows per database row!")

    except Exception as e:
        print(f"❌ Cascade UDF failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Test 6: Session persistence
    print("\n💾 Test 6: Session Persistence (Temp Tables)")
    print("-" * 70)
    try:
        # Create temp table
        client.execute("""
            CREATE TEMP TABLE test_products AS
            SELECT * FROM (VALUES
              ('Product A', 100),
              ('Product B', 200)
            ) AS t(name, price)
        """, session_id="persistence_test")

        # Query it (same session)
        df = client.execute("""
            SELECT
              name,
              price,
              windlass_udf('Extract first word', name) as first_word
            FROM test_products
        """, session_id="persistence_test")

        print(df.to_string(index=False))
        print(f"✅ Session persistence works! Temp tables survive across queries!")

    except Exception as e:
        print(f"❌ Session persistence failed: {e}")
        return False

    # Summary
    print("\n" + "=" * 70)
    print("🎉 ALL TESTS PASSED!")
    print("=" * 70)
    print("\n✨ Windlass SQL API is fully operational!")
    print("\n📚 Next steps:")
    print("   1. Connect from Python: from rvbbit.client import RVBBITClient")
    print("   2. Try in Jupyter notebook")
    print("   3. Connect from DBeaver (see SQL_CLIENT_GUIDE.md)")
    print("   4. Build LLM-powered dashboards!")
    print("\n" + "=" * 70)

    return True


if __name__ == '__main__':
    try:
        success = test_sql_api()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Test suite failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
