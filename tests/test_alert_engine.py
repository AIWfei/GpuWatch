from __future__ import annotations

import datetime as dt
from types import SimpleNamespace as NS

from gpuwatch.alert_engine import AlertEngine, Kind, in_quiet_hours
from gpuwatch.gpu_probe import GpuSample


def sample(used_pct: float, total: int = 24000, index: int = 0) -> GpuSample:
    return GpuSample(index, f"GPU-{index}", "RTX", int(total * used_pct / 100), total, 0, 40)


def make(engine_cls=AlertEngine, busy_again: bool = False, **kw) -> AlertEngine:
    mon = NS(
        metric="used_percent",
        threshold=20,
        hysteresis=5,
        debounce_count=3,
        cooldown_s=600,
        repeat_interval_s=0,
        aggregate="per_gpu",
        gpu_filter=[],
        poll_interval_s=10,
    )
    mon.__dict__.update(kw)
    return engine_cls(mon, busy_again, "srv")


def feed_all(eng: AlertEngine, seq, step: float = 10):
    fired = []
    for i, item in enumerate(seq):
        samples = item if isinstance(item, list) else [sample(item)]
        for event in eng.feed(samples, i * step):
            fired.append((i * step, event.kind, event.key))
    return fired


def kinds(fired):
    return [f[1] for f in fired]


def test_idle_after_three_consecutive_samples():
    eng = make()
    fired = feed_all(eng, [80, 15, 15, 15, 22, 30])
    assert kinds(fired) == [Kind.IDLE]
    assert fired[0][0] == 30


def test_debounce_resets_when_busy():
    eng = make()
    assert kinds(feed_all(eng, [15, 15, 80, 15, 15])) == []
    assert kinds(feed_all(eng, [15, 15, 15, 15])) == [Kind.IDLE]


def test_hysteresis_gray_zone_keeps_state():
    eng = make(cooldown_s=0)
    idle = [15, 15, 15]
    # 22% 与 24% 位于 [20, 25) 灰区，不能触发“重新变忙”，也不重复提醒
    assert kinds(feed_all(eng, idle + [22, 24])) == [Kind.IDLE]
    # 25% 越过回差才回到 BUSY；之后再次连续三次空闲才重新提醒
    fired = feed_all(eng, [25, 15, 15, 15])
    assert kinds(fired) == [Kind.IDLE]


def test_percent_hysteresis_is_capped_at_100():
    eng = make(
        threshold=100,
        hysteresis=5,
        debounce_count=1,
        cooldown_s=0,
        busy_again=True,
    )
    assert kinds(feed_all(eng, [99])) == [Kind.IDLE]
    assert kinds(feed_all(eng, [100])) == [Kind.BUSY_AGAIN]


def test_cooldown_delays_second_notification():
    eng = make()
    seq = [15, 15, 15, 30] + [15] * 70
    fired = feed_all(eng, seq)
    assert fired[0] == (20, Kind.IDLE, "gpu:0")
    assert fired[1][0] == 620
    assert fired[1][1] == Kind.IDLE


def test_repeat_reminder():
    eng = make(cooldown_s=0, repeat_interval_s=100)
    fired = feed_all(eng, [15, 15, 15] + [15] * 10)
    assert fired == [
        (20, Kind.IDLE, "gpu:0"),
        (120, Kind.REMIND, "gpu:0"),
    ]


def test_busy_again_notification_optional():
    eng = make(cooldown_s=0, busy_again=True)
    fired = feed_all(eng, [15, 15, 15, 30])
    assert kinds(fired) == [Kind.IDLE, Kind.BUSY_AGAIN]

    quiet = make(cooldown_s=0, busy_again=False)
    assert kinds(feed_all(quiet, [15, 15, 15, 30])) == [Kind.IDLE]


