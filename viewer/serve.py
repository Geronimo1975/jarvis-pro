import http.server, os, webbrowser
os.chdir(os.path.dirname(os.path.abspath(__file__)))
try:
    srv = http.server.HTTPServer(('127.0.0.1', 4710), http.server.SimpleHTTPRequestHandler)
except OSError:
    srv = http.server.HTTPServer(('127.0.0.1', 0), http.server.SimpleHTTPRequestHandler)
port = srv.server_address[1]
print(f'brain-map -> http://localhost:{port}', flush=True)
webbrowser.open(f'http://localhost:{port}')
srv.serve_forever()
