"""SourceRouter — 教育平台路由與相關性評分。

路由優先序：OFFICIAL_API(0) > OPEN_DATA(1) > WEB_SEARCH(2)
           > TWCAMPUS_DIRECTORY(3) > HEADLESS_BROWSER(4)

score_sources() 回傳 (score, source) pairs，分數 = 關鍵字命中數 + 科目加成；
  -1 表示教育階段不符（強制排除）。
"""
from __future__ import annotations

from opendata_campus_mcp.contracts import AccessStrategy, DiscoveryRequest, EducationSource

PRIORITY_ORDER: list[AccessStrategy] = [
    AccessStrategy.OFFICIAL_API,
    AccessStrategy.OPEN_DATA,
    AccessStrategy.WEB_SEARCH,
    AccessStrategy.TWCAMPUS_DIRECTORY,
    AccessStrategy.HEADLESS_BROWSER,
]


class SourceRouter:
    def __init__(self, known_sources: dict[str, EducationSource]) -> None:
        self._sources = known_sources  # name → EducationSource

    def find_by_name(self, name: str) -> EducationSource | None:
        return self._sources.get(name)

    def find_by_url(self, url: str) -> EducationSource | None:
        for s in self._sources.values():
            if s.official_url.rstrip("/") == url.rstrip("/"):
                return s
        return None

    def score_sources(
        self,
        candidates: list[EducationSource],
        request: DiscoveryRequest,
    ) -> list[tuple[int, EducationSource]]:
        """回傳 (score, source) pairs，降序排列；score=-1 的項目已排除。"""
        pairs = [(self._score(s, request), s) for s in candidates]
        pairs.sort(key=lambda x: (-x[0], x[1].access_strategy.priority))
        return [(sc, s) for sc, s in pairs if sc >= 0]

    def _score(self, source: EducationSource, request: DiscoveryRequest) -> int:
        # 教育階段硬性過濾：source 有明確適用階段但不包含請求階段 → 排除
        if request.education_stage and source.education_stages:
            if request.education_stage not in source.education_stages:
                return -1

        query_tokens = set(request.query.lower().split())
        text = " ".join([
            source.name,
            source.description,
            *source.categories,
            *source.education_stages,
        ]).lower()
        match = sum(1 for t in query_tokens if t in text)

        # 科目加成：query 中的科目關鍵字命中 categories
        if request.subject and any(request.subject in c for c in source.categories):
            match += 2

        return match
