"""The right-hand column of the split screen: boxes stacked top to bottom.

The creator, 2026-10-30: "a right side box that can later get split in
vertical boxes, showing different data -- first box on top shows cpu
usage, gpu history, cpu core usage history; second box memory usage and
cpu use in numbers; 3rd box and so forth for parallel agents, a small
window showing their input; a key and tab to switch between these windows
and make them full size."

A box is anything with a `title` and `render(width, height)` returning
prompt_toolkit-style fragments `[(style, text), ...]`. Nothing here imports
prompt_toolkit: the boxes are plain data and plain text, testable without a
terminal, and `splitscreen.py` frames them.

Readings are real or absent, never invented (the same rule as `vitals.py`):
CPU and memory come from `psutil` when it is installed -- an optional
package, like prompt_toolkit itself -- and the GPU from macOS's own
`ioreg` (`IOAccelerator` "Device Utilization %", no sudo). macOS reports
the GPU as a whole, not per core, so the GPU row is one history, with the
core count beside it. A source that is missing says so in the box.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass, field

#: Samples kept per series: one a second, so a minute of history.
HISTORY = 60
_BLOCKS = "▁▂▃▄▅▆▇█"
_GPU_UTIL = re.compile(r'"Device Utilization %"\s*=\s*(\d+)')
_GPU_CORES = re.compile(r'"gpu-core-count"\s*=\s*(\d+)')


def spark(values, *, width: int, top: float = 100.0) -> str:
    """The last `width` values as block characters, 0..`top`; padded on the
    left with spaces while the history is still filling."""
    tail = list(values)[-width:] if width > 0 else []
    chars = []
    for v in tail:
        frac = 0.0 if top <= 0 else max(0.0, min(1.0, float(v) / top))
        chars.append(_BLOCKS[min(len(_BLOCKS) - 1, int(round(frac * (len(_BLOCKS) - 1))))])
    return " " * max(0, width - len(chars)) + "".join(chars)


def heat(value: float) -> str:
    """The style class for a percentage: calm, busy, hot."""
    return "class:side.hot" if value >= 85 else "class:side.busy" if value >= 50 else "class:side.calm"


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f}{unit}" if unit in ("B", "KB", "MB") else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


@dataclass
class Readings:
    """What the sampler last saw, plus the history behind each series."""
    cpu: deque = field(default_factory=lambda: deque(maxlen=HISTORY))
    cores: list[deque] = field(default_factory=list)
    gpu: deque = field(default_factory=lambda: deque(maxlen=HISTORY))
    gpu_cores: int | None = None
    mem_used: float | None = None
    mem_total: float | None = None
    swap_used: float | None = None
    sim_cpu: float | None = None
    sim_rss: float | None = None
    load: tuple[float, float, float] | None = None
    #: Why a source is absent, by name: shown in the box rather than zeros.
    missing: dict[str, str] = field(default_factory=dict)
    sampled_at: float = 0.0


class SystemSampler:
    """Samples CPU (overall and per core), memory, this process, and the
    GPU. `sample()` is cheap and synchronous except the GPU read, which
    runs `ioreg` and so is taken at most every `gpu_every_s`."""

    def __init__(self, *, psutil_module=None, run=subprocess.run, platform: str = sys.platform,
                 gpu_every_s: float = 2.0, clock=time.monotonic) -> None:
        if psutil_module is None:
            try:
                import psutil as psutil_module  # optional, like prompt_toolkit
            except ImportError:
                psutil_module = None
        self._ps = psutil_module
        self._run = run
        self._platform = platform
        self._gpu_every_s = gpu_every_s
        self._clock = clock
        self._gpu_at = -1e9
        self._proc = None
        self.readings = Readings()
        if self._ps is None:
            self.readings.missing["cpu"] = "psutil is not installed (pip install psutil)"
        else:
            self._ps.cpu_percent(percpu=True)        # the first call only primes the counters
            self._proc = self._ps.Process(os.getpid())
            self._proc.cpu_percent()
        if platform != "darwin":
            self.readings.missing["gpu"] = "GPU use is read on macOS only"

    def sample(self) -> Readings:
        r = self.readings
        r.sampled_at = self._clock()
        if self._ps is not None:
            per_core = list(self._ps.cpu_percent(percpu=True))
            while len(r.cores) < len(per_core):
                r.cores.append(deque(maxlen=HISTORY))
            for series, value in zip(r.cores, per_core):
                series.append(float(value))
            if per_core:
                r.cpu.append(sum(per_core) / len(per_core))
            mem = self._ps.virtual_memory()
            r.mem_used, r.mem_total = float(mem.total - mem.available), float(mem.total)
            try:
                r.swap_used = float(self._ps.swap_memory().used)
            except Exception:  # noqa: BLE001 -- some sandboxes refuse it
                r.swap_used = None
            try:
                r.sim_cpu = float(self._proc.cpu_percent())
                r.sim_rss = float(self._proc.memory_info().rss)
            except Exception:  # noqa: BLE001 -- the process table is not always readable
                r.sim_cpu = r.sim_rss = None
        try:
            r.load = os.getloadavg()
        except (AttributeError, OSError):
            r.load = None
        if self._platform == "darwin" and r.sampled_at - self._gpu_at >= self._gpu_every_s:
            self._gpu_at = r.sampled_at
            self._sample_gpu(r)
        return r

    def _sample_gpu(self, r: Readings) -> None:
        try:
            done = self._run(["ioreg", "-r", "-d", "1", "-c", "IOAccelerator"], capture_output=True,
                             text=True, timeout=2.0)
            text = done.stdout or ""
        except Exception as exc:  # noqa: BLE001 -- no ioreg, a timeout: the box says so
            r.missing["gpu"] = f"ioreg failed: {exc.__class__.__name__}"
            return
        util = _GPU_UTIL.search(text)
        if util is None:
            r.missing["gpu"] = "ioreg reports no GPU utilization here"
            return
        r.missing.pop("gpu", None)
        r.gpu.append(float(util.group(1)))
        cores = _GPU_CORES.search(text)
        if cores is not None:
            r.gpu_cores = int(cores.group(1))


# -- the boxes ----------------------------------------------------------------------------------


class ProcessorBox:
    """Box 1: CPU overall and per core, and the GPU, as one-minute histories."""

    title = "CPU · GPU"

    def __init__(self, sampler: SystemSampler) -> None:
        self._sampler = sampler

    def render(self, width: int, height: int) -> list[tuple[str, str]]:
        r = self._sampler.readings
        out: list[tuple[str, str]] = []
        label_w, tail_w = 5, 5
        spark_w = max(4, width - label_w - tail_w - 1)

        def row(label: str, series, *, extra: str = "") -> None:
            now = series[-1] if series else 0.0
            graph = spark(series, width=max(4, spark_w - len(extra)))
            out.extend([("class:side.label", f"{label:<{label_w}}"), (heat(now), graph),
                        ("class:side.value", f"{now:>4.0f}%"), ("class:side.dim", extra), ("", "\n")])

        if "cpu" in r.missing:
            out.append(("class:side.dim", r.missing["cpu"] + "\n"))
        else:
            row("cpu", r.cpu)
            # As many cores as the box has rows for, after the cpu, gpu and spacer rows.
            room = max(0, height - 3)
            for i, series in enumerate(r.cores[:room]):
                row(f"c{i}", series)
            if len(r.cores) > room:
                out.append(("class:side.dim", f"  +{len(r.cores) - room} more cores (Ctrl-F: full size)\n"))
        if "gpu" in r.missing:
            out.append(("class:side.dim", f"gpu  {r.missing['gpu']}\n"))
        else:
            row("gpu", r.gpu, extra=f"  {r.gpu_cores} cores" if r.gpu_cores else "")
        return out


class MemoryBox:
    """Box 2: memory, swap, load, and Sim's own process, in numbers."""

    title = "Memory · numbers"

    def __init__(self, sampler: SystemSampler) -> None:
        self._sampler = sampler

    def render(self, width: int, height: int) -> list[tuple[str, str]]:
        r = self._sampler.readings
        if "cpu" in r.missing:
            return [("class:side.dim", r.missing["cpu"] + "\n")]
        out: list[tuple[str, str]] = []
        if r.mem_used is not None and r.mem_total:
            pct = 100.0 * r.mem_used / r.mem_total
            bar_w = max(4, width - 18)
            filled = int(round(bar_w * pct / 100.0))
            out += [("class:side.label", "RAM  "), (heat(pct), "█" * filled), ("class:side.dim", "░" * (bar_w - filled)),
                    ("class:side.value", f" {pct:3.0f}%\n"),
                    ("class:side.dim", f"     {human_bytes(r.mem_used)} of {human_bytes(r.mem_total)}\n")]
        if r.swap_used is not None:
            out += [("class:side.label", "swap "), ("class:side.value", f"{human_bytes(r.swap_used)}\n")]
        if r.cpu:
            out += [("class:side.label", "cpu  "), (heat(r.cpu[-1]), f"{r.cpu[-1]:.0f}%"),
                    ("class:side.dim", f"  of {len(r.cores)} cores\n")]
        if r.load is not None:
            out += [("class:side.label", "load "), ("class:side.value", "  ".join(f"{v:.2f}" for v in r.load)),
                    ("class:side.dim", "  1/5/15m\n")]
        if r.sim_rss is not None:
            out += [("class:side.label", "sim  "), ("class:side.value", f"{r.sim_cpu or 0:.0f}% cpu  "),
                    ("class:side.value", f"{human_bytes(r.sim_rss)}\n")]
        return out


