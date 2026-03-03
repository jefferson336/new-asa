#!/usr/bin/env python3
"""
Servidor Completo - Asa de Cristal
Inicia HTTP Server, Login Server e Policy Server em um único processo
"""

import http.server
import socketserver
import socket
import threading
import struct
import hashlib
import time
import uuid
import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import IntEnum

# ============================================================================
# CONFIGURAÇÕES
# ============================================================================

HOST = '0.0.0.0'  # Aceita conexões de qualquer IP
HTTP_PORT = 8081
LOGIN_PORT = 9999
POLICY_PORT = 843
WORLD_PORT = 8888

# Modo de autenticação: 'db' para SQL Server, 'debug' para aceitar qualquer login
AUTH_MODE = 'db'  # Altere para 'debug' se quiser modo sem banco

# Diretório de recursos do jogo
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DIRECTORY = os.path.join(os.path.dirname(SCRIPT_DIR), 'game_resources')

# ============================================================================
# BANCO DE DADOS - SQL SERVER
# ============================================================================

# Instâncias globais para repositórios de banco
_db_available = False
_account_repo = None
_server_repo = None
_role_repo = None

def init_database():
    """Inicializa conexão com o banco de dados"""
    global _db_available, _account_repo, _server_repo, _role_repo
    
    try:
        from database import get_db, get_account_repo, get_server_repo, get_role_repo
        
        db = get_db()
        if db.connect():
            _account_repo = get_account_repo()
            _server_repo = get_server_repo()
            _role_repo = get_role_repo()
            _db_available = True
            log("DB", "✅ Conexão com SQL Server estabelecida!")
            return True
        else:
            log("DB", "⚠️ Não foi possível conectar ao SQL Server")
            return False
    except ImportError as e:
        log("DB", f"⚠️ Módulo pyodbc não instalado: {e}")
        return False
    except Exception as e:
        log("DB", f"⚠️ Erro ao conectar: {e}")
        return False

def get_servers_from_db() -> List[Dict]:
    """Retorna lista de servidores do banco de dados"""
    global _db_available, _server_repo
    
    if _db_available and _server_repo:
        try:
            servers = _server_repo.get_server_list()
            return [{
                'id': s['ServerID'],
                'name': s['ServerName'],
                'host': s['ServerIP'],
                'port': s['ServerPort'],
                'status': s['Status']
            } for s in servers]
        except Exception as e:
            log("DB", f"Erro ao buscar servidores: {e}")
    
    # Fallback: servidor padrão
    return [{'id': 1, 'name': 'Servidor Principal', 'host': '127.0.0.1', 'port': 8888, 'status': 0}]

def authenticate_user(username: str, password_hash: str, key: str, client_ip: str = None) -> Dict:
    """
    Autentica usuário usando o banco de dados
    
    NOTA: O cliente envia MD5(senha + key), então o servidor precisa 
    da senha em texto para calcular o mesmo hash. Limitação do protocolo.
    
    Returns:
        Dict com: success (bool), session_id (str), reason (int), message (str)
    """
    global _db_available, _account_repo
    
    # Modo debug: aceitar qualquer login
    if AUTH_MODE == 'debug' or not _db_available:
        return {
            'success': True,
            'session_id': str(uuid.uuid4()),
            'reason': 0,
            'message': 'Login bem-sucedido (modo debug)'
        }
    
    try:
        # Buscar dados da conta (sem verificar senha ainda)
        result = _account_repo.get_account(username)
        
        if result is None:
            return {
                'success': False,
                'session_id': '',
                'reason': 1,
                'message': 'Usuário não encontrado'
            }
        
        # Cliente faz MD5(key + senha)
        stored_pwd = result['LoginPwd']  # senha em texto
        
        # Tentar: MD5(key + senha)
        hash1 = hashlib.md5((key + stored_pwd).encode()).hexdigest()
        
        log("LOGIN", f"Senha banco: '{stored_pwd}', Key: '{key}'")
        log("LOGIN", f"MD5(key+senha) = MD5('{key}'+'{stored_pwd}'): {hash1}")
        log("LOGIN", f"Hash recebido: {password_hash}")
        
        if hash1.lower() == password_hash.lower():
            log("LOGIN", "✅ Hash corresponde!")
        else:
            log("LOGIN", "❌ Hash NÃO corresponde - verificar banco de dados!")
            return {
                'success': False,
                'session_id': '',
                'reason': 2,
                'message': 'Senha incorreta'
            }
        
        # Verificar ban
        if result.get('IsBanned') and (result.get('BanExpireTime') is None or result.get('BanExpireTime') > datetime.now()):
            return {
                'success': False,
                'session_id': '',
                'reason': 3,
                'message': 'Conta banida'
            }
        
        # Criar sessão
        session_result = _account_repo.create_session(result['AccountUID'], client_ip)
        
        return {
            'success': True,
            'session_id': session_result['Ticket'],
            'account_id': result['AccountUID'],
            'reason': 0,
            'message': 'Login bem-sucedido'
        }
        
    except Exception as e:
        log("DB", f"Erro na autenticação: {e}")
        import traceback
        traceback.print_exc()
        return {
            'success': False,
            'session_id': '',
            'reason': 99,
            'message': f'Erro interno: {e}'
        }

