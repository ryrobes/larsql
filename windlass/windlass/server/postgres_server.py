"""
PostgreSQL wire protocol server for Windlass.

This server accepts connections from any PostgreSQL client (DBeaver, psql, DataGrip, Tableau)
and executes queries on Windlass session DuckDB with windlass_udf() and windlass_cascade_udf().

Each client connection gets its own isolated DuckDB session with:
- windlass_udf() registered (simple LLM UDF)
- windlass_cascade_udf() registered (full cascade per row)
- Temp tables (session-scoped)
- ATTACH support (connect to external databases)

Usage:
    from windlass.server.postgres_server import start_postgres_server

    start_postgres_server(host='0.0.0.0', port=5432)

Then connect from any PostgreSQL client:
    psql postgresql://localhost:5432/default
    DBeaver: Add PostgreSQL connection → localhost:5432
"""

import socket
import threading
import uuid
import traceback
from typing import Optional

from .postgres_protocol import (
    PostgresMessage,
    MessageType,
    CommandComplete,
    ReadyForQuery,
    send_startup_response,
    send_query_results,
    send_error
)


class ClientConnection:
    """
    Represents a single client connection.

    Each client gets:
    - Unique session ID
    - Isolated DuckDB session
    - Windlass UDFs registered
    - Dedicated socket
    """

    def __init__(self, sock, addr, session_prefix='pg_client'):
        self.sock = sock
        self.addr = addr
        self.session_id = f"{session_prefix}_{uuid.uuid4().hex[:8]}"
        self.duckdb_conn = None
        self.running = True
        self.query_count = 0

    def setup_session(self):
        """
        Create DuckDB session and register Windlass UDFs.

        This is called once per client connection.
        The session persists for the lifetime of the connection.
        """
        try:
            # Import here to avoid circular dependencies
            from ..sql_tools.session_db import get_session_db
            from ..sql_tools.udf import register_windlass_udf

            # Get or create session DuckDB
            self.duckdb_conn = get_session_db(self.session_id)

            # Register Windlass UDFs (windlass_udf + windlass_cascade_udf)
            register_windlass_udf(self.duckdb_conn)

            print(f"[{self.session_id}] ✓ Session created with Windlass UDFs registered")

        except Exception as e:
            print(f"[{self.session_id}] ✗ Error setting up session: {e}")
            raise

    def handle_startup(self, startup_params: dict):
        """
        Handle client startup message.

        Extracts database name and username from startup params,
        then sends authentication and configuration responses.
        """
        database = startup_params.get('database', 'default')
        user = startup_params.get('user', 'windlass')
        application_name = startup_params.get('application_name', 'unknown')

        print(f"[{self.session_id}] 🔌 Client startup:")
        print(f"   User: {user}")
        print(f"   Database: {database}")
        print(f"   Application: {application_name}")

        # Send startup response sequence
        send_startup_response(self.sock)

    def handle_query(self, query: str):
        """
        Execute query on DuckDB and send results to client.

        Args:
            query: SQL query string (may include windlass_udf(), windlass_cascade_udf())
        """
        self.query_count += 1

        # Clean query (remove null terminators, whitespace)
        query = query.strip()

        print(f"[{self.session_id}] Query #{self.query_count}: {query[:100]}{'...' if len(query) > 100 else ''}")

        try:
            # Handle PostgreSQL-specific SET commands that DuckDB doesn't understand
            query_upper = query.upper()

            if query_upper.startswith('SET ') or query_upper.startswith('RESET '):
                # PostgreSQL clients send session config commands
                # DuckDB doesn't support many of these, so we fake success
                self._handle_set_command(query)
                return

            # Handle PostgreSQL catalog queries (pg_catalog, information_schema)
            if self._is_catalog_query(query):
                self._handle_catalog_query(query)
                return

            # Execute on DuckDB
            result_df = self.duckdb_conn.execute(query).fetchdf()

            # Send results back to client
            send_query_results(self.sock, result_df)

            print(f"[{self.session_id}]   ✓ Returned {len(result_df)} rows")

        except Exception as e:
            # Send error to client
            error_message = str(e)
            error_detail = traceback.format_exc()

            send_error(self.sock, error_message, detail=error_detail)

            print(f"[{self.session_id}]   ✗ Query error: {error_message}")

    def _is_catalog_query(self, query: str) -> bool:
        """
        Check if query is a PostgreSQL catalog query.

        DBeaver and other clients query pg_catalog, information_schema, pg_class, etc.
        to get metadata (tables, columns, types).

        Returns:
            True if this is a catalog/metadata query
        """
        query_upper = query.upper()

        # Common catalog patterns
        catalog_indicators = [
            'PG_CATALOG',
            'PG_CLASS',
            'PG_NAMESPACE',
            'PG_TYPE',
            'PG_ATTRIBUTE',
            'PG_INDEX',
            'PG_DATABASE',
            'PG_TABLES',
            'PG_PROC',
            'PG_DESCRIPTION',
            'PG_SETTINGS',
            'INFORMATION_SCHEMA',
            '::REGCLASS',  # PostgreSQL type casting
            '::REGPROC',
            '::REGTYPE',
            '::OID',
            'CURRENT_SCHEMA',
            'CURRENT_DATABASE',
            'VERSION()',
            'HAS_TABLE_PRIVILEGE',
            'HAS_SCHEMA_PRIVILEGE'
        ]

        return any(indicator in query_upper for indicator in catalog_indicators)

    def _handle_catalog_query(self, query: str):
        """
        Handle PostgreSQL catalog queries by returning minimal/fake metadata.

        DBeaver queries system catalogs to discover tables, schemas, types, etc.
        We return minimal results to keep it happy.

        Args:
            query: Catalog query
        """
        import pandas as pd

        query_upper = query.upper()

        print(f"[{self.session_id}]   📋 Catalog query detected: {query[:80]}...")

        # Return empty result for most catalog queries
        # DBeaver will think there are no system tables (which is fine!)
        empty_df = pd.DataFrame()

        try:
            # Try to map to DuckDB equivalent if possible
            if 'CURRENT_DATABASE' in query_upper:
                # Return fake database name
                result_df = pd.DataFrame({'current_database': ['default']})

            elif 'CURRENT_SCHEMA' in query_upper or 'CURRENT_SCHEMAS' in query_upper:
                # Return fake schema
                result_df = pd.DataFrame({'current_schema': ['public']})

            elif 'VERSION()' in query_upper:
                # Return version string
                result_df = pd.DataFrame({'version': ['PostgreSQL 14.0 (Windlass/DuckDB)']})

            elif 'PG_TABLES' in query_upper or 'INFORMATION_SCHEMA.TABLES' in query_upper:
                # Return actual tables from DuckDB
                try:
                    result_df = self.duckdb_conn.execute("SHOW TABLES").fetchdf()
                    # Rename columns to match PostgreSQL
                    if 'name' in result_df.columns:
                        result_df = result_df.rename(columns={'name': 'tablename'})
                        result_df['schemaname'] = 'public'
                except:
                    result_df = pd.DataFrame(columns=['schemaname', 'tablename'])

            elif 'PG_CLASS' in query_upper or 'PG_NAMESPACE' in query_upper or 'PG_TYPE' in query_upper:
                # System catalog queries - return empty
                # DBeaver is looking for PostgreSQL internals we don't have
                print(f"[{self.session_id}]   ℹ️  Returning empty result for pg_catalog query")
                result_df = empty_df

            else:
                # Unknown catalog query - return empty
                print(f"[{self.session_id}]   ℹ️  Returning empty result for unknown catalog query")
                result_df = empty_df

            # Send results
            send_query_results(self.sock, result_df)
            print(f"[{self.session_id}]   ✓ Catalog query handled ({len(result_df)} rows)")

        except Exception as e:
            # If anything fails, return empty result (DBeaver will survive)
            print(f"[{self.session_id}]   ⚠️  Catalog query error: {e}, returning empty")
            send_query_results(self.sock, empty_df)

    def _handle_set_command(self, query: str):
        """
        Handle PostgreSQL SET/RESET commands.

        Many PostgreSQL clients send session configuration commands
        that DuckDB doesn't support (e.g., extra_float_digits, DateStyle).

        For v1, we silently accept these to maintain compatibility.

        Args:
            query: SET or RESET command
        """
        query_upper = query.upper()

        # List of PostgreSQL settings we can safely ignore
        IGNORED_SETTINGS = [
            'EXTRA_FLOAT_DIGITS',
            'DATESTYLE',
            'TIMEZONE',
            'CLIENT_ENCODING',
            'APPLICATION_NAME',
            'STANDARD_CONFORMING_STRINGS',
            'INTERVALSTYLE',
            'BYTEA_OUTPUT',
            'DEFAULT_TRANSACTION_ISOLATION',
            'DEFAULT_TRANSACTION_READ_ONLY',
            'DEFAULT_TRANSACTION_DEFERRABLE'
        ]

        # Check if this is an ignored setting
        is_ignored = any(setting in query_upper for setting in IGNORED_SETTINGS)

        if is_ignored:
            # Silently accept (send CommandComplete)
            print(f"[{self.session_id}]   ℹ️  Ignoring PostgreSQL-specific SET: {query[:60]}")
            self.sock.sendall(CommandComplete.encode('SET'))
            self.sock.sendall(ReadyForQuery.encode('I'))
        else:
            # Try to execute on DuckDB (might work for some SET commands)
            try:
                self.duckdb_conn.execute(query)
                print(f"[{self.session_id}]   ✓ SET command executed on DuckDB")
                self.sock.sendall(CommandComplete.encode('SET'))
                self.sock.sendall(ReadyForQuery.encode('I'))
            except Exception as e:
                # DuckDB doesn't support this either - ignore and pretend it worked
                print(f"[{self.session_id}]   ℹ️  Ignoring unsupported SET: {query[:60]}")
                self.sock.sendall(CommandComplete.encode('SET'))
                self.sock.sendall(ReadyForQuery.encode('I'))

    def handle(self):
        """
        Main client handling loop.

        Message flow:
        0. Handle SSL negotiation (reject for v1)
        1. Read startup message
        2. Setup DuckDB session
        3. Send startup response
        4. Loop: Read message → Execute → Send response
        5. Cleanup on disconnect
        """
        try:
            # Step 0: Check for SSL request (common - psql tries SSL first)
            first_message = PostgresMessage.read_startup_message(self.sock)
            if not first_message:
                print(f"[{self.addr}] ✗ Failed to read initial message")
                return

            # Handle SSL request
            if first_message.get('ssl_request'):
                print(f"[{self.addr}] SSL requested - rejecting (not supported in v1)")
                # Send 'N' to indicate SSL not supported
                self.sock.sendall(b'N')

                # Now read the REAL startup message (client will retry without SSL)
                startup = PostgresMessage.read_startup_message(self.sock)
                if not startup:
                    print(f"[{self.addr}] ✗ Failed to read startup after SSL rejection")
                    return
            else:
                # No SSL request - this IS the startup message
                startup = first_message

            # Step 2: Setup DuckDB session with Windlass UDFs
            self.setup_session()

            # Step 3: Send startup response
            self.handle_startup(startup['params'])

            # Step 4: Message loop
            while self.running:
                msg_type, payload = PostgresMessage.read_message(self.sock)

                if msg_type is None:
                    # Connection closed by client
                    print(f"[{self.session_id}] Connection closed by client")
                    break

                if msg_type == MessageType.QUERY:
                    # Simple query protocol
                    # Payload is null-terminated SQL string
                    query = payload.rstrip(b'\x00').decode('utf-8')
                    self.handle_query(query)

                elif msg_type == MessageType.TERMINATE:
                    # Client requested clean disconnect
                    print(f"[{self.session_id}] Client requested termination")
                    break

                elif msg_type in [MessageType.PARSE, MessageType.BIND, MessageType.EXECUTE, MessageType.SYNC]:
                    # Extended query protocol (v2 feature)
                    print(f"[{self.session_id}] Extended query protocol not yet supported")
                    send_error(
                        self.sock,
                        "Extended query protocol not implemented. Use simple query protocol.",
                        detail="Prepared statements (PARSE/BIND/EXECUTE) are not yet supported in Windlass v1."
                    )

                else:
                    # Unknown message type
                    print(f"[{self.session_id}] ⚠ Unknown message type: {msg_type} ({chr(msg_type) if 32 <= msg_type <= 126 else '?'})")
                    send_error(
                        self.sock,
                        f"Unsupported message type: {msg_type}",
                        detail="Windlass PostgreSQL server implements Simple Query Protocol only."
                    )

        except Exception as e:
            print(f"[{self.session_id}] ✗ Connection error: {e}")
            traceback.print_exc()

        finally:
            # Step 5: Cleanup
            self.cleanup()

    def cleanup(self):
        """
        Clean up connection and DuckDB session.

        Called when client disconnects or connection errors.
        """
        print(f"[{self.session_id}] 🧹 Cleaning up ({self.query_count} queries executed)")

        # Close socket
        try:
            self.sock.close()
        except:
            pass

        # Optional: cleanup DuckDB session file
        # For now, we keep session files for debugging/analysis
        # Uncomment to delete:
        # from ..sql_tools.session_db import cleanup_session_db
        # cleanup_session_db(self.session_id, delete_file=True)


