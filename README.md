# Dits

**An offline Morse code timing toolkit: plain-text plans in, exact ITU and Farnsworth timings, WAV tones and keying-trace grades out.**

Dits does the arithmetic behind sending and checking Morse. Give it a character speed, an optional Farnsworth effective speed and a few messages, and it returns exact element and gap lengths, message durations, a per-character cost table, a WAV tone of any message, and a pass or fail grade for a timed keying trace. Everything runs locally on the Python standard library, with no network access and no accounts.

## Features

- **Encode and decode** text to and from Morse, with letters separated by spaces and words by ` / `.
- **Prosigns** written in brackets (`[SK]`, `[AS]`, `[CT]`, `[BK]`), which round-trip through `encode` and `decode`.
- **Exact timing** for any character speed: dit, dah, element, character and word gaps, all kept as fractions and rounded only when printed.
- **Farnsworth spacing** with a separate effective speed. Elements stay at character speed and the gaps stretch so that a PARIS word plus its word gap takes exactly `60 / effective` seconds.
- **Message durations** in seconds, counting every element and gap, with element counts split into dots and dashes.
- **Per-character cost table** that lists how long each supported character takes, slowest first, in ms and in dit units.
- **Plan files** that hold a speed, an optional Farnsworth speed, a tone and any number of numbered messages in one readable file.
- **Line-numbered lint** that reports every problem with `file:line:column`, including bad characters, unknown directives, duplicate keys, empty messages and effective speed above character speed.
- **CI-friendly exit codes**: `lint` and `grade` exit `1` on errors or a failed grade, and `2` on bad usage.
- **JSON output** for `plan --json`, ready for other tools.
- **WAV export** of any message as a 16-bit mono tone at the plan's pitch, with a 5 ms ramp on each element to avoid clicks.
- **Keying-trace grading**: compares measured key-down durations element by element with the ideal timing, flags symbols that were sent wrong and timing outside a set tolerance, and reports a length mismatch.

## Quick start

Requires Python 3.8 or later. There is nothing to install for the tool itself.

```console
$ python3 dits.py encode "CQ DE W1AW K"
-.-. --.- / -.. . / .-- .---- .- .-- / -.-

$ python3 dits.py decode "-.-. --.- / -.. . / -.-"
CQ DE K

$ python3 dits.py timing --wpm 20 --effective 15
Character speed  : 20 WPM
Effective speed  : 15 WPM
Dit              : 60.0 ms
Dah              : 180.0 ms
Element gap      : 60.0 ms
Character gap    : 337.9 ms
Word gap         : 788.4 ms
PARIS + word gap : 4.000 s

$ python3 dits.py lint examples/sample.dit
examples/sample.dit: OK (3 message(s), 20 WPM, effective 15 WPM, tone 650 Hz)
```

The `PARIS + word gap` line is the check for Farnsworth spacing. At 15 WPM effective, the standard word takes exactly 4 seconds, which is `60 / 15`.

A plan file looks like this:

```text
# Field-day practice plan
wpm = 20
effective = 15
tone = 650

msg: CQ CQ DE W1AW W1AW K
msg: PARIS PARIS
msg: [SK] 73 [SK]
```

Then grade a keying trace (one key-down duration in milliseconds per line) against message 2:

```console
$ python3 dits.py grade examples/sample.dit examples/paris.trace --message 2
```

The example trace has one dah keyed short, so the grade reports `WRONG SYMBOL` on that element and exits with status `1`.

## Commands

| Command | What it does |
| --- | --- |
| `encode TEXT...` | Text to Morse |
| `decode MORSE...` | Morse to text; use `/` between words |
| `timing [--wpm W] [--effective E]` | Element and gap lengths for a speed |
| `cost [--wpm W] [--effective E]` | Time per character, slowest first |
| `lint FILE` | Check a plan file; exits `1` on errors |
| `plan FILE [--json]` | Morse, element counts and durations for each message |
| `wav FILE --out PATH [--message N]` | Render one message as a WAV tone |
| `grade FILE TRACE [--message N] [--tolerance PCT]` | Grade a keying trace; exits `1` on failure |

Plan file directives are `wpm`, `effective` and `tone`, each written as `key = value`. Each message is a line that starts with `msg:`. Lines starting with `#` are comments. Messages are numbered in file order, from 1.

## Running it

```console
$ python3 dits.py plan examples/sample.dit
$ python3 dits.py plan examples/sample.dit --json
$ python3 dits.py wav examples/sample.dit --message 1 --out cq.wav
$ python3 dits.py cost --wpm 20 --effective 15
```

## Testing

The tests use [pytest](https://pytest.org), which is the only dependency and is needed for tests alone.

```console
$ python3 -m pip install pytest
$ python3 -m pytest -q
```

The suite covers the Morse tables, encoding and decoding round trips, Farnsworth and PARIS arithmetic, duration and cost, plan and trace parsing with line numbers, grading, WAV output length, and the CLI exit codes.

## Layout

```text
dits.py                  the whole toolkit, one module
examples/sample.dit      a sample plan with three messages
examples/paris.trace     a keying trace for message 2 with one planted error
tests/conftest.py        puts the project root on the import path
tests/test_dits.py       unit and CLI tests
```

## Notes

- Timing follows the ITU PARIS standard: a dit is `1.2 / WPM` seconds and a dah is three dits. Farnsworth spacing uses the standard formula for the stretched gaps.
- Symbols in a keying trace are classified by a two-dit threshold, which sits midway between a dit and a dah.
- Only the characters in the ITU table and the four listed prosigns are supported. Anything else is reported with its line and column.