POLICY_FILE = """<?xml version="1.0"?>
<!DOCTYPE cross-domain-policy SYSTEM "http://www.adobe.com/xml/dtds/cross-domain-policy.dtd">
<cross-domain-policy>
    <allow-access-from domain="*" to-ports="*" />
</cross-domain-policy>\0"""

# ============================================================================
# CÓDIGOS DE COMANDO DO LOGIN
# ============================================================================

class LoginCommand(IntEnum):
    WELCOME_NOTIFY = 16
    LOGIN_REQUEST = 17
    LOGIN_ANSWER = 18
    LOGOUT_REQUEST = 19
    LOGOUT_ANSWER = 20
    SERVER_LIST_REQUEST = 23
    SERVER_LIST_ANSWER = 24

# ============================================================================
# PROTOCOLO DIY - ENCODER/DECODER
# ============================================================================

class PacketBuilder:
    """Constrói packets no formato DIY com VarInt"""
    
    def __init__(self):
        self.buffer = bytearray()
    
    def write_byte(self, value: int) -> 'PacketBuilder':
        self.buffer.append(value & 0xFF)
        return self
    
    def write_short(self, value: int) -> 'PacketBuilder':
        self.buffer.extend(struct.pack('>h', value))
        return self
    
    def write_unsigned_short(self, value: int) -> 'PacketBuilder':
        self.buffer.extend(struct.pack('>H', value))
        return self
    
    def write_int(self, value: int) -> 'PacketBuilder':
        self.buffer.extend(struct.pack('>i', value))
        return self
    
    def write_long(self, value: int) -> 'PacketBuilder':
        self.buffer.extend(struct.pack('>q', value))
        return self
    
    def write_string(self, value: str) -> 'PacketBuilder':
        encoded = value.encode('utf-8') if value else b''
        # Strings usam VarInt para o tamanho
        self.write_varint(len(encoded))
        self.buffer.extend(encoded)
        return self
    
    def write_bool(self, value: bool) -> 'PacketBuilder':
        self.buffer.append(1 if value else 0)
        return self
    
    def write_varint(self, value: int) -> 'PacketBuilder':
        """Escreve um inteiro com tamanho variável (VarInt)"""
        while True:
            byte = value & 0x7F
            value >>= 7
            if value == 0:
                self.buffer.append(byte)
                break
            else:
                self.buffer.append(byte | 0x80)
        return self
    
    def build(self, command_code: int) -> bytes:
        """
        Constrói o packet final no formato DIY:
        - VarInt: tamanho do (command_code + digest + payload) 
        - 2 bytes: command code (unsigned short)
        - 2 bytes: digest (sempre 0 por enquanto)
        - N bytes: payload
        """
        payload = bytes(self.buffer)
        
        # Calcula o tamanho total (command_code + digest + payload)
        total_size = 2 + 2 + len(payload)
        
        # Monta o pacote
        packet = bytearray()
        
        # VarInt do tamanho
        size = total_size
        while True:
            byte = size & 0x7F
            size >>= 7
            if size == 0:
                packet.append(byte)
                break
            else:
                packet.append(byte | 0x80)
        
        # Command code (2 bytes, unsigned)
        packet.extend(struct.pack('>H', command_code))
        
        # Digest (2 bytes) - sempre 0 por enquanto
        packet.extend(struct.pack('>H', 0))
        
        # Payload
        packet.extend(payload)
        
        return bytes(packet)
    
    def reset(self) -> 'PacketBuilder':
        self.buffer = bytearray()
        return self

class PacketReader:
    """Lê packets no formato DIY"""
    
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
    
    def read_byte(self) -> int:
        value = self.data[self.pos]
        self.pos += 1
        return value
    
    def read_short(self) -> int:
        value = struct.unpack('>h', self.data[self.pos:self.pos+2])[0]
        self.pos += 2
        return value
    
    def read_unsigned_short(self) -> int:
        value = struct.unpack('>H', self.data[self.pos:self.pos+2])[0]
        self.pos += 2
        return value
    
    def read_int(self) -> int:
        value = struct.unpack('>i', self.data[self.pos:self.pos+4])[0]
        self.pos += 4
        return value
    
    def read_long(self) -> int:
        value = struct.unpack('>q', self.data[self.pos:self.pos+8])[0]
        self.pos += 8
        return value
    
    def read_varint(self) -> int:
        """Lê um inteiro de tamanho variável (VarInt)"""
        value = 0
        shift = 0
        while True:
            byte = self.data[self.pos]
            self.pos += 1
            value |= (byte & 0x7F) << shift
            if (byte & 0x80) == 0:
                break
            shift += 7
        return value
    
    def read_string(self) -> str:
        # Strings usam VarInt para o tamanho
        length = self.read_varint()
        if length <= 0:
            return ''
        value = self.data[self.pos:self.pos+length].decode('utf-8', errors='replace')
        self.pos += length
        return value
    
    def remaining(self) -> int:
        return len(self.data) - self.pos

# ============================================================================
# LOGGER
# ============================================================================

def log(server_name: str, message: str):
    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f"[{timestamp}] [{server_name}] {message}")

# ============================================================================
# SERVIDOR HTTP
# ============================================================================

class CustomHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Handler HTTP customizado com CORS"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)
    
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        super().end_headers()
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()
    
    def log_message(self, format, *args):
        log("HTTP", format % args)

