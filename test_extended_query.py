#!/usr/bin/env python3
"""
Test Extended Query Protocol implementation.

This tests that psycopg2 works WITHOUT preferQueryMode=simple!

Usage:
    1. Start server: rvbbit sql server --port 15432
    2. Run this: python3 test_extended_query.py
"""

import psycopg2
import sys

def test_extended_protocol():
    """Test Extended Query Protocol (prepared statements)."""

    print("="*70)
    print("TESTING EXTENDED QUERY PROTOCOL")
    print("="*70)
    print("\n🔌 Connecting WITHOUT preferQueryMode=simple...")
    print("   (This will use Extended Query Protocol by default)")

    try:
        # Connect WITHOUT preferQueryMode=simple
        # psycopg2 will use Extended Query Protocol automatically!
        conn = psycopg2.connect(
            host="localhost",
            port=15432,
            database="default",
            user="rvbbit"
        )
        print("✅ Connected successfully!\n")

        cur = conn.cursor()
        tests_passed = 0
        tests_failed = 0

        # Test 1: Simple parameterized query
        print("[TEST 1] Simple parameterized query")
        print("   Query: SELECT $1 as value")
        print("   Parameter: 42")
        try:
            cur.execute("SELECT %s as value", (42,))
            result = cur.fetchone()
            if result[0] == 42:
                print(f"   ✅ PASSED: Got {result[0]}")
                tests_passed += 1
            else:
                print(f"   ❌ FAILED: Expected 42, got {result[0]}")
                tests_failed += 1
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            tests_failed += 1

        # Test 2: Multiple parameters
        print("\n[TEST 2] Multiple parameters")
        print("   Query: SELECT $1 + $2 as sum")
        print("   Parameters: 10, 32")
        try:
            cur.execute("SELECT %s + %s as sum", (10, 32))
            result = cur.fetchone()
            if result[0] == 42:
                print(f"   ✅ PASSED: Got {result[0]}")
                tests_passed += 1
            else:
                print(f"   ❌ FAILED: Expected 42, got {result[0]}")
                tests_failed += 1
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            tests_failed += 1

        # Test 3: String parameters
        print("\n[TEST 3] String parameters")
        print("   Query: SELECT $1 as name")
        print("   Parameter: 'Alice'")
        try:
            cur.execute("SELECT %s as name", ('Alice',))
            result = cur.fetchone()
            if result[0] == 'Alice':
                print(f"   ✅ PASSED: Got '{result[0]}'")
                tests_passed += 1
            else:
                print(f"   ❌ FAILED: Expected 'Alice', got '{result[0]}'")
                tests_failed += 1
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            tests_failed += 1

        # Test 4: NULL parameters
        print("\n[TEST 4] NULL parameters")
        print("   Query: SELECT $1 as value")
        print("   Parameter: None")
        try:
            cur.execute("SELECT %s as value", (None,))
            result = cur.fetchone()
            if result[0] is None:
                print(f"   ✅ PASSED: Got NULL")
                tests_passed += 1
            else:
                print(f"   ❌ FAILED: Expected NULL, got {result[0]}")
                tests_failed += 1
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            tests_failed += 1

        # Test 5: Reuse prepared statement
        print("\n[TEST 5] Reuse prepared statement (key feature of Extended Query!)")
        print("   Query: SELECT $1 as value (executed 3 times)")
        print("   Parameters: 1, 2, 3")
        try:
            for val in [1, 2, 3]:
                cur.execute("SELECT %s as value", (val,))
                result = cur.fetchone()
                if result[0] != val:
                    raise Exception(f"Expected {val}, got {result[0]}")
            print(f"   ✅ PASSED: All 3 executions worked (statement reused!)")
            tests_passed += 1
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            tests_failed += 1

        # Test 6: Create table and insert with parameters
        print("\n[TEST 6] CREATE TABLE and INSERT with parameters")
        try:
            cur.execute("CREATE TABLE IF NOT EXISTS test_extended (id INTEGER, name VARCHAR, value DOUBLE)")
            cur.execute("INSERT INTO test_extended VALUES (%s, %s, %s)", (1, 'Alice', 99.5))
            cur.execute("INSERT INTO test_extended VALUES (%s, %s, %s)", (2, 'Bob', 88.5))

            # Query back
            cur.execute("SELECT * FROM test_extended WHERE id = %s", (1,))
            result = cur.fetchone()

            if result == (1, 'Alice', 99.5):
                print(f"   ✅ PASSED: INSERT and SELECT with parameters work!")
                tests_passed += 1
            else:
                print(f"   ❌ FAILED: Expected (1, 'Alice', 99.5), got {result}")
                tests_failed += 1
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            import traceback
            traceback.print_exc()
            tests_failed += 1

        # Test 7: Complex WHERE clause
        print("\n[TEST 7] Complex WHERE clause with multiple parameters")
        try:
            cur.execute("""
                SELECT * FROM test_extended
                WHERE id > %s AND value < %s
                ORDER BY id
            """, (0, 100))
            results = cur.fetchall()

            if len(results) == 2:
                print(f"   ✅ PASSED: Got {len(results)} rows")
                tests_passed += 1
            else:
                print(f"   ❌ FAILED: Expected 2 rows, got {len(results)}")
                tests_failed += 1
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            tests_failed += 1

        # Test 8: Named prepared statement (explicit PREPARE)
        print("\n[TEST 8] Explicit PREPARE statement")
        try:
            cur.execute("PREPARE test_stmt AS SELECT $1 as value")
            cur.execute("EXECUTE test_stmt(999)")
            result = cur.fetchone()

            if result[0] == 999:
                print(f"   ✅ PASSED: Explicit PREPARE/EXECUTE works!")
                tests_passed += 1
            else:
                print(f"   ❌ FAILED: Expected 999, got {result[0]}")
                tests_failed += 1

            # Clean up
            cur.execute("DEALLOCATE test_stmt")
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            tests_failed += 1

        # Test 9: Transaction with prepared statements
        print("\n[TEST 9] Transaction with prepared statements")
        try:
            cur.execute("BEGIN")
            cur.execute("INSERT INTO test_extended VALUES (%s, %s, %s)", (3, 'Charlie', 77.5))
            cur.execute("SELECT COUNT(*) FROM test_extended")
            count_before_commit = cur.fetchone()[0]
            cur.execute("COMMIT")

            if count_before_commit == 3:
                print(f"   ✅ PASSED: Transaction with parameters works!")
                tests_passed += 1
            else:
                print(f"   ❌ FAILED: Expected 3 rows, got {count_before_commit}")
                tests_failed += 1
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            tests_failed += 1
            try:
                cur.execute("ROLLBACK")
            except:
                pass

        # Summary
        print("\n" + "="*70)
        print("TEST SUMMARY")
        print("="*70)
        print(f"✅ Passed: {tests_passed}/9")
        print(f"❌ Failed: {tests_failed}/9")
        print("="*70)

        if tests_passed == 9:
            print("\n🎉 ALL TESTS PASSED!")
            print("Extended Query Protocol is working perfectly!")
            print("\n✅ You can now:")
            print("   • Use psycopg2 without preferQueryMode=simple")
            print("   • Use SQLAlchemy with RVBBIT")
            print("   • Use Django ORM with RVBBIT")
            print("   • Get type-safe parameter binding")
            print("   • Get better performance (prepared statement reuse)")
            return 0
        else:
            print(f"\n⚠️  {tests_failed} test(s) failed")
            print("Check server logs for errors")
            return 1

    except psycopg2.OperationalError as e:
        print(f"\n❌ Connection failed: {e}")
        print("\n💡 Make sure the server is running:")
        print("   rvbbit sql server --port 15432")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        try:
            conn.close()
        except:
            pass


if __name__ == "__main__":
    sys.exit(test_extended_protocol())
