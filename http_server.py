import http.server
import socketserver
import os
import threading
from datetime import datetime

from config import HTTP_PORT, GAME_RESOURCES_DIR, LOG_COLORS, ENABLE_COLORS


def log(prefix: str, message: str):
    timestamp = datetime.now().strftime('%H:%M:%S')
    if ENABLE_COLORS and prefix in LOG_COLORS:
        color = LOG_COLORS[prefix]
        reset = LOG_COLORS['RESET']
        print(f"[{timestamp}] {color}[{prefix}]{reset} {message}")
    else:
        print(f"[{timestamp}] [{prefix}] {message}")


class GameHTTPHandler(http.server.SimpleHTTPRequestHandler):
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=GAME_RESOURCES_DIR, **kwargs)
    
    def log_message(self, format, *args):
        log("HTTP", f"{self.address_string()} - {format % args}")
    
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        super().end_headers()
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()


class HTTPServer:
    
    def __init__(self, host: str = '0.0.0.0', port: int = HTTP_PORT):
        self.host = host
        self.port = port
        self.server = None
        self.thread = None
    
    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
    
    def _run(self):
        try:
            self.server = socketserver.TCPServer(
                (self.host, self.port), 
                GameHTTPHandler
            )
            log("HTTP", f"Servidor iniciado em {self.host}:{self.port}")
            log("HTTP", f"Servindo arquivos de: {GAME_RESOURCES_DIR}")
            self.server.serve_forever()
        except Exception as e:
            log("HTTP", f"Erro: {e}")
    
    def stop(self):
        if self.server:
            self.server.shutdown()
