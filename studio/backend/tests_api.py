"""
Tests API - Unified Test Dashboard Backend

This module provides REST API endpoints for the test dashboard,
supporting both semantic SQL tests and cascade snapshot tests.

Features:
- Test discovery from cascade files and snapshot directories
- Synchronous test execution with polling for status
- Historical run storage in ClickHouse
- Flaky test detection and analytics
"""

import os
import sys
import json
import uuid
import fnmatch
import subprocess
import traceback
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from flask import Blueprint, jsonify, request

# Add rvbbit to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

tests_bp = Blueprint('tests', __name__)


def _json_safe(value: Any) -> Any:
    """Convert numpy/pandas types to Python native types for JSON serialization."""
    if value is None:
        return None
    # Handle numpy scalars (bool_, int64, float64, etc.)
    if hasattr(value, 'item'):
        return value.item()
    # Handle numpy arrays
    if hasattr(value, 'tolist'):
        return value.tolist()
    # Handle pandas Timestamp
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    # Handle bytes
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    # Recursively handle dicts and lists
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


@dataclass
class TestDefinition:
    """A discovered test definition."""
    test_id: str
    test_type: str  # "semantic_sql" or "cascade_snapshot"
    test_group: str
    test_name: str
    description: str = ""
    source_file: str = ""
    source_line: int = 0
    # For semantic SQL
    sql_query: str = ""
    expect: Any = None
    expect_type: str = ""
    # For snapshots
    validation_modes: List[str] = field(default_factory=list)
    has_contracts: bool = False
    has_anchors: bool = False
    # For visual regression
    initial_url: str = ""
    browser_batch: List[Any] = field(default_factory=list)
    threshold: float = 0.95


@dataclass
class TestResult:
    """Result of a single test execution."""
    test_id: str
    test_type: str
    test_group: str
    test_name: str
    status: str  # "passed", "failed", "error", "skipped"
    duration_ms: float = 0
    description: str = ""
    source_file: str = ""
    source_line: int = 0
    # For semantic SQL
    sql_query: str = ""
    expected_value: str = ""
    actual_value: str = ""
    expect_type: str = ""
    # For cascade snapshots
    validation_mode: str = ""
    cells_validated: int = 0
    contracts_checked: int = 0
    contracts_passed: int = 0
    anchors_checked: int = 0
    anchors_passed: int = 0
    judge_score: Optional[float] = None
    judge_reasoning: str = ""
    # Failure details
    failure_type: str = ""
    failure_message: str = ""
    failure_diff: str = ""
    # Error details
    error_type: str = ""
    error_message: str = ""
    error_traceback: str = ""
    # For visual regression
    session_id: str = ""
    previous_session_id: str = ""
    overall_score: float = 0.0
    is_baseline: bool = False
    screenshots_compared: str = ""  # JSON array of screenshot comparisons


def _get_config():
    """Get RVBBIT configuration."""
    from rvbbit.config import get_config
    return get_config()


def _get_db():
    """Get ClickHouse connection."""
    from rvbbit.db_adapter import get_db_adapter
    return get_db_adapter()


# =============================================================================
# Test Discovery
# =============================================================================

def discover_semantic_sql_tests(filter_pattern: Optional[str] = None) -> List[TestDefinition]:
    """Discover all semantic SQL tests from cascade files."""
    import yaml

    config = _get_config()
    cascades_dir = Path(config.cascades_dir)
    semantic_sql_dir = cascades_dir / 'semantic_sql'

    tests = []

    if not semantic_sql_dir.exists():
        return tests

    for cascade_file in semantic_sql_dir.glob('*.cascade.yaml'):
        try:
            with open(cascade_file) as f:
                cascade = yaml.safe_load(f)
        except Exception:
            continue

        sql_fn = cascade.get('sql_function', {})
        fn_name = sql_fn.get('name', '')
        test_cases = sql_fn.get('test_cases', [])

        if not test_cases:
            continue

        # Apply filter
        if filter_pattern:
            if not fnmatch.fnmatch(fn_name, filter_pattern):
                continue

        for i, test in enumerate(test_cases):
            sql = test.get('sql', '')
            expect = test.get('expect')
            description = test.get('description', f"Test {i+1}")
            skip = test.get('skip', False)

            # Determine expect type
            if isinstance(expect, dict):
                expect_type = expect.get('type', 'complex')
            elif isinstance(expect, bool):
                expect_type = 'boolean'
            elif isinstance(expect, (int, float)):
                expect_type = 'numeric'
            else:
                expect_type = 'exact'

            test_id = f"semantic_sql/{fn_name}/{i}"

            tests.append(TestDefinition(
                test_id=test_id,
                test_type="semantic_sql",
                test_group=f"semantic_sql/{fn_name}",
                test_name=description,
                description=description,
                source_file=str(cascade_file),
                source_line=0,
                sql_query=sql,
                expect=expect,
                expect_type=expect_type,
                validation_modes=['skipped'] if skip else ['internal', 'simple', 'extended']
            ))

    return tests


def discover_snapshot_tests(filter_pattern: Optional[str] = None) -> List[TestDefinition]:
    """Discover all cascade snapshot tests."""
    from rvbbit.testing import SnapshotValidator

    validator = SnapshotValidator()
    tests = []

    for snapshot_file in validator.snapshot_dir.glob('*.json'):
        snapshot_name = snapshot_file.stem

        # Apply filter
        if filter_pattern:
            if not fnmatch.fnmatch(snapshot_name, filter_pattern):
                continue

        try:
            with open(snapshot_file) as f:
                snapshot = json.load(f)

            meta = snapshot.get('metadata', {})
            contracts = snapshot.get('contracts', {})
            anchors = snapshot.get('anchors', [])

            test_id = f"cascade_snapshot/{snapshot_name}"

            tests.append(TestDefinition(
                test_id=test_id,
                test_type="cascade_snapshot",
                test_group="cascade_snapshot",
                test_name=meta.get('name', snapshot_name),
                description=meta.get('description', ''),
                source_file=str(snapshot_file),
                validation_modes=['structure', 'contracts', 'anchors', 'deterministic', 'full'],
                has_contracts=bool(contracts),
                has_anchors=bool(anchors)
            ))
        except Exception:
            continue

    return tests


