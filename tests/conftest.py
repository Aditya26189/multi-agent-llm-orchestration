import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from core.context import SharedContext
from core.budget import ContextBudgetManager


@pytest.fixture
def context():
    return SharedContext(query="test query")


@pytest.fixture
def budget_mgr(context):
    return ContextBudgetManager(context)


@pytest.fixture
def mock_gemini():
    """Mock google.generativeai for tests that don't need real LLM."""
    with patch("google.generativeai.GenerativeModel") as mock:
        model_instance = MagicMock()
        response = MagicMock()
        response.text = '{"result": "mocked response"}'
        model_instance.generate_content = MagicMock(return_value=response)
        mock.return_value = model_instance
        yield model_instance


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
