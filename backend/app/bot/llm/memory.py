import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional

@dataclass
class Message:
    role: str # 'user', 'assistant', 'tool'
    content: str
    timestamp: float = field(default_factory=time.time)

class ChatMemory:
    def __init__(self, ttl_seconds: int = 1800, max_messages: int = 8):
        self._store: Dict[int, deque[Message]] = {}
        self.ttl_seconds = ttl_seconds
        self.max_messages = max_messages

    def add(self, chat_id: int, role: str, content: str):
        if chat_id not in self._store:
            self._store[chat_id] = deque(maxlen=self.max_messages)
        
        # Prune old messages logic could be here, but simpler to just prune on read.
        self._store[chat_id].append(Message(role, content))

    def get_context(self, chat_id: int) -> List[Dict[str, str]]:
        if chat_id not in self._store:
            return []
            
        now = time.time()
        # Filter by TTL
        valid_msgs = [
            m for m in self._store[chat_id] 
            if (now - m.timestamp) < self.ttl_seconds
        ]
        
        # Update store if we pruned
        if len(valid_msgs) < len(self._store[chat_id]):
            self._store[chat_id] = deque(valid_msgs, maxlen=self.max_messages)

        return [{"role": m.role, "content": m.content} for m in valid_msgs]

    def clear(self, chat_id: int):
        if chat_id in self._store:
            del self._store[chat_id]

# Singleton
memory = ChatMemory()
