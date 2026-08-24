import time
from content_platform.workflow_runtime import strict_workflow_lock
class FakeStore:
 def __init__(self): self.heartbeats=0; self.released=0
 def acquire_workflow_lock(self,owner,workflow_id,ttl_seconds): return True
 def heartbeat_workflow_lock(self,owner,ttl_seconds): self.heartbeats+=1; return True
 def release_workflow_lock(self,owner): self.released+=1; return True
def test_strict_workflow_lock_renews_during_long_step():
 store=FakeStore()
 with strict_workflow_lock(store,"owner","workflow",ttl_seconds=0.02): time.sleep(0.07)
 assert store.heartbeats >= 2
 assert store.released == 1
