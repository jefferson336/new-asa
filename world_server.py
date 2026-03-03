import socket
import struct
import time
import logging
from typing import Dict, List, Optional

from .base_server import BaseTCPServer, log
from protocol import PacketReader, PacketBuilder, WorldCommandCode, RoleCommandCode, PlayerCommandCode, BagCommandCode, ShopCommandCode

logger = logging.getLogger(__name__)

from handlers.registry import get_handler_registry

try:
    from game_data.map_teleport_config import MAP_EXITS as _MAP_EXITS_RAW, MAP_ENTRIES as _MAP_ENTRIES_RAW
    
    MAP_EXITS = {}
    for (from_map, exit_id), (to_map, to_entry) in _MAP_EXITS_RAW.items():
        if from_map not in MAP_EXITS:
            MAP_EXITS[from_map] = {}
        MAP_EXITS[from_map][exit_id] = {"toMap": to_map, "toEntry": to_entry}
    
    MAP_ENTRIES = {}
    for (map_id, entry_id), (pos_x, pos_y) in _MAP_ENTRIES_RAW.items():
        if map_id not in MAP_ENTRIES:
            MAP_ENTRIES[map_id] = {}
        MAP_ENTRIES[map_id][entry_id] = {"x": pos_x, "y": pos_y}
    
    print(f"[MAPS] Loaded {len(_MAP_EXITS_RAW)} exits and {len(_MAP_ENTRIES_RAW)} entries from config")
except ImportError as e:
    print(f"[WARN] Could not load map_teleport_config: {e}")
    print("[WARN] Using empty map configs - run generate_map_teleport_sql.py to generate")
    MAP_EXITS = {}
    MAP_ENTRIES = {}

def write_transportable_object(builder: PacketBuilder, write_func, *args, **kwargs):
    """
    Wrapper para escrever objetos transportáveis com prefixo de tamanho (2 bytes ushort).
    O cliente espera: length(2 bytes) + data
    Se length=0, o objeto é null.
    """
    import struct
    
    temp_builder = PacketBuilder()
    write_func(temp_builder, *args, **kwargs)
    obj_data = temp_builder.get_bytes()
    
    builder.write_unsigned_short(len(obj_data))
    builder.write_bytes(obj_data)

def _write_map_point_raw(builder: PacketBuilder, x: int = 0, y: int = 0):
    """Serializa MapPoint (sem prefixo de tamanho): ["x:short","y:short"]"""
    builder.write_short(x)
    builder.write_short(y)

def write_map_point(builder: PacketBuilder, x: int = 0, y: int = 0):
    """Serializa MapPoint COM prefixo de tamanho: ["x:short","y:short"]"""
    before_len = len(builder.get_bytes())
    
    write_transportable_object(builder, _write_map_point_raw, x, y)
    
    after_bytes = builder.get_bytes()[before_len:]
    print(f"[DEBUG] write_map_point: x={x}, y={y} -> bytes: {after_bytes.hex()}")

def _write_dynamic_vars_raw(builder: PacketBuilder, bool_vars: Dict = None, int_vars: Dict = None, str_vars: Dict = None):
    """
    Serializa DynamicVars (sem prefixo):
    ["boolVars:map(string,boolean)","intVars:map(string,vint)","strVars:map(string,string)"]
    """
    bool_vars = bool_vars or {}
    int_vars = int_vars or {}
    str_vars = str_vars or {}
    
    builder.write_varint(len(bool_vars))
    for key, val in bool_vars.items():
        builder.write_string(key)
        builder.write_bool(val)
    
    builder.write_varint(len(int_vars))
    for key, val in int_vars.items():
        builder.write_string(key)
        builder.write_varint(val)
    
    builder.write_varint(len(str_vars))
    for key, val in str_vars.items():
        builder.write_string(key)
        builder.write_string(val)

def write_dynamic_vars(builder: PacketBuilder, bool_vars: Dict = None, int_vars: Dict = None, str_vars: Dict = None):
    """Serializa DynamicVars COM prefixo de tamanho"""
    write_transportable_object(builder, _write_dynamic_vars_raw, bool_vars, int_vars, str_vars)

def _write_task_recorder_raw(builder: PacketBuilder, doing_allocators: Dict = None, doing_tasks: List = None, done_tasks: Dict = None):
    """
    Serializa TaskRecorder (sem prefixo):
    ["doingAllocators:map(ushort,ushort)","doingTasks:array(ushort)","doneTasks:map(ushort,short)"]
    """
    doing_allocators = doing_allocators or {}
    doing_tasks = doing_tasks or []
    done_tasks = done_tasks or {}
    
    builder.write_varint(len(doing_allocators))
    for key, val in doing_allocators.items():
        builder.write_unsigned_short(int(key))
        builder.write_unsigned_short(int(val))
    
    builder.write_varint(len(doing_tasks))
    for task in doing_tasks:
        builder.write_unsigned_short(task)
    
    builder.write_varint(len(done_tasks))
    for key, val in done_tasks.items():
        builder.write_unsigned_short(int(key))
        builder.write_short(int(val))

def write_task_recorder(builder: PacketBuilder, doing_allocators: Dict = None, doing_tasks: List = None, done_tasks: Dict = None):
    """Serializa TaskRecorder COM prefixo de tamanho"""
    write_transportable_object(builder, _write_task_recorder_raw, doing_allocators, doing_tasks, done_tasks)

def _write_friend_info_raw(builder: PacketBuilder, friend: Dict):
    """
    Serializa FriendInfo (sem prefixo):
    ["friendName:string","relationValue:int","sex:byte","level:short","isOnline:boolean","moodIndex:byte"]
    """
    builder.write_string(friend.get('friendName', ''))
    builder.write_int(friend.get('relationValue', 0))
    builder.write_byte(friend.get('sex', 0))
    builder.write_short(friend.get('level', 1))
    builder.write_bool(friend.get('isOnline', False))
    builder.write_byte(friend.get('moodIndex', 0))

def write_friend_info(builder: PacketBuilder, friend: Dict):
    """Serializa FriendInfo COM prefixo de tamanho"""
    write_transportable_object(builder, _write_friend_info_raw, friend)