def test_any_aggregation():
    eng = make(aggregate="any", debounce_count=1)
    samples = [sample(90, index=0), sample(10, index=1)]
    fired = eng.feed(samples, 0)
    assert [(e.kind, e.key) for e in fired] == [(Kind.IDLE, "server")]


def test_all_aggregation():
    eng = make(aggregate="all", debounce_count=1)
    assert eng.feed([sample(90, index=0), sample(10, index=1)], 0) == []
    fired = eng.feed([sample(10, index=0), sample(10, index=1)], 10)
    assert [(e.kind, e.key) for e in fired] == [(Kind.IDLE, "server")]


def test_free_mib_metric():
    eng = make(metric="free_mib", threshold=20480, hysteresis=1024, debounce_count=1)
    # total 24576，used 2048 -> free 22528 >= 20480
    assert kinds(feed_all(eng, [8.34])) == [Kind.IDLE]
    # free 19000 低于阈值-回差，视为重新变忙
    assert kinds(feed_all(eng, [99.0])) == []
    # 阈值与回差之间的灰区：free 20000，不改变状态
    eng2 = make(metric="free_mib", threshold=20480, hysteresis=1024, debounce_count=1)
    feed_all(eng2, [8.34])
    assert eng2.feed([sample(18.63)], 10) == []  # free 19535，灰区
    assert eng2.feed([sample(90)], 20) == []


def test_gpu_filter_only_monitors_selected_gpu():
    eng = make(gpu_filter=[1], debounce_count=1)
    assert eng.feed([sample(5, index=0), sample(90, index=1)], 0) == []
    fired = eng.feed([sample(5, index=0), sample(5, index=1)], 10)
    assert [(e.kind, e.key) for e in fired] == [(Kind.IDLE, "gpu:1")]


def test_per_gpu_emits_for_each_idle_gpu():
    eng = make(debounce_count=1)
    fired = eng.feed([sample(5, index=0), sample(6, index=1)], 0)
    assert [(e.kind, e.key) for e in fired] == [
        (Kind.IDLE, "gpu:0"),
        (Kind.IDLE, "gpu:1"),
    ]


def test_samples_without_memory_are_ignored():
    from gpuwatch.gpu_probe import GpuSample

    eng = make(debounce_count=1)
    bad = GpuSample(0, "u", "RTX", None, None, None, None)
    assert eng.feed([bad], 0) == []
    # 只剩被过滤的 GPU 时也不产生事件
    eng2 = make(gpu_filter=[1], debounce_count=1)
    assert eng2.feed([sample(5, index=0)], 0) == []


def test_quiet_hours_same_day():
    q = NS(enabled=True, start="12:00", end="14:00")
    assert not in_quiet_hours(q, dt.time(11, 59, 59))
    assert in_quiet_hours(q, dt.time(12, 0))
    assert in_quiet_hours(q, dt.time(13, 30))
    assert not in_quiet_hours(q, dt.time(14, 0))


def test_quiet_hours_across_midnight():
    q = NS(enabled=True, start="23:00", end="08:00")
    assert not in_quiet_hours(q, dt.time(22, 59))
    assert in_quiet_hours(q, dt.time(23, 0))
    assert in_quiet_hours(q, dt.time(0, 30))
    assert in_quiet_hours(q, dt.time(7, 59, 59))
    assert not in_quiet_hours(q, dt.time(8, 0))


def test_quiet_hours_disabled():
    q = NS(enabled=False, start="00:00", end="23:59")
    assert not in_quiet_hours(q, dt.time(12, 0))


def test_resume_after_suppression_sends_one_catch_up():
    eng = make(cooldown_s=0, debounce_count=1)
    assert kinds(feed_all(eng, [10])) == [Kind.IDLE]
    # 贪睡/免打扰期间不调用 feed；恢复后 resumed=True 补发一次
    fired = eng.feed([sample(10)], 1000, resumed=True)
    assert [e.kind for e in fired] == [Kind.REMIND]
    assert eng.feed([sample(10)], 1010) == []
