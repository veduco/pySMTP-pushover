import threading
import copy
import asyncio

class QueueBroker:
    def __init__(self):
        self.state = {}
        self.lock = threading.Lock()
        self.subs = []

    def add_sub(self, q: asyncio.Queue):
        with self.lock:
            self.subs.append(q)
            return copy.deepcopy(self.state)

    def remove_sub(self, q: asyncio.Queue):
        with self.lock:
            if q in self.subs:
                self.subs.remove(q)

    def publish(self, action: str, item: dict = None):
        with self.lock:
            if item:
                if action in ("add", "update"):
                    self.state[item["id"]] = item
                elif action == "delete":
                    self.state.pop(item["id"], None)

            for q in self.subs:
                # Fire and forget thread-safe append to asyncio queues
                q.put_nowait({"action": action, "item": item})

broker = QueueBroker()
