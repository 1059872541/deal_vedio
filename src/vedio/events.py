# -*- coding: utf-8 -*-
"""vedio.events —— 运行事件记录

两路输出，各管一头：

    人读：{批次}/log/{日期}.log      明文本，**追加**（旧实现用覆盖模式，跨运行没法对比）
    机器读：{批次}/log/events.jsonl   一行一个 JSON

为什么要机器可读的那份：回答"这次为什么比上次慢""哪个环节失败最多""换台电脑
会不会更慢"这类问题。旧代码把这些信息 print 到控制台就没了。

事件形态::

    {"ts": "2026-11-07T23:41:02", "verb": "splice", "event": "start",
     "collection": "合集一"}
    {"ts": "2026-11-07T23:41:44", "verb": "splice", "event": "done",
     "collection": "合集一", "seconds": 42.1, "mode": "copy", "outputs": 20}
    {"ts": "2026-11-08T00:12:07", "verb": "export", "event": "fail",
     "collection": "合集二", "error": "draft_not_found", "seconds": 3.2}

用法::

    log = EventLog(project.log_dir)
    with log.step("export", "合集一"):
        do_the_work()                # 正常返回 → done；抛异常 → fail 后重新抛
    log.emit("export", "skip", "合集二", reason="还没审字幕")
"""

from __future__ import annotations

import json
import re
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional, TextIO

#: 机器读的事件文件名
EVENTS_FILE = "events.jsonl"

#: 事件类型
START = "start"
DONE = "done"
FAIL = "fail"
SKIP = "skip"
INFO = "info"

#: ANSI 颜色控制符。structlog 的 ConsoleRenderer 会带颜色，写进文件后是乱码，落盘前剥掉
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


class _Tee:
    """把写入同时送到原流和日志文件。

    为什么要在这一层做，而不是去改旧模块的 print：
    模型是**流式输出**的（`print(chunk, end="", flush=True)`），那些字符
    根本没经过 structlog，改日志库抓不到。只有替换 `sys.stdout` 才能全收。
    顺带把 structlog、traceback、第三方库的 print 一起收进来。
    """

    def __init__(self, stream: TextIO, handle: TextIO) -> None:
        self._stream = stream
        self._handle = handle

    def write(self, data: str) -> int:
        try:
            self._handle.write(_strip_ansi(data))
            self._handle.flush()          # 崩了也要留下崩之前的输出，所以每写必 flush
        except (OSError, ValueError):
            pass
        return self._stream.write(data)

    def flush(self) -> None:
        try:
            self._handle.flush()
        except (OSError, ValueError):
            pass
        self._stream.flush()

    def __getattr__(self, item: str) -> Any:
        # 其余属性（encoding / isatty / fileno…）原样转给真流，
        # 免得子进程或库拿到会崩的替代品
        return getattr(self._stream, item)


def _iso(ts: Optional[float] = None) -> str:
    """本地时间 ISO 串，精确到秒（够用，且人眼好读）"""
    return datetime.fromtimestamp(time.time() if ts is None else ts).strftime("%Y-%m-%dT%H:%M:%S")


@dataclass
class Event:
    """一条运行事件"""

    verb: str
    event: str
    ts: str = ""
    collection: Optional[str] = None
    fields: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.ts:
            self.ts = _iso()

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"ts": self.ts, "verb": self.verb, "event": self.event}
        if self.collection:
            d["collection"] = self.collection
        d.update(self.fields)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        known = {"ts", "verb", "event", "collection"}
        extra = {k: v for k, v in data.items() if k not in known}
        return cls(
            verb=str(data.get("verb", "")),
            event=str(data.get("event", "")),
            ts=str(data.get("ts", "")) or _iso(),
            collection=data.get("collection") or None,
            fields=extra,
        )

    def __str__(self) -> str:
        parts = [self.ts, f"[{self.verb}]"]
        if self.collection:
            parts.append(self.collection)
        parts.append(self.event)
        if "seconds" in self.fields:
            parts.append(f"{self.fields['seconds']:.1f}s")
        if "error" in self.fields:
            parts.append(str(self.fields["error"]))
        if "message" in self.fields:
            parts.append(str(self.fields["message"]))
        return " ".join(parts)