def discover_visual_tests(filter_pattern: Optional[str] = None) -> List[TestDefinition]:
    """
    Discover visual regression tests from browsers/visual_tests/*.visual.yaml
    """
    import yaml

    config = _get_config()
    browsers_dir = os.path.join(config.root_dir, 'browsers', 'visual_tests')

    tests = []

    if not os.path.isdir(browsers_dir):
        return tests

    for filename in os.listdir(browsers_dir):
        if not filename.endswith('.visual.yaml'):
            continue

        filepath = os.path.join(browsers_dir, filename)
        try:
            with open(filepath) as f:
                spec = yaml.safe_load(f)

            if not spec:
                continue

            test_id = spec.get('test_id', f"visual/{filename.replace('.visual.yaml', '')}")
            test_name = test_id.split('/')[-1] if '/' in test_id else test_id

            # Apply filter if provided
            if filter_pattern and filter_pattern.lower() not in test_id.lower():
                continue

            tests.append(TestDefinition(
                test_id=test_id,
                test_type='visual_regression',
                test_group=spec.get('group', 'visual'),
                test_name=test_name,
                description=spec.get('description', ''),
                source_file=filepath,
                source_line=0,
                initial_url=spec.get('initial_url', ''),
                browser_batch=spec.get('browser_batch', []),
                threshold=spec.get('threshold', 0.95)
            ))

        except Exception as e:
            print(f"[TestsAPI] Error loading visual test {filename}: {e}")

    return tests


def discover_all_tests(filter_pattern: Optional[str] = None) -> Dict[str, List[TestDefinition]]:
    """Discover all tests from all sources."""
    return {
        'semantic_sql': discover_semantic_sql_tests(filter_pattern),
        'cascade_snapshot': discover_snapshot_tests(filter_pattern),
        'visual_regression': discover_visual_tests(filter_pattern)
    }


# =============================================================================
# Test Execution
# =============================================================================

# Module-level DuckDB connection and lock for internal tests
_duckdb_conn = None
_duckdb_lock = None
_rewriter_func = None


def _get_duckdb_executor():
    """Get or create the DuckDB executor for internal tests."""
    global _duckdb_conn, _duckdb_lock, _rewriter_func

    if _duckdb_conn is None:
        from rvbbit.sql_tools.session_db import get_session_db, get_session_lock
        from rvbbit.sql_tools.udf import register_rvbbit_udf, register_dynamic_sql_functions
        from rvbbit.semantic_sql.registry import initialize_registry
        from rvbbit.sql_rewriter import rewrite_rvbbit_syntax

        # Initialize registry for semantic SQL functions
        initialize_registry(force=True)

        # Use a special session for tests
        session_id = '_tests_api_session'
        _duckdb_conn = get_session_db(session_id)
        _duckdb_lock = get_session_lock(session_id)

        # Register all UDFs
        with _duckdb_lock:
            register_rvbbit_udf(_duckdb_conn)
            register_dynamic_sql_functions(_duckdb_conn)

        _rewriter_func = rewrite_rvbbit_syntax

    return _duckdb_conn, _duckdb_lock, _rewriter_func


def _execute_internal_sql(sql: str, timeout_seconds: int = 120) -> tuple:
    """Execute SQL via internal DuckDB connection with timeout."""
    conn, lock, rewriter_func = _get_duckdb_executor()

    if conn is None or lock is None or rewriter_func is None:
        return None, "DuckDB executor not initialized"

    def _run_sql():
        rewritten_sql = rewriter_func(sql, duckdb_conn=conn)
        with lock:
            result = conn.execute(rewritten_sql)
            df = result.fetchdf()
        if df.empty:
            return None, None
        return df.iloc[0, 0], None

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run_sql)
            try:
                return future.result(timeout=timeout_seconds)
            except FuturesTimeoutError:
                return None, f"Query timed out after {timeout_seconds}s"
    except Exception as e:
        return None, str(e)


def _execute_psql_simple_sql(sql: str, host: str = 'localhost', port: int = 15432, database: str = 'rvbbit') -> tuple:
    """Execute SQL via psql CLI (Simple Query Protocol)."""
    try:
        result = subprocess.run(
            [
                'psql',
                '-h', host,
                '-p', str(port),
                '-d', database,
                '-U', 'user',
                '-t',
                '-A',
                '-c', sql
            ],
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, 'PGPASSWORD': ''}
        )

        if result.returncode != 0:
            error = result.stderr.strip()
            if 'ERROR:' in error:
                error = error.split('ERROR:')[1].split('\n')[0].strip()
            return None, error

        output = result.stdout.strip()
        if not output:
            return None, None

        value = output.split('\n')[0].strip()
        return value, None

    except subprocess.TimeoutExpired:
        return None, "Query timed out (120s)"
    except FileNotFoundError:
        return None, "psql not found - install postgresql-client"
    except Exception as e:
        return None, str(e)


def _execute_extended_sql(sql: str, host: str = 'localhost', port: int = 15432, database: str = 'rvbbit') -> tuple:
    """Execute SQL via psycopg2 (Extended Query Protocol)."""
    try:
        import psycopg2

        conn = psycopg2.connect(
            host=host,
            port=port,
            database=database,
            user='user',
            password=''
        )

        with conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()

        conn.close()

        if row is None:
            return None, None
        return row[0], None

    except ImportError:
        return None, "psycopg2 not installed"
    except Exception as e:
        return None, str(e)