def _write_role_attributes_raw(builder: PacketBuilder, attrs: Dict = None):
    """
    Serializa RoleAttributesInfo (sem prefixo) com todos os campos:
    ["strength:int","wisdom:int","agility:int","vitality:int","hp:double","hpMax:double",
     "mp:int","mpMax:int","sp:int","spMax:int","xp:int","xpMax:int",
     "physicalAttack:int","physicalDefense:int","physicalReduceRate:float",
     "magicAttack:int","magicDefense:int","magicReduceRate:float",
     "hitValue:int","hitRate:float","dodgeValue:int","dodgeRate:float",
     "critValue:int","critRate:float","luckyAttack:int","luckyDefense:int",
     "critDamageMul:float","toughValue:int","pierceAttack:int","pierceDefense:int",
     "singTimeModifier:float","castTimeModifier:float","singTimeReduceMS:int",
     "walkSpeed:int","hpHealValue:int","mpHealValue:int","spHealValue:int",
     "cureValue:int","element1Attack:int","element2Attack:int","element3Attack:int",
     "element4Attack:int","element5Attack:int","element1Defense:int","element2Defense:int",
     "element3Defense:int","element4Defense:int","element5Defense:int",
     "lot:int","loa:int","loh:int"]
    """
    attrs = attrs or {}
    
    builder.write_int(attrs.get('strength', 10))
    builder.write_int(attrs.get('wisdom', 10))
    builder.write_int(attrs.get('agility', 10))
    builder.write_int(attrs.get('vitality', 10))
    
    builder.write_double(float(attrs.get('hp', 100)))
    builder.write_double(float(attrs.get('hpMax', 100)))
    builder.write_int(attrs.get('mp', 50))
    builder.write_int(attrs.get('mpMax', 50))
    builder.write_int(attrs.get('sp', 0))
    builder.write_int(attrs.get('spMax', 100))
    builder.write_int(attrs.get('xp', 0))
    builder.write_int(attrs.get('xpMax', 100))
    
    builder.write_int(attrs.get('physicalAttack', 10))
    builder.write_int(attrs.get('physicalDefense', 5))
    builder.write_float(attrs.get('physicalReduceRate', 0.0))
    builder.write_int(attrs.get('magicAttack', 10))
    builder.write_int(attrs.get('magicDefense', 5))
    builder.write_float(attrs.get('magicReduceRate', 0.0))
    
    builder.write_int(attrs.get('hitValue', 50))
    builder.write_float(attrs.get('hitRate', 0.95))
    builder.write_int(attrs.get('dodgeValue', 10))
    builder.write_float(attrs.get('dodgeRate', 0.05))
    builder.write_int(attrs.get('critValue', 10))
    builder.write_float(attrs.get('critRate', 0.05))
    builder.write_int(attrs.get('luckyAttack', 0))
    builder.write_int(attrs.get('luckyDefense', 0))
    builder.write_float(attrs.get('critDamageMul', 1.5))
    builder.write_int(attrs.get('toughValue', 0))
    builder.write_int(attrs.get('pierceAttack', 0))
    builder.write_int(attrs.get('pierceDefense', 0))
    
    builder.write_float(attrs.get('singTimeModifier', 1.0))
    builder.write_float(attrs.get('castTimeModifier', 1.0))
    builder.write_int(attrs.get('singTimeReduceMS', 0))
    
    builder.write_int(attrs.get('walkSpeed', 200))
    builder.write_int(attrs.get('hpHealValue', 0))
    builder.write_int(attrs.get('mpHealValue', 0))
    builder.write_int(attrs.get('spHealValue', 0))
    builder.write_int(attrs.get('cureValue', 0))
    
    for i in range(1, 6):
        builder.write_int(attrs.get(f'element{i}Attack', 0))
    for i in range(1, 6):
        builder.write_int(attrs.get(f'element{i}Defense', 0))
    
    builder.write_int(attrs.get('lot', 0))
    builder.write_int(attrs.get('loa', 0))
    builder.write_int(attrs.get('loh', 0))

def write_role_attributes(builder: PacketBuilder, attrs: Dict = None):
    """Serializa RoleAttributesInfo COM prefixo de tamanho"""
    write_transportable_object(builder, _write_role_attributes_raw, attrs)

def _write_mate_relation_info_raw(builder: PacketBuilder, mate: Dict = None):
    """
    Serializa MateRelationInfo (sem prefixo):
    ["mateName:string","relationType:byte","mateValue:ushort","mateGold:ushort"]
    """
    mate = mate or {}
    builder.write_string(mate.get('mateName', ''))
    builder.write_byte(mate.get('relationType', 0))
    builder.write_unsigned_short(mate.get('mateValue', 0))
    builder.write_unsigned_short(mate.get('mateGold', 0))

def write_mate_relation_info(builder: PacketBuilder, mate: Dict = None):
    """Serializa MateRelationInfo COM prefixo de tamanho"""
    write_transportable_object(builder, _write_mate_relation_info_raw, mate)

def _write_buff_info_raw(builder: PacketBuilder, buff: Dict):
    """
    Serializa BuffInfo (sem prefixo):
    ["buffId:ushort","durationInSec:vint"]
    """
    builder.write_unsigned_short(buff.get('buffId', 0))
    builder.write_varint(buff.get('durationInSec', 0))

def write_buff_info(builder: PacketBuilder, buff: Dict):
    """Serializa BuffInfo COM prefixo de tamanho"""
    write_transportable_object(builder, _write_buff_info_raw, buff)

def _write_local_player_farm_info_raw(builder: PacketBuilder, farm: Dict = None):
    """
    Serializa LocalPlayerFarmInfo (sem prefixo):
    ["mapId:string","farmId:string","templetCode:string","name:string",
     "ownerId:string","currentLevel:byte","farmExp:int","styleCode:string"]
    """
    farm = farm or {}
    builder.write_string(farm.get('mapId', ''))
    builder.write_string(farm.get('farmId', ''))
    builder.write_string(farm.get('templetCode', ''))
    builder.write_string(farm.get('name', ''))
    builder.write_string(farm.get('ownerId', ''))
    builder.write_byte(farm.get('currentLevel', 1))
    builder.write_int(farm.get('farmExp', 0))
    builder.write_string(farm.get('styleCode', ''))

def write_local_player_farm_info(builder: PacketBuilder, farm: Dict = None):
    """Serializa LocalPlayerFarmInfo COM prefixo de tamanho"""
    write_transportable_object(builder, _write_local_player_farm_info_raw, farm)

