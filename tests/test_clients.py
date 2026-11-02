"""Wire-level checks for the two external clients, against mocked HTTP."""

import json

import anthropic
import httpx
import httpx2  # the Anthropic SDK 2.x HTTP stack
import pytest

from contentfactory.drafts import ChapterNames, JobConfig
from contentfactory.generators import Chapter, ClaudeGenerator, GenContext, GenerationError
from contentfactory.meetstream import (
    MeetStreamClient, MeetStreamNotReady, RecordingLookupError, classify_reference, normalize_meeting_link,
    resolve_recording, summarize_bot,
)


def claude_with(handler) -> ClaudeGenerator:
    client = anthropic.Anthropic(api_key="test", max_retries=0, http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    return ClaudeGenerator(model="claude-opus-5-5", effort="medium", client=client)


def message(text: str, stop_reason: str = "end_turn", **extra) -> dict:
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": text}], "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5}, **extra}


def ctx(transcript) -> GenContext:
    return GenContext(title="Meeting Agents", transcript=transcript, config=JobConfig(),
                      chapters=[Chapter(index=0, first=0, last=4), Chapter(index=1, first=5, last=9)])


def test_claude_request_shape_and_structured_parse(transcript):
    seen = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["body"] = json.loads(request.content)
        seen["beta"] = request.headers.get("anthropic-beta", "")
        out = {"chapters": [{"index": 0, "title": "Why Tools Aren't Agents", "summary": "s", "keywords": ["agents"]},
                            {"index": 1, "title": "Failing Gracefully", "summary": "s", "keywords": ["retries"]}]}
        return httpx2.Response(200, json=message(json.dumps(out)))

    names = claude_with(handler).name_chapters(ctx(transcript))
    assert isinstance(names, ChapterNames) and names.chapters[1].title == "Failing Gracefully"

    body = seen["body"]
    assert body["model"] == "claude-opus-5-5"
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"]["effort"] == "medium"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in seen["beta"]
    assert "temperature" not in body
    # The transcript is the cached prefix shared by every stage.
    system = body["system"]
    assert system[1]["cache_control"] == {"type": "ephemeral"}
    assert "[s0007 " in system[1]["text"] and "Dev Patel:" in system[1]["text"]
    # Chapter ranges are given to the model, not left for it to invent.
    assert "s0001..s0005" in body["messages"][0]["content"]


def test_claude_refusal_is_a_generation_error(transcript):
    def handler(request):
        return httpx2.Response(200, json=message("", stop_reason="refusal",
                                                stop_details={"type": "refusal", "category": "cyber", "explanation": None}))

    with pytest.raises(GenerationError, match="declined"):
        claude_with(handler).name_chapters(ctx(transcript))


def test_claude_auth_error_is_explained(transcript):
    def handler(request):
        return httpx2.Response(401, json={"type": "error", "error": {"type": "authentication_error", "message": "bad key"}})

    with pytest.raises(GenerationError, match="credentials"):
        claude_with(handler).name_chapters(ctx(transcript))


def test_meetstream_uses_token_auth_and_reports_processing():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, request.headers.get("authorization")))
        if request.url.path.endswith("/get_video"):
            return httpx.Response(202, json={"message": "processing"})
        if request.url.path == "/api/v1/bots":
            return httpx.Response(200, json={"bots": [{"BotID": "b1", "Status": "Stopped", "Platform": "Zoom"}],
                                             "hasNextPage": False})
        return httpx.Response(404, json={})

    client = MeetStreamClient("key123", transport=httpx.MockTransport(handler))
    bots = client.list_bots(platform="Zoom")["bots"]
    assert summarize_bot(bots[0])["bot_id"] == "b1"
    with pytest.raises(MeetStreamNotReady):
        client.get_video("b1")
    assert calls[0] == ("/api/v1/bots", "Token key123")


# ---------------------------------------------------------------- resolving MeetStream links

UUID = "0c0f8353-ad37-43af-ac53-322f23d44743"


@pytest.mark.parametrize("a,b", [
    ("https://zoom.us/j/1234567890?pwd=abc", "https://us02web.zoom.us/j/1234567890"),
    ("https://meet.google.com/abc-defg-hij", "HTTPS://Meet.Google.com/abc-defg-hij/?authuser=1"),
    ("https://teams.microsoft.com/l/meetup-join/19%3ameeting_X%40thread.v2/0?context=1",
     "https://teams.microsoft.com/l/meetup-join/19:meeting_X@thread.v2/0"),
])
def test_meeting_links_normalize_to_the_same_key(a, b):
    assert normalize_meeting_link(a) == normalize_meeting_link(b) is not None


