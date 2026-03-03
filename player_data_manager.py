from typing import Dict, List, Optional, Any
from database import DatabaseManager
import json

class PlayerDataManager:
    
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    def _safe_json_loads(self, value, default):
        if not value:
            return default
        try:
            return json.loads(value)
        except:
            return default
    
    def load_player_full_data(self, role_name: str) -> Optional[Dict]:
        """
        Carrega todos os dados do personagem para entrar no mundo.
        Retorna um dicionário completo com todos os dados do LocalPlayerInfo.
        """
        try:
            role_data = self.db.execute_query(
                "SELECT * FROM TB_Role WHERE Name=? AND DeletedFlag=0", (role_name,))
            if not role_data:
                return None
            role = role_data[0]
        except Exception as e:
            return None
        
        player_data = {
            'roleId': role.get('Id') or role.get('RoleID', 0),
            
            'name': role.get('Name', ''),
            'jobCode': role.get('JobCode', 1),
            'sex': role.get('Sex', 0),
            'level': role.get('Level', 1),
            'headIconIndex': role.get('HeadIconIndex', 0),
            'hairStyleIndex': role.get('HairStyleIndex', 0),
            
            'mapId': role.get('MapId') or 'a1',
            'posX': role.get('PosX') or 900,
            'posY': role.get('PosY') or 700,
            'lineIndex': role.get('LineIndex', 0),
            
            'isGM': bool(role.get('IsGM', False)),
            'vipLevel': role.get('VipLevel', 0),
            'vipExp': role.get('VipExp', 0),
            'isDead': bool(role.get('IsDead', False)),
            'isSitting': bool(role.get('IsSitting', False)),
            'statusFlags': role.get('StatusFlags', 0),
            
            'exp': role.get('Exp', 0),
            'maxLevel': role.get('MaxLevel', 999),
            'rebornTimes': role.get('RebornTimes', 0),
            
            'gold': role.get('Gold', 1000),
            'money': role.get('Money', 100),
            'coin': role.get('Coin', 0),
            
            'hp': role.get('HP') or role.get('Hp') or 100,
            'hpMax': role.get('MaxHP') or role.get('HpMax') or 200,
            'mp': role.get('MP') or role.get('Mp') or 50,
            'mpMax': role.get('MaxMP') or role.get('MpMax') or 100,
            
            'strength': role.get('AttrForce') or role.get('Strength') or 10,
            'wisdom': role.get('AttrSpirit') or role.get('Wisdom') or 10,
            'agility': role.get('AttrAgility') or role.get('Agility') or 10,
            'vitality': role.get('AttrVitality') or role.get('Vitality') or 10,
            'freeAttrPt': role.get('AttrRemainPoints') or role.get('FreeAttrPt') or 0,
            
            'physicalAttack': role.get('PhysicalAttack') or 10,
            'physicalDefense': role.get('PhysicalDefense') or 5,
            'magicAttack': role.get('MagicAttack') or 10,
            'magicDefense': role.get('MagicDefense') or 5,
            'walkSpeed': role.get('WalkSpeed') or 200,
            
            'pkMode': role.get('PkMode', 0),
            'pkValue': role.get('PkValue', 0),
            
            'lifeJob': role.get('LifeJob', 0),
            'lifeLevel': role.get('LifeLevel', 0),
            'lifeExp': role.get('LifeExp', 0),
            
            'farmSkillLevelArray': self._safe_json_loads(role.get('FarmSkillLevels'), [0,0,0,0]),
            'farmSkillExpArray': self._safe_json_loads(role.get('FarmSkillExps'), [0,0,0,0]),
            
            'mateRelationInfo': {
                'mateName': role.get('MateName', ''),
                'relationType': role.get('MateRelationType', 0),
                'mateValue': role.get('MateValue', 0),
                'mateGold': role.get('MateGold', 0),
            },
            
            'bkHp': role.get('BkHp', 0),
            'bkHpMax': role.get('BkHpMax', 0),
            'bkMp': role.get('BkMp', 0),
            'bkMpMax': role.get('BkMpMax', 0),
            'petBkHp': role.get('PetBkHp', 0),
            'petBkHpMax': role.get('PetBkHpMax', 0),
            'petBkMp': role.get('PetBkMp', 0),
            'petBkMpMax': role.get('PetBkMpMax', 0),
            
            'honorValue': role.get('HonorValue', 0),
            'honorLevel': role.get('HonorLevel', 0),
            
            'side': role.get('Side', 0),
            
            'BagCapacityPlayer': role.get('BagCapacityPlayer', 36),
            'BagCapacityPet': role.get('BagCapacityPet', 3),
            'BagCapacityRide': role.get('BagCapacityRide', 3),
            
            'payMarks': role.get('PayMarks', 0),
            
            'charmValue': role.get('CharmValue', 0),
            'charmInt': role.get('CharmInt', 0),
            
            'beliefGod': role.get('BeliefGod', 0),
            'beliefLevel': role.get('BeliefLevel', 0),
            
            'armoryLevel': role.get('ArmoryLevel', 0),
            'armoryExp': role.get('ArmoryExp', 0),
            
            'dragonLevel': role.get('DragonLevel', 0),
            'dragonExp': role.get('DragonExp', 0),
            'dragonUpChanceNum': role.get('DragonUpChanceNum', 0),
            
            'isAntoHp': bool(role.get('IsAutoHp', False)),
            'isAntoMp': bool(role.get('IsAutoMp', False)),
            
            'consecutiveLoginDays': role.get('ConsecutiveLoginDays', 1),
            'boonItemCode': role.get('BoonItemCode', ''),
            
            'stirpLevel': role.get('StirpLevel', 0),
            'potentialLevel': role.get('PotentialLevel', 0),
            'potentialValue': role.get('PotentialValue', 0),
            'refineLevel': role.get('RefineLevel', 0),
            'lightLevel': role.get('LightLevel', 0),
            'boneLevel': role.get('BoneLevel', 0),
            
            'constellation': role.get('Constellation', 0),
            'constellationLevel': role.get('ConstellationLevel', 0),
            'constellationTaskId': role.get('ConstellationTaskId', 0),
            
            'luckLevel': role.get('LuckLevel', 0),
            'hartLevel': role.get('HartLevel', 0),
            
            'isUseFashion': bool(role.get('IsUseFashion', True)),  # Default True (ativado)
            
            'gameTimes': role.get('GameTimes', 0),
            'arenaIntegral': role.get('ArenaIntegral', 0),
            'towerValue': role.get('TowerValue', 0),
            
            'rideCode': role.get('RideCode', ''),
            'titleIndex': role.get('TitleIndex', 0),
            'kitTitleIndex': role.get('KitTitleIndex', 0),
            'modelCode': role.get('ModelCode', ''),
            
            'vars': {'bool': {}, 'int': {}, 'str': {}},
            'killedMonsters': {'bool': {}, 'int': {}, 'str': {}},
            'mateVars': {'bool': {}, 'int': {}, 'str': {}},
            'taskRecorder': {'doingAllocators': {}, 'doingTasks': [], 'doneTasks': {}},
            'friendList': [],
            'buffs': [],
            'equipmentModels': {},
            'mainFarm': None,
            'extraFarmArray': [],
            'mapHonorValues': {},
            'pearlNumMap': {},
            'armoryGridInfo': [],
            'sysVars': {'bool': {}, 'int': {}, 'str': {}},
        }
        
        return player_data
    
    def _parse_dynamic_vars(self, var_rows: List[Dict], var_type: str) -> Dict:
        """Parse variáveis dinâmicas do banco"""
        result = {'bool': {}, 'int': {}, 'str': {}}
        for row in var_rows:
            if row.get('VarType') != var_type:
                continue
            name = row['VarName']
            kind = row['VarKind']
            if kind == 'b':
                result['bool'][name] = bool(row['BoolValue'])
            elif kind == 'i':
                result['int'][name] = row['IntValue'] or 0
            elif kind == 's':
                result['str'][name] = row['StrValue'] or ''
        return result
    
    def _parse_tasks(self, task_rows: List[Dict]) -> Dict:
        """Parse tarefas do banco"""
        doing_allocators = {}
        doing_tasks = []
        done_tasks = {}
        
        for row in task_rows:
            task_id = row['TaskId']
            status = row['TaskStatus']
            
            if status == 'D':  # Doing
                doing_tasks.append(task_id)
                if row.get('AllocatorId'):
                    doing_allocators[row['AllocatorId']] = task_id
            elif status == 'C':  # Completed
                done_tasks[task_id] = row.get('CompletedCount', 1)
        
        return {
            'doingAllocators': doing_allocators,
            'doingTasks': doing_tasks,
            'doneTasks': done_tasks
        }
    
    def _parse_friends(self, friend_rows: List[Dict]) -> List[Dict]:
        """Parse amigos do banco"""
        return [
            {
                'friendName': row['FriendName'],
                'relationValue': row['RelationValue'],
                'sex': 0,  # Precisa buscar do outro jogador
                'level': 1,
                'isOnline': False,
                'moodIndex': 0
            }
            for row in friend_rows
        ]
    
    def _parse_buffs(self, buff_rows: List[Dict]) -> List[Dict]:
        """Parse buffs do banco"""
        return [
            {
                'buffId': row['BuffId'],
                'durationInSec': row['DurationSec']
            }
            for row in buff_rows
        ]
    
    def _parse_farms(self, farm_rows: List[Dict]) -> tuple:
        """Parse fazendas do banco"""
        main_farm = None
        extra_farms = []
        
        for row in farm_rows:
            farm_data = {
                'mapId': row['MapId'],
                'farmId': row['FarmId'],
                'templetCode': row['TempletCode'],
                'name': row['FarmName'],
                'ownerId': '',  # Será preenchido
                'currentLevel': row['CurrentLevel'],
                'farmExp': row['FarmExp'],
                'styleCode': row.get('StyleCode', '')
            }
            
            if row['FarmType'] == 'M':
                main_farm = farm_data
            else:
                extra_farms.append(farm_data)
        
        return main_farm, extra_farms
    
    def save_player_basic(self, role_name: str, data: Dict) -> bool:
        """Salva dados básicos do jogador (chamado periodicamente)"""
        result = self.db.call_procedure('SP_SavePlayerData', (
            role_name,
            data.get('mapId', 'a1'),
            data.get('posX', 900),
            data.get('posY', 700),
            data.get('level', 1),
            data.get('exp', 0),
            data.get('hp', 100),
            data.get('hpMax', 100),
            data.get('mp', 50),
            data.get('mpMax', 50),
            data.get('gold', 1000),
            data.get('money', 100),
            data.get('coin', 0),
            data.get('isDead', False),
            data.get('pkValue', 0)
        ))
        return result and result[0].get('RowsAffected', 0) > 0
    
    def save_player_var(self, role_name: str, var_type: str, var_name: str, value: Any) -> None:
        """Salva uma variável dinâmica"""
        if isinstance(value, bool):
            self.db.call_procedure('SP_SavePlayerVar', (
                role_name, var_type, var_name, 'b', value, None, None
            ))
        elif isinstance(value, int):
            self.db.call_procedure('SP_SavePlayerVar', (
                role_name, var_type, var_name, 'i', None, value, None
            ))
        else:
            self.db.call_procedure('SP_SavePlayerVar', (
                role_name, var_type, var_name, 's', None, None, str(value)
            ))
    
    def update_task(self, role_name: str, task_id: int, status: str, 
                    allocator_id: int = None, completed_count: int = 0) -> None:
        """Atualiza status de uma tarefa"""
        self.db.call_procedure('SP_UpdateTaskStatus', (
            role_name, task_id, status, allocator_id, completed_count
        ))
    
    def remove_task(self, role_name: str, task_id: int) -> None:
        """Remove uma tarefa"""
        self.db.call_procedure('SP_RemoveTask', (role_name, task_id))
