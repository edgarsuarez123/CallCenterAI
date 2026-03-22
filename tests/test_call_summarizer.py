"""Unit tests for call_summarizer."""

from unittest.mock import MagicMock, patch

import pytest

from Clinic_app.services import call_summarizer


@pytest.mark.unit
def test_summarize_empty_transcript() -> None:
    assert "no usable transcript" in call_summarizer.summarize_transcript_sync(
        "", "diabetes_hba1c"
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
                "Agent: Hello\nUser: Yes book me", "hypertension_control"
            )
    assert "follow-up" in out.lower()
    mock_client.messages.create.assert_called_once()
