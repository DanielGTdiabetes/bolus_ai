
import pytest
from unittest.mock import Mock, AsyncMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.nightscout_secrets_service import upsert_ns_config, get_ns_config, delete_ns_config
from app.models.nightscout_secrets import NightscoutSecrets
from app.api.nightscout_secrets import put_secret, SecretPayload, get_secret_status, SecretResponse

# Mocks
@pytest.fixture
def mock_session():
    session = AsyncMock(spec=AsyncSession)
    # execute need to return a result that behaves like ScalarResult
    return session

@pytest.fixture
def mock_crypto():
    with patch("app.services.nightscout_secrets_service.encrypt", side_effect=lambda x: f"ENC_{x}") as mock_enc, \
         patch("app.services.nightscout_secrets_service.decrypt", side_effect=lambda x: x.replace("ENC_", "")) as mock_dec:
        yield mock_enc, mock_dec

@pytest.mark.asyncio
async def test_upsert_and_get_secrets(mock_session, mock_crypto):
    # Test Service Logic via mocking DB interaction
    user_id = "testuser"
    url = "http://example.com"
    secret = "mysecret"

    # Assume session.execute returns empty first (not found)
    mock_result = Mock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    # 1. Upsert (Create)
    await upsert_ns_config(mock_session, user_id, url, secret, True)
    
    # Verify add called
    assert mock_session.add.called
    args, _ = mock_session.add.call_args
    obj = args[0]
    assert isinstance(obj, NightscoutSecrets)
    assert obj.user_id == user_id
    assert obj.ns_url == "https://example.com/" # logic adds https and trailing slash
    assert obj.api_secret_enc == "ENC_mysecret"
    
    # 2. Get (Found)
    # Mock return value
    mock_result.scalar_one_or_none.return_value = obj
    
    config = await get_ns_config(mock_session, user_id)
    assert config is not None
    assert config.url == "https://example.com/"
    assert config.api_secret == "mysecret"
    assert config.enabled is True

@pytest.mark.asyncio
async def test_api_integration(mock_session):
    # Test API endpoint logic (mocking service calls if we wanted, or deeper)
    # We will test the API function generic flow
    
    user = Mock()
    user.username = "api_user"
    
    payload = SecretPayload(url="nightscout.test", api_secret="s3cr3t", enabled=True)
    
    # Since we can't easily mock the internal upsert call without patching the module locally:
    with patch("app.api.nightscout_secrets.upsert_ns_config", new_callable=AsyncMock) as mock_upsert:
        resp = await put_secret(payload, user=user, session=mock_session)
        assert resp == {"success": True}
        mock_upsert.assert_called_with(mock_session, "api_user", "nightscout.test", "s3cr3t", True)

    with patch("app.api.nightscout_secrets.get_ns_config", new_callable=AsyncMock) as mock_get:
        # Case: Config exists
        mock_get.return_value = Mock(url="https://ns.test", enabled=True)
        
        status = await get_secret_status(user=user, session=mock_session)
        assert isinstance(status, SecretResponse)
        assert status.enabled is True
        assert status.url == "https://ns.test"
        assert status.has_secret is True
        
        # Case: No config
        mock_get.return_value = None
        status = await get_secret_status(user=user, session=mock_session)
        assert status.has_secret is False
        assert status.url is None

