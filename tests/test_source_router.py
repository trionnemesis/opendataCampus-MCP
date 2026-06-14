"""對應 spec/features/source-routing.feature + discover-sources.feature（過濾部分）。"""
from __future__ import annotations

import pytest

from opendata_campus_mcp.contracts import AccessStrategy, DiscoveryRequest, EducationSource
from opendata_campus_mcp.domain.source_router import SourceRouter

_SOURCES: dict[str, EducationSource] = {
    "教育大市集": EducationSource(
        name="教育大市集",
        official_url="https://market.cloud.edu.tw",
        description="提供各級教案與多媒體教材",
        categories=("教案", "多媒體"),
        education_stages=("國小", "國中", "高中"),
        access_strategy=AccessStrategy.WEB_SEARCH,
    ),
    "因材網": EducationSource(
        name="因材網",
        official_url="https://adl.edu.tw",
        description="適性學習平台，提供分級練習題庫",
        categories=("題庫", "適性學習"),
        education_stages=("國小", "國中"),
        access_strategy=AccessStrategy.WEB_SEARCH,
    ),
    "臺大 OCW": EducationSource(
        name="臺大 OCW",
        official_url="https://ocw.aca.ntu.edu.tw",
        description="大學開放式課程",
        categories=("開放課程", "大學"),
        education_stages=("大學",),
        access_strategy=AccessStrategy.OFFICIAL_API,
    ),
}


@pytest.fixture()
def router() -> SourceRouter:
    return SourceRouter(_SOURCES)


def test_find_by_name(router: SourceRouter):
    s = router.find_by_name("教育大市集")
    assert s is not None
    assert s.official_url == "https://market.cloud.edu.tw"


def test_find_by_name_missing(router: SourceRouter):
    assert router.find_by_name("不存在") is None


def test_find_by_url(router: SourceRouter):
    s = router.find_by_url("https://adl.edu.tw")
    assert s is not None
    assert s.name == "因材網"


def test_find_by_url_trailing_slash(router: SourceRouter):
    s = router.find_by_url("https://adl.edu.tw/")
    assert s is not None


def test_score_keyword_match(router: SourceRouter):
    req = DiscoveryRequest(query="教案 國中")
    pairs = router.score_sources(list(_SOURCES.values()), req)
    # 教育大市集 有「教案」關鍵字 → 得分最高
    assert pairs[0][1].name == "教育大市集"


def test_score_stage_filter_excludes_mismatch(router: SourceRouter):
    req = DiscoveryRequest(query="題庫", education_stage="高中")
    pairs = router.score_sources(list(_SOURCES.values()), req)
    names = [s.name for _, s in pairs]
    # 因材網 只適用 國小/國中，應被排除
    assert "因材網" not in names


def test_score_all_zero_still_returns_valid(router: SourceRouter):
    req = DiscoveryRequest(query="zzz_no_match")
    pairs = router.score_sources(list(_SOURCES.values()), req)
    # 無關鍵字命中，但沒有 stage 限制 → score=0，仍回傳
    assert len(pairs) == len(_SOURCES)
    assert all(sc == 0 for sc, _ in pairs)


def test_higher_priority_strategy_ranks_first_when_equal_score(router: SourceRouter):
    # 臺大 OCW 的 access_strategy=OFFICIAL_API(priority=0) 若 score 相同應排前
    req = DiscoveryRequest(query="課程")  # 臺大 OCW categories 有「課程」
    pairs = router.score_sources(list(_SOURCES.values()), req)
    # 臺大 OCW score > 0（"課程" in "開放課程 大學"）
    top = pairs[0][1]
    assert top.name == "臺大 OCW"