@dataclass
class AgentFeed:
    """What one running task or crew member has done lately, for its box."""
    task_id: str
    title: str
    lines: deque = field(default_factory=lambda: deque(maxlen=200))
    started_at: float = field(default_factory=time.monotonic)
    now_doing: str = ""


class AgentBox:
    """Box 3 and on: one per running agent -- its newest lines, tail first
    in view, like a small terminal of its own."""

    def __init__(self, feed: AgentFeed) -> None:
        self.feed = feed

    @property
    def title(self) -> str:
        return self.feed.title

    def render(self, width: int, height: int) -> list[tuple[str, str]]:
        from .render import fit

        lines = list(self.feed.lines)
        room = max(1, height - (1 if self.feed.now_doing else 0))
        out: list[tuple[str, str]] = []
        for style, text in lines[-room:]:
            out += [(style, fit(" ".join(text.split()), width)), ("", "\n")]
        if self.feed.now_doing:
            out += [("class:side.now", fit("⏺ " + self.feed.now_doing, width)), ("", "\n")]
        if not out:
            out = [("class:side.dim", "starting…\n")]
        return out


class AgentFeeds:
    """The interface's view of what each running agent is doing, fed from
    `task.started` / `task.step` / the task's end. Finished agents leave
    their box after `linger_s`, so a result can still be read."""

    def __init__(self, *, linger_s: float = 20.0, clock=time.monotonic, limit: int = 8) -> None:
        self._feeds: dict[str, AgentFeed] = {}
        self._ended: dict[str, float] = {}
        self._linger_s = linger_s
        self._clock = clock
        self._limit = limit

    def started(self, task_id: str, title: str) -> None:
        if task_id not in self._feeds:
            self._feeds[task_id] = AgentFeed(task_id=task_id, title=title, started_at=self._clock())
        self._ended.pop(task_id, None)

    def step(self, task_id: str, *, tool: str | None, summary: str, ok: bool | None, title: str = "") -> None:
        feed = self._feeds.get(task_id)
        if feed is None:
            self.started(task_id, title or task_id[:8])
            feed = self._feeds[task_id]
        head = " ".join(str(summary or "").split())[:300]
        if ok is None:
            feed.now_doing = f"{tool}: {head}" if tool else head
            return
        feed.now_doing = ""
        mark, style = ("✓", "class:side.ok") if ok else ("✗", "class:side.bad")
        feed.lines.append((style, f"{mark} {tool + '  ' if tool else ''}{head}"))

    def ended(self, task_id: str, status: str, detail: str = "") -> None:
        feed = self._feeds.get(task_id)
        if feed is None:
            return
        feed.now_doing = ""
        icon = {"completed": "✅", "failed": "❌", "blocked": "⏸"}.get(status, "•")
        feed.lines.append(("class:side.end", f"{icon} {status}  {' '.join(str(detail or '').split())[:200]}"))
        self._ended[task_id] = self._clock()

    def boxes(self) -> list[AgentBox]:
        now = self._clock()
        for task_id, at in list(self._ended.items()):
            if now - at > self._linger_s:
                self._ended.pop(task_id, None)
                self._feeds.pop(task_id, None)
        live = sorted(self._feeds.values(), key=lambda f: f.started_at)[-self._limit:]
        return [AgentBox(f) for f in live]


__all__ = ["AgentBox", "AgentFeed", "AgentFeeds", "HISTORY", "MemoryBox", "ProcessorBox", "Readings",
           "SystemSampler", "heat", "human_bytes", "spark"]