def _write_local_player_info_raw(builder: PacketBuilder, role: Dict, attrs: Dict = None):
    """
    Serializa LocalPlayerInfo completo (sem prefixo) (RoleBaseInfo + LocalPlayerInfo fields)
    
    RoleBaseInfo: ["name:string","jobCode:byte","sex:byte","level:short","headIconIndex:ushort","hairStyleIndex:ubyte"]
    
    LocalPlayerInfo adiciona muitos campos!
    """
    start_pos = len(builder.get_bytes())
    
    builder.write_string(role.get('name', ''))
    builder.write_byte(role.get('jobCode', 1))
    builder.write_byte(role.get('sex', 0))
    builder.write_short(role.get('level', 1))
    builder.write_unsigned_short(role.get('headIconIndex', 0))
    builder.write_unsigned_byte(role.get('hairStyleIndex', 0))  # ubyte!
    
    rolebase_end = len(builder.get_bytes())
    print(f"[DEBUG] RoleBaseInfo: {builder.get_bytes()[start_pos:rolebase_end].hex()}")
    
    builder.write_bool(role.get('isGM', False))
    builder.write_byte(role.get('vipLevel', 0))
    builder.write_string(role.get('mapId', 'a1'))
    
    pre_position = len(builder.get_bytes())
    print(f"[DEBUG] até mapId: {builder.get_bytes()[rolebase_end:pre_position].hex()}")
    
    write_map_point(builder, role.get('posX', 900), role.get('posY', 700))
    builder.write_varint(0)
    builder.write_varint(0)
    builder.write_string(role.get('rideCode', ''))
    builder.write_string(role.get('rideMasterPlayerId', ''))
    builder.write_varint(0)
    builder.write_short(role.get('titleIndex', 0))
    builder.write_short(role.get('kitTitleIndex', 0))
    builder.write_bool(role.get('isDead', False))
    builder.write_bool(role.get('isSitting', False))
    builder.write_double(float(role.get('exp', 0)))
    write_role_attributes(builder, attrs)
    builder.write_int(role.get('statusFlags', 0))
    builder.write_double(float(role.get('gold', 0)))
    builder.write_int(role.get('money', 0))
    builder.write_int(role.get('coin', 0))
    builder.write_int(role.get('vipExp', 0))
    builder.write_byte(role.get('lifeJob', 0))
    builder.write_byte(role.get('lifeLevel', 0))
    builder.write_int(role.get('lifeExp', 0))
    farm_skill_levels = role.get('farmSkillLevelArray', [0, 0, 0, 0])
    builder.write_varint(len(farm_skill_levels))
    for lv in farm_skill_levels:
        builder.write_byte(lv)
    farm_skill_exps = role.get('farmSkillExpArray', [0, 0, 0, 0])
    builder.write_varint(len(farm_skill_exps))
    for exp in farm_skill_exps:
        builder.write_int(exp)
    write_local_player_farm_info(builder, role.get('mainFarm'))
    builder.write_varint(0)
    builder.write_byte(role.get('pkMode', 0))
    builder.write_byte(role.get('pkValue', 0))
    builder.write_byte(role.get('lineIndex', 0))
    write_mate_relation_info(builder, role.get('mateRelationInfo'))
    write_dynamic_vars(builder)
    builder.write_int(role.get('bkHp', 0))
    builder.write_int(role.get('bkHpMax', 0))
    builder.write_int(role.get('bkMp', 0))
    builder.write_int(role.get('bkMpMax', 0))
    builder.write_int(role.get('petBkHp', 0))
    builder.write_int(role.get('petBkHpMax', 0))
    builder.write_int(role.get('petBkMp', 0))
    builder.write_int(role.get('petBkMpMax', 0))
    builder.write_int(role.get('honorValue', 0))
    builder.write_byte(role.get('honorLevel', 0))
    builder.write_int(role.get('freeAttrPt', 0))
    builder.write_byte(role.get('rebornTimes', 0))
    builder.write_byte(role.get('side', 0))
    builder.write_int(role.get('payMarks', 0))
    builder.write_int(role.get('charmValue', 0))
    builder.write_int(role.get('charmInt', 0))
    builder.write_byte(role.get('beliefGod', 0))
    builder.write_byte(role.get('beliefLevel', 0))
    builder.write_byte(role.get('armoryLevel', 0))
    builder.write_varint(0)
    builder.write_int(role.get('armoryExp', 0))
    builder.write_short(role.get('maxLevel', 999))
    builder.write_varint(0)
    builder.write_int(role.get('dragonLevel', 0))
    builder.write_int(role.get('dragonExp', 0))
    builder.write_varint(role.get('dragonUpChanceNum', 0))
    builder.write_bool(role.get('isAntoHp', False))
    builder.write_bool(role.get('isAntoMp', False))
    builder.write_int(role.get('consecutiveLoginDays', 1))
    builder.write_string(role.get('boonItemCode', ''))
    builder.write_int(role.get('stirpLevel', 0))
    builder.write_unsigned_byte(role.get('potentialLevel', 0))
    builder.write_int(role.get('potentialValue', 0))
    builder.write_byte(role.get('refineLevel', 0))
    builder.write_byte(role.get('lightLevel', 0))
    builder.write_byte(role.get('boneLevel', 0))
    builder.write_unsigned_byte(role.get('constellation', 0))
    builder.write_unsigned_byte(role.get('constellationLevel', 0))
    builder.write_int(role.get('constellationTaskId', 0))
    builder.write_unsigned_byte(role.get('luckLevel', 0))
    builder.write_unsigned_byte(role.get('hartLevel', 0))
    builder.write_unsigned_byte(role.get('gameTimes', 0))
    builder.write_short(role.get('arenaIntegral', 0))
    builder.write_int(role.get('towerValue', 0))
    builder.write_varint(0)
    builder.write_string(time.strftime('%Y-%m-%d %H:%M:%S'))
    builder.write_string(role.get('modelCode', ''))

def write_local_player_info(builder: PacketBuilder, role: Dict, attrs: Dict = None):
    """Serializa LocalPlayerInfo COM prefixo de tamanho"""
    before = len(builder.get_bytes())
    write_transportable_object(builder, _write_local_player_info_raw, role, attrs)
    after = len(builder.get_bytes())
    data = builder.get_bytes()[before:after]
    size_prefix = int.from_bytes(data[:2], 'big')
    print(f"[DEBUG] LocalPlayerInfo: total={len(data)} bytes, size_prefix={size_prefix}")
    print(f"[DEBUG] Primeiros 50 bytes: {data[:50].hex()}")

