from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum

from .gpu_probe import GpuSample

METRIC_LABELS = {
    "used_percent": "显存占用百分比 (%)",
    "used_mib": "已用显存 (MiB)",
    "free_mib": "空闲显存 (MiB)",
}

AGGREGATE_LABELS = {
    "per_gpu": "逐卡判定",
    "any": "任一 GPU 满足",
    "all": "全部 GPU 满足",
}


class Kind(str, Enum):
    IDLE = "idle"
    REMIND = "remind"
    BUSY_AGAIN = "busy"
    DISCONNECT = "disconnect"
    RECOVER = "recover"
    ERROR = "error"


@dataclass(frozen=True)
class AlertEvent:
    kind: Kind
    key: str
    title: str
    message: str


def in_quiet_hours(q, now: dt.time | None = None) -> bool:
    if not q.enabled:
        return False
    now = now or dt.datetime.now().time()
    start = dt.time.fromisoformat(q.start)
    end = dt.time.fromisoformat(q.end)
    if start <= end:
        return start <= now < end
    return now >= start or now < end


def metric_value(mon, sample: GpuSample) -> float | None:
    if mon.metric == "used_percent":
        return sample.used_percent
    if mon.metric == "used_mib":
        return sample.mem_used_mib
    if mon.metric == "free_mib":
        return sample.free_mib
    return None


def classify(mon, value: float) -> tuple[bool, bool]:
    threshold, hysteresis = mon.threshold, mon.hysteresis
    if mon.metric == "free_mib":
        return value >= threshold, value < max(0, threshold - hysteresis)
    if mon.metric == "used_percent":
        return value < threshold, value >= min(100, threshold + hysteresis)
    return value < threshold, value >= threshold + hysteresis


def is_sample_idle(mon, sample: GpuSample) -> bool | None:
    value = metric_value(mon, sample)
    if value is None:
        return None
    return classify(mon, value)[0]


def _fmt_mib(value: float) -> str:
    return f"{value:,.0f}"


def _fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f} 秒"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.0f} 分钟" if abs(minutes - round(minutes)) < 0.05 else f"{minutes:.1f} 分钟"
    hours = seconds / 3600
    return f"{hours:.1f} 小时"


def format_rule_preview(mon) -> str:
    subject = {
        "per_gpu": "同一块 GPU",
        "any": "任意一块 GPU",
        "all": "所有 GPU",
    }.get(mon.aggregate, "GPU")

    if mon.metric == "used_percent":
        condition = f"{subject}显存占用低于 {mon.threshold:g}%"
        release = f"回升到 {min(100, mon.threshold + mon.hysteresis):g}% 以上"
    elif mon.metric == "used_mib":
        condition = f"{subject}已用显存低于 {_fmt_mib(mon.threshold)} MiB"
        release = f"回升到 {_fmt_mib(mon.threshold + mon.hysteresis)} MiB 以上"
    else:
        condition = f"{subject}空闲显存不低于 {_fmt_mib(mon.threshold)} MiB"
        release = f"回落到 {_fmt_mib(max(0, mon.threshold - mon.hysteresis))} MiB 以下"

    duration = _fmt_duration(mon.poll_interval_s * mon.debounce_count)
    text = (
        f"当{condition}，连续 {mon.debounce_count} 次采样（约 {duration}）后提醒；"
        f"{release}视为重新变忙；"
    )
    if mon.cooldown_s > 0:
        text += f"{_fmt_duration(mon.cooldown_s)}内不重复提醒"
    else:
        text += "不设冷却时间"
    if mon.repeat_interval_s > 0:
        text += f"；持续空闲时每 {_fmt_duration(mon.repeat_interval_s)}重复提醒"
    if mon.gpu_filter:
        gpus = "、".join(str(i) for i in sorted(mon.gpu_filter))
        text += f"；仅监控 GPU {gpus}"
    return text + "。"


@dataclass
class _State:
    status: str = "busy"
    streak: int = 0
    last_notify: float | None = None


class AlertEngine:
    def __init__(self, mon, notify_busy_again: bool, server_name: str):
        self.mon = mon
        self.busy_again = notify_busy_again
        self.name = server_name
        self._st: dict[str, _State] = {}

    def reset(self) -> None:
        self._st.clear()

    def feed(
        self, samples: list[GpuSample], now: float, resumed: bool = False
    ) -> list[AlertEvent]:
        gpu_filter = self.mon.gpu_filter
        picked = [
            s
            for s in samples
            if (not gpu_filter or s.index in gpu_filter)
            and s.mem_used_mib is not None
            and s.mem_total_mib
        ]
        if not picked:
            return []

        flags: list[tuple[bool, bool]] = []
        for sample in picked:
            value = metric_value(self.mon, sample)
            if value is None:
                flags.append((False, True))
            else:
                flags.append(classify(self.mon, value))

        events: list[AlertEvent] = []
        if self.mon.aggregate == "per_gpu":
            for sample, (idle, released) in zip(picked, flags):
                events += self._step(
                    f"gpu:{sample.index}", idle, released, now, [sample], resumed
                )
        else:
            idle_samples = [s for s, fl in zip(picked, flags) if fl[0]]
            if self.mon.aggregate == "any":
                idle = any(fl[0] for fl in flags)
                released = all(fl[1] for fl in flags)
            else:
                idle = all(fl[0] for fl in flags)
                released = any(fl[1] for fl in flags)
            events += self._step(
                "server", idle, released, now, idle_samples or picked, resumed
            )
        return events

    def _step(
        self,
        key: str,
        idle: bool,
        released: bool,
        now: float,
        samples: list[GpuSample],
        resumed: bool,
    ) -> list[AlertEvent]:
        state = self._st.setdefault(key, _State())
        mon = self.mon
        events: list[AlertEvent] = []
        if state.status == "busy":
            state.streak = state.streak + 1 if idle else 0
            cooled = (
                state.last_notify is None
                or now - state.last_notify >= mon.cooldown_s
            )
            if state.streak >= mon.debounce_count and cooled:
                state.status = "idle"
                state.last_notify = now
                events.append(self._event(Kind.IDLE, key, samples))
        else:
            if released:
                state.status = "busy"
                state.streak = 0
                if self.busy_again:
                    events.append(self._event(Kind.BUSY_AGAIN, key, samples))
            elif idle:
                # 贪睡/免打扰结束后补发一次，避免错过提醒窗口
                if resumed:
                    state.last_notify = now
                    events.append(self._event(Kind.REMIND, key, samples))
                elif (
                    mon.repeat_interval_s > 0
                    and state.last_notify is not None
                    and now - state.last_notify >= mon.repeat_interval_s
                ):
                    state.last_notify = now
                    events.append(self._event(Kind.REMIND, key, samples))
        return events

    def _event(self, kind: Kind, key: str, samples: list[GpuSample]) -> AlertEvent:
        def fmt(sample: GpuSample) -> str:
            used = sample.mem_used_mib or 0
            total = sample.mem_total_mib or 0
            percent = sample.used_percent or 0
            return (
                f"GPU {sample.index} {sample.name}：{used / 1024:.1f}/"
                f"{total / 1024:.1f} GiB（{percent:.0f}%）"
            )

        body = "\n".join(fmt(s) for s in samples[:4])
        if len(samples) > 4:
            body += f"\n…等共 {len(samples)} 张"
        title = {
            Kind.IDLE: f"{self.name} 有空闲显存",
            Kind.REMIND: f"{self.name} 显存仍然空闲",
            Kind.BUSY_AGAIN: f"{self.name} 显存已被占用",
        }[kind]
        return AlertEvent(kind, key, title, body)
