"""The negation window looks at the two tokens preceding a sentiment
word, so an intervening intensifier does not block the flip."""

from simorgh.persona.emotion import react


def test_not_very_good_flips_valence():
    plain = react("good")
    negated = react("not very good")
    assert plain.valence > 0
    assert negated.valence < 0


def test_single_token_negation_still_flips():
    assert react("not good").valence < 0


def test_negation_does_not_reach_across_three_tokens():
    # "not" is three tokens before "good"; too far, no flip.
    assert react("not at all very good").valence > 0


def test_non_negator_interveners_do_not_flip():
    assert react("good").valence == react("very good").valence
