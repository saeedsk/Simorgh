"""Streaming log entry parser and schema normalizer."""

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Iterator, List, Optional, Union

LEVEL_MAP: Dict[str, str] = {
    "CRITICAL": "CRITICAL",
    "CRIT": "CRITICAL",
    "FATAL": "CRITICAL",
    "EMERGENCY": "CRITICAL",
    "EMERG": "CRITICAL",
    "ALERT": "CRITICAL",
    "PANIC": "CRITICAL",
    "ERROR": "ERROR",
    "ERR": "ERROR",
    "EROR": "ERROR",
    "SEVERE": "ERROR",
    "WARNING": "WARNING",
    "WARN": "WARNING",
    "WRN": "WARNING",
    "INFO": "INFO",
    "INF": "INFO",
    "INFORMATIONAL": "INFO",
    "NOTICE": "INFO",
    "NOTE": "INFO",
    "DEBUG": "DEBUG",
    "DBG": "DEBUG",
    "TRACE": "DEBUG",
    "VERBOSE": "DEBUG",
}

CLF_PATTERN = re.compile(
    r'^(\S+)\s+(\S+)\s+(\S+)\s+\[([^\]]+)\]\s+"([A-Z]+)\s+([^\s"]*)(?:\s+([^"]+))?"\s+(\d{3}|-)\s+(\d+|-)(?:\s+"([^"]*)"\s+"([^"]*)")?'
)

RFC5424_PATTERN = re.compile(
    r'^<(\d{1,3})>1\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)(?:\s+(-|\[.*?\](?:\[.*?\])*))?(?:\s+(.*))?$'
)

RFC3164_PATTERN = re.compile(
    r'^(?:<(\d{1,3})>)?([A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+(\S+)\s+([^:\[\s]+)(?:\[(\d+)\])?:\s*(.*)$'
)

GENERIC_TS_PATTERN = re.compile(
    r'^\[?(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\]?\s*(.*)$'
)

LOGFMT_PAIR_PATTERN = re.compile(
    r'([a-zA-Z0-9_\-.]+)=(?:"((?:\\.|[^"\\])*)"|(\S+))'
)

RFC5424_SD_PATTERN = re.compile(r'\[([^\[\]]+)\]')
RFC5424_PARAM_PATTERN = re.compile(r'([^=\s]+)="((?:\\.|[^"\\])*)"')


def normalize_level(level: Any) -> str:
    """Normalize various log level representations into a canonical uppercase level."""
    if level is None:
        return "UNKNOWN"
    if isinstance(level, int):
        if level in (0, 1, 2) or level >= 50:
            return "CRITICAL"
        if level == 3 or (40 <= level < 50):
            return "ERROR"
        if level == 4 or (30 <= level < 40):
            return "WARNING"
        if level in (5, 6) or (20 <= level < 30):
            return "INFO"
        if level == 7 or (10 <= level < 20):
            return "DEBUG"
        return "UNKNOWN"
    s = str(level).strip("[](): \t\n\r").upper()
    return LEVEL_MAP.get(s, "UNKNOWN")