def start_http_server():
    """Inicia servidor HTTP"""
    os.chdir(DIRECTORY)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", HTTP_PORT), CustomHTTPRequestHandler) as httpd:
        log("HTTP", f"Servidor HTTP iniciado em http://localhost:{HTTP_PORT}")
        httpd.serve_forever()

# ============================================================================
# SERVIDOR DE POLÍTICA (Flash Security)
# ============================================================================

def start_policy_server():
    """Servidor de política de segurança do Flash"""
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server_socket.bind((HOST, POLICY_PORT))
        server_socket.listen(5)
        log("POLICY", f"Servidor de política iniciado em {HOST}:{POLICY_PORT}")
        
        while True:
            try:
                server_socket.settimeout(1.0)
                client_socket, address = server_socket.accept()
                
                data = client_socket.recv(1024)
                if b"<policy-file-request/>" in data:
                    log("POLICY", f"Requisição de política de {address}")
                    client_socket.send(POLICY_FILE.encode())
                    log("POLICY", f"Política enviada para {address}")
                
                client_socket.close()
                
            except socket.timeout:
                continue
            except Exception as e:
                log("POLICY", f"Erro: {e}")
                
    except PermissionError:
        log("POLICY", f"⚠️ Porta {POLICY_PORT} requer privilégios de administrador!")
        log("POLICY", "Execute como administrador ou altere a porta")
    except Exception as e:
        log("POLICY", f"Erro fatal: {e}")
    finally:
        server_socket.close()

# ============================================================================
# SERVIDOR DE LOGIN
# ============================================================================

class LoginSession:
    """Sessão de login de um cliente"""
    
    def __init__(self, client_socket, address):
        self.socket = client_socket
        self.address = address
        self.key = str(uuid.uuid4())[:8]  # Key para autenticação
        self.username = None
        self.session_id = None
        self.authenticated = False
    
    def log(self, message: str):
        log("LOGIN", f"[{self.address}] {message}")
    
    def send_packet(self, packet: bytes):
        """Envia um pacote para o cliente"""
        try:
            self.socket.send(packet)
            self.log(f"Enviado {len(packet)} bytes: {packet.hex()}")
        except Exception as e:
            self.log(f"Erro ao enviar: {e}")
    
    def send_welcome(self):
        """Envia WelcomeNotify com a key de autenticação"""
        builder = PacketBuilder()
        builder.write_string(self.key)
        packet = builder.build(LoginCommand.WELCOME_NOTIFY)
        self.log(f"Enviando WelcomeNotify (key={self.key})")
        self.send_packet(packet)
    
    def handle_login_request(self, reader: PacketReader):
        """Processa LoginRequest"""
        try:
            username = reader.read_string()
            password_hash = reader.read_string()
            ss_key = reader.read_string() if reader.remaining() > 0 else ""
            
            self.log(f"LoginRequest: user={username}, hash={password_hash[:16]}..., ssKey={ss_key}")
            
            # Obter IP do cliente
            client_ip = self.address[0] if self.address else None
            
            # Autenticar usando banco de dados ou modo debug
            # O cliente envia MD5(senha + key), então passamos a key para verificação
            auth_result = authenticate_user(username, password_hash, self.key, client_ip)
            
            if auth_result['success']:
                self.username = username
                self.session_id = auth_result['session_id']
                self.authenticated = True
                
                self.log(f"✅ Login bem-sucedido! SessionId={self.session_id[:8]}...")
                
                builder = PacketBuilder()
                builder.write_string(self.session_id)  # sessionId
                builder.write_int(0)                    # failureReason (0 = sucesso)
                packet = builder.build(LoginCommand.LOGIN_ANSWER)
                self.send_packet(packet)
            else:
                self.log(f"❌ Login falhou: {auth_result['message']} (reason={auth_result['reason']})")
                self.send_login_failure(auth_result['reason'])
                
        except Exception as e:
            self.log(f"Erro ao processar login: {e}")
            import traceback
            traceback.print_exc()
            self.send_login_failure(99)  # Erro interno
    
    def send_login_failure(self, reason: int):
        """Envia resposta de falha de login"""
        builder = PacketBuilder()
        builder.write_string("")    # sessionId vazio
        builder.write_int(reason)   # failureReason
        packet = builder.build(LoginCommand.LOGIN_ANSWER)
        self.send_packet(packet)
    
    def handle_server_list_request(self, reader: PacketReader):
        """Processa ServerListRequest
        
        Formato ServerListAnswer:
        - serverList:array(ServerInfo)
        - selectedServer:string
        
        Formato ServerInfo (objeto serializado):
        - serverId:string
        - serverName:string
        - serverIP:string
        - serverPort:ushort
        - serverStatus:string
        """
        self.log("ServerListRequest recebido")
        
        # Buscar servidores do banco de dados
        servers = get_servers_from_db()
        
        builder = PacketBuilder()
        
        # Array de servidores (VarInt para tamanho)
        builder.write_varint(len(servers))
        
        for srv in servers:
            # Criar objeto do servidor
            srv_builder = PacketBuilder()
            srv_builder.write_string(str(srv['id']))      # serverId:string
            srv_builder.write_string(srv['name'])          # serverName:string
            srv_builder.write_string(srv['host'])          # serverIP:string
            srv_builder.write_unsigned_short(srv['port'])  # serverPort:ushort
            srv_builder.write_string(str(srv['status']))   # serverStatus:string
            
            # Escreve o objeto com prefixo de tamanho (short)
            srv_data = bytes(srv_builder.buffer)
            builder.write_short(len(srv_data))
            builder.buffer.extend(srv_data)
        
        # Servidor selecionado (string)
        builder.write_string("1")
        
        packet = builder.build(LoginCommand.SERVER_LIST_ANSWER)
        self.log(f"Enviando lista com {len(servers)} servidor(es)")
        self.send_packet(packet)

