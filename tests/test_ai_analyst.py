import pytest
import json
from unittest.mock import MagicMock, patch
from early_detector.analyst import analyze_token_signal

# Mock data
TOKEN_DATA = {
    "symbol": "TEST",
    "address": "So111...",
    "price": 0.001,
    "marketcap": 100000,
    "liquidity": 50000,
    "holders": 100,
}
HISTORY = []

@pytest.fixture
def anyio_backend():
    return 'asyncio'

@pytest.fixture
def mock_genai():
    with patch("early_detector.analyst.genai") as mock:
        yield mock

@pytest.fixture
def mock_genai_old():
    with patch("early_detector.analyst.genai_old") as mock:
        yield mock

@pytest.mark.anyio
async def test_analyze_token_clean_json(mock_genai):
    # Mock clean JSON response
    mock_response = MagicMock()
    mock_response.text = '{"verdict": "BUY", "confidence": 90, "risk_level": "LOW", "reasoning": "Good metrics"}'
    
    mock_client = mock_genai.Client.return_value
    mock_client.models.generate_content.return_value = mock_response
    
    result = await analyze_token_signal(TOKEN_DATA, HISTORY)
    assert result["verdict"] == "BUY"
    assert result["confidence"] == 90

@pytest.mark.anyio
async def test_analyze_token_markdown_json(mock_genai):
    # Mock markdown wrapped JSON
    mock_response = MagicMock()
    mock_response.text = '```json\n{"verdict": "WAIT", "confidence": 50, "risk_level": "MEDIUM", "reasoning": "Uncertain"}\n```'
    
    mock_client = mock_genai.Client.return_value
    mock_client.models.generate_content.return_value = mock_response
    
    result = await analyze_token_signal(TOKEN_DATA, HISTORY)
    assert result["verdict"] == "WAIT"

@pytest.mark.anyio
async def test_analyze_token_messy_text(mock_genai):
    # Mock text with extra noise
    mock_response = MagicMock()
    # ... (rest is same)
    mock_response.text = 'Here is the analysis: {"verdict": "AVOID", "confidence": 10, "risk_level": "HIGH", "reasoning": "Bad"} Hope this helps!'
    
    mock_client = mock_genai.Client.return_value
    mock_client.models.generate_content.return_value = mock_response
    
    result = await analyze_token_signal(TOKEN_DATA, HISTORY)
    assert result["verdict"] == "AVOID"
