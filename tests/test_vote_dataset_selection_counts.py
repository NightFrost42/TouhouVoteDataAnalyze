from scripts_pipeline.build_vote_dataset import jp_selection_count_from_score


def test_jp_2_1_score_recovers_selection_count():
    assert jp_selection_count_from_score(20, 7314, 1507) == 5807


def test_jp_3_2_1_score_recovers_selection_count():
    assert jp_selection_count_from_score(22, 29797, 5162, 3176) == 16297


def test_jp_3_2_1_score_does_not_invent_missing_secondary_count():
    assert jp_selection_count_from_score(21, 27688, 5133) is None


def test_invalid_score_components_remain_missing():
    assert jp_selection_count_from_score(20, 100, 80) is None