def handle_login_client(client_socket, address):
    """Handler para cliente do servidor de login"""
    session = LoginSession(client_socket, address)
    session.log("Cliente conectado")
    
    buffer = b''
    
    try:
        # Enviar boas-vindas
        session.send_welcome()
        
        while True:
            try:
                # Receber dados
                data = client_socket.recv(4096)
                if not data:
                    break
                
                buffer += data
                
                # Processar packets usando VarInt para length
                while len(buffer) >= 1:
                    # Ler VarInt para comprimento
                    length = 0
                    shift = 0
                    varint_bytes = 0
                    
                    for i in range(min(5, len(buffer))):
                        byte = buffer[i]
                        length |= (byte & 0x7F) << shift
                        varint_bytes += 1
                        if (byte & 0x80) == 0:
                            break
                        shift += 7
                    else:
                        # VarInt incompleto
                        if len(buffer) >= 5:
                            session.log(f"VarInt inválido")
                            buffer = buffer[1:]
                        break
                    
                    # Verificar se temos dados suficientes
                    total_len = varint_bytes + length
                    if len(buffer) < total_len:
                        break
                    
                    packet_data = buffer[varint_bytes:total_len]
                    buffer = buffer[total_len:]
                    
                    # Parse: command (2 bytes) + digest (2 bytes) + payload
                    if len(packet_data) < 4:
                        session.log(f"Packet muito pequeno: {len(packet_data)}")
                        continue
                    
                    command = struct.unpack('>H', packet_data[:2])[0]
                    digest = struct.unpack('>H', packet_data[2:4])[0]
                    payload = packet_data[4:]
                    
                    session.log(f"Recebido: cmd={command}, digest={digest}, len={len(payload)}, payload={payload.hex()[:40]}")
                    
                    # Processar comando
                    reader = PacketReader(payload) if payload else PacketReader(b'')
                    
                    if command == LoginCommand.LOGIN_REQUEST:
                        session.handle_login_request(reader)
                    elif command == LoginCommand.SERVER_LIST_REQUEST:
                        session.handle_server_list_request(reader)
                    elif command == LoginCommand.LOGOUT_REQUEST:
                        session.log("Logout request")
                        break
                    else:
                        session.log(f"⚠️ Comando desconhecido: {command}")
                    
            except socket.timeout:
                continue
            except Exception as e:
                session.log(f"Erro: {e}")
                break
                
    except Exception as e:
        session.log(f"Erro na sessão: {e}")
    finally:
        session.log("Cliente desconectado")
        client_socket.close()

def start_login_server():
    """Inicia servidor de login"""
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server_socket.bind((HOST, LOGIN_PORT))
        server_socket.listen(5)
        log("LOGIN", f"Servidor de login iniciado em {HOST}:{LOGIN_PORT}")
        
        while True:
            try:
                server_socket.settimeout(1.0)
                client_socket, address = server_socket.accept()
                client_socket.settimeout(30.0)
                
                # Handler em thread separada
                thread = threading.Thread(
                    target=handle_login_client,
                    args=(client_socket, address),
                    daemon=True
                )
                thread.start()
                
            except socket.timeout:
                continue
            except Exception as e:
                log("LOGIN", f"Erro: {e}")
                
    except Exception as e:
        log("LOGIN", f"Erro fatal: {e}")
    finally:
        server_socket.close()

# ============================================================================
# SERVIDOR WORLD (porta 8888) - Sistema de Personagens
# ============================================================================

class RoleCommandCode(IntEnum):
    """Códigos de comando do Role/World Server (do CommandCodeRole.as)"""
    # Códigos do World
    WORLD_LOGIN_REQ = 33
    WORLD_LOGIN_ANSWER = 34
    
    # Códigos de Role (257+)
    ROLE_LIST_REQ = 257
    ROLE_LIST_ANSWER = 258
    ROLE_NAME_CONFIRM_REQ = 259
    ROLE_NAME_CONFIRM_ANSWER = 260
    CREATE_ROLE_REQ = 261
    CREATE_ROLE_ANSWER = 262
    DELETE_ROLE_REQ = 263
    DELETE_ROLE_ANSWER = 264
    SELECT_ROLE_REQ = 265
    SELECT_ROLE_ANSWER = 272
    RECOVER_ROLE_REQ = 273
    RECOVER_ROLE_ANSWER = 274
    SET_ROLE_PW_REQ = 275
    SET_ROLE_PW_ANSWER = 276

# ============================================================================
# FUNÇÕES DE PERSONAGENS - BANCO DE DADOS
# ============================================================================

