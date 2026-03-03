import pyodbc
from typing import Dict, List, Optional

DB_SERVER = '26.107.162.208'
DB_NAME = 'mspt1'
DB_USER = 'fgcuser'
DB_PASSWORD = 'EDE(hGp6vz2q_sb'
DB_TRUSTED = False

_db_instance = None

class Database:
    def __init__(self):
        self.conn = None
        
    def connect(self) -> bool:
        try:
            if DB_TRUSTED:
                conn_str = f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={DB_SERVER};DATABASE={DB_NAME};Trusted_Connection=yes;'
            else:
                conn_str = f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={DB_SERVER};DATABASE={DB_NAME};UID={DB_USER};PWD={DB_PASSWORD}'
            self.conn = pyodbc.connect(conn_str)
            return True
        except Exception as e:
            print(f"[DB] Erro conexão: {e}")
            return False
    
    def execute_query(self, query: str, params: tuple = None) -> List[Dict]:
        if not self.conn:
            return []
        cursor = self.conn.cursor()
        cursor.execute(query, params or ())
        columns = [col[0] for col in cursor.description] if cursor.description else []
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    def execute_non_query(self, query: str, params: tuple = None) -> int:
        if not self.conn:
            return 0
        cursor = self.conn.cursor()
        cursor.execute(query, params or ())
        self.conn.commit()
        return cursor.rowcount
    
    def execute_proc(self, proc_name: str, params: Dict = None) -> List[Dict]:
        if not self.conn:
            return []
        cursor = self.conn.cursor()
        param_str = ', '.join([f"@{k}=?" for k in (params or {}).keys()])
        query = f"EXEC {proc_name} {param_str}" if param_str else f"EXEC {proc_name}"
        cursor.execute(query, tuple((params or {}).values()))
        
        if cursor.description:
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        return []
    
    def execute_proc_multi(self, proc_name: str, params: Dict = None) -> List[List[Dict]]:
        if not self.conn:
            return []
        cursor = self.conn.cursor()
        param_str = ', '.join([f"@{k}=?" for k in (params or {}).keys()])
        query = f"EXEC {proc_name} {param_str}" if param_str else f"EXEC {proc_name}"
        cursor.execute(query, tuple((params or {}).values()))
        
        results = []
        while True:
            if cursor.description:
                columns = [col[0] for col in cursor.description]
                rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
                results.append(rows)
            if not cursor.nextset():
                break
        return results

# Alias para compatibilidade
DatabaseManager = Database

class AccountRepository:
    def __init__(self, db: Database):
        self.db = db
    
    def get_account(self, username: str) -> Optional[Dict]:
        result = self.db.execute_query(
            "SELECT Id, Username, PasswordHash, Status FROM TB_Account WHERE Username=?",
            (username,))
        if result:
            r = result[0]
            return {
                'AccountUID': r.get('Id'),
                'Username': r.get('Username'),
                'LoginPwd': r.get('PasswordHash', ''),
                'IsBanned': r.get('Status', 0) == 2,
                'IsAdult': True
            }
        return None
    
    def create_session(self, account_id: int, client_ip: str) -> Dict:
        import uuid
        ticket = str(uuid.uuid4())
        try:
            self.db.execute_non_query(
                "DELETE FROM TB_Session WHERE AccountId=?", (account_id,))
            self.db.execute_non_query(
                "INSERT INTO TB_Session (AccountId, SessionKey, ClientIP, CreatedAt) VALUES (?, ?, ?, GETDATE())",
                (account_id, ticket, client_ip))
        except:
            pass
        return {'Ticket': ticket}
    
    def authenticate(self, username: str, password: str) -> Optional[Dict]:
        result = self.db.execute_query(
            "SELECT Id, Username, Status FROM TB_Account WHERE Username=? AND PasswordHash=?",
            (username, password))
        return result[0] if result else None

class ServerRepository:
    def __init__(self, db: Database):
        self.db = db
    
    def get_server_list(self) -> List[Dict]:
        return self.db.execute_query(
            "SELECT Id as ServerID, ServerName, ServerIP, ServerPort, Status FROM TB_Server WHERE Status=1")