def _run_semantic_sql_test(test: TestDefinition, mode: str = 'internal') -> TestResult:
    """Execute a single semantic SQL test."""
    start_time = datetime.now(timezone.utc)
    result = TestResult(
        test_id=test.test_id,
        test_type=test.test_type,
        test_group=test.test_group,
        test_name=test.test_name,
        description=test.description,
        source_file=test.source_file,
        source_line=test.source_line,
        sql_query=test.sql_query,
        expect_type=test.expect_type,
        expected_value=json.dumps(_json_safe(test.expect)) if test.expect else "",
        validation_mode=mode,
        status='pending'
    )

    # Check if test is skipped
    if 'skipped' in test.validation_modes and len(test.validation_modes) == 1:
        result.status = 'skipped'
        result.duration_ms = 0
        return result

    try:
        if mode == 'internal':
            actual, error = _execute_internal_sql(test.sql_query)
        elif mode == 'simple':
            actual, error = _execute_psql_simple_sql(test.sql_query)
        else:  # extended
            actual, error = _execute_extended_sql(test.sql_query)

        if error:
            result.status = 'error'
            result.error_type = 'ExecutionError'
            result.error_message = error
        else:
            result.actual_value = json.dumps(_json_safe(actual)) if actual is not None else "NULL"
            passed = _check_expectation(actual, test.expect)
            result.status = 'passed' if passed else 'failed'

            if not passed:
                result.failure_type = 'assertion'
                result.failure_message = f"Expected {test.expect}, got {actual}"
                result.failure_diff = f"Expected: {json.dumps(_json_safe(test.expect))}\nActual: {json.dumps(_json_safe(actual))}"

    except Exception as e:
        result.status = 'error'
        result.error_type = type(e).__name__
        result.error_message = str(e)
        result.error_traceback = traceback.format_exc()

    end_time = datetime.now(timezone.utc)
    result.duration_ms = (end_time - start_time).total_seconds() * 1000

    return result


def _check_expectation(actual: Any, expect: Any) -> bool:
    """Check if actual value matches expectation."""
    if expect is None:
        return actual is None

    if isinstance(expect, dict):
        expect_type = expect.get('type', 'exact')

        if expect_type == 'contains':
            value = expect.get('value', '')
            return value.lower() in str(actual).lower()

        elif expect_type == 'range':
            min_val = expect.get('min', float('-inf'))
            max_val = expect.get('max', float('inf'))
            try:
                return min_val <= float(actual) <= max_val
            except (ValueError, TypeError):
                return False

        elif expect_type == 'one_of':
            values = expect.get('values', [])
            return actual in values

        elif expect_type == 'regex':
            import re
            pattern = expect.get('pattern', '')
            return bool(re.search(pattern, str(actual)))

        elif expect_type == 'not_empty':
            return bool(actual)

        else:
            return actual == expect

    # Boolean comparison
    if isinstance(expect, bool):
        if isinstance(actual, bool):
            return actual == expect
        if isinstance(actual, str):
            return actual.lower() == str(expect).lower()
        return bool(actual) == expect

    # Numeric comparison with tolerance
    if isinstance(expect, (int, float)):
        try:
            return abs(float(actual) - expect) < 0.0001
        except (ValueError, TypeError):
            return str(actual) == str(expect)

    # String comparison
    return str(actual).lower() == str(expect).lower()


def _run_snapshot_test(test: TestDefinition, mode: str = 'structure') -> TestResult:
    """Execute a single cascade snapshot test."""
    from rvbbit.testing import SnapshotValidator

    start_time = datetime.now(timezone.utc)
    result = TestResult(
        test_id=test.test_id,
        test_type=test.test_type,
        test_group=test.test_group,
        test_name=test.test_name,
        description=test.description,
        source_file=test.source_file,
        validation_mode=mode,
        status='pending'
    )

    snapshot_name = test.test_id.split('/')[-1]

    try:
        validator = SnapshotValidator()
        replay_result = validator.validate(snapshot_name, verbose=False, mode=mode)

        result.status = 'passed' if replay_result.passed else 'failed'

        if replay_result.contract_results:
            result.contracts_checked = len(replay_result.contract_results)
            result.contracts_passed = sum(1 for passed, _ in replay_result.contract_results if passed)

        if replay_result.anchor_results:
            result.anchors_checked = len(replay_result.anchor_results)
            result.anchors_passed = sum(1 for passed, _ in replay_result.anchor_results if passed)

        result.cells_validated = len(replay_result.checks) if replay_result.checks else 0

        if not replay_result.passed:
            result.failure_type = 'validation'
            failures = replay_result.failures or []
            if failures:
                result.failure_message = failures[0].get('message', 'Validation failed')
                result.failure_diff = json.dumps(_json_safe(failures), indent=2)

    except Exception as e:
        result.status = 'error'
        result.error_type = type(e).__name__
        result.error_message = str(e)
        result.error_traceback = traceback.format_exc()

    end_time = datetime.now(timezone.utc)
    result.duration_ms = (end_time - start_time).total_seconds() * 1000

    return result


