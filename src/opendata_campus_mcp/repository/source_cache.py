"""已知教育平台靜態目錄。

提供預先驗證的平台清單，作為 discover_education_sources 的主要來源；
TWCampus 僅在本地目錄不足時才補充呼叫，減少 TWCampus 請求頻率。

新增平台：在 _CATALOG 中加一筆即可；production 可改為讀取 YAML/JSON 設定檔。
"""
from __future__ import annotations

from opendata_campus_mcp.contracts import AccessStrategy, EducationSource

_CATALOG: list[EducationSource] = [
    EducationSource(
        name="教育大市集",
        official_url="https://market.cloud.edu.tw",
        description="教育部數位內容入口，提供各級教案、多媒體教材與學習活動",
        categories=("教案", "多媒體", "學習活動", "教材"),
        education_stages=("國小", "國中", "高中"),
        access_strategy=AccessStrategy.WEB_SEARCH,
    ),
    EducationSource(
        name="因材網",
        official_url="https://adl.edu.tw",
        description="教育部適性學習平台，提供分級練習題庫與自動診斷評量",
        categories=("題庫", "適性學習", "評量", "練習"),
        education_stages=("國小", "國中"),
        access_strategy=AccessStrategy.WEB_SEARCH,
    ),
    EducationSource(
        name="CIRN",
        official_url="https://cirn.moe.edu.tw",
        description="課程研究發展院資源入口，提供國中小課程綱要與教學資源",
        categories=("課程綱要", "教學資源", "教案", "評量工具"),
        education_stages=("國小", "國中"),
        access_strategy=AccessStrategy.WEB_SEARCH,
    ),
    EducationSource(
        name="教育部數位教學資源入口網",
        official_url="https://cloud.edu.tw",
        description="整合 OpenEdu 資源，提供開放授權教學素材",
        categories=("開放教育", "數位資源", "OER", "教學素材"),
        education_stages=("國小", "國中", "高中", "大學"),
        access_strategy=AccessStrategy.WEB_SEARCH,
    ),
    EducationSource(
        name="全民英檢 GEPT",
        official_url="https://www.gept.org.tw",
        description="英語能力測驗資源、歷屆試題與學習建議",
        categories=("英語", "檢定", "考試", "歷屆試題"),
        education_stages=("國中", "高中", "大學", "全階段"),
        access_strategy=AccessStrategy.WEB_SEARCH,
    ),
    EducationSource(
        name="國立公共資訊圖書館",
        official_url="https://www.nlpi.edu.tw",
        description="公共數位圖書館，提供電子書、數位資源與線上學習課程",
        categories=("電子書", "數位圖書館", "線上課程", "學習資源"),
        education_stages=("全階段",),
        access_strategy=AccessStrategy.WEB_SEARCH,
    ),
    EducationSource(
        name="教育部學力認證",
        official_url="https://www.ceec.edu.tw",
        description="大學入學考試中心，提供學科能力測驗與歷屆試題",
        categories=("學測", "指考", "歷屆試題", "升學"),
        education_stages=("高中",),
        access_strategy=AccessStrategy.WEB_SEARCH,
    ),
    EducationSource(
        name="均一教育平台",
        official_url="https://www.junyiacademy.org",
        description="非營利線上學習平台，提供數學、自然、語文等科目影片與練習",
        categories=("影片教學", "練習題", "數學", "自然", "語文"),
        education_stages=("國小", "國中", "高中"),
        access_strategy=AccessStrategy.WEB_SEARCH,
    ),
    EducationSource(
        name="臺大開放式課程 NTU OCW",
        official_url="https://ocw.aca.ntu.edu.tw",
        description="國立臺灣大學開放式課程，提供大學級影片講義",
        categories=("開放課程", "大學課程", "影片", "講義"),
        education_stages=("大學",),
        access_strategy=AccessStrategy.WEB_SEARCH,
    ),
    EducationSource(
        name="國教院課程資源網",
        official_url="https://www.naer.edu.tw",
        description="國家教育研究院課程資源，提供十二年國教相關素材",
        categories=("十二年國教", "課程資源", "素養導向"),
        education_stages=("國小", "國中", "高中"),
        access_strategy=AccessStrategy.WEB_SEARCH,
    ),
]


def get_known_sources() -> dict[str, EducationSource]:
    """回傳 name → EducationSource 字典（shallow copy）。"""
    return {s.name: s for s in _CATALOG}