class WorldSession:
    
    def __init__(self, client_socket: socket.socket, address: tuple, server: 'WorldServer'):
        self.socket = client_socket
        self.address = address
        self.server = server
        self.session_id: Optional[str] = None
        self.account_id: Optional[str] = None
        self.selected_role: Optional[Dict] = None
        self.player_data: Optional[Dict] = None
    
    def log(self, message: str):
        log("WORLD", f"[{self.address}] {message}")
    
    def send_packet(self, packet: bytes):
        """Envia pacote ao cliente"""
        try:
            self.socket.send(packet)
            self.log(f"Enviado {len(packet)} bytes")
        except Exception as e:
            self.log(f"Erro ao enviar: {e}")
    
    
    def handle_enter_world(self, reader: PacketReader):
        """
        Entrar no mundo/jogo (cmd 513)
        
        PlayerEnterWorldAnswer campos:
        - role:LocalPlayerInfo
        - clientConfig:string
        - vars:DynamicVars
        - killedMonsters:DynamicVars
        - taskRecorder:TaskRecorder
        - friendList:array(FriendInfo)
        - isWaiting:boolean
        - waitingTotal:short
        - waitingIndex:short
        - failureReason:string
        - sysVars:DynamicVars
        """
        try:
            self.log(f"=== PlayerEnterWorldRequest (cmd 513) ===")
            
            if not self.selected_role:
                self.log("❌ Nenhum personagem selecionado!")
                builder = PacketBuilder()
                self._write_enter_world_error(builder, "Nenhum personagem selecionado")
                self.send_packet(builder.build(PlayerCommandCode.PLAYER_ENTER_WORLD_ANSWER))
                return
            
            role_name = self.selected_role.get('name', '')
            self.log(f"Entrando com personagem: {role_name}")
            
            player_data = None
            if self.server._db_available:
                self.log(f"🔍 Banco disponível, carregando dados de {role_name}...")
                try:
                    from player_data_manager import PlayerDataManager
                    pdm = PlayerDataManager(self.server._get_db())
                    player_data = pdm.load_player_full_data(role_name)
                    if player_data:
                        self.log(f"✅ Dados carregados: posX={player_data.get('posX')}, posY={player_data.get('posY')}, mapId={player_data.get('mapId')}")
                        # TEMPORÁRIO: Forçar posição padrão para debug
                        player_data['posX'] = 900
                        player_data['posY'] = 700
                        player_data['mapId'] = 'a1'
                except Exception as e:
                    self.log(f"⚠️ Erro ao carregar do banco: {e}")
            
            if not player_data:
                self.log("⚠️ Usando dados básicos (banco indisponível)")
                player_data = {
                    'name': role_name,
                    'jobCode': self.selected_role.get('jobCode', 1),
                    'sex': self.selected_role.get('sex', 0),
                    'level': self.selected_role.get('level', 1),
                    'headIconIndex': self.selected_role.get('headIconIndex', 0),
                    'hairStyleIndex': self.selected_role.get('hairStyleIndex', 0),
                    'mapId': 'a1',
                    'posX': 32,
                    'posY': 63,
                }
            
            self.player_data = player_data
            
            builder = PacketBuilder()
            
            write_local_player_info(builder, player_data, player_data)
            
            builder.write_string(player_data.get('clientConfig', ''))
            
            vars_data = player_data.get('vars', {})
            write_dynamic_vars(builder, 
                vars_data.get('bool', {}), 
                vars_data.get('int', {}), 
                vars_data.get('str', {}))
            
            killed = player_data.get('killedMonsters', {})
            write_dynamic_vars(builder,
                killed.get('bool', {}),
                killed.get('int', {}),
                killed.get('str', {}))
            
            task_rec = player_data.get('taskRecorder', {})
            write_task_recorder(builder,
                task_rec.get('doingAllocators', {}),
                task_rec.get('doingTasks', []),
                task_rec.get('doneTasks', {}))
            
            friends = player_data.get('friendList', [])
            builder.write_varint(len(friends))
            for friend in friends:
                write_friend_info(builder, friend)
            
            builder.write_bool(False)
            
            builder.write_short(0)
            
            builder.write_short(0)
            
            builder.write_string("")
            
            sys_vars = player_data.get('sysVars', {})
            write_dynamic_vars(builder,
                sys_vars.get('bool', {}),
                sys_vars.get('int', {}),
                sys_vars.get('str', {}))
            
            packet = builder.build(PlayerCommandCode.PLAYER_ENTER_WORLD_ANSWER)
            self.log(f"📦 Pacote 514: {len(packet)} bytes total, payload hex (primeiros 100): {packet[:100].hex()}")
            self.send_packet(packet)
            self.log(f"✅ PlayerEnterWorldAnswer enviado!")
            
            self._auto_send_map_data()
            
        except Exception as e:
            self.log(f"Erro ao entrar no mundo: {e}")
            import traceback
            traceback.print_exc()
    
    def _auto_send_map_data(self):
        try:
            if not self.player_data:
                return
            
            map_id = self.player_data.get('mapId', 'a1')
            
            builder = PacketBuilder()
            builder.write_string(map_id)
            builder.write_varint(0)
            builder.write_varint(0)
            builder.write_varint(0)
            builder.write_varint(0)
            builder.write_varint(0)
            builder.write_varint(0)
            builder.write_varint(0)
            write_dynamic_vars(builder)
            
            self.send_packet(builder.build(PlayerCommandCode.PLAYER_VIEW_MAP_ANSWER))
            self.log(f"✅ [AUTO] PlayerViewMapAnswer enviado para {map_id}")
            
            self._send_enter_map_answer()
            
        except Exception as e:
            self.log(f"Erro ao enviar dados do mapa automaticamente: {e}")
    
    def handle_view_map(self, reader: PacketReader):
        """
        Ver mapa (cmd 521) - Enviado pelo cliente após carregar recursos do mapa
        
        PlayerViewMapRequest: sem campos (field list vazio)
        
        PlayerViewMapAnswer campos:
        - mapId:string
        - remotePlayers:array(RemotePlayerInfo)
        - monsters:array(MonsterInfo)
        - traps:array(MapTrapInfo)
        - items:array(MapItemInfo)
        - farmsInUse:array(FarmInfo)
        - farmBuildings:array(FarmBuildingInfo)
        - farmHarvests:array(FarmHarvestInfo)
        - mapVars:DynamicVars
        """
        try:
            self.log(f"=== PlayerViewMapRequest (cmd 521) ===")
            
            if not self.selected_role:
                self.log("❌ Nenhum personagem selecionado!")
                return
            
            map_id = getattr(self, 'player_data', {}).get('mapId', 'a1')
            
            builder = PacketBuilder()
            
            builder.write_string(map_id)
            self.log(f"  mapId: {map_id}")
            
            builder.write_varint(0)
            
            builder.write_varint(0)
            
            builder.write_varint(0)
            
            builder.write_varint(0)
            
            builder.write_varint(0)
            
            builder.write_varint(0)
            
            builder.write_varint(0)
            
            write_dynamic_vars(builder)
            
            self.send_packet(builder.build(PlayerCommandCode.PLAYER_VIEW_MAP_ANSWER))
            self.log(f"✅ PlayerViewMapAnswer enviado!")
            
            self._send_enter_map_answer()
            
        except Exception as e:
            self.log(f"Erro ao processar view map: {e}")
            import traceback
            traceback.print_exc()
    
    def _send_enter_map_answer(self):
        if not self.player_data:
            return
        
        map_id = self.player_data.get('mapId', 'a1')
        pos_x = self.player_data.get('posX', 1024)
        pos_y = self.player_data.get('posY', 2048)
        line_index = self.player_data.get('lineIndex', 0)
        
        builder = PacketBuilder()
        
        builder.write_string(map_id)
        write_map_point(builder, pos_x, pos_y)
        builder.write_string("")
        builder.write_byte(line_index)
        
        self.send_packet(builder.build(518))
        self.log(f"✅ PlayerEnterMapAnswer enviado: map={map_id}, pos=({pos_x}, {pos_y})")
        
        self._send_all_bag_capacities()
    
    def _send_all_bag_capacities(self):
        
        bag_player = self.player_data.get('BagCapacityPlayer', 36) if self.player_data else 36
        bag_pet = self.player_data.get('BagCapacityPet', 3) if self.player_data else 3
        bag_ride = self.player_data.get('BagCapacityRide', 3) if self.player_data else 3
        
        self.log(f"📦 Capacidades: Player={bag_player}, Pet={bag_pet}, Ride={bag_ride}")
        
        self._send_bag_capacity(1, bag_player)
        self._send_bag_capacity(2, bag_pet)
        self._send_bag_capacity(3, bag_ride)
        
        self._send_all_inventory_items()
    
    def _send_all_inventory_items(self):
        if not self.selected_role:
            return
        
        role_name = self.selected_role.get('name', '')
        if not role_name:
            return
        
        try:
            from inventory_manager import InventoryManager
            inv_mgr = InventoryManager(self.server._get_db())
            
            for bag_index in [1, 2, 3]:
                items = inv_mgr.load_inventory(role_name, bag_index)
                if items:
                    self._send_bag_check(bag_index, items)
                    self.log(f"📦 Inventário bag {bag_index}: {len(items)} itens enviados")
            
            equip_items = inv_mgr.load_inventory(role_name, 10)
            if equip_items:
                is_use_fashion = self.player_data.get('isUseFashion', True)  # Default True
                fashion_builder = PacketBuilder()
                fashion_builder.write_bool(is_use_fashion)
                self.send_packet(fashion_builder.build(4612))
                self.log(f"🎨 FASHION LOGIN: {is_use_fashion} (carregado do DB)")
                
                for equip in equip_items:
                    item_def_result = self.server._db.execute_query(
                        "SELECT * FROM TB_ItemDefinition WHERE ItemCode = ?",
                        (equip.item_code,)
                    )
                    item_def = item_def_result[0] if item_def_result else None
                    self._send_view_item_answer(equip, equip.item_id, item_def)
                self.log(f"📦 GameItemFullInfo: {len(equip_items)} itens pré-carregados")
                
                self._send_equipment_check_notify(equip_items)
                
                self._send_player_attributes()
                
                self.log(f"⚔️ Equipamentos: {len(equip_items)} itens enviados")
            else:
                self.log(f"⚔️ Equipamentos: nenhum equipado")
                
                # TEMPORÁRIO: Comentado para debug
                # self._send_player_attributes()
            
                    
        except Exception as e:
            self.log(f"❌ Erro ao carregar inventário: {e}")
            import traceback
            traceback.print_exc()
    
    def _send_equipment_check_notify(self, items: list, empty_equipment_slots: list = None):
        """
        Envia PlayerEquipmentCheckNotify (cmd 4609)
        Campos: changedEquipments:array(EquippedItemInfo)
        
        EquippedItemInfo: equipmentKind:ushort, equipment:GameItemBriefInfo
        GameItemBriefInfo: itemId:string, itemCode:string, itemCount:ubyte
        
        Args:
            items: Lista de itens equipados (ItemInfo objects)
            empty_equipment_slots: Lista de slots que ficaram vazios (enviados com equipment=null)
        """
        empty_equipment_slots = empty_equipment_slots or []
        total_entries = len(items) + len(empty_equipment_slots)
        
        slots_info = []
        for item in items:
            slot_index = item.slot_index if hasattr(item, 'slot_index') else item.get('SlotIndex', 0)
            item_code = item.item_code if hasattr(item, 'item_code') else item.get('ItemCode', '')
            slots_info.append(f"slot {slot_index}={item_code}")
        for empty_slot in empty_equipment_slots:
            slots_info.append(f"slot {empty_slot}=NULL")
        logger.info(f"📤 CMD 4609: Enviando {total_entries} entries: {', '.join(slots_info)}")
        
        builder = PacketBuilder()
        
        builder.write_varint(total_entries)
        
        for empty_slot in empty_equipment_slots:
            item_builder = PacketBuilder()
            
            item_builder.write_unsigned_short(empty_slot)
            
            item_builder.write_unsigned_short(0)
            
            item_data = item_builder.get_bytes()
            builder.write_unsigned_short(len(item_data))
            builder.write_bytes(item_data)
        for item in items:
            item_builder = PacketBuilder()
            
            slot_index = item.slot_index if hasattr(item, 'slot_index') else item.get('SlotIndex', 0)
            item_builder.write_unsigned_short(slot_index)
            
            brief_builder = PacketBuilder()
            
            item_id = item.item_id if hasattr(item, 'item_id') else item.get('ItemId', '')
            brief_builder.write_string(item_id)
            
            item_code = item.item_code if hasattr(item, 'item_code') else item.get('ItemCode', '')
            brief_builder.write_string(item_code)
            
            item_count = item.item_count if hasattr(item, 'item_count') else item.get('ItemCount', 1)
            brief_builder.write_unsigned_byte(item_count)
            
            brief_data = brief_builder.get_bytes()
            item_builder.write_unsigned_short(len(brief_data))
            item_builder.write_bytes(brief_data)
            
            item_data = item_builder.get_bytes()
            builder.write_unsigned_short(len(item_data))
            builder.write_bytes(item_data)
        
        self.send_packet(builder.build(4609))
        self.log(f"✅ PlayerEquipmentCheckNotify enviado: {len(items)} equipados, {len(empty_equipment_slots)} vazios (NULL)")
    
    def _send_player_attributes(self):
        if not self.player_data:
            return
        
        from attribute_calculator import AttributeCalculator
        calculator = AttributeCalculator(self.server._get_db())
        
        role_name = self.player_data.get('name')
        equip_attrs = calculator.calculate_equipment_attributes(role_name)
        
        attr_data, stats = calculator.build_player_attributes_packet(self.player_data, equip_attrs)
        
        builder = PacketBuilder()
        builder.write_unsigned_short(len(attr_data))
        builder.write_bytes(attr_data)
        self.send_packet(builder.build(578))
        
        self.log(f"✅ PlayerAttributesChangeNotify enviado: ATK={stats['physical_attack']}, DEF={stats['physical_defense']}, HP={stats['hp']}/{stats['hp_max']:.0f}")
        if equip_attrs:
            equip_bonus_str = ", ".join([f"attr{k}:+{v:.1f}" for k, v in sorted(equip_attrs.items())[:5]])
            self.log(f"   📊 Bônus equipamentos: {equip_bonus_str}...")
    
    def _send_initial_equipment_models(self, role_name: str):
        """
        Envia RemoteEquipmentModelCheckNotify (cmd 865) para o jogador local
        quando entra no mundo, usando os modelos salvos no banco.
        
        Formato: roleName:string, equipmentModels:map(byte,string)
        """
        equip_models = self.player_data.get('equipmentModels', {}) if self.player_data else {}
        
        if not equip_models:
            self.log(f"⚔️ Nenhum modelo de equipamento para enviar")
            return
        
        builder = PacketBuilder()
        
        builder.write_string(role_name)
        
        builder.write_varint(len(equip_models))
        
        for slot, model_code in equip_models.items():
            builder.write_byte(int(slot))
            builder.write_string(model_code or '')
        
        self.send_packet(builder.build(865))
        self.log(f"✅ RemoteEquipmentModelCheckNotify enviado: {equip_models}")
    
    def _send_bag_capacity(self, bag_index: int, capacity: int):
        """
        Envia PlayerBagCapacityChangeNotify (cmd 5122) para desbloquear slots do inventário.
        
        Args:
            bag_index: Tipo de bag (1=PLAYER_MAIN_BAG, 2=PET_BAG, 3=RIDE_BAG, etc)
            capacity: Número de slots desbloqueados
        """
        builder = PacketBuilder()
        
        builder.write_byte(bag_index)
        builder.write_unsigned_byte(capacity)
        
        self.send_packet(builder.build(5122))
        self.log(f"✅ PlayerBagCapacityChangeNotify enviado: bagIndex={bag_index}, capacity={capacity}")
    
    
    def handle_bag_check(self, reader: PacketReader):
        """
        Sincronizar inventário (usado ao abrir bag ou entrar no jogo)
        Envia PlayerBagCheckNotify (cmd 5121)
        """
        try:
            if not self.player_data:
                return
            
            role_name = self.player_data.get('name', '')
            
            from inventory_manager import InventoryManager
            inv_mgr = InventoryManager(self.server._get_db())
            
            for bag_index in [1, 2, 3]:
                items = inv_mgr.load_inventory(role_name, bag_index)
                if items:
                    self._send_bag_check(bag_index, items)
                    
        except Exception as e:
            self.log(f"Erro ao carregar inventário: {e}")
            import traceback
            traceback.print_exc()
    
    def _send_bag_check(self, bag_index: int, items: list, empty_slots: list = None):
        """
        Envia PlayerBagCheckNotify (cmd 5121)
        Campos: bagIndex:byte, changedItems:array(BagItemInfo)
        
        BagItemInfo: itemIndex:ubyte, gameItem:GameItemBriefInfo
        GameItemBriefInfo: itemId:string, itemCode:string, itemCount:ubyte
        
        Args:
            bag_index: Índice da bag
            items: Lista de itens existentes
            empty_slots: Lista de slots que ficaram vazios (opcional)
        """
        builder = PacketBuilder()
        
        builder.write_byte(bag_index)
        
        empty_slots = empty_slots or []
        total_entries = len(items) + len(empty_slots)
        
        builder.write_varint(total_entries)
        
        for slot_index in empty_slots:
            item_builder = PacketBuilder()
            
            item_builder.write_unsigned_byte(slot_index)
            
            game_item_builder = PacketBuilder()
            game_item_builder.write_string("")  # itemId vazio
            game_item_builder.write_string("")  # itemCode vazio
            game_item_builder.write_unsigned_byte(0)
            
            game_item_data = game_item_builder.get_bytes()
            item_builder.write_short(len(game_item_data))
            item_builder.write_bytes(game_item_data)
            
            item_data = item_builder.get_bytes()
            builder.write_short(len(item_data))
            builder.write_bytes(item_data)
        
        for item in items:
            item_builder = PacketBuilder()
            
            item_builder.write_unsigned_byte(item.slot_index)
            
            game_item_builder = PacketBuilder()
            game_item_builder.write_string(item.item_id)
            game_item_builder.write_string(item.item_code)
            game_item_builder.write_unsigned_byte(min(item.item_count, 255))
            
            game_item_data = game_item_builder.get_bytes()
            item_builder.write_short(len(game_item_data))
            item_builder.write_bytes(game_item_data)
            
            item_data = item_builder.get_bytes()
            builder.write_short(len(item_data))
            builder.write_bytes(item_data)
        
        self.send_packet(builder.build(BagCommandCode.PLAYER_BAG_CHECK_NOTIFY))
        self.log(f"✅ BagCheckNotify enviado: bag={bag_index}, items={len(items)}, empty_slots={len(empty_slots)}")

    def _send_item_added_notify(self, items_added: list):
        """
        Envia PlayerItemAddedNotify (cmd 5131) - Notificação de item obtido
        Mostra: efeito flutuante do item acima do personagem + mensagem no chat
        
        Campos: itemsAdded:array(GameItemBriefInfo)
        GameItemBriefInfo: itemId:string, itemCode:string, itemCount:ubyte
        
        Args:
            items_added: Lista de dicts com: 
                - item_id: ID único do item (ou string vazia se não tiver)
                - item_code: Código do item (ex: "bq200d")  
                - count: Quantidade
        """
        if not items_added:
            return
            
        builder = PacketBuilder()
        
        builder.write_varint(len(items_added))
        
        for item in items_added:
            item_id = str(item.get('item_id', ''))
            item_code = str(item.get('item_code', ''))
            count = min(item.get('count', 1), 255)  # ubyte max = 255
            
            item_builder = PacketBuilder()
            item_builder.write_string(item_id)
            item_builder.write_string(item_code)
            item_builder.write_unsigned_byte(count)
            
            item_data = item_builder.get_bytes()
            builder.write_short(len(item_data))
            builder.write_bytes(item_data)
        
        self.send_packet(builder.build(BagCommandCode.PLAYER_ITEM_ADDED_NOTIFY))
        
        item_names = [f"{i.get('item_code')} x{i.get('count', 1)}" for i in items_added]
        self.log(f"✨ ItemAddedNotify enviado: {', '.join(item_names)}")
    

    def _send_view_item_answer(self, item, item_id: str, item_def: dict = None):
        """
        Envia PlayerViewItemAnswer (cmd 5134)
        
        Campos: ["itemId:string","item:com.sunweb.game.rpg.gameItem.GameItemFullInfo"]
        
        GameItemFullInfo:
        ["itemId:string","itemCode:string","expiredTimeLeftInHour:int","canTrade:boolean",
         "equipmentInfo:...","rideInfo:...","expendableInfo:...","petInfo:...","genieInfo:...",
         "elementInfo:...","devilInfo:..."]
        
        item pode ser ItemInfo (dataclass) ou None
        """
        builder = PacketBuilder()
        
        builder.write_string(item_id)
        
        if item is None:
            builder.write_short(0)
        else:
            item_builder = PacketBuilder()
            
            item_code = item.item_code if hasattr(item, 'item_code') else ''
            is_bound = item.is_bound if hasattr(item, 'is_bound') else False
            
            can_trade = not is_bound
            
            item_builder.write_string(item_id)
            
            item_builder.write_string(item_code)
            
            item_builder.write_int(2147483647)
            
            item_builder.write_bool(can_trade)
            
            item_type = item_def.get('ItemType', 0) if item_def else 0
            if item_type == 4:
                self._write_equipment_info(item_builder, item, item_def)
            else:
                item_builder.write_short(0)
            
            item_builder.write_short(0)
            
            if item_type == 1:
                self._write_expendable_info(item_builder, item, item_def)
            else:
                item_builder.write_short(0)
            
            item_builder.write_short(0)
            
            item_builder.write_short(0)
            
            item_builder.write_short(0)
            
            item_builder.write_short(0)
            
            item_data = item_builder.get_bytes()
            builder.write_short(len(item_data))
            builder.write_bytes(item_data)
        
        self.send_packet(builder.build(BagCommandCode.PLAYER_VIEW_ITEM_ANSWER))
        self.log(f"📤 ViewItemAnswer: id={item_id}, found={item is not None}")
    
    def _write_expendable_info(self, builder: PacketBuilder, item, item_def: dict):
        """
        Escreve ItemExpendableInfo
        Campos: ["usePlace:string"]
        """
        exp_builder = PacketBuilder()
        
        exp_builder.write_string("")
        
        exp_data = exp_builder.get_bytes()
        builder.write_short(len(exp_data))
        builder.write_bytes(exp_data)
    
    def _write_equipment_info(self, builder: PacketBuilder, item, item_def: dict):
        """
        Escreve ItemEquipmentInfo
        Campos complexos - enviar valores básicos
        """
        eq_builder = PacketBuilder()
        
        eq_builder.write_bool(False)
        eq_builder.write_byte(0)
        eq_builder.write_short(100)
        eq_builder.write_short(100)
        eq_builder.write_bool(False)
        eq_builder.write_string("")
        is_bound = item.is_bound if hasattr(item, 'is_bound') else False
        eq_builder.write_bool(is_bound)
        eq_builder.write_byte(0)
        eq_builder.write_varint(0)
        enhance_level = item.enhance_level if hasattr(item, 'enhance_level') else 0
        eq_builder.write_byte(enhance_level)
        eq_builder.write_string("")
        eq_builder.write_string("")
        eq_builder.write_float(0.0)
        eq_builder.write_byte(0)
        eq_builder.write_varint(0)
        eq_builder.write_varint(0)
        eq_builder.write_byte(0)
        eq_builder.write_string("")
        eq_builder.write_string("")
        eq_builder.write_string("")
        eq_builder.write_unsigned_short(0)
        eq_builder.write_varint(0)
        eq_builder.write_string("")
        eq_builder.write_unsigned_byte(0)
        eq_builder.write_unsigned_byte(0)
        eq_builder.write_unsigned_short(0)
        eq_builder.write_unsigned_byte(0)
        eq_builder.write_varint(0)
        eq_builder.write_unsigned_short(0)
        eq_builder.write_string("")
        eq_builder.write_varint(0)
        eq_builder.write_varint(0)
        eq_builder.write_string("")
        eq_builder.write_unsigned_byte(0)
        eq_builder.write_float(0.0)
        eq_builder.write_varint(0)
        eq_builder.write_varint(0)
        eq_builder.write_unsigned_byte(0)
        
        eq_data = eq_builder.get_bytes()
        builder.write_short(len(eq_data))
        builder.write_bytes(eq_data)
    
    
    def _send_shop_buy_result(self, success: bool, error_msg: str = ""):
        """Envia resultado da compra na loja (cmd 2819)"""
        builder = PacketBuilder()
        
        builder.write_bool(success)
        builder.write_string(error_msg)
        
        self.send_packet(builder.build(ShopCommandCode.SHOP_BUY_ITEM_ANSWER))
        self.log(f"📤 ShopBuyAnswer: success={success}, error={error_msg}")
    
    def _send_shop_sell_result(self, success: bool, error_msg: str = ""):
        """Envia resultado da venda na loja (cmd 2820)"""
        builder = PacketBuilder()
        builder.write_bool(success)
        builder.write_string(error_msg)
        self.send_packet(builder.build(ShopCommandCode.SHOP_SELL_ITEM_ANSWER))
        self.log(f"📤 ShopSellAnswer: success={success}, error={error_msg}")
    
    def _update_gold_in_db(self, amount: int, is_absolute: bool = False):
        """
        Atualiza gold do jogador no banco de dados usando stored procedure.
        
        Args:
            amount: Quantidade a adicionar (positivo) ou subtrair (negativo), 
                   ou valor absoluto se is_absolute=True
            is_absolute: Se True, usa SP_UpdateGold (define valor absoluto),
                        Se False, usa SP_AddGold (adiciona/subtrai)
        
        Returns:
            Tuple[bool, int]: (sucesso, novo_gold)
        """
        if not self.player_data:
            return False, 0
            
        role_id = self.player_data.get('roleId', 0)
        if not role_id:
            self.log(f"❌ roleId não encontrado no player_data")
            return False, 0
            
        try:
            db = self.server._get_db()
            if not db:
                self.log(f"❌ DatabaseManager não disponível")
                return False, 0
            
            if is_absolute:
                sql = "DECLARE @Result INT; EXEC SP_UpdateGold @RoleID=?, @NewGold=?, @Result=@Result OUTPUT; SELECT @Result AS Result;"
                results = db.execute_query(sql, (role_id, amount))
                result = results[0]['Result'] if results else -1
                new_gold = amount
            else:
                sql = "DECLARE @NewGold BIGINT, @Result INT; EXEC SP_AddGold @RoleID=?, @Amount=?, @NewGold=@NewGold OUTPUT, @Result=@Result OUTPUT; SELECT @NewGold AS NewGold, @Result AS Result;"
                results = db.execute_query(sql, (role_id, amount))
                if results:
                    new_gold = results[0].get('NewGold', 0)
                    result = results[0].get('Result', -1)
                else:
                    new_gold = 0
                    result = -1
            
            if result == 0:
                self.log(f"💰 Gold atualizado via SP: amount={amount}, novo={new_gold}")
                return True, new_gold
            elif result == -2:
                self.log(f"❌ Gold insuficiente para operação: {amount}")
                return False, self.player_data.get('gold', 0)
            else:
                self.log(f"❌ Erro na SP de gold: result={result}")
                return False, 0
                    
        except Exception as e:
            self.log(f"❌ Erro ao atualizar gold no DB: {e}")
            import traceback
            traceback.print_exc()
            return False, 0
    
    def _send_gold_change(self, gold_changed: int = 0):
        """
        Envia notificação de mudança de gold (cmd 563)
        
        Campos esperados pelo cliente:
        - goldChanged:int - diferença (positivo = ganhou, negativo = perdeu)
        - goldCurrent:double - gold atual total
        """
        if not self.player_data:
            return
            
        gold_current = float(self.player_data.get('gold', 0))
        
        builder = PacketBuilder()
        builder.write_int(gold_changed)
        builder.write_double(gold_current)
        
        self.send_packet(builder.build(PlayerCommandCode.PLAYER_GOLD_CHANGE_NOTIFY))
        self.log(f"📤 GoldChange: changed={gold_changed}, current={gold_current}")
    
    def _update_money_in_db(self, amount: int) -> tuple:
        """
        Atualiza money (cristal) do jogador no banco de dados usando SP_UpdateMoney.
        
        Args:
            amount: Quantidade a adicionar (positivo) ou subtrair (negativo)
        
        Returns:
            Tuple[bool, int]: (sucesso, novo_money)
        """
        if not self.player_data:
            return False, 0
            
        role_id = self.player_data.get('roleId', 0)
        if not role_id:
            self.log(f"❌ roleId não encontrado no player_data")
            return False, 0
            
        try:
            db = self.server._get_db()
            if not db:
                self.log(f"❌ DatabaseManager não disponível")
                return False, 0
            
            sql = """
                DECLARE @NewMoney BIGINT, @Result INT;
                EXEC SP_UpdateMoney @RoleID=?, @Amount=?, @NewMoney=@NewMoney OUTPUT, @Result=@Result OUTPUT;
                SELECT @NewMoney AS NewMoney, @Result AS Result;
            """
            results = db.execute_query(sql, (role_id, amount))
            
            if results:
                new_money = results[0].get('NewMoney', 0)
                result_code = results[0].get('Result', -1)
                
                if result_code == 0:
                    self.log(f"💎 Cristal atualizado via SP: amount={amount}, novo={new_money}")
                    return True, new_money
                elif result_code == -1:
                    self.log(f"❌ SP_UpdateMoney: Role não encontrada ({role_id})")
                    return False, 0
                elif result_code == -2:
                    self.log(f"❌ SP_UpdateMoney: Saldo insuficiente (atual={new_money}, necessário={-amount})")
                    return False, new_money
            
            self.log(f"❌ SP_UpdateMoney: Sem resultado")
            return False, 0
                    
        except Exception as e:
            self.log(f"❌ Erro ao atualizar money no DB: {e}")
            import traceback
            traceback.print_exc()
            return False, 0
    
    def _send_money_change(self, money_changed: int = 0):
        """
        Envia notificação de mudança de money/cristal (cmd 564)
        
        Campos esperados pelo cliente:
        - moneyChanged:int - diferença (positivo = ganhou, negativo = perdeu)
        - moneyCurrent:double - money atual total
        """
        if not self.player_data:
            return
            
        money_current = float(self.player_data.get('money', 0))
        
        builder = PacketBuilder()
        builder.write_int(money_changed)
        builder.write_double(money_current)
        
        self.send_packet(builder.build(PlayerCommandCode.PLAYER_MONEY_CHANGE_NOTIFY))
        self.log(f"📤 MoneyChange: changed={money_changed}, current={money_current}")
    
    def _write_enter_world_error(self, builder: PacketBuilder, error_msg: str):
        """Escreve resposta de erro para EnterWorld"""
        
        empty_role = {'name': '', 'jobCode': 1, 'sex': 0, 'level': 1}
        write_local_player_info(builder, empty_role, {})
        
        builder.write_string("")  # clientConfig
        write_dynamic_vars(builder)
        write_dynamic_vars(builder)
        write_task_recorder(builder)
        builder.write_varint(0)
        builder.write_bool(False)
        builder.write_short(0)
        builder.write_short(0)
        builder.write_string(error_msg)
        write_dynamic_vars(builder)
    