def get_roles_for_account(account_id: str) -> List[Dict]:
    """Retorna personagens de uma conta do banco de dados"""
    global _db_available, _role_repo
    
    if _db_available and _role_repo:
        try:
            # account_id pode ser UID numérico ou ticket
            account_uid = None
            
            # Tentar converter para int diretamente
            try:
                account_uid = int(account_id)
            except ValueError:
                # É um ticket, buscar UID
                account_data = _role_repo.get_account_by_ticket(account_id)
                if account_data:
                    account_uid = account_data['AccountUID']
            
            if account_uid:
                db_roles = _role_repo.get_roles_by_account(account_uid)
                roles = []
                for r in db_roles:
                    roles.append({
                        'id': r['RoleID'],
                        'name': r['Name'],
                        'jobCode': r['JobCode'],
                        'sex': r['Sex'],
                        'level': r['Level'],
                        'headIconIndex': r['HeadIconIndex'],
                        'hairStyleIndex': r['HairStyleIndex'],
                        'accountId': str(r['AccountUID']),
                        'createTime': str(r.get('CreateTime', '')),
                        'lastPlayTime': str(r.get('LastPlayTime', '')),
                        'deletedFlag': bool(r.get('DeletedFlag', False)),
                        'willDeleteTime': str(r.get('WillDeleteTime', '')) if r.get('WillDeleteTime') else '',
                        'equipmentModels': {},
                        'hasRolePassword': bool(r.get('HasRolePassword', False))
                    })
                return roles
        except Exception as e:
            log("DB", f"Erro ao buscar personagens: {e}")
    
    return []

def create_role_for_account(account_id: str, role_data: Dict) -> Dict:
    """Cria novo personagem para conta no banco de dados"""
    global _db_available, _role_repo
    
    if _db_available and _role_repo:
        try:
            # Determinar account_uid
            account_uid = None
            try:
                account_uid = int(account_id)
            except ValueError:
                # É um ticket
                account_data = _role_repo.get_account_by_ticket(account_id)
                if account_data:
                    account_uid = account_data['AccountUID']
            
            if account_uid:
                result = _role_repo.create_role(
                    account_uid=account_uid,
                    name=role_data.get('name', 'Personagem'),
                    job_code=role_data.get('jobCode', 1),
                    sex=role_data.get('sex', 0),
                    head_icon_index=role_data.get('headIconIndex', 0),
                    hair_style_index=role_data.get('hairStyleIndex', 0)
                )
                
                if result.get('Status') == 0:
                    # Sucesso - retornar dados formatados
                    return {
                        'id': result.get('RoleID'),
                        'name': result.get('Name'),
                        'jobCode': result.get('JobCode'),
                        'sex': result.get('Sex'),
                        'level': result.get('Level', 1),
                        'headIconIndex': result.get('HeadIconIndex', 0),
                        'hairStyleIndex': result.get('HairStyleIndex', 0),
                        'accountId': str(result.get('AccountUID', account_uid)),
                        'createTime': str(result.get('CreateTime', '')),
                        'lastPlayTime': str(result.get('LastPlayTime', '')),
                        'deletedFlag': False,
                        'willDeleteTime': '',
                        'equipmentModels': {},
                        'hasRolePassword': False
                    }
                else:
                    log("DB", f"Erro ao criar personagem: {result.get('Message')}")
                    return {'error': result.get('Message', 'Erro ao criar personagem')}
        except Exception as e:
            log("DB", f"Erro ao criar personagem no DB: {e}")
            import traceback
            traceback.print_exc()
    
    return {'error': 'Banco de dados não disponível'}

def check_role_name_available(name: str) -> bool:
    """Verifica se nome de personagem está disponível"""
    global _db_available, _role_repo
    
    if _db_available and _role_repo:
        try:
            return _role_repo.check_name(name)
        except Exception as e:
            log("DB", f"Erro ao verificar nome: {e}")
    
    return True  # Fallback: assumir disponível

def select_role_for_account(account_id: str, name: str, password: str = None) -> Dict:
    """Seleciona personagem para jogar"""
    global _db_available, _role_repo
    
    if _db_available and _role_repo:
        try:
            account_uid = None
            try:
                account_uid = int(account_id)
            except ValueError:
                account_data = _role_repo.get_account_by_ticket(account_id)
                if account_data:
                    account_uid = account_data['AccountUID']
            
            if account_uid:
                return _role_repo.select_role(account_uid, name, password)
        except Exception as e:
            log("DB", f"Erro ao selecionar personagem: {e}")
    
    return {'IsDone': 0, 'FailureReason': 'Erro interno'}

def delete_role_for_account(account_id: str, name: str) -> Dict:
    """Marca personagem para deleção"""
    global _db_available, _role_repo
    
    if _db_available and _role_repo:
        try:
            account_uid = None
            try:
                account_uid = int(account_id)
            except ValueError:
                account_data = _role_repo.get_account_by_ticket(account_id)
                if account_data:
                    account_uid = account_data['AccountUID']
            
            if account_uid:
                return _role_repo.delete_role(account_uid, name)
        except Exception as e:
            log("DB", f"Erro ao deletar personagem: {e}")
    
    return {'IsDone': 0, 'FailureReason': 'Erro interno'}

