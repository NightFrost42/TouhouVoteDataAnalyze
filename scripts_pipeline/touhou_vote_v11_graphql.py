"""Read-only GraphQL documents for https://touhou.vote/v11/ results.

The result API uses HTTP POST for queries, but none of the documents in this
module is a mutation.  The module has no import-time network side effects.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping
from urllib.request import Request, urlopen


ENDPOINT = "https://touhou.vote/res-be/graphql"
V11_VOTE_START = "2023-12-29T10:00:00.000Z"
V11_VOTE_YEAR = 11

V11_INDEX_JS = "https://touhou.vote/v11/assets/index-c1d6c5d6.js"
V11_QUESTIONNAIRE_DEFINITION_JS = (
    "https://touhou.vote/v11/assets/questionnaire-b69f5aad.js"
)
V11_DOUJIN_RESULT_JS = "https://touhou.vote/v11/assets/Doujin-f64f63b8.js"
V11_DOUJIN_RESULT_MAP = (
    "https://touhou.vote/v11/assets/Doujin-f64f63b8.js.map"
)


MUSIC_RANKING_QUERY = r"""
query MusicRanking($query: String, $voteStart: DateTimeUtc!, $voteYear: Int!) {
  queryMusicRanking(query: $query, voteStart: $voteStart, voteYear: $voteYear) {
    global {
      totalUniqueItems
      totalFirst
      totalVotes
      averageVotesPerItem
      medianVotesPerItem
    }
    entries {
      rank
      displayRank
      name
      voteCount
      firstVoteCount
      firstVotePercentage
      firstVoteCountWeighted
      votePercentage
      firstPercentage
      maleVoteCount
      malePercentagePerChar
      femaleVoteCount
      femalePercentagePerChar
      album
      nameJpn
      firstAppearance
      malePercentagePerTotal
      femalePercentagePerTotal
    }
  }
}
"""

MUSIC_SINGLE_TREND_QUERY = r"""
query MusicSingleTrend(
  $voteStart: DateTimeUtc!
  $voteYear: Int!
  $rank: Int!
  $query: String
) {
  queryMusicSingle(
    voteStart: $voteStart
    voteYear: $voteYear
    rank: $rank
    query: $query
  ) {
    name
    voteCount
    firstVoteCount
    firstVotePercentage
    votePercentage
    firstPercentage
    numReasons
    trend { hrs cnt }
    trendFirst { hrs cnt }
  }
}
"""

MUSIC_REASONS_QUERY = r"""
query MusicReasons(
  $voteStart: DateTimeUtc!
  $voteYear: Int!
  $rank: Int!
  $query: String
) {
  queryMusicSingle(
    voteStart: $voteStart
    voteYear: $voteYear
    rank: $rank
    query: $query
  ) {
    name
    voteCount
    firstVoteCount
    firstVotePercentage
    votePercentage
    firstPercentage
    reasons
    numReasons
  }
}
"""

MUSIC_TREND_QUERY = r"""
query MusicTrend(
  $voteStart: DateTimeUtc!
  $voteYear: Int!
  $names: [String!]!
) {
  queryMusicTrend(
    voteStart: $voteStart
    voteYear: $voteYear
    names: $names
  ) {
    trend { hrs cnt }
    trendFirst { hrs cnt }
  }
}
"""


CP_RANKING_QUERY = r"""
query CPRanking($query: String, $voteStart: DateTimeUtc!, $voteYear: Int!) {
  queryCPRanking(query: $query, voteStart: $voteStart, voteYear: $voteYear) {
    global {
      totalUniqueItems
      totalFirst
      totalVotes
      averageVotesPerItem
      medianVotesPerItem
    }
    entries {
      rank
      displayRank
      cp { a b c }
      aActive
      bActive
      cActive
      noneActive
      voteCount
      firstVoteCount
      firstVotePercentage
      firstVoteCountWeighted
      votePercentage
      firstPercentage
      maleVoteCount
      malePercentagePerChar
      malePercentagePerTotal
      femaleVoteCount
      femalePercentagePerChar
      femalePercentagePerTotal
    }
  }
}
"""

CP_SINGLE_TREND_QUERY = r"""
query CPSingleTrend(
  $voteStart: DateTimeUtc!
  $voteYear: Int!
  $rank: Int!
  $query: String
) {
  queryCPSingle(
    voteStart: $voteStart
    voteYear: $voteYear
    rank: $rank
    query: $query
  ) {
    cp { a b c }
    aActive
    bActive
    cActive
    noneActive
    voteCount
    firstVoteCount
    firstVotePercentage
    votePercentage
    firstPercentage
    trend { hrs cnt }
    trendFirst { hrs cnt }
    numReasons
  }
}
"""

CP_REASONS_QUERY = r"""
query CPReasons(
  $voteStart: DateTimeUtc!
  $voteYear: Int!
  $rank: Int!
  $query: String
) {
  queryCPSingle(
    voteStart: $voteStart
    voteYear: $voteYear
    rank: $rank
    query: $query
  ) {
    cp { a b c }
    aActive
    bActive
    cActive
    noneActive
    voteCount
    firstVoteCount
    firstVotePercentage
    votePercentage
    firstPercentage
    reasons
    numReasons
  }
}
"""


QUESTIONNAIRE_QUERY = r"""
query Questionnaire(
  $voteStart: DateTimeUtc!
  $voteYear: Int!
  $query: String
  $questionsOfInterest: [String!]!
) {
  queryQuestionnaire(
    voteStart: $voteStart
    voteYear: $voteYear
    query: $query
    questionsOfInterest: $questionsOfInterest
  ) {
    entries {
      questionId
      answersCat {
        aid
        totalVotes
        maleVotes
        femaleVotes
      }
      answersStr
      totalAnswers
      totalMale
      totalFemale
    }
  }
  queryCompletionRates(
    voteStart: $voteStart
    voteYear: $voteYear
    query: $query
  ) {
    items { name rate numComplete total }
  }
}
"""

QUESTIONNAIRE_TREND_QUERY = r"""
query QuestionnaireTrend(
  $voteStart: DateTimeUtc!
  $voteYear: Int!
  $questionIds: [String!]!
  $query: String
) {
  queryGlobalStats(
    voteStart: $voteStart
    voteYear: $voteYear
    query: $query
  ) {
    voteYear
    numVote
    numChar
    numMusic
    numCp
    numDoujin
    numMale
    numFemale
  }
  queryQuestionnaireTrend(
    voteStart: $voteStart
    voteYear: $voteYear
    questionIds: $questionIds
    query: $query
  ) {
    trend { hrs cnt }
    trendFirst { hrs cnt }
  }
}
"""

GLOBAL_STATS_QUERY = r"""
query GlobalStats($query: String, $voteStart: DateTimeUtc!, $voteYear: Int!) {
  queryGlobalStats(query: $query, voteStart: $voteStart, voteYear: $voteYear) {
    voteYear
    numVote
    numChar
    numMusic
    numCp
    numDoujin
    numMale
    numFemale
  }
}
"""


def v11_variables(query_filter: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build variables; the official frontend omits ``query`` when unfiltered."""
    variables: dict[str, Any] = {
        "voteStart": V11_VOTE_START,
        "voteYear": V11_VOTE_YEAR,
    }
    if query_filter:
        variables["query"] = query_filter
    variables.update(extra)
    return variables