def _run_visual_test(test: TestDefinition, db) -> TestResult:
    """Execute a single visual regression test."""
    import subprocess
    import uuid
    from rvbbit.visual_compare import compare_sessions, VisualTestResult

    start_time = datetime.now(timezone.utc)
    result = TestResult(
        test_id=test.test_id,
        test_type=test.test_type,
        test_group=test.test_group,
        test_name=test.test_name,
        description=test.description,
        source_file=test.source_file,
        validation_mode='visual',
        status='pending'
    )

    config = _get_config()
    browsers_dir = os.path.join(config.root_dir, 'browsers')

    # Generate session ID for this run
    session_id = f"visual_{test.test_id.replace('/', '_')}_{uuid.uuid4().hex[:8]}"

    try:
        # Find previous run for this test from ClickHouse
        previous_session_id = None
        try:
            prev_rows = db.query("""
                SELECT session_id FROM test_results
                WHERE test_id = %(test_id)s
                  AND test_type = 'visual_regression'
                  AND session_id != ''
                ORDER BY started_at DESC
                LIMIT 1
            """, {'test_id': test.test_id})
            if prev_rows:
                previous_session_id = prev_rows[0]['session_id']
        except Exception as e:
            print(f"[TestsAPI] Could not find previous visual run: {e}")

        # Convert browser batch to JSON string
        commands_json = json.dumps(test.browser_batch)

        # Run browser batch via CLI
        cmd = [
            'rvbbit', 'browser', 'batch',
            '--url', test.initial_url or 'http://localhost:5550',
            '--commands', commands_json,
            '--client-id', session_id
        ]

        print(f"[TestsAPI] Running visual test: {' '.join(cmd)}")
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if proc.returncode != 0:
            result.status = 'error'
            result.error_type = 'BrowserBatchError'
            result.error_message = proc.stderr[:500] if proc.stderr else 'Browser batch failed'
            return result

        # Compare screenshots to previous run
        current_session_path = os.path.join(browsers_dir, session_id)
        previous_session_path = os.path.join(browsers_dir, previous_session_id) if previous_session_id else None

        # Create diff output directory
        diff_dir = os.path.join(browsers_dir, 'visual_diffs', test.test_id.replace('/', '_'), session_id)
        os.makedirs(diff_dir, exist_ok=True)

        comparison = compare_sessions(
            previous_session_path=previous_session_path,
            current_session_path=current_session_path,
            test_id=test.test_id,
            threshold=test.threshold,
            diff_output_dir=diff_dir
        )

        # Populate result
        result.session_id = session_id
        result.previous_session_id = previous_session_id or ''
        result.overall_score = comparison.overall_score
        result.is_baseline = comparison.is_baseline
        result.screenshots_compared = json.dumps([
            {
                'name': s.name,
                'similarity': s.similarity,
                'passed': s.passed,
                'previous_path': s.previous_path,
                'current_path': s.current_path,
                'diff_path': s.diff_path,
                'error': s.error
            }
            for s in comparison.screenshots
        ])

        if comparison.is_baseline:
            result.status = 'passed'
            result.failure_message = 'Baseline established (first run)'
        elif comparison.passed:
            result.status = 'passed'
        else:
            result.status = 'failed'
            result.failure_type = 'visual_drift'
            failed_screenshots = [s for s in comparison.screenshots if not s.passed]
            result.failure_message = f"{len(failed_screenshots)} screenshots below threshold ({test.threshold:.0%})"

    except subprocess.TimeoutExpired:
        result.status = 'error'
        result.error_type = 'Timeout'
        result.error_message = 'Browser batch timed out after 120s'
    except Exception as e:
        result.status = 'error'
        result.error_type = type(e).__name__
        result.error_message = str(e)
        result.error_traceback = traceback.format_exc()

    end_time = datetime.now(timezone.utc)
    result.duration_ms = (end_time - start_time).total_seconds() * 1000

    return result


