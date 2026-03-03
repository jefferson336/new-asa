# Asa de Cristal - Server Documentation

## Overview

Private server implementation for the Flash MMORPG "Asa de Cristal", written in Python.

---

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   HTTP Server   │     │  Login Server   │     │  World Server   │
│   (port 8081)   │     │   (port 9999)   │     │   (port 8888)   │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         │              ┌────────┴────────┐              │
         │              │  Policy Server  │              │
         │              │   (port 843)    │              │
         │              └─────────────────┘              │
         │                                               │
         └───────────────────┬───────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │   SQL Server    │
                    │    Database     │
                    └─────────────────┘
```

---

## Directory Structure

```
server_py/
├── main.py                    # Entry point - starts all servers
├── config.py                  # Centralized configuration (ports, paths, auth mode)
├── inventory_manager.py       # Inventory system operations (add, move, use, equip items)
├── player_data_manager.py     # Player data loading/saving from database
├── item_config_loader.py      # Loads item definitions from iie.txt
│
├── servers/                   # Server implementations
│   ├── __init__.py
│   ├── base_server.py         # Base TCP server class with threading
│   ├── http_server.py         # HTTP server for game resources (SWF, XML)
│   ├── login_server.py        # Authentication server (ticket generation)
│   ├── policy_server.py       # Flash cross-domain policy server
│   └── world_server.py        # Main game server (movement, combat, etc.)
│
├── handlers/                  # Modular packet handlers
│   ├── __init__.py
│   ├── base_handler.py        # Base class for all handlers
│   ├── registry.py            # Central handler registry and dispatch system
│   ├── world_handler.py       # World login, ping, config (5 commands)
│   ├── role_handler.py        # Character CRUD operations (5 commands)
│   ├── movement_handler.py    # Player movement and map transitions (2 commands)
│   ├── inventory_handler.py   # Bag management, item usage (7 commands)
│   └── shop_handler.py        # Buy/sell operations (3 commands)
│
├── protocol/                  # Network protocol implementation
│   ├── __init__.py
│   ├── commands.py            # Command code enums (Login, World, Role, Bag, Shop)
│   ├── packet_reader.py       # Packet deserialization (VarInt, strings, etc.)
│   └── packet_builder.py      # Packet serialization with header construction
│
├── game_data/                 # Game configuration data
│   ├── __init__.py
│   └── map_teleport_config.py # Auto-generated map exits and entries
│
├── game_resources/            # Static files served by HTTP server
│   ├── index.html             # Game launcher page
│   ├── crossdomain.xml        # Flash cross-domain policy
│   ├── WebLaucher.swf         # Flash launcher
│   ├── bin/                   # Compiled game files
│   ├── LoadingBG/             # Loading screen assets
│   └── res/                   # Game resources (hashed filenames)
│
├── tools/                     # Development and debugging tools
│   ├── packet_proxy.py        # TCP proxy for packet interception
│   └── sql/                   # SQL scripts
│
└── logs/                      # Packet logs (JSON format)
```

---

## Servers

### HTTP Server (port 8081)

Serves static game resources using Python's SimpleHTTPRequestHandler with CORS headers for Flash compatibility.

| Endpoint | Description |
|----------|-------------|
| `/` | Game launcher (index.html) |
| `/crossdomain.xml` | Flash cross-domain policy |
| `/bin/*` | Compiled game SWF files |
| `/res/*` | Game resources |

### Login Server (port 9999)

Handles player authentication and server selection.

| Command | Code | Direction | Description |
|---------|------|-----------|-------------|
| WelcomeNotify | 16 | S→C | Sends session key on connect |
| LoginRequest | 17 | C→S | Username + password hash |
| LoginAnswer | 18 | S→C | Success/failure + ticket |
| ServerListRequest | 23 | C→S | Request available servers |
| ServerListAnswer | 24 | S→C | Server list with status |

### World Server (port 8888)

Main game server handling all gameplay logic.

**World Commands:**
| Command | Code | Description |
|---------|------|-------------|
| WorldLoginReq | 33 | Enter world with ticket |
| WorldLoginAnswer | 34 | Login result |
| WorldPingEcho | 49 | Keep-alive ping |
| ClientSaveConfigNotify | 50 | Save client settings |

**Role Commands (257-276):**
| Command | Code | Description |
|---------|------|-------------|
| RoleListReq | 257 | Get character list |
| RoleNameConfirmReq | 259 | Check name availability |
| CreateRoleReq | 261 | Create new character |
| DeleteRoleReq | 263 | Delete character |
| SelectRoleReq | 265 | Select character to play |

**Player Commands (513-676):**
| Command | Code | Description |
|---------|------|-------------|
| PlayerEnterWorldReq | 513 | Enter game world |
| PlayerEnterMapReq | 517 | Transition between maps |
| PlayerMoveReq | 519 | Movement with path |
| PositionCheckNotify | 520 | Server position sync |
| UseSkillReq | 545 | Use skill |
| SendMsgRequest | 673 | Chat message |

**Bag Commands (5121-5141):**
| Command | Code | Description |
|---------|------|-------------|
| BagCheckNotify | 5121 | Sync inventory |
| UseItemReq | 5124 | Use/equip item |
| MoveItemReq | 5125 | Move item between slots |
| DropItemReq | 5127 | Drop item |
| ViewItemReq | 5133 | Get item details |
| BagSortReq | 5141 | Sort inventory |

**Equipment Commands:**
| Command | Code | Description |
|---------|------|-------------|
| EquipmentCheckNotify | 4609 | Sync equipment |
| RemoveEquipmentReq | 4610 | Unequip item |

**Shop Commands (2817-2821):**
| Command | Code | Description |
|---------|------|-------------|
| ShopSellItemReq | 2817 | Sell to NPC |
| ShopBuyItemReq | 2818 | Buy with gold |
| StoreBuyItemReq | 2819 | Buy with crystals |

### Policy Server (port 843)

Returns Flash socket policy XML for cross-domain socket access.

---

## Protocol

### Packet Structure

```
┌──────────────┬─────────┬────────┬──────────┐
│ VarInt Length│ Command │ Digest │ Payload  │
│   (1-5 bytes)│ (2 bytes)│(2 bytes)│ (N bytes)│
└──────────────┴─────────┴────────┴──────────┘
```

- **Length**: VarInt encoding the total size of Command + Digest + Payload
- **Command**: 2-byte unsigned short (Big Endian)
- **Digest**: 2-byte checksum (typically 0)
- **Payload**: Variable-length data

### Data Types

| Type | Size | Description |
|------|------|-------------|
| byte | 1 | Signed byte (-128 to 127) |
| ubyte | 1 | Unsigned byte (0 to 255) |
| short | 2 | Signed 16-bit (Big Endian) |
| ushort | 2 | Unsigned 16-bit (Big Endian) |
| int | 4 | Signed 32-bit (Big Endian) |
| uint | 4 | Unsigned 32-bit (Big Endian) |
| long | 8 | Signed 64-bit (Big Endian) |
| float | 4 | 32-bit float (Big Endian) |
| double | 8 | 64-bit double (Big Endian) |
| varint | 1-5 | Variable-length integer (7 bits per byte, MSB = continue) |
| string | N | VarInt length + UTF-8 bytes |
| bool | 1 | 0 = false, non-zero = true |

### Transportable Objects

Complex objects are prefixed with a 2-byte size (ushort):
```
┌────────────┬──────────────┐
│ Size (2B)  │ Object Data  │
└────────────┴──────────────┘
```
If size = 0, the object is null.

---

## Handler System

Handlers are modular classes that process specific command groups.

### Creating a Handler

```python
from handlers.base_handler import BaseHandler
from protocol.commands import SomeCommandCode

class MyHandler(BaseHandler):
    @classmethod
    def get_handlers(cls):
        return {
            SomeCommandCode.MY_COMMAND: 'handle_my_command',
        }
    
    def handle_my_command(self, reader):
        data = reader.read_string()
        # Process and respond
        builder = PacketBuilder()
        builder.write_bool(True)
        self.send_packet(builder.build(SomeCommandCode.MY_RESPONSE))
```

### Handler Properties

| Property | Description |
|----------|-------------|
| `self.session` | Current client session |
| `self.server` | World server instance |
| `self.player_data` | Current player's data dict |
| `self.role_name` | Current character name |
| `self.account_id` | Account identifier |

---

## Configuration

### config.py

| Variable | Default | Description |
|----------|---------|-------------|
| HOST | 0.0.0.0 | Bind address |
| HTTP_PORT | 8081 | HTTP server port |
| LOGIN_PORT | 9999 | Login server port |
| WORLD_PORT | 8888 | World server port (env: WORLD_PORT) |
| POLICY_PORT | 843 | Policy server port |
| AUTH_MODE | debug | 'debug' = accept any login, 'db' = SQL Server auth |
| GAME_RESOURCES_DIR | ./game_resources | Static files directory |

---

## Debug Mode

### Packet Proxy

Intercepts packets between client and server for debugging:

```bash
# Start server on port 8889
set WORLD_PORT=8889 && python main.py

# Start proxy on 8888 -> 8889
python tools/packet_proxy.py --listen-port 8888 --target-port 8889
```

### Debug Scripts

| Script | Description |
|--------|-------------|
| START_DEBUG_PROXY.bat | Starts server + proxy for packet capture |
| start_debug_proxy.py | Python alternative |
| debug_packet.py | Single packet decoder |

---

## Map System

### Configuration

Map exits and entries are defined in `game_data/map_teleport_config.py`:

```python
MAP_EXITS = {
    ('a1', 'x1'): ('a2', 'e1'),  # From map a1, exit x1 -> map a2, entry e1
}

MAP_ENTRIES = {
    ('a2', 'e1'): (1024, 2048),  # Map a2, entry e1 -> spawn at (1024, 2048)
}
```

### Teleportation Flow

1. Client sends PlayerEnterMapReq with `fromMapId` and `exitId`
2. Server looks up exit in MAP_EXITS
3. Server finds spawn position in MAP_ENTRIES
4. Server sends PlayerEnterMapAnswer with new map and position

---

## Inventory System

### Bag Types

| Index | Type |
|-------|------|
| 1 | Player inventory |
| 2 | Pet inventory |
| 3 | Mount inventory |
| 10+ | Equipment slots |

### Equipment Slots

| Slot | Type |
|------|------|
| 0 | Weapon |
| 1 | Armor |
| 2 | Helmet |
| 3 | Gloves |
| 4 | Boots |
| 5 | Necklace |
| 6 | Ring 1 |
| 7 | Ring 2 |
| 8 | Belt |
| 9 | Cape |

---

## Running the Server

### Quick Start

```bash
cd server_py
python main.py
```

### With Packet Proxy

```bash
START_DEBUG_PROXY.bat
```

### Requirements

- Python 3.8+
- pyodbc (optional, for SQL Server)
- SQL Server database (optional)

---

## Authentication Modes

### Debug Mode (AUTH_MODE = 'debug')

Accepts any username/password combination. Creates accounts and characters on-the-fly.

### Database Mode (AUTH_MODE = 'db')

Validates credentials against SQL Server database. Requires:
- pyodbc installed
- SQL Server connection configured
- Database schema created

---

## Item Configuration

Items are loaded from `iie.txt` (JSON format) via ItemConfigLoader:

```python
from item_config_loader import item_config

item = item_config.get_item('sword_001')
model = item_config.get_model_code('sword_001')
```

---

## Logging

Server logs use colored output with prefixes:

| Prefix | Color | Server |
|--------|-------|--------|
| HTTP | Blue | HTTP Server |
| LOGIN | Green | Login Server |
| WORLD | Magenta | World Server |
| POLICY | Yellow | Policy Server |
| DB | Cyan | Database |

Packet logs are saved in `logs/` directory as JSON files.
