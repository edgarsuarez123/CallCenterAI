"""Unit tests for call_summarizer."""

from unittest.mock import MagicMock, patch

import pytest

from Clinic_app.services import call_summarizer


@pytest.mark.unit
def test_summarize_empty_transcript() -> None:
    assert "no usable transcript" in call_summarizer.summarize_transcript_sync(
        "", "colorectal"
    ).lower()


@pytest.mark.unit
def test_summarize_with_mock_claude() -> None:
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=" Patient scheduled a follow-up visit. ")]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_msg

    with patch.object(call_summarizer, "_get_anthropic_client", return_value=mock_client):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "x"}):
            out = call_summarizer.summarize_transcript_sync(
                "Agent: Hello\nUser: Yes book me", "preventive_visit"
            )
    assert "follow-up" in out.lower()
    mock_client.messages.create.assert_called_once()


@pytest.mark.unit
def test_extract_order_notes_empty_transcript() -> None:
    out = call_summarizer.extract_order_based_notes_sync("", "colorectal")
    assert out["patient_agreed"] is None
    assert "no usable transcript" in out["note"].lower()


@pytest.mark.unit
def test_extract_order_notes_with_mock_claude() -> None:
    payload = (
        '{"patient_agreed": true, "action_for_staff": "Send kit", '
        '"note": "Patient agreed to mail the kit."}'
    )
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=payload)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_msg

    with patch.object(call_summarizer, "_get_anthropic_client", return_value=mock_client):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "x"}):
            out = call_summarizer.extract_order_based_notes_sync(
                "Agent: Offer kit\nUser: Yes", "colorectal"
            )
    assert out["patient_agreed"] is True
    assert out["action_for_staff"] == "Send kit"
    assert "agreed" in out["note"].lower()
    mock_client.messages.create.assert_called_once()


@pytest.mark.unit
def test_extract_order_notes_unparseable_returns_fallback() -> None:
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text="not json at all {{{")]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_msg

    with patch.object(call_summarizer, "_get_anthropic_client", return_value=mock_client):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "x"}):
            out = call_summarizer.extract_order_based_notes_sync(
                "some transcript", "colorectal"
            )
    assert out["patient_agreed"] is None
    assert "unavailable" in out["note"].lower()
