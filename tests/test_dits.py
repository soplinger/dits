import pathlib
import wave
from fractions import Fraction

import pytest

import dits
from dits import MorseError, decode, encode, grade, parse_plan, parse_trace, timing


def test_morse_codes_are_unique_across_letters_digits_punctuation_and_prosigns():
    codes = list(dits.MORSE.values()) + list(dits.PROSIGNS.values())
    assert len(codes) == len(set(codes))


def test_encode_letters_words_and_prosigns():
    assert encode("sos") == "... --- ..."
    assert encode("  E   T  ") == ". / -"
    assert encode("[SK] 73") == "...-.- / --... ...--"


def test_decode_round_trips_encoded_text():
    text = "CQ DE W1AW K"
    assert decode(encode(text)) == text
    assert decode("...-.- / --... ...--") == "[SK] 73"


def test_encode_reports_column_of_unsupported_character():
    with pytest.raises(MorseError) as info:
        encode("AB#")
    assert info.value.column == 3


def test_decode_rejects_unknown_group():
    with pytest.raises(MorseError):
        decode("..-.-.-")


def test_standard_paris_word_is_fifty_units():
    t = timing(20)
    assert t.dit == Fraction(3, 50)
    assert dits.paris_word_seconds(t) == Fraction(3)


def test_farnsworth_stretches_gaps_but_keeps_elements():
    standard = timing(20)
    farnsworth = timing(20, 10)
    assert farnsworth.dit == standard.dit
    assert farnsworth.char_gap > 3 * farnsworth.dit
    assert dits.paris_word_seconds(farnsworth) == Fraction(6)  # 60 / effective


def test_effective_speed_faster_than_character_speed_is_rejected():
    with pytest.raises(ValueError):
        timing(15, 20)


def test_duration_counts_element_letter_and_word_gaps():
    t = timing(20)
    # E (1 dit) + word gap (7 dits) + T (3 dits) = 11 dits of 60 ms
    assert float(dits.duration("E T", t)) == pytest.approx(0.66)


def test_summarize_counts_dots_and_dashes():
    row = dits.summarize("SOS", timing(20))
    assert (row["dots"], row["dashes"], row["elements"]) == (6, 3, 9)


def test_cost_table_slowest_character_takes_19_dits():
    # 0, comma and ) are all 19 dit units, so check the time rather than the label
    t = timing(20)
    assert dits.cost_table(t)[0][1] == 19 * t.dit


def test_parse_plan_reports_line_and_column_for_each_problem():
    source = (
        "wpm = 20\n"
        "effective = 25\n"
        "speed = 3\n"
        "msg: HELLO #\n"
        "msg:\n"
        "msg: OK\n"
    )
    plan, errors = parse_plan(source)
    found = sorted((e.line, e.column) for e in errors)
    assert found == [(2, 1), (3, 1), (4, 12), (5, 5)]
    assert [m.text for m in plan.messages] == ["OK"]
    assert plan.messages[0].number == 3


def test_parse_plan_defaults_when_directives_are_missing():
    plan, errors = parse_plan("msg: E\n")
    assert errors == []
    assert (plan.wpm, plan.effective, plan.tone) == (20, 20, 600)


def test_parse_trace_rejects_bad_values_with_line_numbers():
    durations, errors = parse_trace("60\nabc\n-5\n# comment\n62\n")
    assert [e.line for e in errors] == [2, 3]
    assert [line for line, _ in durations] == [1, 5]


def test_grade_passes_clean_dit_and_flags_dah_keyed_short():
    t = timing(20)
    good = grade("E", t, [Fraction(60, 1000)])
    assert good.ok

    bad = grade("T", t, [Fraction(60, 1000)])
    assert not bad.ok
    assert bad.mismatches == 1
    assert bad.elements[0].symbol == "."


def test_grade_fails_when_trace_length_differs():
    report = grade("PARIS", timing(20), [Fraction(60, 1000)] * 13)
    assert report.expected_count == 14
    assert not report.length_ok
    assert not report.ok


def test_render_wav_length_matches_timeline(tmp_path):
    out = tmp_path / "msg.wav"
    t = timing(20, 15)
    seconds = dits.render_wav(str(out), "PARIS", t, tone_hz=600)
    with wave.open(str(out), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 8000
        assert wav.getnframes() / 8000 == pytest.approx(seconds, abs=0.001)
        assert seconds == pytest.approx(float(dits.duration("PARIS", t)), abs=0.001)


def test_lint_command_exit_codes(tmp_path, capsys):
    bad = tmp_path / "bad.dit"
    bad.write_text("wpm = 20\nmsg: HI!\n", encoding="utf-8")
    assert dits.main(["lint", str(bad)]) == 1
    assert "bad.dit:2:8: error:" in capsys.readouterr().out

    good = tmp_path / "good.dit"
    good.write_text("wpm = 18\nmsg: HI\n", encoding="utf-8")
    assert dits.main(["lint", str(good)]) == 0


def test_grade_command_fails_on_example_trace(capsys):
    examples = pathlib.Path(dits.__file__).resolve().parent / "examples"
    code = dits.main(["grade", str(examples / "sample.dit"),
                      str(examples / "paris.trace"), "--message", "2"])
    assert code == 1
    out = capsys.readouterr().out
    assert "result: FAIL" in out
    assert "WRONG SYMBOL" in out