class WindlassPostgresServer:
    """
    PostgreSQL wire protocol server for Windlass.

    Listens on TCP port, accepts PostgreSQL client connections,
    and routes queries to Windlass DuckDB sessions.

    Features:
    - Concurrent connections (thread per client)
    - Isolated DuckDB sessions (one per client)
    - Windlass UDFs auto-registered
    - Simple Query Protocol (sufficient for most tools)
    """

    def __init__(self, host='0.0.0.0', port=5432, session_prefix='pg_client'):
        """
        Initialize server.

        Args:
            host: Host to listen on (0.0.0.0 = all interfaces)
            port: Port to listen on (5432 = standard PostgreSQL port)
            session_prefix: Prefix for DuckDB session IDs
        """
        self.host = host
        self.port = port
        self.session_prefix = session_prefix
        self.running = False
        self.client_count = 0

    def start(self):
        """
        Start server and accept connections.

        This is a blocking call - runs until interrupted (Ctrl+C).
        """
        # Create TCP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Bind to host:port
        try:
            sock.bind((self.host, self.port))
        except OSError as e:
            print("=" * 70)
            print("❌ ERROR: Could not start server")
            print("=" * 70)
            print(f"Failed to bind to {self.host}:{self.port}")
            print(f"Error: {e}")
            print(f"\n💡 Possible causes:")
            print(f"   1. Port {self.port} is already in use")
            print(f"   2. Permission denied (ports < 1024 require root)")
            print(f"\n💡 Solutions:")
            print(f"   1. Stop other process: sudo lsof -ti:{self.port} | xargs kill")
            print(f"   2. Use different port: windlass server --port 5433")
            print(f"   3. Use sudo (not recommended): sudo windlass server --port {self.port}")
            print("=" * 70)
            return

        sock.listen(5)  # Backlog of 5 pending connections
        self.running = True

        # Print startup banner
        print("=" * 70)
        print("🌊 WINDLASS POSTGRESQL SERVER")
        print("=" * 70)
        print(f"📡 Listening on: {self.host}:{self.port}")
        print(f"🔗 Connection string: postgresql://windlass@localhost:{self.port}/default")
        print()
        print("✨ Available SQL functions:")
        print("   • windlass_udf(instructions, input_value)")
        print("     → Simple LLM extraction/classification")
        print()
        print("   • windlass_cascade_udf(cascade_path, json_inputs)")
        print("     → Full multi-phase cascade per row (with soundings!)")
        print()
        print("📚 Connect from:")
        print(f"   • psql:      psql postgresql://localhost:{self.port}/default")
        print(f"   • DBeaver:   New Connection → PostgreSQL → localhost:{self.port}")
        print(f"   • Python:    psycopg2.connect('postgresql://localhost:{self.port}/default')")
        print(f"   • DataGrip:  New Data Source → PostgreSQL → localhost:{self.port}")
        print()
        print("💡 Each connection gets:")
        print("   • Isolated DuckDB session")
        print("   • Temp tables (session-scoped)")
        print("   • Windlass UDFs registered")
        print("   • ATTACH support (connect to Postgres/MySQL/S3)")
        print()
        print("⏸️  Press Ctrl+C to stop")
        print("=" * 70)

        try:
            while self.running:
                # Accept new connection (blocking)
                client_sock, addr = sock.accept()
                self.client_count += 1

                print(f"\n🔌 Client #{self.client_count} connected from {addr[0]}:{addr[1]}")

                # Handle client in separate thread (allows concurrent connections)
                client = ClientConnection(client_sock, addr, self.session_prefix)
                thread = threading.Thread(
                    target=client.handle,
                    daemon=True,
                    name=f"Client-{self.client_count}"
                )
                thread.start()

        except KeyboardInterrupt:
            print("\n\n⏹️  Shutting down server...")
            print(f"   Total connections served: {self.client_count}")

        except Exception as e:
            print(f"\n❌ Server error: {e}")
            traceback.print_exc()

        finally:
            sock.close()
            self.running = False
            print("✅ Server stopped")


def start_postgres_server(host='0.0.0.0', port=5432, session_prefix='pg_client'):
    """
    Start Windlass PostgreSQL wire protocol server.

    Args:
        host: Host to listen on (default: 0.0.0.0 = all interfaces)
        port: Port to listen on (default: 5432 = standard PostgreSQL)
        session_prefix: Prefix for DuckDB session IDs (default: 'pg_client')

    Example:
        # Start server
        start_postgres_server(port=5433)

        # Connect from psql
        $ psql postgresql://localhost:5433/default

        # Query with LLM UDFs!
        default=> SELECT windlass_udf('Extract brand', 'Apple iPhone') as brand;
         brand
        -------
         Apple
        (1 row)
    """
    server = WindlassPostgresServer(host, port, session_prefix)
    server.start()