class WorldSession:
    """Sessão do World Server"""
    
    def __init__(self, client_socket, address):
        self.socket = client_socket
        self.address = address
        self.session_id = None
        self.account_id = None
        self.selected_role = None
    
    def log(self, message: str):
        log("WORLD", f"[{self.address}] {message}")
    
    def send_packet(self, packet: bytes):
        try:
            self.socket.send(packet)
            self.log(f"Enviado {len(packet)} bytes: {packet.hex()}")
        except Exception as e:
            self.log(f"Erro ao enviar: {e}")
    
    def handle_world_login(self, reader: PacketReader):
        """
        Processa login no world server (cmd 33)
        
        Request:
        - sessionId:string
        - serverId:string
        
        Answer:
        - isDone:boolean
        - failureReason:string
        """
        try:
            session_id = reader.read_string()
            server_id = reader.read_string() if reader.remaining() > 0 else ""
            self.session_id = session_id
            # Usar session_id como account_id por enquanto
            self.account_id = session_id[:8] if session_id else "default"
            self.log(f"WorldLoginRequest: sessionId={session_id[:16] if session_id else 'vazio'}..., serverId={server_id}")
            
            # Enviar resposta de sucesso
            # isDone:boolean, failureReason:string
            builder = PacketBuilder()
            builder.write_bool(True)    # isDone = true
            builder.write_string("")    # failureReason vazio
            packet = builder.build(RoleCommandCode.WORLD_LOGIN_ANSWER)
            self.send_packet(packet)
            self.send_packet(packet)
            
        except Exception as e:
            self.log(f"Erro no world login: {e}")
            import traceback
            traceback.print_exc()
    
    def handle_role_list(self, reader: PacketReader):
        """
        Processa RoleListRequest (cmd 257)
        
        Request: ssKey:short
        Answer: roles:array(RoleSystemInfo)
        
        RoleSystemInfo herda de RoleBaseInfo:
        - name:string
        - jobCode:byte
        - sex:byte  
        - level:short
        - headIconIndex:ushort
        - hairStyleIndex:ubyte
        
        + campos próprios:
        - accountId:string
        - createTime:string
        - lastPlayTime:string
        - deletedFlag:boolean
        - willDeleteTime:string
        - equipmentModels:map(byte,string)
        - hasRolePassword:boolean
        """
        try:
            ss_key = reader.read_short() if reader.remaining() >= 2 else 0
            self.log(f"RoleListRequest recebido (ssKey={ss_key})")
            
            # Buscar personagens da conta
            roles = get_roles_for_account(self.account_id)
            self.log(f"Encontrados {len(roles)} personagens para conta {self.account_id}")
            
            builder = PacketBuilder()
            
            # Array de roles (VarInt para tamanho)
            builder.write_varint(len(roles))
            
            for role in roles:
                # Criar objeto RoleSystemInfo serializado
                role_builder = PacketBuilder()
                
                # RoleBaseInfo fields
                role_builder.write_string(role.get('name', 'Personagem'))
                role_builder.write_byte(role.get('jobCode', 1))
                role_builder.write_byte(role.get('sex', 0))
                role_builder.write_short(role.get('level', 1))
                role_builder.write_unsigned_short(role.get('headIconIndex', 0))
                role_builder.write_byte(role.get('hairStyleIndex', 0))
                
                # RoleSystemInfo fields
                role_builder.write_string(str(role.get('accountId', '')))
                role_builder.write_string(str(role.get('createTime', '')))
                role_builder.write_string(str(role.get('lastPlayTime', '')))
                role_builder.write_bool(role.get('deletedFlag', False))
                role_builder.write_string(str(role.get('willDeleteTime', '')))
                
                # equipmentModels:map(byte,string) - mapa vazio
                equip = role.get('equipmentModels', {})
                role_builder.write_varint(len(equip))
                for slot, model in equip.items():
                    role_builder.write_byte(int(slot))
                    role_builder.write_string(str(model))
                
                role_builder.write_bool(role.get('hasRolePassword', False))
                
                # Escreve o objeto com prefixo de tamanho (short)
                role_data = bytes(role_builder.buffer)
                builder.write_short(len(role_data))
                builder.buffer.extend(role_data)
            
            packet = builder.build(RoleCommandCode.ROLE_LIST_ANSWER)
            self.log(f"Enviando RoleListAnswer com {len(roles)} personagem(ns)")
            self.send_packet(packet)
            
        except Exception as e:
            self.log(f"Erro ao listar roles: {e}")
            import traceback
            traceback.print_exc()
    
    def handle_role_name_confirm(self, reader: PacketReader):
        """
        Processa RoleNameConfirmRequest (cmd 259)
        Verifica se nome de personagem está disponível
        """
        try:
            name = reader.read_string()
            self.log(f"RoleNameConfirmRequest: name={name}")
            
            # Verificar se nome já existe usando banco de dados
            name_available = check_role_name_available(name)
            
            builder = PacketBuilder()
            if not name_available:
                builder.write_bool(False)  # isDone = false
                builder.write_string("Nome já está em uso")
            else:
                builder.write_bool(True)   # isDone = true
                builder.write_string("")   # sem erro
            
            packet = builder.build(RoleCommandCode.ROLE_NAME_CONFIRM_ANSWER)
            self.send_packet(packet)
            
        except Exception as e:
            self.log(f"Erro ao confirmar nome: {e}")
    
    def handle_create_role(self, reader: PacketReader):
        """
        Processa CreateRoleRequest (cmd 261)
        
        Request:
        - landCode:string
        - role:RoleBaseInfo (name, jobCode, sex, level, headIconIndex, hairStyleIndex)
        
        Answer:
        - role:RoleSystemInfo (ou null se erro)
        - failureReason:string
        """
        try:
            land_code = reader.read_string()
            self.log(f"CreateRoleRequest: landCode={land_code}")
            
            # Ler RoleBaseInfo (objeto serializado)
            # Primeiro vem o tamanho do objeto
            role_size = reader.read_short()
            
            # Ler campos do RoleBaseInfo
            name = reader.read_string()
            job_code = reader.read_byte()
            sex = reader.read_byte()
            level = reader.read_short()
            head_icon = reader.read_unsigned_short()
            hair_style = reader.read_byte()
            
            self.log(f"Criando role: name={name}, job={job_code}, sex={sex}, level={level}")
            
            # Criar personagem no banco de dados
            role_data = {
                'name': name,
                'jobCode': job_code,
                'sex': sex,
                'level': 1,  # Sempre começa nível 1
                'headIconIndex': head_icon,
                'hairStyleIndex': hair_style,
            }
            
            new_role = create_role_for_account(self.account_id, role_data)
            
            builder = PacketBuilder()
            
            if 'error' in new_role:
                # Role null (tamanho 0) + mensagem de erro
                builder.write_short(0)  # objeto vazio
                builder.write_string(new_role['error'])
                self.log(f"Erro ao criar personagem: {new_role['error']}")
            else:
                self.log(f"✅ Personagem criado: {new_role}")
                
                # Serializar RoleSystemInfo
                role_builder = PacketBuilder()
                role_builder.write_string(new_role['name'])
                role_builder.write_byte(new_role['jobCode'])
                role_builder.write_byte(new_role['sex'])
                role_builder.write_short(new_role['level'])
                role_builder.write_unsigned_short(new_role['headIconIndex'])
                role_builder.write_byte(new_role['hairStyleIndex'])
                role_builder.write_string(str(new_role['accountId']))
                role_builder.write_string(str(new_role['createTime']))
                role_builder.write_string(str(new_role['lastPlayTime']))
                role_builder.write_bool(new_role['deletedFlag'])
                role_builder.write_string(str(new_role['willDeleteTime']))
                
                # equipmentModels vazio
                role_builder.write_varint(0)
                role_builder.write_bool(new_role['hasRolePassword'])
                
                role_bytes = bytes(role_builder.buffer)
                builder.write_short(len(role_bytes))
                builder.buffer.extend(role_bytes)
                builder.write_string("")  # sem erro
            
            packet = builder.build(RoleCommandCode.CREATE_ROLE_ANSWER)
            self.send_packet(packet)
            
        except Exception as e:
            self.log(f"Erro ao criar role: {e}")
            import traceback
            traceback.print_exc()
    
    def handle_select_role(self, reader: PacketReader):
        """
        Processa SelectRoleRequest (cmd 265)
        
        Request:
        - name:string
        - password:string
        
        Answer (cmd 272):
        - isDone:boolean
        - failureReason:string
        """
        try:
            name = reader.read_string()
            password = reader.read_string()
            
            self.log(f"SelectRoleRequest: name={name}, password={'*'*len(password) if password else '(vazio)'}")
            
            # Selecionar personagem usando banco de dados
            result = select_role_for_account(self.account_id, name, password)
            
            builder = PacketBuilder()
            
            if result.get('IsDone'):
                # Buscar dados do personagem para armazenar na sessão
                for role in get_roles_for_account(self.account_id):
                    if role.get('name') == name:
                        self.selected_role = role
                        break
                builder.write_bool(True)   # isDone
                builder.write_string("")   # sem erro
                self.log(f"✅ Personagem selecionado: {name}")
            else:
                builder.write_bool(False)  # isDone
                builder.write_string(result.get('FailureReason', 'Erro ao selecionar'))
                self.log(f"❌ Falha ao selecionar: {result.get('FailureReason')}")
            
            packet = builder.build(RoleCommandCode.SELECT_ROLE_ANSWER)
            self.send_packet(packet)
            
        except Exception as e:
            self.log(f"Erro ao selecionar role: {e}")
            import traceback
            traceback.print_exc()
    
    def handle_delete_role(self, reader: PacketReader):
        """Processa DeleteRoleRequest (cmd 263)"""
        try:
            name = reader.read_string()
            self.log(f"DeleteRoleRequest: name={name}")
            
            # Marcar para deleção usando banco de dados
            result = delete_role_for_account(self.account_id, name)
            
            builder = PacketBuilder()
            builder.write_bool(bool(result.get('IsDone')))
            builder.write_string(result.get('FailureReason', '') if not result.get('IsDone') else '')
            
            packet = builder.build(RoleCommandCode.DELETE_ROLE_ANSWER)
            self.send_packet(packet)
            
            if result.get('IsDone'):
                self.log(f"✅ Personagem marcado para deleção: {name}")
            else:
                self.log(f"❌ Falha ao deletar: {result.get('FailureReason')}")
            
        except Exception as e:
            self.log(f"Erro ao deletar role: {e}")

