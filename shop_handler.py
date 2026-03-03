from typing import Dict
from .base_handler import BaseHandler
from protocol.packet_reader import PacketReader
from protocol.packet_builder import PacketBuilder
from protocol.commands import ShopCommandCode

class ShopHandler(BaseHandler):
    
    @classmethod
    def get_handlers(cls) -> Dict[int, str]:
        return {
            ShopCommandCode.SHOP_SELL_ITEM_REQ: 'handle_sell_item',
            ShopCommandCode.SHOP_BUY_ITEM_REQ: 'handle_buy_item_gold',
            ShopCommandCode.STORE_BUY_ITEM_REQ: 'handle_buy_item_crystal',
        }
    
    
    def handle_buy_item_gold(self, reader: PacketReader):
        """
        Comprar item da loja com gold.
        
        Formato:
        - npcId:string - ID do NPC vendedor
        - count:byte, bagIndex:byte, extras:bytes (do NPC)
        - [itemCode:string, count:byte, bagIndex:byte, extras:bytes]... (itens)
        """
        try:
            raw_data = reader.data[reader.pos:]
            self.log(f"🛒 ShopBuyItem (gold) raw ({len(raw_data)} bytes): {raw_data.hex()}")
            
            npc_id = reader.read_string()
            self.log(f"🏪 NPC Vendedor: {npc_id}")
            
            npc_count = reader.read_byte() if reader.remaining() >= 1 else 0
            npc_bag = reader.read_byte() if reader.remaining() >= 1 else 0
            
            npc_extras = self._read_extras_until_string(reader)
            self.log(f"  NPC extras: {npc_extras}")
            
            items_to_buy = self._parse_buy_items(reader)
            self.log(f"🛒 Total itens a comprar: {len(items_to_buy)}")
            
            if not items_to_buy:
                self.log("❌ Nenhum item encontrado no pacote")
                self._send_buy_result(False, "Nenhum item especificado")
                return
            
            if not self.player_data:
                self._send_buy_result(False, "Jogador não logado")
                return
            
            from inventory_manager import InventoryManager
            inv_mgr = InventoryManager(self.get_db())
            
            bought_items, total_spent, error = self._process_gold_purchase(
                inv_mgr, items_to_buy
            )
            
            if total_spent > 0:
                success_gold, new_gold = self.session._update_gold_in_db(-total_spent)
                if success_gold:
                    self.player_data['gold'] = new_gold
                    self.session._send_gold_change(-total_spent)
            
            success = len(bought_items) > 0
            self._send_buy_result(success, error if not success else "")
            
            if success:
                self._send_purchase_updates(inv_mgr, bought_items, items_to_buy)
                
        except Exception as e:
            self.log(f"Erro ao comprar item: {e}")
            import traceback
            traceback.print_exc()
            self._send_buy_result(False, str(e))
    
    
    def handle_buy_item_crystal(self, reader: PacketReader):
        """
        Comprar item com cristal/money.
        
        Formato StoreBuyItemRequest:
        - buyItemList:array(BuyItemInfo) -> VarInt length + array
        - giveToPlayerId:string
        - ssKey:short
        
        BuyItemInfo (cada item prefixado com ushort do tamanho):
        - [objectSize:ushort]
        - itemCode:string
        - itemCount:ubyte  
        - buyMode:byte
        """
        try:
            self.log(f"📦 STORE_BUY_ITEM_REQ (compra com cristal)")
            
            remaining_data = reader.data[reader.pos:]
            self.log(f"  Dados brutos ({len(remaining_data)} bytes): {remaining_data.hex()}")
            
            items_to_buy = []
            array_len = reader.read_varint() if reader.remaining() >= 1 else 0
            self.log(f"  Array length (VarInt): {array_len}")
            
            if array_len > 0 and array_len <= 50:
                for i in range(array_len):
                    if reader.remaining() < 4:
                        break
                    
                    object_size = reader.read_unsigned_short()
                    self.log(f"  Object {i+1} size: {object_size} bytes")
                    
                    if object_size == 0:
                        continue
                    
                    item_code = reader.read_string()
                    item_count = reader.read_unsigned_byte() if reader.remaining() >= 1 else 1
                    buy_mode = reader.read_byte() if reader.remaining() >= 1 else 0
                    
                    items_to_buy.append({
                        'itemCode': item_code,
                        'count': item_count,
                        'buyMode': buy_mode
                    })
                    self.log(f"  Item {i+1}: code={item_code}, count={item_count}, mode={buy_mode}")
            
            give_to_player_id = ""
            if reader.remaining() >= 1:
                try:
                    give_to_player_id = reader.read_string()
                    self.log(f"  GiveToPlayerId: {give_to_player_id}")
                except:
                    pass
            
            ss_key = 0
            if reader.remaining() >= 2:
                try:
                    ss_key = reader.read_short()
                    self.log(f"  SSKey: {ss_key}")
                except:
                    pass
            
            self.log(f"🛒 Total itens a comprar com cristal: {len(items_to_buy)}")
            
            if not items_to_buy:
                self.log("❌ Nenhum item encontrado no pacote")
                return
            
            if not self.player_data:
                self.log("❌ Jogador não logado")
                return
            
            from inventory_manager import InventoryManager
            inv_mgr = InventoryManager(self.get_db())
            
            current_money = self.player_data.get('money', 0)
            self.log(f"💎 Cristal atual: {current_money}")
            
            bought_items, total_spent, _ = self._process_crystal_purchase(
                inv_mgr, items_to_buy, current_money
            )
            
            if total_spent > 0:
                success_money, new_money = self.session._update_money_in_db(-total_spent)
                if success_money:
                    self.player_data['money'] = new_money
                    self.session._send_money_change(-total_spent)
            
            if bought_items:
                items = inv_mgr.load_inventory(self.role_name, 1)
                self.session._send_bag_check(1, items)
                
                items_for_notify = [
                    {
                        'item_id': str(bi.get('itemId', '')),
                        'item_code': bi['itemCode'],
                        'count': bi['count']
                    }
                    for bi in bought_items
                ]
                self.session._send_item_added_notify(items_for_notify)
            
            self.log(f"🛒 Compra com cristal finalizada: {len(bought_items)} itens, {total_spent} cristais")
                
        except Exception as e:
            self.log(f"Erro ao comprar item com cristal: {e}")
            import traceback
            traceback.print_exc()
    
    
    def handle_sell_item(self, reader: PacketReader):
        """Vender item para NPC"""
        try:
            raw_data = reader.data[reader.pos:]
            self.log(f"🛒 ShopSellItem raw ({len(raw_data)} bytes): {raw_data.hex()}")
            
            npc_id = reader.read_string()
            self.log(f"🏪 NPC Vendedor: {npc_id}")
            
            npc_count = reader.read_byte() if reader.remaining() >= 1 else 0
            npc_bag = reader.read_byte() if reader.remaining() >= 1 else 0
            
            npc_extras = []
            for _ in range(3):
                if reader.remaining() > 0:
                    npc_extras.append(reader.read_byte())
            
            self.log(f"  NPC extras: {npc_extras}")
            
            bag_index = reader.read_byte() if reader.remaining() >= 1 else 1
            slot_index = reader.read_byte() if reader.remaining() >= 1 else 0
            count = reader.read_byte() if reader.remaining() >= 1 else 1
            
            extras = []
            while reader.remaining() > 0:
                extras.append(reader.read_byte())
            
            self.log(f"  📦 Vender: bag={bag_index}, slot={slot_index}, count={count}")
            
            if not self.player_data:
                self._send_sell_result(False, "Jogador não logado")
                return
            
            if bag_index == 0:
                bag_index = 1
            
            from inventory_manager import InventoryManager
            inv_mgr = InventoryManager(self.get_db())
            
            items = inv_mgr.load_inventory(self.role_name, bag_index)
            item_to_sell = next(
                (i for i in items if i.get('SlotIndex') == slot_index), 
                None
            )
            
            if not item_to_sell:
                self.log(f"❌ Item não encontrado no slot {slot_index}")
                self._send_sell_result(False, "Item não encontrado")
                return
            
            item_code = item_to_sell.get('ItemCode', '')
            current_count = item_to_sell.get('ItemCount', 1)
            
            item_def = inv_mgr.get_item_definition(item_code)
            sell_price = item_def.get('SellPrice', 0) if item_def else 0
            
            sell_count = min(count, current_count)
            total_gold = sell_price * sell_count
            
            self.log(f"  💰 {item_code} x{sell_count} @ {sell_price}g = {total_gold}g")
            
            result = inv_mgr.remove_item(self.role_name, bag_index, slot_index, sell_count)
            
            if not result.get('success', False):
                self._send_sell_result(False, "Erro ao remover item")
                return
            
            success_gold, new_gold = self.session._update_gold_in_db(total_gold)
            if success_gold:
                self.player_data['gold'] = new_gold
            
            self.log(f"✅ Vendido! Novo gold: {new_gold}")
            
            self.session._send_gold_change(total_gold)
            self._send_sell_result(True)
            
            items = inv_mgr.load_inventory(self.role_name, bag_index)
            self.session._send_bag_check(bag_index, items)
            
        except Exception as e:
            self.log(f"Erro ao vender item: {e}")
            import traceback
            traceback.print_exc()
            self._send_sell_result(False, str(e))
    
    
    def _read_extras_until_string(self, reader: PacketReader, max_bytes: int = 5) -> list:
        """Lê bytes extras até encontrar o início de uma string"""
        extras = []
        while reader.remaining() > 0 and len(extras) < max_bytes:
            peek_pos = reader.pos
            peek_byte = reader.data[peek_pos]
            
            if 1 <= peek_byte <= 20 and reader.remaining() >= peek_byte + 3:
                potential_str = reader.data[peek_pos + 1:peek_pos + 1 + peek_byte]
                if all(32 <= b <= 126 for b in potential_str):
                    break
            
            extras.append(reader.read_byte())
        return extras
    
    def _parse_buy_items(self, reader: PacketReader, max_items: int = 20) -> list:
        """Parse lista de itens a comprar"""
        items = []
        
        while reader.remaining() >= 3 and len(items) < max_items:
            try:
                item_code = reader.read_string()
                
                if not item_code or len(item_code) < 2:
                    break
                if not any(c.isalnum() for c in item_code):
                    break
                
                count = reader.read_byte() if reader.remaining() >= 1 else 1
                bag_index = reader.read_byte() if reader.remaining() >= 1 else 1
                extras = self._read_extras_until_string(reader)
                
                items.append({
                    'itemCode': item_code,
                    'count': count,
                    'bagIndex': bag_index if bag_index > 0 else 1,
                    'extras': extras
                })
                
            except:
                break
        
        return items
    
    def _process_gold_purchase(self, inv_mgr, items_to_buy: list):
        """Processa compra com gold, retorna (bought_items, total_spent, error)"""
        bought_items = []
        total_spent = 0
        error_msg = ""
        current_gold = self.player_data.get('gold', 0)
        
        for item_info in items_to_buy:
            item_code = item_info['itemCode']
            count = item_info['count']
            bag_index = item_info['bagIndex']
            
            item_def = inv_mgr.get_item_definition(item_code)
            buy_price = item_def.get('BuyPrice', 0) if item_def else 0
            total_cost = buy_price * count
            
            remaining = current_gold - total_spent
            if total_cost > remaining:
                error_msg = f"Gold insuficiente para {item_code}"
                self.log(f"❌ {error_msg}")
                continue
            
            result = inv_mgr.add_item(
                role_name=self.role_name,
                item_code=item_code,
                count=count,
                bag_index=bag_index
            )
            
            if result['success']:
                bought_items.append({
                    'itemCode': item_code,
                    'count': count,
                    'slot': result.get('slot_index', 0),
                    'itemId': result.get('item_id', '')
                })
                total_spent += total_cost
                self.log(f"✅ Comprado: {item_code} x{count} por {total_cost}g")
            else:
                error_msg = result.get('error', 'Erro desconhecido')
                self.log(f"❌ Erro: {error_msg}")
        
        return bought_items, total_spent, error_msg
    
    def _process_crystal_purchase(self, inv_mgr, items_to_buy: list, current_money: int):
        """Processa compra com cristal"""
        bought_items = []
        total_spent = 0
        error_msg = ""
        
        for item_info in items_to_buy:
            item_code = item_info['itemCode']
            count = item_info['count']
            
            item_def = inv_mgr.get_item_definition(item_code)
            if not item_def:
                self.log(f"⚠️ Item não encontrado: {item_code}")
                continue
            
            premium_price = item_def.get('PremiumPrice', -1) or -1
            if premium_price < 0:
                self.log(f"⚠️ {item_code} não vende por cristal (PremiumPrice={premium_price})")
                continue
            
            total_cost = premium_price * count
            remaining = current_money - total_spent
            
            if total_cost > remaining:
                self.log(f"❌ Cristal insuficiente para {item_code}")
                continue
            
            result = inv_mgr.add_item(
                role_name=self.role_name,
                item_code=item_code,
                count=count,
                bag_index=1
            )
            
            if result['success']:
                bought_items.append({
                    'itemCode': item_code,
                    'count': count,
                    'slot': result.get('slot_index', 0),
                    'itemId': result.get('item_id', '')
                })
                total_spent += total_cost
                self.log(f"✅ Comprado: {item_code} x{count} por {total_cost} cristais")
            else:
                error_msg = result.get('error', '')
                self.log(f"❌ Erro: {error_msg}")
        
        return bought_items, total_spent, error_msg
    
    def _send_purchase_updates(self, inv_mgr, bought_items: list, items_to_buy: list):
        """Envia atualizações após compra bem-sucedida"""
        bag_index = items_to_buy[0].get('bagIndex', 1) if items_to_buy else 1
        
        items = inv_mgr.load_inventory(self.role_name, bag_index)
        self.session._send_bag_check(bag_index, items)
        
        items_for_notify = [
            {
                'item_id': str(bi.get('itemId', '')),
                'item_code': bi['itemCode'],
                'count': bi['count']
            }
            for bi in bought_items
        ]
        self.session._send_item_added_notify(items_for_notify)
    
    def _send_buy_result(self, success: bool, error_msg: str = ""):
        """Envia resultado da compra"""
        builder = PacketBuilder()
        builder.write_bool(success)
        builder.write_string(error_msg)
        self.send_packet(builder.build(ShopCommandCode.SHOP_BUY_ITEM_ANSWER))
        self.log(f"📤 ShopBuyAnswer: success={success}, error={error_msg}")
    
    def _send_sell_result(self, success: bool, error_msg: str = ""):
        """Envia resultado da venda"""
        builder = PacketBuilder()
        builder.write_bool(success)
        builder.write_string(error_msg)
        self.send_packet(builder.build(ShopCommandCode.SHOP_SELL_ITEM_ANSWER))
        self.log(f"📤 ShopSellAnswer: success={success}, error={error_msg}")
