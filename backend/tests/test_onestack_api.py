"""
測試 onestack_api.py 四類 Supabase filter 封裝的參數傳遞正確性
使用 mock request_fn 驗證，不依賴真實 DB。
"""
import pytest
from unittest.mock import AsyncMock

from app.core.onestack_api import (
    _patch_by_id,
    _query_pending,
    _upsert,
    get_device_info,
)


@pytest.fixture
def mock_request():
    """建立可追蹤呼叫的 mock request_fn"""
    return AsyncMock()


# ─── 1. PATCH by id ───


class TestPatchById:
    async def test_params_contain_eq_filter(self, mock_request):
        mock_request.return_value = None
        await _patch_by_id(mock_request, "cli_tasks", "task-42", {"status": "done"})

        mock_request.assert_called_once_with(
            "PATCH",
            "cli_tasks",
            params={"id": "eq.task-42"},
            json_data={"status": "done"},
        )

    async def test_numeric_id(self, mock_request):
        mock_request.return_value = None
        await _patch_by_id(mock_request, "aegis_commands", 99, {"status": "ok"})

        mock_request.assert_called_once_with(
            "PATCH",
            "aegis_commands",
            params={"id": "eq.99"},
            json_data={"status": "ok"},
        )

    async def test_returns_request_result(self, mock_request):
        mock_request.return_value = {"id": "x"}
        result = await _patch_by_id(mock_request, "t", "x", {})
        assert result == {"id": "x"}


# ─── 2. Pending poll ───


class TestQueryPending:
    async def test_default_limit(self, mock_request):
        mock_request.return_value = []
        await _query_pending(mock_request, "cli_tasks", "dev-1")

        mock_request.assert_called_once_with(
            "GET",
            "cli_tasks",
            params={
                "device_id": "eq.dev-1",
                "status": "eq.pending",
                "order": "created_at.asc",
                "limit": "10",
            },
        )

    async def test_custom_limit(self, mock_request):
        mock_request.return_value = []
        await _query_pending(mock_request, "cli_tasks", "dev-1", limit=5)

        args = mock_request.call_args
        assert args.kwargs["params"]["limit"] == "5"

    async def test_returns_list(self, mock_request):
        rows = [{"id": 1}, {"id": 2}]
        mock_request.return_value = rows
        result = await _query_pending(mock_request, "t", "d")
        assert result == rows

    async def test_non_list_returns_empty(self, mock_request):
        mock_request.return_value = None
        result = await _query_pending(mock_request, "t", "d")
        assert result == []

    async def test_non_list_dict_returns_empty(self, mock_request):
        mock_request.return_value = {"error": "bad"}
        result = await _query_pending(mock_request, "t", "d")
        assert result == []


# ─── 3. Upsert ───


class TestUpsert:
    async def test_on_conflict_and_prefer_header(self, mock_request):
        mock_request.return_value = None
        rows = [{"device_id": "d1", "name": "Alice"}]
        await _upsert(mock_request, "members", "device_id,aegis_member_id", rows)

        mock_request.assert_called_once_with(
            "POST",
            "members?on_conflict=device_id,aegis_member_id",
            json_data=rows,
            prefer_override="resolution=merge-duplicates,return=minimal",
        )

    async def test_empty_rows_skips_request(self, mock_request):
        result = await _upsert(mock_request, "t", "id", [])
        assert result is None
        mock_request.assert_not_called()

    async def test_multiple_rows(self, mock_request):
        mock_request.return_value = None
        rows = [{"id": 1}, {"id": 2}, {"id": 3}]
        await _upsert(mock_request, "t", "id", rows)

        call_json = mock_request.call_args.kwargs["json_data"]
        assert len(call_json) == 3


# ─── 4. Device query ───


class TestGetDeviceInfo:
    async def test_default_select(self, mock_request):
        mock_request.return_value = [{"id": "dev-1", "device_name": "My PC"}]
        result = await get_device_info(mock_request, "dev-1")

        mock_request.assert_called_once_with(
            "GET",
            "cli_devices",
            params={
                "id": "eq.dev-1",
                "select": "id,device_name",
            },
        )
        assert result == {"id": "dev-1", "device_name": "My PC"}

    async def test_custom_select(self, mock_request):
        mock_request.return_value = [{"id": "dev-1", "owner_id": "u1"}]
        result = await get_device_info(mock_request, "dev-1", select="id,owner_id")

        assert mock_request.call_args.kwargs["params"]["select"] == "id,owner_id"
        assert result == {"id": "dev-1", "owner_id": "u1"}

    async def test_empty_list_returns_none(self, mock_request):
        mock_request.return_value = []
        result = await get_device_info(mock_request, "dev-x")
        assert result is None

    async def test_none_returns_none(self, mock_request):
        mock_request.return_value = None
        result = await get_device_info(mock_request, "dev-x")
        assert result is None

    async def test_unwraps_first_element(self, mock_request):
        mock_request.return_value = [{"id": "a"}, {"id": "b"}]
        result = await get_device_info(mock_request, "a")
        assert result == {"id": "a"}