def handle_world_client(client_socket, address):
    """Handler para cliente do World Server"""
    session = WorldSession(client_socket, address)
    session.log("Cliente conectado ao World Server")
    
    buffer = b''
    
    try:
        while True:
            try:
                data = client_socket.recv(4096)
                if not data:
                    break
                
                buffer += data
                
                # Processar packets usando VarInt para length
                while len(buffer) >= 1:
                    # Ler VarInt para comprimento
                    length = 0
                    shift = 0
                    varint_bytes = 0
                    
                    for i in range(min(5, len(buffer))):
                        byte = buffer[i]
                        length |= (byte & 0x7F) << shift
                        varint_bytes += 1
                        if (byte & 0x80) == 0:
                            break
                        shift += 7
                    else:
                        if len(buffer) >= 5:
                            session.log(f"VarInt inválido")
                            buffer = buffer[1:]
                        break
                    
                    total_len = varint_bytes + length
                    if len(buffer) < total_len:
                        break
                    
                    packet_data = buffer[varint_bytes:total_len]
                    buffer = buffer[total_len:]
                    
                    # Parse: command (2 bytes) + digest (2 bytes) + payload
                    if len(packet_data) < 4:
                        session.log(f"Packet muito pequeno: {len(packet_data)}")
                        continue
                    
                    command = struct.unpack('>H', packet_data[:2])[0]
                    digest = struct.unpack('>H', packet_data[2:4])[0]
                    payload = packet_data[4:]
                    
                    session.log(f"Recebido: cmd={command}, digest={digest}, len={len(payload)}, payload={payload.hex()[:60] if payload else ''}")
                    
                    reader = PacketReader(payload) if payload else PacketReader(b'')
                    
                    # Comandos do World
                    if command == RoleCommandCode.WORLD_LOGIN_REQ:
                        session.handle_world_login(reader)
                    
                    # Comandos de Role (257+)
                    elif command == RoleCommandCode.ROLE_LIST_REQ:
                        session.handle_role_list(reader)
                    elif command == RoleCommandCode.ROLE_NAME_CONFIRM_REQ:
                        session.handle_role_name_confirm(reader)
                    elif command == RoleCommandCode.CREATE_ROLE_REQ:
                        session.handle_create_role(reader)
                    elif command == RoleCommandCode.SELECT_ROLE_REQ:
                        session.handle_select_role(reader)
                    elif command == RoleCommandCode.DELETE_ROLE_REQ:
                        session.handle_delete_role(reader)
                    
                    else:
                        session.log(f"⚠️ Comando desconhecido: {command}")
                        
            except socket.timeout:
                continue
            except Exception as e:
                session.log(f"Erro: {e}")
                import traceback
                traceback.print_exc()
                break
                
    except Exception as e:
        session.log(f"Erro na sessão: {e}")
    finally:
        session.log("Cliente desconectado")
        client_socket.close()

