"""
Asa de Cristal - Attribute Calculator
Calcula atributos do jogador baseado em stats base + equipamentos
"""

from typing import Dict
from database import DatabaseManager
from attribute_enums import AttributeCode as AC


class AttributeCalculator:
    """Calcula atributos do jogador"""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    def calculate_equipment_attributes(self, role_name: str) -> Dict[int, float]:
        """
        Calcula os atributos dos equipamentos equipados.
        
        BaseAttributes são aumentados em 0.5% por EnhanceLevel (máximo 10% em +20).
        ExtAttributes são valores fixos que não mudam com fortalecimento.
        
        Args:
            role_name: Nome do personagem
            
        Returns:
            dict: Dicionário com códigos de atributo -> valores somados
        """
        equip_bag = 10
        
        # Buscar itens equipados com EnhanceLevel
        equip_items = self.db.execute_proc('SP_LoadInventory', {
            'RoleName': role_name,
            'BagIndex': equip_bag
        })
        
        attributes = {}  # codigo_atributo -> valor
        
        for item_row in equip_items:
            item_code = item_row['ItemCode']
            enhance_level = item_row.get('EnhanceLevel', 0)
            
            # Buscar BaseAttributes e ExtAttributes separados
            item_def = self.db.execute_query(
                "SELECT BaseAttributes, ExtAttributes FROM TB_ItemDefinition WHERE ItemCode = ?",
                (item_code,)
            )
            
            if not item_def:
                continue
            
            base_attr_json = item_def[0].get('BaseAttributes')
            ext_attr_json = item_def[0].get('ExtAttributes')
            
            try:
                import json
                
                # Processar baseAttr (aumenta 0.5% por nível, máximo 10% em +20)
                if base_attr_json:
                    base_attrs = json.loads(base_attr_json)
                    for attr in base_attrs:
                        attr_code = attr.get('attr', 0)
                        base_value = float(attr.get('value', 0))
                        # Fórmula: valor_base × (1 + min(EnhanceLevel, 20) × 0.005)
                        # +1 = +0.5%, +2 = +1.0%, ..., +20 = +10% (máximo)
                        enhance_bonus = min(enhance_level, 20) * 0.005
                        final_value = base_value * (1.0 + enhance_bonus)
                        attributes[attr_code] = attributes.get(attr_code, 0) + final_value
                
                # Processar extAttr (valores fixos, não afetados por fortalecimento)
                if ext_attr_json:
                    ext_attrs = json.loads(ext_attr_json)
                    for attr in ext_attrs:
                        attr_code = attr.get('attr', 0)
                        attr_value = float(attr.get('value', 0))
                        attributes[attr_code] = attributes.get(attr_code, 0) + attr_value
                        
            except Exception as e:
                print(f"⚠️ Erro ao processar atributos do item {item_code}: {e}")
                continue
        
        return attributes
    
    def build_player_attributes_packet(self, player_data: dict, equip_attrs: dict):
        """
        Constrói o pacote RoleAttributesInfo com todos os atributos calculados.
        
        Aplica a lógica de BASE_VALUE + RATE + EXTRA_VALUE conforme RoleAttributesModifierEnum:
        - ADD_BASE_VALUE (XXX0): Valor base do equipamento (já afetado por EnhanceLevel)
        - ADD_RATE (XXX1): Porcentagem que multiplica o valor base do jogador
        - ADD_EXTRA_VALUE (XXX2): Valor flat adicional
        
        Args:
            player_data: Dados do jogador (level, strength, etc)
            equip_attrs: Atributos dos equipamentos (dict código -> valor)
            
        Returns:
            bytes: Dados do RoleAttributesInfo serializados
        """
        from protocol.packet_builder import PacketBuilder
        
        # Valores base do personagem vindos do banco de dados
        level = player_data.get('level', 1)
        
        # ALL_ATTR_ADD_VALUE aumenta todos os atributos base igualmente
        all_attr_bonus = int(equip_attrs.get(AC.ALL_ATTR_ADD_VALUE, 0))
        
        base_strength = player_data.get('strength', 10) + all_attr_bonus
        base_agility = player_data.get('agility', 10) + all_attr_bonus
        base_wisdom = player_data.get('wisdom', 10) + all_attr_bonus
        base_vitality = player_data.get('vitality', 10) + all_attr_bonus
        
        # Função auxiliar para calcular atributo com base/rate/extra
        def calc_attr(base_player, base_code, rate_code, extra_code):
            """Calcula: base_player * (1 + rate) + base_equip + extra_equip"""
            base_equip = equip_attrs.get(base_code, 0)
            rate = equip_attrs.get(rate_code, 0)
            extra = equip_attrs.get(extra_code, 0)
            return int(base_player * (1.0 + rate) + base_equip + extra)
        
        # HP/MP calculados
        base_hp = 100 + base_vitality * 10 + level * 50
        hp_max = calc_attr(base_hp, AC.HP_MAX_ADD_BASE_VALUE, AC.HP_MAX_ADD_RATE, AC.HP_MAX_ADD_EXTRA_VALUE)
        
        base_mp = 50 + base_wisdom * 5 + level * 20
        mp_max = calc_attr(base_mp, AC.MP_MAX_ADD_BASE_VALUE, AC.MP_MAX_ADD_RATE, AC.MP_MAX_ADD_EXTRA_VALUE)
        
        # Physical Attack
        base_phys_atk = base_strength * 2 + level * 3
        physical_attack = calc_attr(base_phys_atk, AC.PHYSICAL_ATTACK_ADD_BASE_VALUE, AC.PHYSICAL_ATTACK_ADD_RATE, AC.PHYSICAL_ATTACK_ADD_EXTRA_VALUE)
        
        # Magic Attack
        base_mag_atk = base_wisdom * 2 + level * 3
        magic_attack = calc_attr(base_mag_atk, AC.MAGIC_ATTACK_ADD_BASE_VALUE, AC.MAGIC_ATTACK_ADD_RATE, AC.MAGIC_ATTACK_ADD_EXTRA_VALUE)
        
        # Physical Defense
        base_phys_def = base_vitality * 2
        physical_defense = calc_attr(base_phys_def, AC.PHYSICAL_DEFENSE_ADD_BASE_VALUE, AC.PHYSICAL_DEFENSE_ADD_RATE, AC.PHYSICAL_DEFENSE_ADD_EXTRA_VALUE)
        
        # Magic Defense
        base_mag_def = base_wisdom * 2
        magic_defense = calc_attr(base_mag_def, AC.MAGIC_DEFENSE_ADD_BASE_VALUE, AC.MAGIC_DEFENSE_ADD_RATE, AC.MAGIC_DEFENSE_ADD_EXTRA_VALUE)
        
        # Reduce Rates
        physical_reduce_rate = 0.1 + equip_attrs.get(AC.PHYSICAL_REDUCE_RATE_ADD_VALUE, 0)
        magic_reduce_rate = 0.1 + equip_attrs.get(AC.MAGIC_REDUCE_RATE_ADD_VALUE, 0)
        
        # Hit/Dodge/Crit
        hit_value = base_agility * 2 + int(equip_attrs.get(AC.HIT_VALUE_ADD_VALUE, 0))
        hit_rate = 1.0 + base_agility * 0.01 + equip_attrs.get(AC.HIT_RATE_ADD_VALUE, 0)
        
        dodge_value = base_agility * 2 + int(equip_attrs.get(AC.DODGE_VALUE_ADD_VALUE, 0))
        dodge_rate = base_agility * 0.005 + equip_attrs.get(AC.DODGE_RATE_ADD_VALUE, 0)
        
        crit_value = base_agility + int(equip_attrs.get(AC.CRIT_VALUE_ADD_VALUE, 0))
        crit_rate = 0.05 + equip_attrs.get(AC.CRIT_RATE_ADD_VALUE, 0)
        
        crit_damage_mul = 1.5 + equip_attrs.get(AC.CRIT_DAMAGE_MUL_ADD_VALUE, 0)
        
        # HP/MP atuais
        hp = player_data.get('hp', hp_max)
        mp = player_data.get('mp', mp_max)
        
        # Construir RoleAttributesInfo
        attr_builder = PacketBuilder()
        
        # strength:int, wisdom:int, agility:int, vitality:int
        attr_builder.write_int(int(base_strength))
        attr_builder.write_int(int(base_wisdom))
        attr_builder.write_int(int(base_agility))
        attr_builder.write_int(int(base_vitality))
        
        # hp:double, hpMax:double, mp:int, mpMax:int
        attr_builder.write_double(float(hp))
        attr_builder.write_double(float(hp_max))
        attr_builder.write_int(mp)
        attr_builder.write_int(mp_max)
        
        # sp:int, spMax:int, xp:int, xpMax:int
        attr_builder.write_int(100)
        attr_builder.write_int(100)
        attr_builder.write_int(100)
        attr_builder.write_int(100)
        
        # physicalAttack:int, physicalDefense:int, physicalReduceRate:float
        attr_builder.write_int(physical_attack)
        attr_builder.write_int(physical_defense)
        attr_builder.write_float(physical_reduce_rate)
        
        # magicAttack:int, magicDefense:int, magicReduceRate:float
        attr_builder.write_int(magic_attack)
        attr_builder.write_int(magic_defense)
        attr_builder.write_float(magic_reduce_rate)
        
        # hitValue:int, hitRate:float, dodgeValue:int, dodgeRate:float
        attr_builder.write_int(hit_value)
        attr_builder.write_float(hit_rate)
        attr_builder.write_int(dodge_value)
        attr_builder.write_float(dodge_rate)
        
        # critValue:int, critRate:float, luckyAttack:int, luckyDefense:int
        attr_builder.write_int(crit_value)
        attr_builder.write_float(crit_rate)
        attr_builder.write_int(int(equip_attrs.get(AC.LUCKY_ATTACK_ADD_VALUE, 0)))
        attr_builder.write_int(int(equip_attrs.get(AC.LUCKY_DEFENSE_ADD_VALUE, 0)))
        
        # critDamageMul:float, toughValue:int, pierceAttack:int, pierceDefense:int
        attr_builder.write_float(crit_damage_mul)
        attr_builder.write_int(int(equip_attrs.get(AC.TOUGH_VALUE_ADD_VALUE, 0)))
        attr_builder.write_int(int(equip_attrs.get(AC.PIERCE_ATTACK_ADD_VALUE, 0)))
        attr_builder.write_int(int(equip_attrs.get(AC.PIERCE_DEFENSE_ADD_VALUE, 0)))
        
        # singTimeModifier:float, castTimeModifier:float, singTimeReduceMS:int
        attr_builder.write_float(1.0 + equip_attrs.get(AC.SING_SPEED_ADD_RATE, 0))
        attr_builder.write_float(1.0 + equip_attrs.get(AC.CAST_SPEED_ADD_RATE, 0))
        attr_builder.write_int(int(equip_attrs.get(AC.SING_TIME_REDUCEMS_ADD_VALUE, 0)))
        
        # walkSpeed:int, hpHealValue:int, mpHealValue:int, spHealValue:int, cureValue:int
        walk_speed = 150 + int(equip_attrs.get(AC.WALK_SPEED_ADD_VALUE, 0))
        attr_builder.write_int(walk_speed)
        attr_builder.write_int(int(base_vitality + equip_attrs.get(AC.HP_HEAL_VALUE_ADD_VALUE, 0)))
        attr_builder.write_int(int(base_wisdom + equip_attrs.get(AC.MP_HEAL_VALUE_ADD_VALUE, 0)))
        attr_builder.write_int(10 + int(equip_attrs.get(AC.SP_HEAL_VALUE_ADD_VALUE, 0)))
        
        # Cure value com base/rate/extra
        cure_value = calc_attr(base_wisdom, AC.CURE_VALUE_ADD_VALUE, AC.CURE_VALUE_ADD_RATE, AC.CURE_VALUE_ADD_EXTRA_VALUE)
        attr_builder.write_int(cure_value)
        
        # element1-5 Attack com base/rate/extra
        for i in range(5):
            base_code = AC.ELEMENT1_ATTACK_ADD_BASE_VALUE + (i * 10)
            rate_code = AC.ELEMENT1_ATTACK_ADD_RATE + (i * 10)
            extra_code = AC.ELEMENT1_ATTACK_ADD_EXTRA_VALUE + (i * 10)
            elem_atk = calc_attr(0, base_code, rate_code, extra_code)
            attr_builder.write_int(elem_atk)
        
        # element1-5 Defense com base/rate/extra
        for i in range(5):
            base_code = AC.ELEMENT1_DEFENSE_ADD_BASE_VALUE + (i * 10)
            rate_code = AC.ELEMENT1_DEFENSE_ADD_RATE + (i * 10)
            extra_code = AC.ELEMENT1_DEFENSE_ADD_EXTRA_VALUE + (i * 10)
            elem_def = calc_attr(0, base_code, rate_code, extra_code)
            attr_builder.write_int(elem_def)
        
        # lot:int, loa:int, loh:int
        attr_builder.write_int(0)
        attr_builder.write_int(0)
        attr_builder.write_int(0)
        
        return attr_builder.get_bytes(), {
            'physical_attack': physical_attack,
            'physical_defense': physical_defense,
            'hp': hp,
            'hp_max': hp_max,
            'equip_attrs': equip_attrs
        }
