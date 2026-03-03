import threading
from typing import Dict
from .base_handler import BaseHandler
from protocol.packet_reader import PacketReader
from protocol.packet_builder import PacketBuilder
from protocol.commands import BagCommandCode, EquipmentCommandCode

class InventoryHandler(BaseHandler):
    
    @classmethod
    def get_handlers(cls) -> Dict[int, str]:
        return {
            BagCommandCode.PLAYER_USE_ITEM_REQ: 'handle_use_item',
            BagCommandCode.PLAYER_MOVE_ITEM_REQ: 'handle_move_item',
            BagCommandCode.PLAYER_DROP_ITEM_REQ: 'handle_drop_item',
            BagCommandCode.PLAYER_VIEW_ITEM_REQ: 'handle_view_item',
            EquipmentCommandCode.PLAYER_REMOVE_EQUIPMENT_REQ: 'handle_remove_equipment',
            4611: 'handle_switch_fashion',  # PLAYER_SWITCH_FASHION_REQUEST
            5141: 'handle_bag_sort',  # PLAYER_BAG_SORT_REQUEST
        }
    
    def handle_use_item(self, reader: PacketReader):
        """
        Usar item (cmd 5124)
        Se bagIndex >= 10, é desequipar item
        Se bagIndex == 1, é usar/equipar item
        """
        try:
            raw_data = reader.data[reader.pos:]
            self.log(f"🎮 UseItem raw ({len(raw_data)} bytes): {raw_data.hex()}")
            
            bag_index = reader.read_unsigned_byte()
            
            first_byte = reader.data[reader.pos]
            if first_byte >= 128:
                item_index = reader.read_varint()
            else:
                item_index = reader.read_unsigned_byte()
            
            map_id = reader.read_string() if reader.remaining() > 0 else ""
            
            target_x, target_y = 0, 0
            if reader.remaining() >= 2:
                point_size = reader.read_short()
                if point_size == 4:
                    target_x = reader.read_short()
                    target_y = reader.read_short()
                elif point_size > 0:
                    reader.skip(point_size)
            
            target_obj_id = reader.read_string() if reader.remaining() > 0 else ""
            
            self.log(f"🎮 UseItem: bag={bag_index}, slot={item_index}, map={map_id}")
            
            if not self.player_data:
                self.log("❌ Player data não disponível")
                return
            
            role_name = self.role_name
            
            if bag_index >= 10:
                self._handle_unequip_item(role_name, bag_index, item_index)
            else:
                self._handle_use_or_equip_item(role_name, bag_index, item_index)
                
        except Exception as e:
            self.log(f"Erro ao usar item: {e}")
            import traceback
            traceback.print_exc()
    
    def _handle_use_or_equip_item(self, role_name: str, bag_index: int, slot_index: int):
        """Usa ou equipa um item do inventário"""
        from inventory_manager import InventoryManager
        inv_mgr = InventoryManager(self.get_db())
        
        items = inv_mgr.load_inventory(role_name, bag_index)
        item = next((i for i in items if i.slot_index == slot_index), None)
        
        if not item:
            self.log(f"❌ Item não encontrado no slot {slot_index}")
            return
        
        item_def = self.get_db().execute_query(
            "SELECT * FROM TB_ItemDefinition WHERE ItemCode = ?",
            (item.item_code,)
        )
        
        if not item_def:
            self.log(f"❌ Definição do item {item.item_code} não encontrada")
            return
        
        item_def = item_def[0]
        item_type = item_def.get('ItemType', 0)
        
        self.log(f"📦 Item: {item.item_code}, tipo={item_type}")
        
        if item_type == 4:
            self._equip_item(role_name, item, item_def, bag_index, slot_index)
        elif item_type == 2:
            self._consume_item(role_name, item, item_def, bag_index, slot_index)
        else:
            self.log(f"⚠️ Tipo de item {item_type} não implementado")
    
    def _equip_item(self, role_name: str, item, item_def: dict, from_bag: int, from_slot: int):
        """Equipa um item de equipamento"""
        from inventory_manager import InventoryManager
        inv_mgr = InventoryManager(self.get_db())
        
        subtype = item_def.get('ItemSubType', item_def.get('SubType', 0))
        equip_slot = self._get_equip_slot_for_subtype(subtype)
        
        self.log(f"🔧 Item {item.item_code}: SubType={subtype}, slot={equip_slot}")
        
        if equip_slot < 0:
            self.log(f"❌ SubType {subtype} não é equipável")
            return
        
        equip_bag = 10
        
        result = inv_mgr.equip_item(role_name, from_bag, from_slot, equip_bag, equip_slot)
        
        if not result['success']:
            self.log(f"❌ Erro ao equipar: {result['error']}")
            return
        
        from item_config_loader import item_config
        model_code = item_config.get_model_code(item.item_code)
        
        if not model_code:
            self.log(f"⚠️ ModelCode não encontrado para {item.item_code} no iie.txt!")
        
        self.log(f"📋 FASHION DEBUG: ItemCode={item.item_code}, SubType={item_def.get('ItemSubType')}, ModelCode={model_code}, EquipSlot={equip_slot}")
        
        self._update_equipment_model(role_name, equip_slot, model_code)
        
        if self.player_data and 'equipmentModels' in self.player_data:
            self.player_data['equipmentModels'][equip_slot] = model_code
            self.log(f"📋 FASHION DEBUG: equipmentModels atualizado: {self.player_data['equipmentModels']}")
        
        self._send_item_used_notify(from_bag, from_slot, item.item_code)
        
        items_from = inv_mgr.load_inventory(role_name, from_bag)
        self.session._send_bag_check(from_bag, items_from, [from_slot])
        
        items_equip = inv_mgr.load_inventory(role_name, equip_bag)
        
        for equip_item in items_equip:
            equip_item_def_result = self.get_db().execute_query(
                "SELECT * FROM TB_ItemDefinition WHERE ItemCode = ?",
                (equip_item.item_code,)
            )
            equip_item_def = equip_item_def_result[0] if equip_item_def_result else None
            self.session._send_view_item_answer(equip_item, equip_item.item_id, equip_item_def)
        self.log(f"📦 GameItemFullInfo: {len(items_equip)} equipamentos pré-carregados")
        
        self.session._send_equipment_check_notify(items_equip)
        
        self.session._send_player_attributes()
        
        self._send_equipment_model_delayed(role_name, 0.5)
        
        self.log(f"✅ Item {item.item_code} equipado no slot {equip_slot} com modelo {model_code}!")
    
    def _consume_item(self, role_name: str, item, item_def: dict, bag_index: int, slot_index: int):
        """Usa um item consumível"""
        from inventory_manager import InventoryManager
        inv_mgr = InventoryManager(self.get_db())
        
        result = inv_mgr.remove_item(role_name, bag_index, slot_index, 1)
        
        if result['success']:
            self._send_item_used_notify(bag_index, slot_index, item.item_code)
            
            items = inv_mgr.load_inventory(role_name, bag_index)
            remaining = next((i for i in items if i.slot_index == slot_index), None)
            empty = [slot_index] if not remaining else []
            self.session._send_bag_check(bag_index, items, empty)
            
            self.log(f"✅ Item {item.item_code} usado!")
    
    def _handle_unequip_item(self, role_name: str, equip_bag: int, equip_slot: int):
        """Desequipa um item"""
        from inventory_manager import InventoryManager
        inv_mgr = InventoryManager(self.get_db())
        
        equipped_items = inv_mgr.load_inventory(role_name, equip_bag)
        item = next((i for i in equipped_items if i.slot_index == equip_slot), None)
        
        if not item:
            self.log(f"❌ Nenhum item no slot {equip_slot}")
            return
        
        main_bag = 1
        capacity = self.player_data.get('bag_capacity_player', 42) if self.player_data else 42
        empty_slot = inv_mgr.find_empty_slot(role_name, main_bag, capacity)
        
        if empty_slot is None:
            self.log(f"❌ Inventário cheio")
            return
        
        result = inv_mgr.equip_item(role_name, equip_bag, equip_slot, main_bag, empty_slot)
        
        if not result['success']:
            self.log(f"❌ Erro ao desequipar: {result['error']}")
            return
        
        self._update_equipment_model(role_name, equip_slot, '')
        
        if self.player_data and 'equipmentModels' in self.player_data:
            if equip_slot in self.player_data['equipmentModels']:
                del self.player_data['equipmentModels'][equip_slot]
        
        
        self.log(f"🔍 DEBUG: Carregando inventário da bag {equip_bag} para verificar itens restantes...")
        items_equip = inv_mgr.load_inventory(role_name, equip_bag)
        self.log(f"🔍 DEBUG: Retornados {len(items_equip)} itens da bag {equip_bag}: {[f'slot{i.slot_index}={i.item_code}' for i in items_equip]}")
        
        for equip_item in items_equip:
            equip_item_def_result = self.get_db().execute_query(
                "SELECT * FROM TB_ItemDefinition WHERE ItemCode = ?",
                (equip_item.item_code,)
            )
            equip_item_def = equip_item_def_result[0] if equip_item_def_result else None
            self.session._send_view_item_answer(equip_item, equip_item.item_id, equip_item_def)
        self.log(f"📦 GameItemFullInfo: {len(items_equip)} equipamentos atualizados")
        
        self.session._send_equipment_check_notify(items_equip, empty_equipment_slots=[equip_slot])
        
        self.session._send_player_attributes()
        
        items_main = inv_mgr.load_inventory(role_name, main_bag)
        self.session._send_bag_check(main_bag, items_main, [empty_slot])
        
        self._send_equipment_model_delayed(role_name, 0.5)
        
        self.log(f"✅ Item {item.item_code} desequipado do slot {equip_slot}")
    
    def _get_equip_slot_for_subtype(self, subtype: int) -> int:
        """Retorna o slot de equipamento para um subtype"""
        if subtype >= 1024:
            kind = subtype - 1024
        else:
            kind = subtype
        
        kind_to_slot = {
            0: 0,
            1: 1,
            2: 2,
            3: 3,
            4: 4,
            5: 5,
            6: 6,
            7: 7,
            8: 8,
            9: 9,
            10: 10,
            11: 11, 12: 12, 13: 13, 14: 14, 15: 15,
            102: 102,
            103: 103,
            104: 104,
        }
        
        return kind_to_slot.get(kind, -1)
    
    def _send_item_used_notify(self, bag_index: int, slot_index: int, item_code: str):
        """Envia PlayerItemUsedNotify (cmd 5130)"""
        builder = PacketBuilder()
        builder.write_string(item_code)
        self.send_packet(builder.build(BagCommandCode.PLAYER_ITEM_USED_NOTIFY))
    
    def _update_equipment_model(self, role_name: str, slot: int, model_code: str):
        """Atualiza o modelo de equipamento no banco de dados"""
        try:
            self.get_db().execute_proc('SP_UpdateEquipmentModel', {
                'RoleName': role_name,
                'Slot': slot,
                'ModelCode': model_code
            })
            self.log(f"💾 Modelo {model_code} salvo no slot {slot}")
        except Exception as e:
            self.log(f"❌ Erro ao salvar modelo: {e}")
    
    def _send_equipment_model_delayed(self, role_name: str, delay: float):
        """
        Envia RemoteEquipmentModelCheckNotify (cmd 865) com delay.
        Isso garante que o cmd 4609 seja processado primeiro pelo cliente.
        """
        import time
        current_time = time.time()
        self.log(f"⏱️ TIMER DEBUG: Agendando cmd 865 para {delay}s no futuro (timestamp={current_time:.3f})")
        timer = threading.Timer(delay, self._send_equipment_model_update, args=[role_name, current_time])
        timer.start()
    
    def _send_equipment_model_update(self, role_name: str, scheduled_time: float):
        """
        Envia RemoteEquipmentModelCheckNotify (cmd 865)
        Atualiza o modelo visual do personagem no cliente
        
        Formato: roleName:string, equipmentModels:map(byte,string)
        
        IMPORTANTE: O servidor envia TODOS os equipamentos (normais E fashion).
        O cliente decide qual renderizar baseado em seu próprio isUseFashion.
        """
        import time
        actual_time = time.time()
        elapsed = actual_time - scheduled_time
        self.log(f"⏱️ TIMER DEBUG: Executando cmd 865 após {elapsed:.3f}s (esperado: 0.5s)")
        
        builder = PacketBuilder()
        
        builder.write_string(role_name)
        self.log(f"📋 FASHION DEBUG: Enviando roleName='{role_name}'")
        
        equip_models = self.player_data.get('equipmentModels', {}) if self.player_data else {}
        
        self.log(f"📋 FASHION DEBUG: equipmentModels do player_data: {equip_models}")
        
        builder.write_varint(len(equip_models))
        self.log(f"📋 FASHION DEBUG: map size = {len(equip_models)}")
        
        for slot, model_code in equip_models.items():
            builder.write_byte(int(slot))
            builder.write_string(model_code or '')
            self.log(f"📋 FASHION DEBUG: slot {slot} (byte) -> model '{model_code}'")
        
        packet_data = builder.build(865)
        self.log(f"📋 FASHION DEBUG: Pacote cmd=865, tamanho={len(packet_data)}, hex={packet_data.hex()}")
        self.send_packet(packet_data)
        self.log(f"✅ RemoteEquipmentModelCheckNotify enviado: {equip_models}")

    def handle_move_item(self, reader: PacketReader):
        """Mover item no inventário (cmd 5125)"""
        try:
            bag_index = reader.read_byte()
            from_slot = reader.read_varint()
            to_slot = reader.read_varint()
            
            self.log(f"MoveItem: bag={bag_index}, from={from_slot}, to={to_slot}")
            
            if not self.player_data:
                return
            
            from inventory_manager import InventoryManager
            inv_mgr = InventoryManager(self.get_db())
            
            result = inv_mgr.move_item(self.role_name, bag_index, from_slot, to_slot)
            
            if result['success']:
                items = inv_mgr.load_inventory(self.role_name, bag_index)
                from_slot_occupied = any(item.slot_index == from_slot for item in items)
                empty_slots = [from_slot] if not from_slot_occupied else []
                self.session._send_bag_check(bag_index, items, empty_slots)
            else:
                self.log(f"❌ Erro ao mover item: {result['error']}")
                
        except Exception as e:
            self.log(f"Erro ao mover item: {e}")
            import traceback
            traceback.print_exc()
    
    def handle_drop_item(self, reader: PacketReader):
        """Dropar item (cmd 5127)"""
        try:
            bag_index = reader.read_byte()
            slot_index = reader.read_varint()
            drop_count = reader.read_varint()
            
            self.log(f"DropItem: bag={bag_index}, slot={slot_index}, count={drop_count}")
            
            if not self.player_data:
                return
            
            from inventory_manager import InventoryManager
            inv_mgr = InventoryManager(self.get_db())
            
            result = inv_mgr.remove_item(self.role_name, bag_index, slot_index, drop_count)
            
            if result['success']:
                items = inv_mgr.load_inventory(self.role_name, bag_index)
                self.session._send_bag_check(bag_index, items)
            else:
                self.log(f"❌ Erro ao dropar: {result['error']}")
                
        except Exception as e:
            self.log(f"Erro ao dropar item: {e}")
            import traceback
            traceback.print_exc()
    
    def handle_view_item(self, reader: PacketReader):
        """Ver detalhes de um item (cmd 5133)"""
        try:
            item_id = reader.read_string()
            self.log(f"ViewItem: itemId={item_id}")
            
            builder = PacketBuilder()
            builder.write_string(item_id)
            builder.write_unsigned_short(0)
            self.send_packet(builder.build(BagCommandCode.PLAYER_VIEW_ITEM_ANSWER))
            
        except Exception as e:
            self.log(f"Erro ao ver item: {e}")

    def handle_remove_equipment(self, reader: PacketReader):
        """
        Desequipar item (cmd 4610 - PLAYER_REMOVE_EQUIPMENT_REQUEST)
        
        Request: equipmentKind:byte, toBagItemIndex:byte
        
        equipmentKind = slot do equipamento (0=arma, 1=capacete, etc)
        toBagItemIndex = slot destino na bag principal (ou -1 para primeiro slot livre)
        """
        try:
            equipment_kind = reader.read_byte()
            to_bag_index = reader.read_byte()
            
            self.log(f"⚔️ RemoveEquipment: equipKind={equipment_kind}, toBag={to_bag_index}")
            
            if not self.player_data:
                self.log("❌ Jogador não logado")
                return
            
            self._handle_unequip_item(self.role_name, 10, equipment_kind)
            
        except Exception as e:
            self.log(f"Erro ao desequipar: {e}")
            import traceback
            traceback.print_exc()
    
    def handle_switch_fashion(self, reader: PacketReader):
        """
        Alterna entre mostrar fashion ou armadura normal (cmd 4611)
        
        PlayerSwitchFashionRequest: isUseFashion:boolean
        PlayerSwitchFashionNotify: isUseFashion:boolean
        """
        try:
            is_use_fashion = reader.read_bool()
            
            self.log(f"🎨 SwitchFashion: isUseFashion={is_use_fashion}")
            
            if self.player_data:
                self.player_data['isUseFashion'] = is_use_fashion
                role_id = self.player_data.get('roleId')
                if role_id:
                    db = self.get_db()
                    db.execute_query(
                        "UPDATE TB_Role SET IsUseFashion = ? WHERE RoleID = ?",
                        (1 if is_use_fashion else 0, role_id)
                    )
                    self.log(f"💾 IsUseFashion salvo no DB: {is_use_fashion}")
            
            builder = PacketBuilder()
            builder.write_bool(is_use_fashion)
            self.send_packet(builder.build(4612))
            
            self.log(f"✅ PlayerSwitchFashionNotify enviado: {is_use_fashion}")
            
            from inventory_manager import InventoryManager
            inv_mgr = InventoryManager(self.get_db())
            role_name = self.role_name
            
            equip_items = inv_mgr.load_inventory(role_name, 10)
            if equip_items:
                for equip_item in equip_items:
                    equip_item_def_result = self.get_db().execute_query(
                        "SELECT * FROM TB_ItemDefinition WHERE ItemCode = ?",
                        (equip_item.item_code,)
                    )
                    equip_item_def = equip_item_def_result[0] if equip_item_def_result else None
                    self.session._send_view_item_answer(equip_item, equip_item.item_id, equip_item_def)
                
                self.session._send_equipment_check_notify(equip_items)
                self.log(f"🔄 Equipamentos reenviados para atualizar visual fashion")
            
        except Exception as e:
            self.log(f"Erro ao alternar fashion: {e}")
            import traceback
            traceback.print_exc()
    
    def handle_bag_sort(self, reader: PacketReader):
        """
        Organizar itens da mochila (cmd 5141 - PLAYER_BAG_SORT_REQUEST)
        
        Formato: bagIndex:byte
        
        Ordem de prioridade (por tipo):
        1. EXPENDABLE (1) - consumíveis/poções
        2. COLLECTION (2) - materiais/baús
        3. EQUIPMENT (4) - equipamentos
        4. PET (8)
        5. RIDE (16) - montarias
        6. SKILL (1048576)
        7. Outros
        
        Dentro do mesmo tipo: ordenar por itemCode
        """
        try:
            raw_data = reader.data[reader.pos:]
            self.log(f"📦 BagSort raw ({len(raw_data)} bytes): {raw_data.hex()}")
            
            if reader.remaining() >= 3:
                ss_key = reader.read_short()
                self.log(f"  ssKey: {ss_key}")
            
            bag_index = reader.read_byte() if reader.remaining() >= 1 else 1
            self.log(f"🗂️ BagSort: bagIndex={bag_index}")
            
            if not self.player_data:
                self.log("❌ Jogador não logado")
                return
            
            role_name = self.role_name
            
            from inventory_manager import InventoryManager
            inv_mgr = InventoryManager(self.get_db())
            
            items = inv_mgr.load_inventory(role_name, bag_index)
            
            if not items:
                self.log("  Bag vazia, nada a ordenar")
                return
            
            self.log(f"  📋 {len(items)} itens antes da ordenação")
            
            type_priority = {
                1: 0,
                2: 1,
                4: 2,
                8: 3,
                16: 4,
                32: 5,
                128: 6,
                1048576: 7,
                2097152: 8,
            }
            
            items_with_type = []
            for item in items:
                item_code = item.item_code
                item_def = inv_mgr.get_item_definition(item_code)
                item_type = item_def.get('ItemType', 99) if item_def else 99
                
                items_with_type.append({
                    'item': item,
                    'type': item_type,
                    'type_priority': type_priority.get(item_type, 99),
                    'code': item_code
                })
            
            items_with_type.sort(key=lambda x: (x['type_priority'], x['code']))
            
            db = self.get_db()
            if not db:
                self.log("❌ DB não disponível")
                return
            
            for new_slot, item_data in enumerate(items_with_type):
                item = item_data['item']
                old_slot = item.slot_index
                
                if old_slot != new_slot:
                    self.log(f"    {item.item_code}: slot {old_slot} -> {new_slot} (invId={item.inventory_id})")
                    
                    sql = "UPDATE TB_RoleInventory SET SlotIndex = ? WHERE InventoryID = ?"
                    db.execute_query(sql, (new_slot, item.inventory_id))
            
            self.log(f"  ✅ Itens reorganizados")
            
            old_slots = set(item_data['item'].slot_index for item_data in items_with_type)
            new_slots = set(range(len(items_with_type)))
            empty_slots = list(old_slots - new_slots)
            
            items_updated = inv_mgr.load_inventory(role_name, bag_index)
            self.session._send_bag_check(bag_index, items_updated, empty_slots)
            self.log(f"  📤 Bag enviada: {len(items_updated)} itens, {len(empty_slots)} slots vazios")
            
        except Exception as e:
            self.log(f"Erro ao ordenar bag: {e}")
            import traceback
            traceback.print_exc()