def start_world_server():
    """Inicia servidor World"""
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server_socket.bind((HOST, WORLD_PORT))
        server_socket.listen(5)
        log("WORLD", f"Servidor World iniciado em {HOST}:{WORLD_PORT}")
        
        while True:
            try:
                server_socket.settimeout(1.0)
                client_socket, address = server_socket.accept()
                client_socket.settimeout(60.0)
                
                thread = threading.Thread(
                    target=handle_world_client,
                    args=(client_socket, address),
                    daemon=True
                )
                thread.start()
                
            except socket.timeout:
                continue
            except Exception as e:
                log("WORLD", f"Erro: {e}")
                
    except Exception as e:
        log("WORLD", f"Erro fatal: {e}")
    finally:
        server_socket.close()

# ============================================================================
# MAIN
# ============================================================================

def main():
    print("\n" + "="*70)
    print("  🎮 Servidor Asa de Cristal - Completo")
    print("="*70)
    print(f"  🌐 HTTP:    http://localhost:{HTTP_PORT}")
    print(f"  📡 Login:   {HOST}:{LOGIN_PORT}")
    print(f"  🌍 World:   {HOST}:{WORLD_PORT}")
    print(f"  🔒 Policy:  {HOST}:{POLICY_PORT}")
    print("="*70)
    
    # Inicializar banco de dados
    print(f"\n  💾 Modo de autenticação: {AUTH_MODE}")
    if AUTH_MODE == 'db':
        print("  📊 Conectando ao SQL Server...")
        if init_database():
            print("  ✅ Banco de dados conectado!")
            servers = get_servers_from_db()
            print(f"  📋 {len(servers)} servidor(es) carregado(s) do banco")
        else:
            print("  ⚠️ Banco não disponível - usando modo debug")
    else:
        print("  ⚠️ Modo DEBUG - aceitando qualquer login")
    
    print("\n  Pressione Ctrl+C para parar\n")
    
    # Iniciar threads
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    login_thread = threading.Thread(target=start_login_server, daemon=True)
    policy_thread = threading.Thread(target=start_policy_server, daemon=True)
    world_thread = threading.Thread(target=start_world_server, daemon=True)
    
    http_thread.start()
    login_thread.start()
    policy_thread.start()
    world_thread.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n  ✅ Servidor encerrado.\n")
        sys.exit(0)

if __name__ == "__main__":
    main()
