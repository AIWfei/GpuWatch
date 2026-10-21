from __future__ import annotations

import pytest

from gpuwatch.gpu_probe import (
    ProbeError,
    build_command,
    describe_failure,
    parse_query_output,
)


def test_single_gpu():
    text = "0, GPU-3f0a9c1e, NVIDIA GeForce RTX 4090, 1043, 24564, 3, 41\n"
    samples = parse_query_output(text)
    assert len(samples) == 1
    s = samples[0]
    assert (s.index, s.uuid, s.name) == (0, "GPU-3f0a9c1e", "NVIDIA GeForce RTX 4090")
    assert (s.mem_used_mib, s.mem_total_mib, s.util_percent, s.temp_c) == (1043, 24564, 3, 41)
    assert s.used_percent == pytest.approx(1043 * 100 / 24564)
    assert s.free_mib == 24564 - 1043


def test_multi_gpu():
    text = (
        "0, GPU-a, RTX 4090, 1043, 24564, 3, 41\n"
        "1, GPU-b, RTX 4090, 22816, 24564, 97, 68\n"
    )
    samples = parse_query_output(text)
    assert [s.index for s in samples] == [0, 1]
    assert samples[1].mem_used_mib == 22816


def test_na_and_unsupported_fields():
    text = "0, GPU-a, RTX 3090, 500, 24576, [N/A], [Not Supported]\n"
    s = parse_query_output(text)[0]
    assert s.util_percent is None
    assert s.temp_c is None
    assert s.mem_used_mib == 500


def test_name_containing_comma():
    text = '2, GPU-c, "NVIDIA A100, PCIe 80GB", 4096, 81920, 12, 50\n'
    s = parse_query_output(text)[0]
    assert s.name == "NVIDIA A100, PCIe 80GB"
    assert s.index == 2
    assert s.mem_total_mib == 81920


def test_junk_lines_are_ignored():
    text = (
        "Welcome to Ubuntu 22.04 LTS\n"
        "Last login: Mon Oct 20 10:00:00 2026 from 10.0.0.1\n"
        "0, GPU-a, RTX 4090, 1000, 24000, 5, 40\n"
        "some trailing noise\n"
    )
    samples = parse_query_output(text)
    assert len(samples) == 1


def test_all_na_row_is_kept_with_none_values():
    text = "0, GPU-a, [N/A], [N/A], [N/A], [N/A], [N/A]\n"
    samples = parse_query_output(text)
    assert samples[0].mem_used_mib is None
    assert samples[0].used_percent is None
    assert samples[0].free_mib is None


def test_empty_output_raises():
    with pytest.raises(ProbeError, match="无法解析"):
        parse_query_output("")


def test_describe_failure_127():
    msg = describe_failure(127, "bash: nvidia-smi: command not found", "")
    assert "找不到 nvidia-smi" in msg


def test_describe_failure_124():
    msg = describe_failure(124, "", "")
    assert "超时" in msg


def test_describe_failure_other():
    msg = describe_failure(9, "NVIDIA-SMI has failed", "")
    assert "退出码 9" in msg
    assert "NVIDIA-SMI has failed" in msg


def test_build_command_quotes_path():
    cmd = build_command("/opt/my tools/nvidia-smi")
    assert "'/opt/my tools/nvidia-smi'" in cmd
    assert "LC_ALL=C" in cmd
    assert "timeout 15" in cmd
    assert "--format=csv,noheader,nounits" in cmd


def test_used_percent_none_when_invalid_total():
    from gpuwatch.gpu_probe import GpuSample

    s = GpuSample(0, "u", "RTX", 100, None, 0, 30)
    assert s.used_percent is None
    assert s.free_mib is None
