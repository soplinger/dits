#!/usr/bin/env python3
"""dits: an offline Morse code timing toolkit.

Plain-text plan files go in; exact ITU and Farnsworth timings, Morse text,
WAV audio and keying-trace grades come out. Standard library only, and the
code never touches the network. All timing is kept as Fraction seconds so
the numbers are exact until they are printed.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import wave
from array import array
from dataclasses import dataclass
from fractions import Fraction
from typing import Dict, List, Optional, Tuple

MORSE: Dict[str, str] = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.",
    "G": "--.", "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..",
    "M": "--", "N": "-.", "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.",
    "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.",
    ".": ".-.-.-", ",": "--..--", "?": "..--..", "'": ".----.", "/": "-..-.",
    "(": "-.--.", ")": "-.--.-", ":": "---...", ";": "-.-.-.", "=": "-...-",
    "+": ".-.-.", "-": "-....-", '"': ".-..-.", "@": ".--.-.",
}

# Prosigns are written in square brackets, e.g. "[SK]". Codes that clash with
# a punctuation mark (AR vs "+", BT vs "=", KN vs "(") are left out on purpose.
PROSIGNS: Dict[str, str] = {
    "SK": "...-.-", "AS": ".-...", "CT": "-.-.-", "BK": "-...-.-",
}

REVERSE: Dict[str, str] = {code: ch for ch, code in MORSE.items()}
REVERSE.update({code: f"[{name}]" for name, code in PROSIGNS.items()})

# ITU PARIS word: 31 element units, 4 inter-character gaps of 3 units and one
# word gap of 7 units, which makes 50 units in total. Farnsworth spacing
# stretches the 19 gap units, and keeps element timing at the character speed.
PARIS_ELEMENT_UNITS = 31
PARIS_GAP_UNITS = 19
DEFAULT_WPM = Fraction(20)
DEFAULT_TONE = 600
DEFAULT_TOLERANCE = Fraction(25, 100)


class MorseError(ValueError):
    """A bad character or code. ``column`` is 1-based within the text."""

    def __init__(self, message: str, column: Optional[int] = None):
        super().__init__(message)
        self.column = column


# ---------------------------------------------------------------- encoding

Word = List[Tuple[str, str]]  # (dot/dash code, label) for each letter


def _parse_words(text: str) -> List[Word]:
    """Split text into words of letters. Each letter is a (code, label) pair."""
    words: List[Word] = []
    current: Word = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isspace():
            if current:
                words.append(current)
                current = []
            i += 1
            continue
        if ch == "[":
            end = text.find("]", i)
            if end == -1:
                raise MorseError("unclosed prosign, missing ']'", i + 1)
            name = text[i + 1:end].strip().upper()
            if name not in PROSIGNS:
                raise MorseError(f"unknown prosign [{name}]", i + 1)
            current.append((PROSIGNS[name], f"[{name}]"))
            i = end + 1
            continue
        code = MORSE.get(ch.upper())
        if code is None:
            raise MorseError(f"unsupported character {ch!r}", i + 1)
        current.append((code, ch.upper()))
        i += 1
    if current:
        words.append(current)
    return words


def encode(text: str) -> str:
    """Morse for text: letters separated by spaces, words by ' / '."""
    return " / ".join(" ".join(code for code, _ in word) for word in _parse_words(text))


def decode(morse: str) -> str:
    """Text for Morse: letters separated by spaces, words by '/'."""
    if not morse.strip():
        return ""
    words = []
    for chunk in morse.strip().split("/"):
        letters = chunk.split()
        if not letters:
            raise MorseError("empty word between '/' separators")
        decoded = []
        for group in letters:
            label = REVERSE.get(group)
            if label is None:
                raise MorseError(f"unknown Morse group {group!r}")
            decoded.append(label)
        words.append("".join(decoded))
    return " ".join(words)


# ---------------------------------------------------------------- timing

@dataclass(frozen=True)
class Timing:
    """Every value is in seconds and kept exact."""

    wpm: Fraction
    effective: Fraction
    dit: Fraction
    element_gap: Fraction
    char_gap: Fraction
    word_gap: Fraction

    @property
    def dah(self) -> Fraction:
        return 3 * self.dit


def timing(wpm, effective=None) -> Timing:
    """Element and gap lengths for character speed ``wpm`` with optional
    Farnsworth effective speed ``effective`` (defaults to ``wpm``)."""
    wpm = Fraction(wpm)
    effective = wpm if effective is None else Fraction(effective)
    if wpm <= 0:
        raise ValueError("wpm must be positive")
    if effective <= 0:
        raise ValueError("effective speed must be positive")
    if effective > wpm:
        raise ValueError(f"effective speed ({_num(effective)}) cannot exceed wpm ({_num(wpm)})")
    dit = Fraction(6, 5) / wpm
    gap_unit = (Fraction(60) / effective - PARIS_ELEMENT_UNITS * dit) / PARIS_GAP_UNITS
    return Timing(wpm, effective, dit, dit, 3 * gap_unit, 7 * gap_unit)


def timeline(text: str, t: Timing) -> List[Tuple[bool, Fraction]]:
    """Key-down (True) and key-up (False) segments for text, in order."""
    segments: List[Tuple[bool, Fraction]] = []
    for wi, word in enumerate(_parse_words(text)):
        if wi:
            segments.append((False, t.word_gap))
        for li, (code, _) in enumerate(word):
            if li:
                segments.append((False, t.char_gap))
            for ei, element in enumerate(code):
                if ei:
                    segments.append((False, t.element_gap))
                segments.append((True, t.dit if element == "." else t.dah))
    return segments


def duration(text: str, t: Timing) -> Fraction:
    return sum((seconds for _, seconds in timeline(text, t)), Fraction(0))


def paris_word_seconds(t: Timing) -> Fraction:
    """PARIS plus its trailing word gap. Farnsworth sets this to 60 / effective."""
    return PARIS_ELEMENT_UNITS * t.dit + 4 * t.char_gap + t.word_gap


def cost_table(t: Timing) -> List[Tuple[str, Fraction]]:
    """Each supported character with its time on its own, slowest first."""
    rows = [(ch, duration(ch, t)) for ch in MORSE]
    return sorted(rows, key=lambda row: (-row[1], row[0]))


def summarize(text: str, t: Timing) -> dict:
    morse = encode(text)
    dots = morse.count(".")
    dashes = morse.count("-")
    return {
        "text": text,
        "morse": morse,
        "dots": dots,
        "dashes": dashes,
        "elements": dots + dashes,
        "seconds": float(duration(text, t)),
    }


def render_wav(path: str, text: str, t: Timing, tone_hz: int = DEFAULT_TONE,
               rate: int = 8000, ramp_ms: int = 5) -> float:
    """Write text as a mono 16-bit WAV tone. Returns the length in seconds."""
    ramp = max(1, rate * ramp_ms // 1000)
    samples = array("h")
    for key_down, seconds in timeline(text, t):
        n = round(seconds * rate)
        for i in range(n):
            if not key_down:
                samples.append(0)
                continue
            env = min(1.0, i / ramp, (n - 1 - i) / ramp)
            value = 0.6 * env * math.sin(2 * math.pi * tone_hz * i / rate)
            samples.append(int(32767 * value))
    if sys.byteorder == "big":
        samples.byteswap()
    with wave.open(path, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(samples.tobytes())
    return len(samples) / rate


# ---------------------------------------------------------------- plan files

@dataclass(frozen=True)
class LintError:
    line: int
    column: int
    message: str


@dataclass(frozen=True)
class Message:
    number: int
    line: int
    text: str


@dataclass(frozen=True)
class Plan:
    wpm: Fraction
    effective: Fraction
    tone: int
    messages: List[Message]


DIRECTIVES = ("wpm", "effective", "tone")


def parse_plan(source: str) -> Tuple[Plan, List[LintError]]:
    """Parse a plan file. Every problem becomes a LintError with its line and column.

    Lines are either blank, '# comment', 'wpm = 20', 'effective = 15',
    'tone = 600' or 'msg: TEXT'. Messages are numbered in file order, from 1.
    """
    errors: List[LintError] = []
    values: Dict[str, Tuple[int, str, int]] = {}
    messages: List[Message] = []
    number = 0
    for lineno, raw in enumerate(source.splitlines(), start=1):
        body = raw.lstrip()
        indent = len(raw) - len(body)
        if not body or body.startswith("#"):
            continue
        if body.startswith("msg:"):
            number += 1
            rest = body[4:]
            text = rest.strip()
            start = indent + 4 + (len(rest) - len(rest.lstrip())) + 1
            if not text:
                errors.append(LintError(lineno, start, "empty message"))
                continue
            try:
                _parse_words(text)
            except MorseError as exc:
                errors.append(LintError(lineno, start + (exc.column or 1) - 1, str(exc)))
                continue
            messages.append(Message(number, lineno, text))
            continue
        key, sep, value = body.partition("=")
        key = key.strip().lower()
        if not sep or key not in DIRECTIVES:
            errors.append(LintError(
                lineno, indent + 1,
                f"unknown directive {key!r}; expected wpm, effective, tone or msg:"))
            continue
        if key in values:
            errors.append(LintError(
                lineno, indent + 1,
                f"duplicate {key}, first set on line {values[key][0]}"))
            continue
        values[key] = (lineno, value.strip(), indent + 1)

    def number_value(key: str, default: Fraction) -> Fraction:
        if key not in values:
            return default
        lineno, raw_value, column = values[key]
        try:
            return Fraction(raw_value)
        except (ValueError, ZeroDivisionError):
            errors.append(LintError(lineno, column, f"{key} must be a number, got {raw_value!r}"))
            return default

    wpm = number_value("wpm", DEFAULT_WPM)
    effective = number_value("effective", wpm)
    tone = number_value("tone", Fraction(DEFAULT_TONE))
    if "wpm" in values and not (0 < wpm <= 100):
        errors.append(LintError(values["wpm"][0], values["wpm"][2], "wpm must be between 0 and 100"))
    if "effective" in values and not (0 < effective <= 100):
        errors.append(LintError(values["effective"][0], values["effective"][2],
                                "effective must be between 0 and 100"))
    if "effective" in values and effective > wpm:
        errors.append(LintError(
            values["effective"][0], values["effective"][2],
            f"effective ({_num(effective)}) cannot exceed wpm ({_num(wpm)})"))
    if "tone" in values and not (tone.denominator == 1 and 100 <= tone <= 4000):
        errors.append(LintError(values["tone"][0], values["tone"][2],
                                "tone must be a whole number of Hz from 100 to 4000"))
    errors.sort(key=lambda err: (err.line, err.column))
    return Plan(wpm, effective, int(tone), messages), errors


def parse_trace(source: str) -> Tuple[List[Tuple[int, Fraction]], List[LintError]]:
    """Keying trace: one key-down duration in milliseconds per line."""
    durations: List[Tuple[int, Fraction]] = []
    errors: List[LintError] = []
    for lineno, raw in enumerate(source.splitlines(), start=1):
        body = raw.strip()
        if not body or body.startswith("#"):
            continue
        try:
            ms = Fraction(body)
        except (ValueError, ZeroDivisionError):
            errors.append(LintError(lineno, 1, f"not a number of milliseconds: {body!r}"))
            continue
        if ms <= 0:
            errors.append(LintError(lineno, 1, "duration must be positive"))
            continue
        durations.append((lineno, ms / 1000))
    return durations, errors


# ---------------------------------------------------------------- grading

@dataclass(frozen=True)
class ElementGrade:
    index: int
    expected: str
    measured: Fraction
    ideal: Fraction
    symbol: str
    deviation: Fraction
    flagged: bool

    @property
    def ok(self) -> bool:
        return self.symbol == self.expected and not self.flagged


@dataclass(frozen=True)
class GradeReport:
    elements: List[ElementGrade]
    expected_count: int
    measured_count: int

    @property
    def length_ok(self) -> bool:
        return self.expected_count == self.measured_count

    @property
    def ok(self) -> bool:
        return self.length_ok and all(e.ok for e in self.elements)

    @property
    def mismatches(self) -> int:
        return sum(1 for e in self.elements if e.symbol != e.expected)

    @property
    def flagged(self) -> int:
        return sum(1 for e in self.elements if e.flagged)


def grade(text: str, t: Timing, measured: List[Fraction],
          tolerance: Fraction = DEFAULT_TOLERANCE) -> GradeReport:
    """Compare key-down durations (seconds) with the ideal elements for text.

    An element counts as a dit below two dit lengths and as a dah above that.
    An element is flagged when it is further than ``tolerance`` from its ideal.
    """
    expected = [element for word in _parse_words(text) for code, _ in word for element in code]
    elements: List[ElementGrade] = []
    for i, (want, seconds) in enumerate(zip(expected, measured), start=1):
        symbol = "." if seconds < 2 * t.dit else "-"
        ideal = t.dit if want == "." else t.dah
        deviation = (seconds - ideal) / ideal
        elements.append(ElementGrade(i, want, seconds, ideal, symbol, deviation,
                                     abs(deviation) > tolerance))
    return GradeReport(elements, len(expected), len(measured))


# ---------------------------------------------------------------- formatting

def _num(x) -> str:
    return f"{float(x):g}"


def _ms(seconds) -> str:
    return f"{float(seconds) * 1000:.1f} ms"


def format_timing(t: Timing) -> str:
    rows = [
        ("Character speed", f"{_num(t.wpm)} WPM"),
        ("Effective speed", f"{_num(t.effective)} WPM"),
        ("Dit", _ms(t.dit)),
        ("Dah", _ms(t.dah)),
        ("Element gap", _ms(t.element_gap)),
        ("Character gap", _ms(t.char_gap)),
        ("Word gap", _ms(t.word_gap)),
        ("PARIS + word gap", f"{float(paris_word_seconds(t)):.3f} s"),
    ]
    return "\n".join(f"{label:<17}: {value}" for label, value in rows)


def format_cost(t: Timing) -> str:
    lines = [f"{'char':<6}{'time':>12}{'dits':>8}"]
    for ch, seconds in cost_table(t):
        dits = seconds / t.dit
        lines.append(f"{ch:<6}{_ms(seconds):>12}{_num(dits):>8}")
    return "\n".join(lines)


def format_grade(report: GradeReport, tolerance: Fraction) -> str:
    lines = [f"{'#':>3}  {'sent':<5}{'ms':>9}{'ideal':>9}{'dev':>9}  {'heard':<6}status"]
    for e in report.elements:
        status = "ok"
        if e.symbol != e.expected:
            status = "WRONG SYMBOL"
        elif e.flagged:
            status = "off timing"
        lines.append(
            f"{e.index:>3}  {e.expected:<5}{float(e.measured) * 1000:>9.1f}"
            f"{float(e.ideal) * 1000:>9.1f}{float(e.deviation) * 100:>+8.1f}%  "
            f"{e.symbol:<6}{status}")
    lines.append("")
    if not report.length_ok:
        lines.append(f"length: expected {report.expected_count} elements, "
                     f"trace has {report.measured_count}")
    lines.append(f"elements: {report.expected_count}, mismatched symbols: {report.mismatches}, "
                 f"outside ±{_num(tolerance * 100)}%: {report.flagged}")
    lines.append("result: PASS" if report.ok else "result: FAIL")
    return "\n".join(lines)


# ---------------------------------------------------------------- CLI

def _load_plan(path: str) -> Optional[Plan]:
    with open(path, encoding="utf-8") as fh:
        plan, errors = parse_plan(fh.read())
    if errors:
        for err in errors:
            print(f"{path}:{err.line}:{err.column}: error: {err.message}")
        print(f"{len(errors)} error(s)")
        return None
    return plan


def _pick(plan: Plan, number: int) -> Message:
    for message in plan.messages:
        if message.number == number:
            return message
    raise ValueError(f"no valid message number {number} in the plan")


def cmd_encode(args) -> int:
    print(encode(" ".join(args.text)))
    return 0


def cmd_decode(args) -> int:
    print(decode(" ".join(args.morse)))
    return 0


def cmd_timing(args) -> int:
    print(format_timing(timing(args.wpm, args.effective)))
    return 0


def cmd_cost(args) -> int:
    print(format_cost(timing(args.wpm, args.effective)))
    return 0


def cmd_lint(args) -> int:
    plan = _load_plan(args.file)
    if plan is None:
        return 1
    print(f"{args.file}: OK ({len(plan.messages)} message(s), {_num(plan.wpm)} WPM, "
          f"effective {_num(plan.effective)} WPM, tone {plan.tone} Hz)")
    return 0


def cmd_plan(args) -> int:
    plan = _load_plan(args.file)
    if plan is None:
        return 1
    t = timing(plan.wpm, plan.effective)
    rows = []
    for m in plan.messages:
        row = summarize(m.text, t)
        row.update(number=m.number, line=m.line, wpm=_num(plan.wpm),
                   effective=_num(plan.effective))
        rows.append(row)
    total = sum(r["seconds"] for r in rows)
    if args.json:
        print(json.dumps({"messages": rows, "total_seconds": round(total, 3)}, indent=2))
        return 0
    for r in rows:
        print(f"[{r['number']}] line {r['line']}: {r['text']}")
        print(f"    morse   : {r['morse']}")
        print(f"    elements: {r['elements']} ({r['dots']} dots, {r['dashes']} dashes)")
        print(f"    duration: {r['seconds']:.3f} s at {r['wpm']} WPM, effective {r['effective']} WPM")
    print(f"total: {len(rows)} message(s), {total:.3f} s")
    return 0


def cmd_wav(args) -> int:
    plan = _load_plan(args.file)
    if plan is None:
        return 1
    message = _pick(plan, args.message)
    t = timing(plan.wpm, plan.effective)
    seconds = render_wav(args.out, message.text, t, plan.tone)
    print(f"wrote {args.out}: {seconds:.3f} s at {plan.tone} Hz")
    return 0


def cmd_grade(args) -> int:
    plan = _load_plan(args.plan)
    if plan is None:
        return 1
    with open(args.trace, encoding="utf-8") as fh:
        trace, errors = parse_trace(fh.read())
    if errors:
        for err in errors:
            print(f"{args.trace}:{err.line}:{err.column}: error: {err.message}")
        return 1
    message = _pick(plan, args.message)
    t = timing(plan.wpm, plan.effective)
    tolerance = Fraction(args.tolerance) / 100
    report = grade(message.text, t, [seconds for _, seconds in trace], tolerance)
    print(format_grade(report, tolerance))
    return 0 if report.ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dits", description="Offline Morse code timing toolkit.")
    sub = parser.add_subparsers(dest="command", required=True)

    def speed_args(p):
        p.add_argument("--wpm", type=Fraction, default=DEFAULT_WPM,
                       help="character speed (default 20)")
        p.add_argument("--effective", type=Fraction, default=None,
                       help="Farnsworth effective speed (default: same as --wpm)")

    p = sub.add_parser("encode", help="text to Morse")
    p.add_argument("text", nargs="+")
    p.set_defaults(func=cmd_encode)

    p = sub.add_parser("decode", help="Morse to text")
    p.add_argument("morse", nargs="+", help="e.g. '.... . .-.. .-.. ---' '/' '.-- --- .-. .-.. -..'")
    p.set_defaults(func=cmd_decode)

    p = sub.add_parser("timing", help="element and gap lengths for a speed")
    speed_args(p)
    p.set_defaults(func=cmd_timing)

    p = sub.add_parser("cost", help="time per character, slowest first")
    speed_args(p)
    p.set_defaults(func=cmd_cost)

    p = sub.add_parser("lint", help="check a plan file, exit 1 on errors")
    p.add_argument("file")
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("plan", help="Morse, elements and durations for each message")
    p.add_argument("file")
    p.add_argument("--json", action="store_true", help="print JSON instead of text")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("wav", help="render one message as a WAV tone")
    p.add_argument("file")
    p.add_argument("--message", type=int, default=1, help="message number (default 1)")
    p.add_argument("--out", required=True, help="output .wav path")
    p.set_defaults(func=cmd_wav)

    p = sub.add_parser("grade", help="grade a keying trace against a message")
    p.add_argument("plan")
    p.add_argument("trace", help="one key-down duration in ms per line")
    p.add_argument("--message", type=int, default=1, help="message number (default 1)")
    p.add_argument("--tolerance", type=Fraction, default=Fraction(25),
                   help="allowed timing error in percent (default 25)")
    p.set_defaults(func=cmd_grade)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, OSError) as exc:
        print(f"dits: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