def questionnaire_answer(question_id: str | int, answer_id: str | int) -> str:
    """Return a filter clause such as ``q11011=1101102``."""
    qid = str(question_id)
    if qid.startswith("q"):
        qid = qid[1:]
    return f"q{qid}={answer_id}"


def chars_any(names: Iterable[str]) -> str:
    """Match a ballot containing any character in one array (OR semantics)."""
    return "chars:" + json.dumps(list(names), ensure_ascii=False)


def chars_first(name: str) -> str:
    return "chars_first=" + json.dumps(name, ensure_ascii=False)


def musics_any(names: Iterable[str]) -> str:
    """Match a ballot containing any music in one array (OR semantics)."""
    return "musics:" + json.dumps(list(names), ensure_ascii=False)


def musics_first(name: str) -> str:
    return "musics_first=" + json.dumps(name, ensure_ascii=False)


def all_of(*clauses: str) -> str:
    return " AND ".join(f"({clause})" for clause in clauses if clause)


def any_of(*clauses: str) -> str:
    return " OR ".join(f"({clause})" for clause in clauses if clause)


def post_graphql(
    document: str,
    variables: Mapping[str, Any],
    *,
    timeout: float = 60,
) -> dict[str, Any]:
    """Execute a read-only GraphQL query using only the Python standard library."""
    payload = json.dumps(
        {"query": document, "variables": dict(variables)},
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(
        ENDPOINT,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "TouhouVoteDataAudit/1.0",
        },
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        result = json.load(response)
    if result.get("errors"):
        raise RuntimeError(json.dumps(result["errors"], ensure_ascii=False))
    return result["data"]


if __name__ == "__main__":
    # Print a safe example; importing or running this module does not crawl by default.
    female_filter = questionnaire_answer("q11011", "1101102")
    print(json.dumps(v11_variables(female_filter), ensure_ascii=False, indent=2))
