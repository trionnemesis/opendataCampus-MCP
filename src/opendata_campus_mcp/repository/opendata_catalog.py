"""教育類 open data dataset 靜態目錄（data.gov.tw）。

data.gov.tw 無匿名關鍵字搜尋 API,且 datasetId 為不可枚舉的數字 → discover 必須靠
預先驗證的 dataset 清單。此 catalog 是 **dataset 層**（與 source_cache 的平台層不同
粒度,故分離成獨立檔）。新增 dataset：先以 `/api/v2/rest/dataset/{id}` 確認 success=true,
再於 _CATALOG 加一筆。

全部 8 筆皆為教育部（統計處/高教司）出版,授權 OGDL v1.0,附 CSV/JSON 下載點。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class OpenDataset:
    """data.gov.tw 教育 dataset 的 catalog 條目。"""

    dataset_id: str
    title: str
    summary: str = ""
    keywords: tuple[str, ...] = ()
    education_stages: tuple[str, ...] = ()
    formats: tuple[str, ...] = field(default=("CSV", "JSON"))


_CATALOG: list[OpenDataset] = [
    # ── 名錄型（較貼近資源發現）──────────────────────────────────────────────
    OpenDataset(
        dataset_id="6091",
        title="大專校院名錄",
        summary="全臺灣大專校院通訊資料（校名、地址、電話、網址）",
        keywords=("名錄", "大專", "大專校院", "學校"),
        education_stages=("大學",),
    ),
    OpenDataset(
        dataset_id="6089",
        title="一般高級中等學校名錄",
        summary="全臺灣高中職校名錄與通訊資料",
        keywords=("名錄", "高中", "高級中等學校", "學校"),
        education_stages=("高中",),
    ),
    # ── 統計型 ──────────────────────────────────────────────────────────────
    OpenDataset(
        dataset_id="6288",
        title="大專校院圖書館統計",
        summary="大專校院圖書館館藏、電子書、座位與流通統計",
        keywords=("圖書館", "大專校院", "統計", "館藏"),
        education_stages=("大學",),
    ),
    OpenDataset(
        dataset_id="9624",
        title="大專校院各校科系別專任教師數",
        summary="各校日夜間部、系所、職級之專任教師人數",
        keywords=("教師", "大專校院", "科系", "師資", "統計"),
        education_stages=("大學",),
    ),
    OpenDataset(
        dataset_id="40121",
        title="各級學校縣市別學生人數",
        summary="各縣市各級學校（幼兒園至大學、特教）學生人數",
        keywords=("學生", "各級學校", "縣市", "學生數", "統計"),
        education_stages=("全階段",),
    ),
    OpenDataset(
        dataset_id="31437",
        title="各級學校概況—校數、專任教師數及職員數",
        summary="各級學校校數、專任教師數及職員數概況",
        keywords=("學校概況", "校數", "教師", "職員", "統計"),
        education_stages=("全階段",),
    ),
    OpenDataset(
        dataset_id="31438",
        title="各級學校年齡別學生人數",
        summary="各級學校依年齡別的學生人數分布",
        keywords=("學生", "年齡", "各級學校", "學生數", "統計"),
        education_stages=("全階段",),
    ),
    OpenDataset(
        dataset_id="40118",
        title="各級學校學生人數占年底人口比率",
        summary="各級學校學生人數占年底人口的比率",
        keywords=("學生", "人口比率", "各級學校", "統計"),
        education_stages=("全階段",),
    ),
]


def get_opendata_catalog() -> list[OpenDataset]:
    """回傳教育 open data dataset 目錄（shallow copy）。"""
    return list(_CATALOG)
