#!/usr/bin/env python3
"""Local server for floorplan editor with integrated route testing.

Serves floorplan_editor.html and handles route test API calls.
POST /api/route with coords JSON → returns routed count + DRC.

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    python3 modular/floorplan_server.py
    # Open http://localhost:8765
"""
import http.server
import json
import os
import subprocess
import sys
import threading

PORT = 8765
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LAYOUT_DIR = os.path.dirname(SCRIPT_DIR)
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')


class RouteHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SCRIPT_DIR, **kwargs)

    def do_POST(self):
        if self.path == '/api/route':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            coords = json.loads(body)

            # Save coords
            fp_path = os.path.join(OUT_DIR, 'floorplan_coords.json')
            with open(fp_path, 'w') as f:
                json.dump(coords, f, indent=2)

            # Run assemble + route in background
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            try:
                # Assemble
                subprocess.run(
                    ['klayout', '-n', 'sg13g2', '-zz', '-r', 'modular/assemble.py'],
                    cwd=LAYOUT_DIR, capture_output=True, timeout=60)

                # Route
                result = subprocess.run(
                    [sys.executable, 'modular/route_intermodule.py'],
                    cwd=LAYOUT_DIR, capture_output=True, text=True, timeout=120)

                # Parse result
                routed = 0
                failed = []
                for line in result.stdout.split('\n'):
                    if 'Routed:' in line:
                        routed = int(line.split('Routed:')[1].split('/')[0].strip())
                    if 'collision' in line or 'insufficient' in line:
                        failed.append(line.strip())

                response = {'routed': routed, 'total': 23, 'failed': failed,
                            'status': 'ok' if routed == 23 else 'partial'}
            except Exception as e:
                response = {'routed': 0, 'total': 23, 'failed': [str(e)], 'status': 'error'}

            self.wfile.write(json.dumps(response).encode())
            return

        self.send_response(404)
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, format, *args):
        if '/api/' in str(args[0]):
            print(f'  API: {args[0]}')


if __name__ == '__main__':
    os.chdir(LAYOUT_DIR)
    server = http.server.HTTPServer(('', PORT), RouteHandler)
    print(f'Floorplan server: http://localhost:{PORT}/floorplan_editor.html')
    print('API: POST /api/route with coords JSON')
    print('Press Ctrl+C to stop')
    server.serve_forever()