def execute_tests(tests: List[TestDefinition], run_id: str, options: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a batch of tests synchronously."""
    results: List[TestResult] = []
    fail_fast = options.get('fail_fast', False)
    ssql_mode = options.get('ssql_mode', 'internal')
    snapshot_mode = options.get('snapshot_mode', 'structure')

    db = _get_db()

    # Determine run type
    types = set(t.test_type for t in tests)
    if len(types) == 2:
        run_type = 'mixed'
    elif 'semantic_sql' in types:
        run_type = 'semantic_sql'
    else:
        run_type = 'cascade_snapshot'

    # Calculate total test executions (SQL full mode runs 3x)
    sql_count = sum(1 for t in tests if t.test_type == 'semantic_sql')
    snapshot_count = len(tests) - sql_count
    if ssql_mode == 'full':
        total_executions = sql_count * 3 + snapshot_count
    else:
        total_executions = len(tests)

    # Insert run record
    started_at = datetime.now(timezone.utc)
    try:
        db.execute("""
            INSERT INTO test_runs (
                run_id, run_type, started_at, status, total_tests,
                trigger, trigger_source, test_filter, run_options
            ) VALUES (
                %(run_id)s, %(run_type)s, %(started_at)s, 'running', %(total_tests)s,
                %(trigger)s, %(trigger_source)s, %(test_filter)s, %(run_options)s
            )
        """, {
            'run_id': run_id,
            'run_type': run_type,
            'started_at': started_at,
            'total_tests': total_executions,
            'trigger': options.get('trigger', 'manual'),
            'trigger_source': options.get('trigger_source', ''),
            'test_filter': options.get('filter', ''),
            'run_options': json.dumps(options)
        })
        print(f"[TestsAPI] Created run record: {run_id} ({total_executions} test executions)")
    except Exception as e:
        print(f"[TestsAPI] Failed to create run record: {e}")
        # Continue anyway - we can still run tests and return results

    passed_count = 0
    failed_count = 0
    error_count = 0
    skipped_count = 0
    should_stop = False

    for i, test in enumerate(tests):
        if should_stop:
            break

        print(f"[TestsAPI] Running test {i+1}/{len(tests)}: {test.test_id}")

        # Determine which modes to run
        if test.test_type == 'semantic_sql':
            if ssql_mode == 'full':
                modes_to_run = ['internal', 'simple', 'extended']
            else:
                modes_to_run = [ssql_mode]
        elif test.test_type == 'visual_regression':
            modes_to_run = ['visual']  # Visual tests have only one mode
        else:
            modes_to_run = [snapshot_mode]

        # Execute test for each mode
        for mode in modes_to_run:
            if should_stop:
                break

            mode_label = f" [{mode}]" if len(modes_to_run) > 1 else ""
            try:
                if test.test_type == 'semantic_sql':
                    result = _run_semantic_sql_test(test, mode=mode)
                elif test.test_type == 'visual_regression':
                    result = _run_visual_test(test, db)
                else:
                    result = _run_snapshot_test(test, mode=mode)
            except Exception as e:
                # Create error result for crashed test
                print(f"[TestsAPI]   CRASH{mode_label}: {type(e).__name__}: {str(e)[:200]}")
                result = TestResult(
                    test_id=test.test_id,
                    test_type=test.test_type,
                    test_group=test.test_group,
                    test_name=test.test_name,
                    description=test.description,
                    source_file=test.source_file,
                    source_line=test.source_line,
                    sql_query=test.sql_query,
                    validation_mode=mode,
                    status='error',
                    error_type=type(e).__name__,
                    error_message=f"Test crashed: {str(e)}",
                    error_traceback=traceback.format_exc(),
                    duration_ms=0
                )

            print(f"[TestsAPI]   Result{mode_label}: {result.status} ({result.duration_ms:.1f}ms)")
            if result.error_message:
                print(f"[TestsAPI]   Error: {result.error_message[:200]}")

            results.append(result)

            # Update counts
            if result.status == 'passed':
                passed_count += 1
            elif result.status == 'failed':
                failed_count += 1
                if fail_fast:
                    should_stop = True
            elif result.status == 'error':
                error_count += 1
                if fail_fast:
                    should_stop = True
            elif result.status == 'skipped':
                skipped_count += 1

            # Store result
            try:
                _store_test_result(run_id, result)
            except Exception as e:
                print(f"[TestsAPI]   Failed to store result: {e}")

    # Update run record
    completed_at = datetime.now(timezone.utc)
    duration_ms = (completed_at - started_at).total_seconds() * 1000
    final_status = 'passed' if failed_count == 0 and error_count == 0 else 'failed'

    db.execute("""
        ALTER TABLE test_runs UPDATE
            completed_at = %(completed_at)s,
            duration_ms = %(duration_ms)s,
            status = %(status)s,
            passed_tests = %(passed)s,
            failed_tests = %(failed)s,
            error_tests = %(error)s,
            skipped_tests = %(skipped)s
        WHERE run_id = %(run_id)s
    """, {
        'run_id': run_id,
        'completed_at': completed_at,
        'duration_ms': duration_ms,
        'status': final_status,
        'passed': passed_count,
        'failed': failed_count,
        'error': error_count,
        'skipped': skipped_count
    })

    return {
        'run_id': run_id,
        'status': final_status,
        'duration_ms': duration_ms,
        'total': len(tests),
        'passed': passed_count,
        'failed': failed_count,
        'error': error_count,
        'skipped': skipped_count,
        'results': [_json_safe(asdict(r)) for r in results]
    }


def _store_test_result(run_id: str, result: TestResult):
    """Store a test result in ClickHouse."""
    db = _get_db()

    # Base columns that always exist
    base_columns = """
        run_id, test_id, test_type, test_group, test_name, test_description,
        source_file, source_line, started_at, completed_at, duration_ms, status,
        sql_query, expected_value, actual_value, expect_type,
        validation_mode, cells_validated, contracts_checked, contracts_passed,
        anchors_checked, anchors_passed, judge_score, judge_reasoning,
        failure_type, failure_message, failure_diff,
        error_type, error_message, error_traceback
    """
    base_values = """
        %(run_id)s, %(test_id)s, %(test_type)s, %(test_group)s, %(test_name)s, %(description)s,
        %(source_file)s, %(source_line)s, %(started_at)s, %(completed_at)s, %(duration_ms)s, %(status)s,
        %(sql_query)s, %(expected_value)s, %(actual_value)s, %(expect_type)s,
        %(validation_mode)s, %(cells_validated)s, %(contracts_checked)s, %(contracts_passed)s,
        %(anchors_checked)s, %(anchors_passed)s, %(judge_score)s, %(judge_reasoning)s,
        %(failure_type)s, %(failure_message)s, %(failure_diff)s,
        %(error_type)s, %(error_message)s, %(error_traceback)s
    """

    base_params = {
        'run_id': run_id,
        'test_id': result.test_id,
        'test_type': result.test_type,
        'test_group': result.test_group,
        'test_name': result.test_name,
        'description': result.description,
        'source_file': result.source_file,
        'source_line': result.source_line,
        'started_at': datetime.now(timezone.utc),
        'completed_at': datetime.now(timezone.utc),
        'duration_ms': result.duration_ms,
        'status': result.status,
        'sql_query': result.sql_query,
        'expected_value': result.expected_value,
        'actual_value': result.actual_value,
        'expect_type': result.expect_type,
        'validation_mode': result.validation_mode,
        'cells_validated': result.cells_validated,
        'contracts_checked': result.contracts_checked,
        'contracts_passed': result.contracts_passed,
        'anchors_checked': result.anchors_checked,
        'anchors_passed': result.anchors_passed,
        'judge_score': result.judge_score,
        'judge_reasoning': result.judge_reasoning,
        'failure_type': result.failure_type,
        'failure_message': result.failure_message,
        'failure_diff': result.failure_diff,
        'error_type': result.error_type,
        'error_message': result.error_message,
        'error_traceback': result.error_traceback,
    }

    # Try with visual columns first
    try:
        visual_columns = ", session_id, previous_session_id, overall_score, is_baseline, screenshots_compared"
        visual_values = ", %(session_id)s, %(previous_session_id)s, %(overall_score)s, %(is_baseline)s, %(screenshots_compared)s"
        visual_params = {
            'session_id': result.session_id,
            'previous_session_id': result.previous_session_id,
            'overall_score': result.overall_score,
            'is_baseline': 1 if result.is_baseline else 0,
            'screenshots_compared': result.screenshots_compared
        }

        db.execute(f"""
            INSERT INTO test_results ({base_columns}{visual_columns})
            VALUES ({base_values}{visual_values})
        """, {**base_params, **visual_params})
    except Exception as e:
        # Fall back to base columns only if visual columns don't exist
        if 'session_id' in str(e) or 'No such column' in str(e):
            db.execute(f"""
                INSERT INTO test_results ({base_columns})
                VALUES ({base_values})
            """, base_params)
        else:
            raise


# =============================================================================
# API Endpoints
# =============================================================================

@tests_bp.route('/api/tests', methods=['GET'])
def list_tests():
    """
    Discover all available tests.

    Query params:
        type: Filter by test type (semantic_sql, cascade_snapshot)
        filter: Pattern filter (e.g., "quality*", "routing*")

    Returns:
        Discovered tests grouped by type
    """
    try:
        test_type = request.args.get('type')
        filter_pattern = request.args.get('filter')

        all_tests = discover_all_tests(filter_pattern)

        if test_type:
            all_tests = {k: v for k, v in all_tests.items() if k == test_type}

        # Convert to dicts
        result = {}
        total = 0
        for type_name, tests in all_tests.items():
            result[type_name] = [_json_safe(asdict(t)) for t in tests]
            total += len(tests)

        return jsonify({
            'tests': result,
            'total': total,
            'counts': {k: len(v) for k, v in result.items()}
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@tests_bp.route('/api/tests/run', methods=['POST'])
def run_tests():
    """
    Execute tests synchronously.

    Request body:
        test_ids: List of test IDs to run (optional, runs all if not specified)
        type: Test type filter (semantic_sql, cascade_snapshot)
        filter: Pattern filter
        fail_fast: Stop on first failure (default: false)
        ssql_mode: Mode for semantic SQL tests (internal, simple, extended)
        snapshot_mode: Mode for snapshot tests (structure, contracts, anchors, deterministic, full)

    Returns:
        Full test run results
    """
    try:
        data = request.get_json(silent=True) or {}

        test_ids = data.get('test_ids', [])
        test_type = data.get('type')
        filter_pattern = data.get('filter')

        # Discover tests
        all_tests = discover_all_tests(filter_pattern)

        if test_type:
            all_tests = {k: v for k, v in all_tests.items() if k == test_type}

        # Flatten and filter
        tests = []
        for type_tests in all_tests.values():
            for test in type_tests:
                if not test_ids or test.test_id in test_ids:
                    tests.append(test)

        if not tests:
            return jsonify({'error': 'No tests found matching criteria'}), 404

        print(f"[TestsAPI] Running {len(tests)} tests...")
        for t in tests[:5]:  # Log first 5
            print(f"  - {t.test_id}: {t.test_name}")
        if len(tests) > 5:
            print(f"  ... and {len(tests) - 5} more")

        # Create run
        run_id = f"test_run_{uuid.uuid4().hex[:12]}"

        options = {
            'fail_fast': data.get('fail_fast', False),
            'ssql_mode': data.get('ssql_mode', 'internal'),
            'snapshot_mode': data.get('snapshot_mode', 'structure'),
            'filter': filter_pattern or '',
            'trigger': 'api',
            'trigger_source': 'studio'
        }

        # Execute synchronously
        print(f"[TestsAPI] Starting execution with run_id={run_id}")
        result = execute_tests(tests, run_id, options)
        print(f"[TestsAPI] Execution complete: {result.get('passed', 0)} passed, {result.get('failed', 0)} failed")

        return jsonify(result)

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@tests_bp.route('/api/tests/runs', methods=['GET'])
def list_runs():
    """
    Get historical test runs.

    Query params:
        status: Filter by status (running, passed, failed, error)
        type: Filter by run type (semantic_sql, cascade_snapshot, mixed)
        limit: Max results (default: 50)
        offset: Offset for pagination

    Returns:
        List of test runs with summary stats
    """
    try:
        db = _get_db()

        status = request.args.get('status')
        run_type = request.args.get('type')
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))

        where_clauses = []
        params = {}

        if status:
            where_clauses.append("status = %(status)s")
            params['status'] = status

        if run_type:
            where_clauses.append("run_type = %(run_type)s")
            params['run_type'] = run_type

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        query = f"""
            SELECT
                run_id, run_type, started_at, completed_at, duration_ms, status,
                total_tests, passed_tests, failed_tests, error_tests, skipped_tests,
                trigger, trigger_source, test_filter
            FROM test_runs
            WHERE {where_sql}
            ORDER BY started_at DESC
            LIMIT %(limit)s OFFSET %(offset)s
        """
        params['limit'] = limit
        params['offset'] = offset

        rows = db.query(query, params)

        # Get total count
        count_query = f"SELECT count() as cnt FROM test_runs WHERE {where_sql}"
        count_result = db.query(count_query, params)
        total = count_result[0]['cnt'] if count_result else 0

        runs = []
        for row in rows:
            runs.append({
                'run_id': row['run_id'],
                'run_type': row['run_type'],
                'started_at': row['started_at'].isoformat() if row.get('started_at') else None,
                'completed_at': row['completed_at'].isoformat() if row.get('completed_at') else None,
                'duration_ms': row.get('duration_ms'),
                'status': row['status'],
                'total_tests': row.get('total_tests'),
                'passed_tests': row.get('passed_tests'),
                'failed_tests': row.get('failed_tests'),
                'error_tests': row.get('error_tests'),
                'skipped_tests': row.get('skipped_tests'),
                'trigger': row.get('trigger'),
                'trigger_source': row.get('trigger_source'),
                'test_filter': row.get('test_filter')
            })

        return jsonify({
            'runs': runs,
            'total': total,
            'limit': limit,
            'offset': offset
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@tests_bp.route('/api/tests/runs/<run_id>', methods=['GET'])
def get_run(run_id: str):
    """
    Get detailed results for a specific test run.
    """
    try:
        db = _get_db()

        # Get run metadata
        run_query = """
            SELECT
                run_id, run_type, started_at, completed_at, duration_ms, status,
                total_tests, passed_tests, failed_tests, error_tests, skipped_tests,
                trigger, trigger_source, test_filter, run_options, error_message, error_traceback
            FROM test_runs
            WHERE run_id = %(run_id)s
        """
        run_rows = db.query(run_query, {'run_id': run_id})

        if not run_rows:
            return jsonify({'error': 'Run not found'}), 404

        row = run_rows[0]
        run = {
            'run_id': row['run_id'],
            'run_type': row['run_type'],
            'started_at': row['started_at'].isoformat() if row.get('started_at') else None,
            'completed_at': row['completed_at'].isoformat() if row.get('completed_at') else None,
            'duration_ms': row.get('duration_ms'),
            'status': row['status'],
            'total_tests': row.get('total_tests'),
            'passed_tests': row.get('passed_tests'),
            'failed_tests': row.get('failed_tests'),
            'error_tests': row.get('error_tests'),
            'skipped_tests': row.get('skipped_tests'),
            'trigger': row.get('trigger'),
            'trigger_source': row.get('trigger_source'),
            'test_filter': row.get('test_filter'),
            'run_options': json.loads(row['run_options']) if row.get('run_options') else {},
            'error_message': row.get('error_message'),
            'error_traceback': row.get('error_traceback')
        }

        # Get test results - check if visual columns exist first
        try:
            # Try with visual columns
            results_query = """
                SELECT
                    test_id, test_type, test_group, test_name, test_description,
                    source_file, source_line, duration_ms, status,
                    sql_query, expected_value, actual_value, expect_type,
                    validation_mode, cells_validated, contracts_checked, contracts_passed,
                    anchors_checked, anchors_passed, judge_score, judge_reasoning,
                    failure_type, failure_message, failure_diff,
                    error_type, error_message, error_traceback,
                    session_id, previous_session_id, overall_score, is_baseline, screenshots_compared
                FROM test_results
                WHERE run_id = %(run_id)s
                ORDER BY test_type, test_group, test_id
            """
            result_rows = db.query(results_query, {'run_id': run_id})
            has_visual_columns = True
        except Exception:
            # Fallback without visual columns
            results_query = """
                SELECT
                    test_id, test_type, test_group, test_name, test_description,
                    source_file, source_line, duration_ms, status,
                    sql_query, expected_value, actual_value, expect_type,
                    validation_mode, cells_validated, contracts_checked, contracts_passed,
                    anchors_checked, anchors_passed, judge_score, judge_reasoning,
                    failure_type, failure_message, failure_diff,
                    error_type, error_message, error_traceback
                FROM test_results
                WHERE run_id = %(run_id)s
                ORDER BY test_type, test_group, test_id
            """
            result_rows = db.query(results_query, {'run_id': run_id})
            has_visual_columns = False

        results = []
        for row in result_rows:
            result = {
                'test_id': row['test_id'],
                'test_type': row['test_type'],
                'test_group': row['test_group'],
                'test_name': row['test_name'],
                'test_description': row.get('test_description'),
                'source_file': row.get('source_file'),
                'source_line': row.get('source_line'),
                'duration_ms': row.get('duration_ms'),
                'status': row['status'],
                'sql_query': row.get('sql_query'),
                'expected_value': row.get('expected_value'),
                'actual_value': row.get('actual_value'),
                'expect_type': row.get('expect_type'),
                'validation_mode': row.get('validation_mode'),
                'cells_validated': row.get('cells_validated'),
                'contracts_checked': row.get('contracts_checked'),
                'contracts_passed': row.get('contracts_passed'),
                'anchors_checked': row.get('anchors_checked'),
                'anchors_passed': row.get('anchors_passed'),
                'judge_score': row.get('judge_score'),
                'judge_reasoning': row.get('judge_reasoning'),
                'failure_type': row.get('failure_type'),
                'failure_message': row.get('failure_message'),
                'failure_diff': row.get('failure_diff'),
                'error_type': row.get('error_type'),
                'error_message': row.get('error_message'),
                'error_traceback': row.get('error_traceback'),
            }
            if has_visual_columns:
                result['session_id'] = row.get('session_id')
                result['previous_session_id'] = row.get('previous_session_id')
                result['overall_score'] = row.get('overall_score')
                result['is_baseline'] = bool(row.get('is_baseline'))
                result['screenshots_compared'] = row.get('screenshots_compared')
            results.append(result)

        return jsonify({
            'run': run,
            'results': results
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@tests_bp.route('/api/tests/stats', methods=['GET'])
def get_test_stats():
    """
    Get test dashboard statistics.

    Query params:
        days: Number of days to look back (default: 7)

    Returns:
        Summary statistics and trends
    """
    try:
        db = _get_db()
        days = int(request.args.get('days', 7))

        # Recent run stats
        recent_query = """
            SELECT
                run_type,
                status,
                count() as run_count,
                sum(passed_tests) as total_passed,
                sum(failed_tests) as total_failed,
                sum(error_tests) as total_errors,
                avg(duration_ms) as avg_duration_ms
            FROM test_runs
            WHERE started_at >= now() - INTERVAL %(days)s DAY
            GROUP BY run_type, status
        """
        recent_rows = db.query(recent_query, {'days': days})

        recent_stats = {}
        for row in recent_rows:
            run_type = row['run_type']
            if run_type not in recent_stats:
                recent_stats[run_type] = {}
            recent_stats[run_type][row['status']] = {
                'run_count': row['run_count'],
                'total_passed': row['total_passed'],
                'total_failed': row['total_failed'],
                'total_errors': row['total_errors'],
                'avg_duration_ms': row['avg_duration_ms']
            }

        # Daily trends
        trend_query = """
            SELECT
                toDate(started_at) as date,
                sum(passed_tests) as passed,
                sum(failed_tests) as failed,
                sum(error_tests) as errors,
                count() as run_count
            FROM test_runs
            WHERE started_at >= now() - INTERVAL %(days)s DAY
            GROUP BY date
            ORDER BY date
        """
        trend_rows = db.query(trend_query, {'days': days})

        daily_trends = [
            {
                'date': row['date'].isoformat() if row.get('date') else None,
                'passed': row.get('passed', 0),
                'failed': row.get('failed', 0),
                'errors': row.get('errors', 0),
                'run_count': row.get('run_count', 0)
            }
            for row in trend_rows
        ]

        return jsonify({
            'recent_stats': recent_stats,
            'daily_trends': daily_trends,
            'days': days
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@tests_bp.route('/api/tests/history/bulk', methods=['GET'])
def get_bulk_test_history():
    """
    Get execution history for all tests (last N runs per test, grouped by mode).
    Efficient bulk endpoint for grid sparklines.

    Query params:
        limit: Number of recent runs per test per mode (default: 10)

    Returns:
        Dictionary mapping test_id -> {mode -> list of {status, run_id}} ordered newest first
    """
    try:
        db = _get_db()
        limit = int(request.args.get('limit', 10))

        # Get last N results per test+mode using window function
        # Mode comes from validation_mode (set on each result), falling back to run_options
        query = """
            SELECT
                sub.test_id,
                sub.test_type,
                sub.status,
                sub.run_id,
                sub.mode
            FROM (
                SELECT
                    tr.test_id,
                    tr.test_type,
                    tr.status,
                    tr.run_id,
                    r.started_at,
                    CASE
                        WHEN tr.test_type = 'semantic_sql' THEN
                            coalesce(nullIf(tr.validation_mode, ''), JSONExtractString(r.run_options, 'ssql_mode'), 'internal')
                        WHEN tr.test_type = 'visual_regression' THEN
                            coalesce(nullIf(tr.validation_mode, ''), 'visual')
                        ELSE
                            coalesce(nullIf(tr.validation_mode, ''), JSONExtractString(r.run_options, 'snapshot_mode'), 'structure')
                    END as mode,
                    row_number() OVER (
                        PARTITION BY tr.test_id,
                        CASE
                            WHEN tr.test_type = 'semantic_sql' THEN
                                coalesce(nullIf(tr.validation_mode, ''), JSONExtractString(r.run_options, 'ssql_mode'), 'internal')
                            WHEN tr.test_type = 'visual_regression' THEN
                                coalesce(nullIf(tr.validation_mode, ''), 'visual')
                            ELSE
                                coalesce(nullIf(tr.validation_mode, ''), JSONExtractString(r.run_options, 'snapshot_mode'), 'structure')
                        END
                        ORDER BY r.started_at DESC
                    ) as rn
                FROM test_results tr
                JOIN test_runs r ON tr.run_id = r.run_id
            ) sub
            WHERE sub.rn <= %(limit)s
            ORDER BY sub.test_id, sub.mode, sub.rn
        """

        rows = db.query(query, {'limit': limit})

        # Group by test_id -> mode -> list of results
        history = {}
        for row in rows:
            test_id = row['test_id']
            mode = row['mode'] or 'default'

            if test_id not in history:
                history[test_id] = {}
            if mode not in history[test_id]:
                history[test_id][mode] = []

            history[test_id][mode].append({
                'status': row['status'],
                'run_id': row['run_id']
            })

        return jsonify({
            'history': history,
            'limit': limit
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@tests_bp.route('/api/tests/visual/screenshot/<path:filepath>', methods=['GET'])
def get_visual_screenshot(filepath: str):
    """
    Serve a screenshot image from the browsers directory.
    Path should be relative to RVBBIT_ROOT/browsers/
    """
    from flask import send_file
    try:
        config = _get_config()
        browsers_dir = os.path.join(config.root_dir, 'browsers')
        full_path = os.path.join(browsers_dir, filepath)

        # Security: ensure path is within browsers directory
        full_path = os.path.abspath(full_path)
        if not full_path.startswith(os.path.abspath(browsers_dir)):
            return jsonify({'error': 'Invalid path'}), 400

        if not os.path.exists(full_path):
            return jsonify({'error': 'File not found'}), 404

        # Determine mime type
        ext = os.path.splitext(full_path)[1].lower()
        mime_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp'
        }
        mime_type = mime_types.get(ext, 'application/octet-stream')

        return send_file(full_path, mimetype=mime_type)

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@tests_bp.route('/api/tests/<path:test_id>/history', methods=['GET'])
def get_test_history(test_id: str):
    """
    Get execution history for a specific test.
    """
    try:
        db = _get_db()
        limit = int(request.args.get('limit', 50))

        query = """
            SELECT
                r.run_id as run_id,
                r.started_at as started_at,
                tr.status as status,
                tr.duration_ms as duration_ms,
                tr.failure_message as failure_message,
                tr.error_message as error_message
            FROM test_results tr
            JOIN test_runs r ON tr.run_id = r.run_id
            WHERE tr.test_id = %(test_id)s
            ORDER BY r.started_at DESC
            LIMIT %(limit)s
        """

        rows = db.query(query, {'test_id': test_id, 'limit': limit})

        history = [
            {
                'run_id': row['run_id'],
                'started_at': row['started_at'].isoformat() if row.get('started_at') else None,
                'status': row['status'],
                'duration_ms': row.get('duration_ms'),
                'failure_message': row.get('failure_message'),
                'error_message': row.get('error_message')
            }
            for row in rows
        ]

        total = len(history)
        passed = sum(1 for h in history if h['status'] == 'passed')
        pass_rate = (passed / total * 100) if total > 0 else 0

        return jsonify({
            'test_id': test_id,
            'history': history,
            'total': total,
            'passed': passed,
            'pass_rate': pass_rate
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
