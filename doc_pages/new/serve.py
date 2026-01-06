#!/usr/bin/env python3
"""
Simple development server for RVBBIT docs.
Serves files with correct MIME types for ES modules.

Usage:
    python serve.py [port]
    Default port: 8000

Then open: http://localhost:8000
"""

import http.server
import socketserver
import sys
import os

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

# Change to script directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Custom handler with correct MIME types
class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        '': 'application/octet-stream',
        '.html': 'text/html',
        '.css': 'text/css',
        '.js': 'application/javascript',
        '.json': 'application/json',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.svg': 'image/svg+xml',
        '.otf': 'font/otf',
        '.ttf': 'font/ttf',
        '.woff': 'font/woff',
        '.woff2': 'font/woff2',
    }

    def end_headers(self):
        # Enable CORS for local development
        self.send_header('Access-Control-Allow-Origin', '*')
        # Don't cache during development
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        super().end_headers()

print(f"\\n  RVBBIT Documentation Server")
print(f"  ===========================")
print(f"  Serving at: http://localhost:{PORT}")
print(f"  Press Ctrl+C to stop\\n")

with socketserver.TCPServer(("", PORT), Handler) as httpd:
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\\nServer stopped.")
