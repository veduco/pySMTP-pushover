import copy
import asyncio

class QueueBroker:
    def __init__(self):
        self.state = {}
        self.subs = []

    def add_sub(self, q: asyncio.Queue):
        self.subs.append(q)
        return copy.deepcopy(self.state)

    def remove_sub(self, q: asyncio.Queue):
        if q in self.subs:
            self.subs.remove(q)

    def publish(self, action: str, item: dict = None):
        if item:
            if action in ("add", "update"):
                self.state[item["id"]] = item
            elif action == "delete":
                self.state.pop(item["id"], None)

        for q in self.subs:
            # put_nowait instantly drops the event into the stream without blocking
            q.put_nowait({"action": action, "item": item})

broker = QueueBroker()