class RoleRepository:
    def __init__(self, db: Database):
        self.db = db
    
    def get_account_by_ticket(self, ticket: str) -> Optional[Dict]:
        result = self.db.execute_query(
            "SELECT AccountId as AccountUID FROM TB_Session WHERE SessionKey=?", (ticket,))
        if result:
            return result[0]
        # Modo debug: usar conta fixa ID=1 para todos
        existing = self.db.execute_query("SELECT Id FROM TB_Account WHERE Id=1")
        if not existing:
            self.db.execute_non_query(
                "SET IDENTITY_INSERT TB_Account ON; INSERT INTO TB_Account (Id, Username, PasswordHash) VALUES (1, 'debug', 'debug'); SET IDENTITY_INSERT TB_Account OFF;")
        return {'AccountUID': 1}
    
    def get_roles_by_account(self, account_id) -> List[Dict]:
        return self.db.execute_query(
            "SELECT * FROM TB_Role WHERE AccountId=? AND DeletedFlag=0", (account_id,))
    
    def check_name(self, name: str) -> bool:
        result = self.db.execute_query("SELECT 1 FROM TB_Role WHERE Name=?", (name,))
        return len(result) == 0
    
    def create_role(self, account_uid: int = None, account_id: int = None, name: str = '', 
                     job_code: int = 1, sex: int = 0, head_icon_index: int = 0, 
                     hair_style_index: int = 0, data: Dict = None) -> Dict:
        acc_id = account_uid or account_id
        if data:
            name = data.get('name', name)
            job_code = data.get('jobCode', job_code)
            sex = data.get('sex', sex)
            head_icon_index = data.get('headIconIndex', head_icon_index)
            hair_style_index = data.get('hairStyleIndex', hair_style_index)
        
        self.db.execute_non_query(
            """INSERT INTO TB_Role (AccountId, Name, JobCode, Sex, Level, HeadIconIndex, HairStyleIndex)
               VALUES (?, ?, ?, ?, 1, ?, ?)""",
            (acc_id, name, job_code, sex, head_icon_index, hair_style_index))
        
        result = self.db.execute_query("SELECT * FROM TB_Role WHERE Name=?", (name,))
        if result:
            r = result[0]
            return {
                'Status': 0,
                'RoleID': r.get('Id'),
                'Name': r.get('Name'),
                'JobCode': r.get('JobCode'),
                'Sex': r.get('Sex'),
                'Level': r.get('Level', 1),
                'HeadIconIndex': r.get('HeadIconIndex', 0),
                'HairStyleIndex': r.get('HairStyleIndex', 0),
                'AccountUID': acc_id,
                'CreateTime': str(r.get('CreatedAt', '')),
                'LastPlayTime': str(r.get('LastPlayTime', ''))
            }
        return {'Status': 1, 'Message': 'Erro ao criar'}
    
    def delete_role(self, account_id: int, name: str) -> bool:
        return self.db.execute_non_query(
            "UPDATE TB_Role SET DeletedFlag=1 WHERE AccountId=? AND Name=?", (account_id, name)) > 0
    
    def select_role(self, account_id: int, name: str, password: str = None) -> Dict:
        result = self.db.execute_query(
            "SELECT 1 FROM TB_Role WHERE AccountId=? AND Name=? AND DeletedFlag=0", (account_id, name))
        if len(result) > 0:
            return {'IsDone': True, 'FailureReason': ''}
        return {'IsDone': False, 'FailureReason': 'Personagem não encontrado'}

def get_db() -> Database:
    global _db_instance
    if not _db_instance:
        _db_instance = Database()
    return _db_instance

def get_account_repo() -> AccountRepository:
    return AccountRepository(get_db())

def get_server_repo() -> ServerRepository:
    return ServerRepository(get_db())

def get_role_repo() -> RoleRepository:
    return RoleRepository(get_db())
