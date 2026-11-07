"""Unit tests for the overview output safety rules."""

from __future__ import annotations

import pytest

from app.overview_service import (
    MAX_OVERVIEW_LENGTH,
    OverviewContentError,
    _safe_output,
)


def test_plain_summary_is_accepted():
    text = "客户询价304不锈钢管件共1万件，要求FOB报价、MOQ、交期与付款条款。"
    assert _safe_output(text, source_text="Dear Sir, we need 10,000 elbows...") == text


def test_label_prefix_is_stripped_not_rejected():
    raw = "中文概要：客户询价不锈钢管件，要求报价与交期。"
    assert _safe_output(raw, source_text="email body") == "客户询价不锈钢管件，要求报价与交期。"


def test_summary_discussing_overview_feature_is_valid():
    # A customer/probe email about the summary feature itself must still get
    # a real summary; mentioning "中文概要" is business content, not a leak.
    text = "发件人测试LLM连接是否正常，要求据此显示可用或不可用。"
    source = "If the LLM connection works, the front end displays 中文概要: 可用."
    assert _safe_output(text, source_text=source) == text


@pytest.mark.parametrize(
    "marker",
    (
        "你是企业运营收件箱的客户消息业务概要器",
        "必须优先提取客户主要意图",
        "不要逐句翻译，只要业务概要",
        "只返回纯文本，不要其他内容",
        "不要输出标题、JSON、HTML",
    ),
)
def test_instruction_echo_is_rejected(marker: str):
    text = (marker + "。客户询问交期。")[:MAX_OVERVIEW_LENGTH]
    with pytest.raises(OverviewContentError):
        _safe_output(text, source_text="email body")


def test_overlong_output_is_rejected():
    text = "长" * (MAX_OVERVIEW_LENGTH + 1)
    with pytest.raises(OverviewContentError):
        _safe_output(text, source_text="email body")


def test_verbatim_source_echo_is_rejected():
    source = "客户询问交期"
    with pytest.raises(OverviewContentError):
        _safe_output(source, source_text=source)


def test_non_text_output_is_rejected():
    with pytest.raises(OverviewContentError):
        _safe_output({"choices": []}, source_text="email body")