def test_classify_reference():
    assert classify_reference(UUID) == ("bot_id", UUID)
    assert classify_reference(f"https://app.meetstream.ai/bots/{UUID}?tab=video") == ("meetstream_url", UUID)
    assert classify_reference(f"https://api.meetstream.ai/api/v1/bots/{UUID}/detail")[1] == UUID
    assert classify_reference("https://meet.google.com/abc-defg-hij")[0] == "meeting_link"
    with pytest.raises(RecordingLookupError, match="doesn't contain a bot id"):
        classify_reference("https://app.meetstream.ai/dashboard")
    with pytest.raises(RecordingLookupError, match="Not a MeetStream link"):
        classify_reference("https://www.youtube.com/watch?v=x")


def bots_client(pages: list[dict], calls: list | None = None) -> MeetStreamClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(dict(request.url.params))
        i = min(len(calls or [None]) - 1, len(pages) - 1) if calls is not None else 0
        return httpx.Response(200, json=pages[i])
    return MeetStreamClient("k", transport=httpx.MockTransport(handler))


LINK = "https://meet.google.com/abc-defg-hij"


def bot(bot_id, status, created, link=LINK):
    return {"bot_id": bot_id, "status": status, "meeting_link": link, "created_at": created}


def test_meeting_link_resolves_to_newest_finished_recording():
    page = {"bots": [bot("old", "Stopped", "2026-10-01T10:00:00Z"),
                     bot("new", "Done", "2026-10-20T10:00:00Z"),
                     bot("live", "InMeeting", "2026-10-27T10:00:00Z"),
                     bot("other", "Done", "2026-10-25T10:00:00Z", link="https://zoom.us/j/999")],
            "hasNextPage": False}
    r = resolve_recording(bots_client([page]), LINK + "?authuser=0")
    assert (r.bot_id, r.resolved_from) == ("new", "meeting_link")
    assert {b["bot_id"] for b in r.other_matches} == {"old", "live"}


def test_meeting_link_with_only_a_live_bot_or_a_denied_bot():
    live = {"bots": [bot("b", "InMeeting", "2026-10-27T10:00:00Z")], "hasNextPage": False}
    with pytest.raises(RecordingLookupError, match="still in that meeting"):
        resolve_recording(bots_client([live]), LINK)
    denied = {"bots": [bot("b", "NotAllowed", "2026-10-27T10:00:00Z")], "hasNextPage": False}
    with pytest.raises(RecordingLookupError, match="didn't record it"):
        resolve_recording(bots_client([denied]), LINK)
    with pytest.raises(RecordingLookupError, match="No MeetStream bot has joined"):
        resolve_recording(bots_client([{"bots": [], "hasNextPage": False}]), LINK)


def test_meeting_link_search_follows_pages_and_stops_if_cursor_is_ignored():
    calls: list = []
    p1 = {"bots": [bot("a", "Done", "2026-10-01", link="https://zoom.us/j/1")], "hasNextPage": True, "nextCursor": "c1"}
    p2 = {"bots": [bot("b", "Done", "2026-10-02")], "hasNextPage": True, "nextCursor": "c2"}
    r = resolve_recording(bots_client([p1, p2, p2], calls), LINK)
    assert r.bot_id == "b"
    assert calls[1].get("cursor") == "c1"
    assert len(calls) == 3  # third call returned page 2 again (no new bots), so it stopped


def test_meeting_link_falls_back_to_bot_detail_when_list_omits_links():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/bots":
            return httpx.Response(200, json={"bots": [{"BotID": "x1", "Status": "Done"}, {"BotID": "x2", "Status": "Done"}],
                                             "hasNextPage": False})
        bot_id = request.url.path.split("/")[-2]
        link = LINK if bot_id == "x2" else "https://zoom.us/j/1"
        return httpx.Response(200, json={"bot_details": {"BotID": bot_id, "MeetingLink": link, "Status": "Stopped",
                                                         "CreatedAt": "2026-10-20T10:00:00Z"}})

    r = resolve_recording(MeetStreamClient("k", transport=httpx.MockTransport(handler)), LINK)
    assert r.bot_id == "x2"


def test_bot_id_and_meetstream_url_need_no_api_call():
    def handler(request):
        raise AssertionError("no API call expected")
    client = MeetStreamClient("k", transport=httpx.MockTransport(handler))
    assert resolve_recording(client, UUID).bot_id == UUID
    assert resolve_recording(client, f"https://app.meetstream.ai/bots/{UUID}").resolved_from == "meetstream_url"