def normalize_timestamp(val: Any, default_year: Optional[int] = None) -> Optional[str]:
    """Normalize integer, float, or string timestamps into ISO 8601 UTC representation."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        num = float(val)
        if num > 1e16:
            num /= 1e9
        elif num > 1e13:
            num /= 1e6
        elif num > 1e10:
            num /= 1e3
        try:
            dt = datetime.fromtimestamp(num, tz=timezone.utc)
            return dt.isoformat().replace("+00:00", "Z")
        except (ValueError, OverflowError, OSError):
            return None

    val_str = str(val).strip()
    if not val_str:
        return None

    if re.match(r'^-?\d+(\.\d+)?$', val_str):
        try:
            return normalize_timestamp(float(val_str), default_year)
        except ValueError:
            pass

    s = val_str.replace(',', '.')

    # Common Log Format: DD/Mon/YYYY:HH:MM:SS +ZZZZ
    try:
        dt = datetime.strptime(s, "%d/%b/%Y:%H:%M:%S %z")
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        pass

    # BSD Syslog format: Mon DD HH:MM:SS
    for fmt in ("%b %d %H:%M:%S", "%b  %d %H:%M:%S", "%b %d %H:%M:%S.%f", "%b  %d %H:%M:%S.%f"):
        try:
            dt = datetime.strptime(s, fmt)
            year = default_year or datetime.now(timezone.utc).year
            dt = dt.replace(year=year, tzinfo=timezone.utc)
            return dt.isoformat().replace("+00:00", "Z")
        except ValueError:
            pass

    # ISO 8601 variations
    iso_candidate = s
    if iso_candidate.endswith("Z"):
        iso_candidate = iso_candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(iso_candidate)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
    except ValueError:
        pass

    return None


def coerce_scalar(val: str) -> Any:
    """Convert unquoted scalar strings to int, float, bool, None, or string."""
    if val is None:
        return None
    low = val.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "none", "nil"):
        return None
    if re.match(r'^-?\d+$', val):
        try:
            return int(val)
        except ValueError:
            pass
    if re.match(r'^-?\d+\.\d+$', val):
        try:
            return float(val)
        except ValueError:
            pass
    return val


def parse_logfmt_string(s: str) -> Dict[str, Any]:
    """Extract key-value pairs from a logfmt formatted string."""
    res = {}
    for match in LOGFMT_PAIR_PATTERN.finditer(s):
        k = match.group(1)
        if match.group(2) is not None:
            v = re.sub(r'\\(.)', r'\1', match.group(2))
        else:
            v = match.group(3)
        res[k] = coerce_scalar(v)
    return res


def parse_rfc5424_sd(sd_text: str) -> Dict[str, Dict[str, str]]:
    """Parse structured data elements from RFC 5424 syslog."""
    if not sd_text or sd_text == "-":
        return {}
    sd_dict = {}
    for match in RFC5424_SD_PATTERN.finditer(sd_text):
        content = match.group(1).strip()
        parts = content.split(None, 1)
        if not parts:
            continue
        sd_id = parts[0]
        params = {}
        if len(parts) > 1:
            for p in RFC5424_PARAM_PATTERN.finditer(parts[1]):
                params[p.group(1)] = re.sub(r'\\(.)', r'\1', p.group(2))
        sd_dict[sd_id] = params
    return sd_dict


def _normalize_dict(d: dict, raw: str = "", default_year: Optional[int] = None) -> dict:
    """Normalize a dictionary of attributes into the canonical schema."""
    d_copy = dict(d)

    raw_ts = None
    for k in ("@timestamp", "timestamp", "time", "ts", "datetime", "date", "created_at", "asctime"):
        if k in d_copy:
            raw_ts = d_copy.pop(k)
            break
    norm_ts = normalize_timestamp(raw_ts, default_year)

    raw_lvl = None
    for k in ("level", "severity", "log_level", "lvl", "priority"):
        if k in d_copy:
            raw_lvl = d_copy.pop(k)
            break
    norm_lvl = normalize_level(raw_lvl)

    msg = None
    for k in ("message", "msg", "log", "description", "event", "text"):
        if k in d_copy:
            msg = d_copy.pop(k)
            break
    if msg is None:
        if "error" in d_copy and isinstance(d_copy["error"], str):
            msg = d_copy.pop("error")
        else:
            msg = ""

    service = None
    for k in ("service", "service_name", "app", "application", "logger", "logger_name", "component"):
        if k in d_copy:
            val = d_copy.pop(k)
            if val is not None:
                service = str(val)
            break

    source = None
    for k in ("source", "host", "hostname", "ip", "client_ip", "caller"):
        if k in d_copy:
            val = d_copy.pop(k)
            if val is not None:
                source = str(val)
            break

    return {
        "timestamp": norm_ts,
        "level": norm_lvl,
        "message": str(msg) if msg is not None else "",
        "service": service,
        "source": source,
        "attributes": d_copy,
        "raw": raw or json.dumps(d)
    }


def _parse_json(text: str, default_year: Optional[int] = None) -> Optional[dict]:
    s = text.strip()
    if not (s.startswith("{") and s.endswith("}")):
        return None
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return _normalize_dict(obj, raw=text, default_year=default_year)
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _parse_clf(line: str, default_year: Optional[int] = None) -> Optional[dict]:
    m = CLF_PATTERN.match(line)
    if not m:
        return None
    host, ident, auth, raw_ts, method, path, proto, status_str, bytes_str, ref, ua = m.groups()
    norm_ts = normalize_timestamp(raw_ts, default_year)
    status_code = int(status_str) if status_str.isdigit() else None
    bytes_sent = int(bytes_str) if bytes_str.isdigit() else (0 if bytes_str == '-' else None)

    if status_code is not None:
        if status_code >= 500:
            level = "ERROR"
        elif status_code >= 400:
            level = "WARNING"
        else:
            level = "INFO"
    else:
        level = "INFO"

    proto_str = f" {proto}" if proto else ""
    message = f"{method} {path}{proto_str}"
    if status_code is not None:
        message += f" {status_code}"

    attributes = {
        "http_method": method,
        "http_path": path,
    }
    if proto:
        attributes["http_proto"] = proto
    if status_code is not None:
        attributes["http_status"] = status_code
    if bytes_sent is not None:
        attributes["bytes_sent"] = bytes_sent
    if ident and ident != "-":
        attributes["ident"] = ident
    if auth and auth != "-":
        attributes["auth_user"] = auth
    if ref and ref != "-":
        attributes["referrer"] = ref
    if ua and ua != "-":
        attributes["user_agent"] = ua

    return {
        "timestamp": norm_ts,
        "level": level,
        "message": message,
        "service": "http",
        "source": host if host != "-" else None,
        "attributes": attributes,
        "raw": line
    }


def _parse_syslog_5424(line: str, default_year: Optional[int] = None) -> Optional[dict]:
    m = RFC5424_PATTERN.match(line)
    if not m:
        return None
    prival_str, ts_str, host, app, procid, msgid, sd_str, msg = m.groups()
    prival = int(prival_str)
    facility = prival // 8
    severity = prival % 8
    level = normalize_level(severity)
    norm_ts = normalize_timestamp(ts_str, default_year) if ts_str != "-" else None

    attributes = {"facility": facility}
    if procid and procid != "-":
        attributes["proc_id"] = procid
    if msgid and msgid != "-":
        attributes["msg_id"] = msgid
    if sd_str and sd_str != "-":
        sd_data = parse_rfc5424_sd(sd_str)
        if sd_data:
            attributes["structured_data"] = sd_data

    return {
        "timestamp": norm_ts,
        "level": level,
        "message": (msg or "").strip(),
        "service": app if app != "-" else None,
        "source": host if host != "-" else None,
        "attributes": attributes,
        "raw": line
    }


def _parse_syslog_3164(line: str, default_year: Optional[int] = None) -> Optional[dict]:
    m = RFC3164_PATTERN.match(line)
    if not m:
        return None
    prival_str, ts_str, host, tag, pid_str, msg = m.groups()
    norm_ts = normalize_timestamp(ts_str, default_year)
    attributes = {}
    if prival_str is not None:
        prival = int(prival_str)
        facility = prival // 8
        severity = prival % 8
        level = normalize_level(severity)
        attributes["facility"] = facility
    else:
        level = "INFO"

    if pid_str:
        try:
            attributes["pid"] = int(pid_str)
        except ValueError:
            attributes["pid"] = pid_str

    return {
        "timestamp": norm_ts,
        "level": level,
        "message": msg.strip(),
        "service": tag if tag != "-" else None,
        "source": host if host != "-" else None,
        "attributes": attributes,
        "raw": line
    }


def _parse_logfmt(line: str, default_year: Optional[int] = None) -> Optional[dict]:
    pairs = parse_logfmt_string(line)
    if len(pairs) >= 2 or (len(pairs) == 1 and any(k in pairs for k in ("level", "lvl", "msg", "ts", "time"))):
        return _normalize_dict(pairs, raw=line, default_year=default_year)
    return None


def _parse_timestamped(line: str, default_year: Optional[int] = None) -> Optional[dict]:
    m = GENERIC_TS_PATTERN.match(line)
    if not m:
        return None
    raw_ts, rest = m.groups()
    norm_ts = normalize_timestamp(raw_ts, default_year)

    levels = {
        "DEBUG", "INFO", "WARN", "WARNING", "ERROR", "CRIT", "CRITICAL", "FATAL", "TRACE",
        "NOTICE", "ALERT", "EMERG", "EMERGENCY"
    }

    level = "UNKNOWN"
    service = None
    msg = rest.strip()

    dash_parts = [p.strip() for p in rest.lstrip(" -|:").split(" - ") if p.strip()]
    if len(dash_parts) >= 3:
        if dash_parts[1].upper() in levels:
            level = normalize_level(dash_parts[1])
            service = dash_parts[0]
            msg = " - ".join(dash_parts[2:])
        elif dash_parts[0].upper() in levels:
            level = normalize_level(dash_parts[0])
            service = dash_parts[1]
            msg = " - ".join(dash_parts[2:])
    elif len(dash_parts) == 2 and dash_parts[0].upper() in levels:
        level = normalize_level(dash_parts[0])
        msg = dash_parts[1]
    else:
        m2 = re.match(r'^([A-Za-z]+):([a-zA-Z0-9_.-]+):(.*)$', rest.strip())
        if m2 and m2.group(1).upper() in levels:
            level = normalize_level(m2.group(1))
            service = m2.group(2)
            msg = m2.group(3).strip()
        else:
            curr = rest.strip()
            tokens = []
            while curr:
                curr = curr.lstrip(" -|:")
                bm = re.match(r'^[\[\(]([^\s\]\)]+)[\]\)]\s*(.*)$', curr)
                if bm:
                    tokens.append(bm.group(1))
                    curr = bm.group(2)
                    continue
                wm = re.match(r'^([A-Za-z0-9_.-]+)(?::|\s+)\s*(.*)$', curr)
                if wm:
                    tok = wm.group(1)
                    if tok.upper() in levels or (tokens and tokens[0].upper() in levels):
                        tokens.append(tok)
                        curr = wm.group(2)
                        continue
                break
            for t in tokens:
                if level == "UNKNOWN" and t.upper() in levels:
                    level = normalize_level(t)
                elif service is None:
                    service = t
            msg = curr.lstrip(" -|:").strip()

    attributes = {}
    if "=" in msg:
        embedded_pairs = parse_logfmt_string(msg)
        if len(embedded_pairs) >= 1:
            attributes.update(embedded_pairs)

    return {
        "timestamp": norm_ts,
        "level": level,
        "message": msg,
        "service": service,
        "source": None,
        "attributes": attributes,
        "raw": line
    }


def _parse_fallback(line: str) -> dict:
    return {
        "timestamp": None,
        "level": "UNKNOWN",
        "message": line,
        "service": None,
        "source": None,
        "attributes": {},
        "raw": line
    }


def normalize_log(
    entry: Union[str, bytes, dict],
    format: str = "auto",
    default_year: Optional[int] = None
) -> dict:
    """Parse a single log entry and normalize it to the unified schema."""
    if isinstance(entry, dict):
        return _normalize_dict(entry, default_year=default_year)
    if isinstance(entry, bytes):
        entry = entry.decode("utf-8", errors="replace")

    line = entry.rstrip("\r\n")
    fmt = format.lower()

    if fmt == "json":
        res = _parse_json(line, default_year)
        return res if res is not None else _parse_fallback(line)
    elif fmt in ("syslog_rfc5424", "rfc5424", "syslog5424"):
        res = _parse_syslog_5424(line, default_year)
        return res if res is not None else _parse_fallback(line)
    elif fmt in ("syslog_rfc3164", "rfc3164", "syslog3164", "syslog"):
        res = _parse_syslog_3164(line, default_year)
        return res if res is not None else _parse_fallback(line)
    elif fmt in ("clf", "combined", "common", "apache", "nginx"):
        res = _parse_clf(line, default_year)
        return res if res is not None else _parse_fallback(line)
    elif fmt in ("logfmt", "keyvalue", "kv"):
        res = _parse_logfmt(line, default_year)
        return res if res is not None else _parse_fallback(line)
    elif fmt in ("timestamped", "generic", "standard"):
        res = _parse_timestamped(line, default_year)
        return res if res is not None else _parse_fallback(line)
    elif fmt == "auto":
        s = line.strip()
        if s.startswith("{") and s.endswith("}"):
            res = _parse_json(line, default_year)
            if res is not None:
                return res
        if s.startswith("<") and re.match(r'^<\d{1,3}>1\s', s):
            res = _parse_syslog_5424(line, default_year)
            if res is not None:
                return res
        if CLF_PATTERN.match(line):
            res = _parse_clf(line, default_year)
            if res is not None:
                return res
        if RFC3164_PATTERN.match(line):
            res = _parse_syslog_3164(line, default_year)
            if res is not None:
                return res
        if GENERIC_TS_PATTERN.match(line):
            res = _parse_timestamped(line, default_year)
            if res is not None:
                return res
        if LOGFMT_PAIR_PATTERN.search(line):
            res = _parse_logfmt(line, default_year)
            if res is not None:
                return res
        return _parse_fallback(line)
    else:
        raise ValueError(f"Unknown format: {format}")


parse_entry = normalize_log


class LogStreamNormalizer:
    """Stateful streaming log parser with multi-line traceback and block support."""

    def __init__(
        self,
        format: str = "auto",
        multiline: bool = True,
        default_year: Optional[int] = None
    ):
        self.format = format
        self.multiline = multiline
        self.default_year = default_year
        self._buffer: List[str] = []

    def parse_entry(self, entry: Union[str, bytes, dict]) -> dict:
        return normalize_log(entry, format=self.format, default_year=self.default_year)

    def _should_continue(self, next_line: str) -> bool:
        if not self._buffer:
            return False
        s = next_line.strip()
        if not s:
            return True

        if next_line.startswith((' ', '\t')):
            return True

        if s.startswith(('Traceback (most recent call last):', 'Caused by:', '... ', 'at ', 'During handling of the above exception')):
            return True

        joined = "\n".join(self._buffer)
        if joined.lstrip().startswith(('{', '[')):
            open_c = joined.count('{') - joined.count('}')
            open_b = joined.count('[') - joined.count(']')
            if open_c > 0 or open_b > 0:
                return True

        last_line = self._buffer[-1]
        has_tb = any("Traceback (most recent call last):" in bl for bl in self._buffer)
        if has_tb and last_line.startswith((' ', '\t')):
            return True

        return False

    def _flush_buffer(self) -> Optional[dict]:
        if not self._buffer:
            return None
        lines = self._buffer
        self._buffer = []

        full_text = "\n".join(lines)
        if len(lines) == 1:
            return self.parse_entry(lines[0])

        if lines[0].lstrip().startswith(('{', '[')):
            try:
                parsed = json.loads(full_text)
                if isinstance(parsed, dict):
                    return _normalize_dict(parsed, raw=full_text, default_year=self.default_year)
            except (json.JSONDecodeError, ValueError):
                pass

        record = self.parse_entry(lines[0])
        continuation = "\n".join(lines[1:])
        record["raw"] = full_text
        record["message"] = (record["message"] + "\n" + continuation).strip()

        if "Traceback (most recent call last):" in continuation or any(l.startswith((' ', '\t')) for l in lines[1:]):
            record["attributes"]["stack_trace"] = continuation

        return record

    def feed(self, line: Union[str, bytes]) -> Iterator[dict]:
        """Feed a single line into the normalizer and yield any completed records."""
        if isinstance(line, bytes):
            line = line.decode("utf-8", errors="replace")
        line = line.rstrip("\r\n")

        if not self.multiline:
            if line.strip():
                yield self.parse_entry(line)
            return

        if not self._buffer:
            if line.strip():
                self._buffer.append(line)
            return

        if self._should_continue(line):
            self._buffer.append(line)
        else:
            rec = self._flush_buffer()
            if rec:
                yield rec
            if line.strip():
                self._buffer.append(line)

    def flush(self) -> Iterator[dict]:
        """Flush any buffered log entry remaining at end of stream."""
        rec = self._flush_buffer()
        if rec:
            yield rec


def parse_stream(
    stream: Union[Iterable[Union[str, bytes]], str, bytes],
    format: str = "auto",
    multiline: bool = True,
    default_year: Optional[int] = None
) -> Iterator[dict]:
    """Parse a stream of log lines, yielding schema-normalized log records."""
    if isinstance(stream, (str, bytes)):
        if isinstance(stream, bytes):
            stream = stream.decode("utf-8", errors="replace")
        stream = stream.splitlines(keepends=True)

    normalizer = LogStreamNormalizer(
        format=format,
        multiline=multiline,
        default_year=default_year
    )
    for chunk in stream:
        yield from normalizer.feed(chunk)
    yield from normalizer.flush()