class EventLog:
    """一个批次的运行记录器。

    Args:
        log_dir: `{批次}/log`。不存在会自动建。
        history_dir: 可选的跨批次累积目录。给了就把精简记录同时追加到
                     ``{history_dir}/events.jsonl``，用于跨批次对比。
        clock: 便于测试替换（返回秒级时间戳）。
    """

    def __init__(self, log_dir: Path, history_dir: Optional[Path] = None, clock=time.time) -> None:
        self.log_dir = Path(log_dir)
        self.history_dir = Path(history_dir) if history_dir else None
        self._clock = clock

    # ── 路径 ──

    @property
    def events_path(self) -> Path:
        return self.log_dir / EVENTS_FILE

    def human_path(self, ts: Optional[str] = None) -> Path:
        day = (ts or _iso(self._clock()))[:10]
        return self.log_dir / f"{day}.log"

    # ── 写 ──

    def emit(self, verb: str, event: str, collection: Optional[str] = None,
             **fields: Any) -> Event:
        """记一条事件（同时写人读日志和 JSONL）"""
        ev = Event(verb=verb, event=event, collection=collection, fields=fields)
        self._append_jsonl(ev)
        self._append_human(ev)
        self._append_history(ev)
        return ev

    def _append_jsonl(self, ev: Event) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(ev.as_dict(), ensure_ascii=False) + "\n")

    def _append_human(self, ev: Event) -> None:
        switch = {"start": "开始", "done": "完成", "fail": "失败", "skip": "跳过", "info": "信息"}
        line = f"{ev.ts.replace('T', ' ')}  {switch.get(ev.event, ev.event):<4}  {ev}"
        path = self.human_path(ev.ts)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(line + "\n")

    def _append_history(self, ev: Event) -> None:
        """精简记录：只留跨批次对比用得上的字段"""
        if self.history_dir is None:
            return
        slim = {k: ev.as_dict()[k] for k in ("ts", "verb", "event") if k in ev.as_dict()}
        for k in ("collection", "seconds", "error", "mode"):
            if k in ev.fields or (k == "collection" and ev.collection):
                slim[k] = ev.collection if k == "collection" else ev.fields.get(k)
        try:
            self.history_dir.mkdir(parents=True, exist_ok=True)
            with (self.history_dir / EVENTS_FILE).open("a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(slim, ensure_ascii=False) + "\n")
        except OSError:
            pass                     # 历史记录写不进去不该影响主流程

    @contextmanager
    def step(self, verb: str, collection: Optional[str] = None, **fields: Any) -> Iterator[Event]:
        """包一段工作，自动记录 start / done / fail（含耗时）。

        异常会被**原样重新抛出** —— 这个装饰器只负责记录，不负责吞错。
        """
        started = self._clock()
        self.emit(verb, START, collection, **fields)
        try:
            yield self
        except Exception as exc:
            self.emit(verb, FAIL, collection,
                      seconds=round(self._clock() - started, 1),
                      error=type(exc).__name__,
                      message=str(exc))
            raise
        else:
            self.emit(verb, DONE, collection,
                      seconds=round(self._clock() - started, 1), **fields)

    @contextmanager
    def capture(self, name: str, collection: Optional[str] = None) -> Iterator[Path]:
        """把这段工作里的 stdout / stderr 原样存到文件。

        给"会自己 print 一堆东西"的旧代码用：剪映控制器、LangGraph agent、
        流式输出的模型回复。它们的输出去不了 `events.jsonl`（那是结构化的），
        又不能不存 —— 出问题时唯一能看的就是它。

        Yields:
            日志文件路径（调用方把它写进事件里，方便日后回看）
        """
        stamp = datetime.fromtimestamp(self._clock()).strftime("%Y%m%d-%H%M%S")
        label = f"{name}-{collection}" if collection else name
        path = self.log_dir / f"{label}-{stamp}.log"
        self.log_dir.mkdir(parents=True, exist_ok=True)

        handle = path.open("a", encoding="utf-8", newline="\n")
        old_out, old_err = sys.stdout, sys.stderr
        try:
            sys.stdout = _Tee(old_out, handle)
            sys.stderr = _Tee(old_err, handle)
            yield path
        finally:
            sys.stdout, sys.stderr = old_out, old_err
            handle.close()

    # ── 读 ──

    def read(self) -> list[Event]:
        return read_events(self.events_path)

    def last(self, verb: Optional[str] = None,
             collection: Optional[str] = None,
             event: Optional[str] = None) -> Optional[Event]:
        """最近一条匹配的事件（status 用它判断"做到哪了"）"""
        for ev in reversed(self.read()):
            if verb is not None and ev.verb != verb:
                continue
            if collection is not None and ev.collection != collection:
                continue
            if event is not None and ev.event != event:
                continue
            return ev
        return None

    def failed(self) -> list[Event]:
        return [e for e in self.read() if e.event == FAIL]


# ─────────────────────────── 模块级工具 ───────────────────────────

def read_events(path: Path) -> list[Event]:
    """读 JSONL；坏行跳过（后缀写一半也不能让 status 崩掉）"""
    path = Path(path)
    if not path.is_file():
        return []
    out: list[Event] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                out.append(Event.from_dict(data))
    return out


def summarize(events: list[Event]) -> dict[str, dict[str, Any]]:
    """按 verb 汇总：次数 / 成功 / 失败 / 总耗时 / 平均耗时。

    只统计 done 事件的 seconds —— fail 事件的耗时没参考价值（多半是秒级超时）。
    """
    stats: dict[str, dict[str, Any]] = {}
    for ev in events:
        s = stats.setdefault(ev.verb, {"count": 0, "done": 0, "fail": 0, "seconds": 0.0, "samples": 0})
        s["count"] += 1
        if ev.event == DONE:
            s["done"] += 1
            sec = ev.fields.get("seconds")
            if isinstance(sec, (int, float)):
                s["seconds"] += float(sec)
                s["samples"] += 1
        elif ev.event == FAIL:
            s["fail"] += 1
    for s in stats.values():
        s["avg_seconds"] = round(s["seconds"] / s["samples"], 1) if s["samples"] else None
        s["seconds"] = round(s["seconds"], 1)
    return stats


# ─────────────────────────── 日志文件（capture 的产物） ───────────────────────────

@dataclass
class LogFile:
    """`log/` 下的一个日志文件"""

    path: Path
    size: int
    modified: str

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.path.name, "size": self.size,
                "modified": self.modified, "path": str(self.path)}


def list_logs(log_dir: Path, keyword: Optional[str] = None) -> list[LogFile]:
    """列出 `log/` 下的日志文件，**最新的在前**。

    Args:
        keyword: 文件名里要包含的子串，如合集名 `合集一`；None = 全部
    """
    d = Path(log_dir)
    if not d.is_dir():
        return []
    out: list[LogFile] = []
    for p in d.iterdir():
        if not p.is_file():
            continue
        if keyword and keyword not in p.name:
            continue
        try:
            stat = p.stat()
        except OSError:
            continue
        out.append(LogFile(
            path=p, size=stat.st_size,
            modified=datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        ))
    out.sort(key=lambda f: f.path.stat().st_mtime, reverse=True)
    return out


def tail_log(path: Path, lines: int = 40) -> str:
    """读日志最后 N 行。

    用 `errors="replace"` 读 —— 日志里可能混进编码错乱的字节（子进程输出、
    剪贴板内容），不能让看日志本身失败。
    """
    p = Path(path)
    if not p.is_file():
        return ""
    text = p.read_text(encoding="utf-8", errors="replace")
    rows = text.splitlines()
    return "\n".join(rows[-lines:]) if lines > 0 else ""
