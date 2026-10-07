"""沙盒推演：what-if 全量模拟——推演 = 在另一个世界里真的做一遍。

沙盒是真 KnowledgeBase：新建实例覆盖可变层（effects/retractions/params/
pending，declared 从 ttl 重新 parse），execute/审批门/全量重算零改动复用。
推演结束沙盒即弃——执行是假的（不落库），因果链是真的（全真管线跑出来），
真实世界一个字节不动。
"""
from engine.knowledge_base import KnowledgeBase


def open_sandbox(real_kb: KnowledgeBase) -> KnowledgeBase:
    """按当前真实世界快照造一个沙盒：可变层拷贝，declared 重新加载。"""
    sim = KnowledgeBase()
    with real_kb._lock:          # 快照取锁内一致瞬间；RLock 可重入
        for t in real_kb.effects:
            sim.effects.add(t)
        for t in real_kb.retractions:
            sim.retractions.add(t)
        sim.params = dict(real_kb.params)
        sim.pending = set(real_kb.pending)
    sim.refresh()
    sim.world.bootstrap()        # 派生状态基于沙盒事实重算
    return sim
