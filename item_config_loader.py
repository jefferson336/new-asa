import json
import os

class ItemConfigLoader:
    
    _instance = None
    _items_cache = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_items()
        return cls._instance
    
    def _load_items(self):
        try:
            iie_path = os.path.join(os.path.dirname(__file__), '..', 'downloader', 'out', 'iie.txt')
            
            with open(iie_path, 'r', encoding='utf-8') as f:
                items_list = json.load(f)
            
            for item in items_list:
                item_code = item.get('code')
                if item_code:
                    self._items_cache[item_code] = item
            
            print(f"✅ Item Config Loader: {len(self._items_cache)} itens carregados")
        except Exception as e:
            print(f"❌ Erro ao carregar iie.txt: {e}")
            self._items_cache = {}
    
    def get_item(self, item_code: str) -> dict:
        """Retorna configuração do item pelo código"""
        return self._items_cache.get(item_code)
    
    def get_model_code(self, item_code: str) -> str:
        """Retorna modelCode do item"""
        item = self.get_item(item_code)
        if item and 'properties' in item:
            return item['properties'].get('modelCode', '')
        return ''

item_config = ItemConfigLoader()
