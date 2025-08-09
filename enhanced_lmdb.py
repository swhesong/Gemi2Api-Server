import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Union, Any
import json

try:
    import lmdb
    import orjson
    HAS_LMDB = True
except ImportError:
    HAS_LMDB = False
    lmdb = None
    orjson = None


class EnhancedLMDBConversationStore:
    """Enhanced LMDB conversation storage with intelligent session reuse"""
    
    def __init__(self, db_path: str = "./data/lmdb", max_db_size: int = 134217728):
        self.db_path = Path(db_path)
        self.max_db_size = max_db_size
        self._env = None
        self._init_environment()
    
    def _init_environment(self):
        """Initialize LMDB environment"""
        if not HAS_LMDB:
            print("⚠️ LMDB not available, session persistence disabled")
            return
            
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._env = lmdb.open(
                str(self.db_path),
                map_size=self.max_db_size,
                max_dbs=3,
                writemap=True,
                readahead=False,
                meminit=False,
            )
            print(f"✅ Enhanced LMDB store initialized at {self.db_path}")
        except Exception as e:
            print(f"⚠️ Failed to initialize LMDB: {str(e)}")
            self._env = None
    
    def _hash_conversation(self, client_id: str, model: str, messages: List[Dict]) -> str:
        """Generate hash for conversation (项目N算法)"""
        combined_hash = hashlib.sha256()
        combined_hash.update(client_id.encode("utf-8"))
        combined_hash.update(model.encode("utf-8"))
        
        for message in messages:
            if isinstance(message, dict):
                message_str = json.dumps(message, sort_keys=True)
            else:
                message_str = json.dumps({"role": message.role, "content": message.content}, sort_keys=True)
            combined_hash.update(message_str.encode('utf-8'))
        
        return combined_hash.hexdigest()
    
    def store_conversation(self, messages: List[Dict], client_id: str, model: str, session_metadata: Optional[Dict] = None) -> Optional[str]:
        """Store conversation with enhanced metadata"""
        if not self._env or not messages:
            return None
            
        try:
            conv_hash = self._hash_conversation(client_id, model, messages)
            data = {
                "messages": messages,
                "client_id": client_id,
                "model": model,
                "session_metadata": session_metadata or {},
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
            
            with self._env.begin(write=True) as txn:
                serialized_data = orjson.dumps(data) if orjson else json.dumps(data).encode('utf-8')
                txn.put(conv_hash.encode('utf-8'), serialized_data)
                
                # Store reverse lookup
                lookup_key = f"lookup_{conv_hash}"
                txn.put(lookup_key.encode('utf-8'), conv_hash.encode('utf-8'))
            
            print(f"💾 Stored conversation with hash: {conv_hash[:16]}...")
            return conv_hash
        except Exception as e:
            print(f"⚠️ Failed to store conversation: {str(e)}")
            return None
    
    def find_reusable_session(self, model: str, messages: List[Dict], available_clients: Optional[List[str]] = None) -> tuple[Optional[Dict], List[Dict]]:
        """
        Find reusable session using intelligent prefix matching (项目N的核心算法)
        
        Returns:
            tuple of (stored_session_data, remaining_messages)
        """
        if not self._env or len(messages) < 2:
            return None, messages
        
        available_clients = available_clients or ["env_client"]
        
        try:
            # Walk backwards through message history to find longest matching prefix
            for search_end in range(len(messages) - 1, 1, -1):
                search_history = messages[:search_end]
                
                # Only try to match if last stored message would be assistant/system
                if search_history[-1].get("role") not in {"assistant", "system"}:
                    continue
                
                # Try each available client
                for client_id in available_clients:
                    try:
                        search_hash = self._hash_conversation(client_id, model, search_history)
                        
                        with self._env.begin() as txn:
                            data = txn.get(search_hash.encode('utf-8'))
                            if data:
                                stored_data = orjson.loads(data) if orjson else json.loads(data.decode('utf-8'))
                                remaining_messages = messages[search_end:]
                                
                                print(f"♻️ Found reusable session for {len(search_history)} messages, {len(remaining_messages)} remaining")
                                return stored_data, remaining_messages
                                
                    except Exception as e:
                        print(f"⚠️ Error checking client {client_id}: {str(e)}")
                        continue
            
            return None, messages
            
        except Exception as e:
            print(f"⚠️ Error in session reuse search: {str(e)}")
            return None, messages
    
    def sanitize_assistant_messages(self, messages: List[Dict]) -> List[Dict]:
        """Remove thinking tags from assistant messages (项目N功能)"""
        cleaned_messages = []
        for msg in messages:
            if msg.get("role") == "assistant" and isinstance(msg.get("content"), str):
                content = msg["content"]
                # Remove <think>...</think> tags
                cleaned_content = re.sub(r'^(\s*<think>.*?</think>\n?)', '', content, flags=re.DOTALL)
                cleaned_content = cleaned_content.strip()
                
                if cleaned_content != content:
                    cleaned_msg = {**msg, "content": cleaned_content}
                    cleaned_messages.append(cleaned_msg)
                else:
                    cleaned_messages.append(msg)
            else:
                cleaned_messages.append(msg)
        
        return cleaned_messages
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics"""
        if not self._env:
            return {"available": False}
        
        try:
            with self._env.begin() as txn:
                stats = txn.stat()
            return {
                "available": True,
                "stats": stats,
                "path": str(self.db_path),
                "entries": stats.get('entries', 0)
            }
        except Exception as e:
            return {"available": True, "error": str(e)}
