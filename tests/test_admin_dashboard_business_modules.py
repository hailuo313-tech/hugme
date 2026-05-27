from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_conversation_dashboard_is_business_command_center() -> None:
    page = (ROOT / "admin" / "app" / "conversations" / "page.tsx").read_text(
        encoding="utf-8"
    )

    assert "会话流控" in page
    assert "会话总览已升级为业务工作台" in page
    assert "业务链路状态" in page
    assert "链接转化归因" in page
    assert "会话工作队列" in page
    assert "话术命中轨迹" in page
    assert "推荐话术 Top3" in page
    assert "接入TG账号" in page
    assert 'href="/admin/telegram-accounts"' in page
    assert 'href="/admin/data"' in page


def test_conversation_dashboard_keeps_business_api_integrations() -> None:
    page = (ROOT / "admin" / "app" / "conversations" / "page.tsx").read_text(
        encoding="utf-8"
    )

    assert 'const CONVERSATION_LIST_API_MARKER = "/admin/conversations?";' in page
    assert "apiFetch<ListResponse>(" in page
    assert 'apiFetch<DetailResponse>(`/admin/conversations/${conversationId}`)' in page
    assert 'apiFetch<{ items: ScriptSuggestion[] }>("/scripts/suggest"' in page
    assert 'apiFetch<ScriptTraceResponse>(`/archive/premium-chat/${conversationId}/trace`)' in page
    assert "if (isPremium(response.conversation))" in page
    assert "精聊话术轨迹仅对 S/A 用户启用" in page
    assert "`/ops-ai/conversations/${detail.conversation.conversation_id}/assist`" in page


def test_conversation_queue_shows_claimed_after_operator_takeover() -> None:
    page = (ROOT / "admin" / "app" / "conversations" / "page.tsx").read_text(
        encoding="utf-8"
    )

    assert "function queueStateLabel(row: ConversationRow)" in page
    assert 'row.assigned_operator_id || row.state === "HUMAN_LOCKED"' in page
    assert 'return "已接管";' in page
    assert "{queueStateLabel(row)}" in page
    assert "`/admin/conversations/${row.conversation_id}/accept`" in page
    assert "processConversation(row)" in page


def test_conversation_drawer_supports_operator_translation_helpers() -> None:
    page = (ROOT / "admin" / "app" / "conversations" / "page.tsx").read_text(
        encoding="utf-8"
    )

    assert "translation_zh" in page
    assert "中文参考" in page
    assert "翻译全部信息" in page
    assert 'apiFetch<TranslateResponse>("/ops-ai/translate"' in page
    assert "messageTranslations[message.id]" in page