class WorldServer(BaseTCPServer):
    
    def __init__(self, host: str = '0.0.0.0', port: int = 8888):
        super().__init__('WORLD', host, port)
        self._db = None
        self._db_available = False
        self._role_repo = None
        self._init_database()
    
    def _init_database(self):
        try:
            from database import get_db, get_role_repo
            
            self._db = get_db()
            if self._db.connect():
                self._role_repo = get_role_repo()
                self._db_available = True
                self.log("✅ Banco de dados conectado")
        except ImportError:
            self._db = None
            self.log("⚠️ pyodbc não instalado - modo debug")
        except Exception as e:
            self._db = None
            self.log(f"⚠️ Erro DB: {e}")
    
    def _get_db(self):
        return self._db
    
    def handle_client(self, client_socket: socket.socket, address: tuple):
        """Processa cliente do World Server"""
        session = WorldSession(client_socket, address, self)
        session.log("Cliente conectado")
        
        buffer = b''
        
        try:
            while True:
                data = client_socket.recv(4096)
                if not data:
                    break
                
                buffer += data
                
                while len(buffer) >= 1:
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
                            buffer = buffer[1:]
                        break
                    
                    total_len = varint_bytes + length
                    if len(buffer) < total_len:
                        break
                    
                    packet_data = buffer[varint_bytes:total_len]
                    buffer = buffer[total_len:]
                    
                    if len(packet_data) < 4:
                        continue
                    
                    command = struct.unpack('>H', packet_data[:2])[0]
                    payload = packet_data[4:]
                    
                    session.log(f"📥 Recebido cmd={command} ({len(payload)} bytes payload)")
                    
                    reader = PacketReader(payload)
                    
                    handler_registry = get_handler_registry()
                    if handler_registry.can_handle(command):
                        handler_registry.dispatch(command, session, reader)
                        continue
                    
                    if command == PlayerCommandCode.PLAYER_ENTER_WORLD_REQ:
                        session.handle_enter_world(reader)
                    elif command == PlayerCommandCode.PLAYER_VIEW_MAP_REQ:
                        session.handle_view_map(reader)
                    
                    elif command == BagCommandCode.PLAYER_BAG_CHECK_NOTIFY:
                        session.handle_bag_check(reader)
                    
                    else:
                        session.log(f"Comando desconhecido: {command}")
                        
        except Exception as e:
            session.log(f"Erro: {e}")
            import traceback
            traceback.print_exc()
        finally:
            handler_registry = get_handler_registry()
            handler_registry.cleanup_session(session)
            
            client_socket.close()
            session.log("🔌 Cliente desconectado")
    
    
    def get_account_by_ticket(self, ticket: str) -> Optional[Dict]:
        """Busca conta pelo ticket"""
        if self._db_available and self._role_repo:
            try:
                return self._role_repo.get_account_by_ticket(ticket)
            except Exception as e:
                self.log(f"Erro ao buscar conta: {e}")
        return None
    
    def get_roles_for_account(self, account_id: str) -> List[Dict]:
        """Retorna personagens de uma conta"""
        if self._db_available and self._role_repo:
            try:
                account_uid = None
                try:
                    account_uid = int(account_id)
                except ValueError:
                    account_data = self._role_repo.get_account_by_ticket(account_id)
                    if account_data:
                        account_uid = account_data['AccountUID']
                
                if account_uid:
                    db_roles = self._role_repo.get_roles_by_account(account_uid)
                    return [{
                        'id': r.get('Id') or r.get('RoleID'),
                        'name': r.get('Name'),
                        'jobCode': r.get('JobCode'),
                        'sex': r.get('Sex'),
                        'level': r.get('Level'),
                        'headIconIndex': r.get('HeadIconIndex'),
                        'hairStyleIndex': r.get('HairStyleIndex'),
                        'accountId': str(r.get('AccountId') or r.get('AccountUID')),
                        'createTime': str(r.get('CreatedAt') or r.get('CreateTime', '')),
                        'lastPlayTime': str(r.get('LastPlayTime', '')),
                        'deletedFlag': bool(r.get('DeletedFlag', False)),
                        'willDeleteTime': str(r.get('WillDeleteTime', '')) if r.get('WillDeleteTime') else '',
                        'equipmentModels': {},
                        'hasRolePassword': bool(r.get('HasRolePassword', False))
                    } for r in db_roles]
            except Exception as e:
                self.log(f"Erro ao buscar roles: {e}")
        return []
    
    def check_role_name(self, name: str) -> bool:
        """Verifica se nome está disponível"""
        if self._db_available and self._role_repo:
            try:
                return self._role_repo.check_name(name)
            except:
                pass
        return True
    
    def create_role(self, account_id: str, role_data: Dict) -> Dict:
        """Cria novo personagem"""
        if self._db_available and self._role_repo:
            try:
                account_uid = None
                try:
                    account_uid = int(account_id)
                except ValueError:
                    account_data = self._role_repo.get_account_by_ticket(account_id)
                    if account_data:
                        account_uid = account_data['AccountUID']
                
                if account_uid:
                    result = self._role_repo.create_role(
                        account_uid=account_uid,
                        name=role_data.get('name', ''),
                        job_code=role_data.get('jobCode', 1),
                        sex=role_data.get('sex', 0),
                        head_icon_index=role_data.get('headIconIndex', 0),
                        hair_style_index=role_data.get('hairStyleIndex', 0)
                    )
                    
                    if result.get('Status') == 0:
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
                        return {'error': result.get('Message', 'Erro')}
            except Exception as e:
                self.log(f"Erro ao criar role: {e}")
        
        return {'error': 'Banco não disponível'}
    
    def select_role(self, account_id: str, name: str, password: str = None) -> Dict:
        """Seleciona personagem"""
        if self._db_available and self._role_repo:
            try:
                account_uid = None
                try:
                    account_uid = int(account_id)
                except ValueError:
                    account_data = self._role_repo.get_account_by_ticket(account_id)
                    if account_data:
                        account_uid = account_data['AccountUID']
                
                if account_uid:
                    return self._role_repo.select_role(account_uid, name, password)
            except Exception as e:
                self.log(f"Erro ao selecionar role: {e}")
        
        return {'IsDone': 0, 'FailureReason': 'Erro interno'}
    
    def delete_role(self, account_id: str, name: str) -> Dict:
        """Deleta personagem"""
        if self._db_available and self._role_repo:
            try:
                account_uid = None
                try:
                    account_uid = int(account_id)
                except ValueError:
                    account_data = self._role_repo.get_account_by_ticket(account_id)
                    if account_data:
                        account_uid = account_data['AccountUID']
                
                if account_uid:
                    return self._role_repo.delete_role(account_uid, name)
            except Exception as e:
                self.log(f"Erro ao deletar role: {e}")
        
        return {'IsDone': 0, 'FailureReason': 'Erro interno'}

if __name__ == '__main__':
    server = WorldServer()
    try:
        server.start()
    except KeyboardInterrupt:
        pass

