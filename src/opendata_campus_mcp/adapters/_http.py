"""共用 HTTP 基礎設施 — adapter 間共用的 SSLContext 建構。

台灣 .edu.tw 政府教育平台多以 GCA 憑證簽發、部分缺 Subject Key Identifier，
在 certifi + 嚴格 OpenSSL 下驗證失敗；統一改用 OS 系統信任庫驗證（不放寬安全）。
WebSearchAdapter 與 EduMarketApiAdapter 共用此處,避免重複維護憑證 workaround。
"""
from __future__ import annotations

import os
import ssl

import truststore


def build_ssl_context() -> ssl.SSLContext:
    """以 OS 系統信任庫建立 SSLContext，並納入 SSL_CERT_FILE / SSL_CERT_DIR。

    truststore 不讀 SSL_CERT_FILE / SSL_CERT_DIR；corporate proxy 或 private-CA
    環境下這些變數仍需被納入信任,故在此一併手動載入。
    """
    ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    cert_file = os.environ.get("SSL_CERT_FILE")
    cert_dir = os.environ.get("SSL_CERT_DIR")
    if cert_file or cert_dir:
        ctx.load_verify_locations(cafile=cert_file, capath=cert_dir)
    return ctx
