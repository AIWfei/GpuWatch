from __future__ import annotations

import csv
import io
import shlex
from dataclasses import dataclass

FIELDS = (
    "index,uuid,name,memory.used,memory.total,"
    "utilization.gpu,temperature.gpu"
)


class ProbeError(Exception):
    pass


@dataclass(frozen=True)
class GpuSample:
    index: int
    uuid: str
    name: str
    mem_used_mib: int | None
    mem_total_mib: int | None
    util_percent: int | None
    temp_c: int | None

    @property
    def used_percent(self) -> float | None:
        if self.mem_used_mib is None or not self.mem_total_mib:
            return None
        return self.mem_used_mib * 100 / self.mem_total_mib

    @property
    def free_mib(self) -> int | None:
        if self.mem_used_mib is None or self.mem_total_mib is None:
            return None
        return self.mem_total_mib - self.mem_used_mib


def build_command(smi_path: str = "nvidia-smi") -> str:
    return (
        f"LC_ALL=C timeout 15 {shlex.quote(smi_path)} "
        f"--query-gpu={FIELDS} --format=csv,noheader,nounits"
    )


def _int(text: str) -> int | None:
    try:
        return int(float(text.strip()))
    except (TypeError, ValueError):
        return None


def parse_query_output(text: str) -> list[GpuSample]:
    out: list[GpuSample] = []
    for row in csv.reader(io.StringIO(text), skipinitialspace=True):
        if len(row) < 7 or not row[0].strip().isdigit():
            continue
        used, total, util, temp = (_int(x) for x in row[-4:])
        name = ",".join(row[2:-4]).strip()
        out.append(
            GpuSample(
                index=int(row[0].strip()),
                uuid=row[1].strip(),
                name=name,
                mem_used_mib=used,
                mem_total_mib=total,
                util_percent=util,
                temp_c=temp,
            )
        )
    if not out:
        raise ProbeError("无法解析 nvidia-smi 输出：" + text[:200])
    return out


def describe_failure(code: int, stderr: str, stdout: str) -> str:
    lines = (stderr or stdout).strip().splitlines()
    first = lines[0].strip() if lines else ""
    if code == 127:
        return "服务器上找不到 nvidia-smi，请在连接设置中填写完整路径"
    if code == 124:
        return "nvidia-smi 执行超时（GPU 或驱动可能异常）"
    return f"nvidia-smi 退出码 {code}：{first}" if first else f"nvidia-smi 退出码 {code}"


def query_gpus(ssh, server) -> list[GpuSample]:
    result = ssh.exec(build_command(server.nvidia_smi_path), timeout=20)
    if result.exit_code != 0:
        raise ProbeError(describe_failure(result.exit_code, result.stderr, result.stdout))
    return parse_query_output(result.stdout)
