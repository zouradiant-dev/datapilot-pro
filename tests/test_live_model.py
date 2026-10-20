import os

import pytest

from datapilot.config import Settings
from datapilot.graph import run_question


@pytest.mark.live
@pytest.mark.integration
async def test_real_model_postgres_workflow(pg_settings):
    if os.getenv("DATAPILOT_RUN_LIVE_TESTS") != "1":
        pytest.skip("Live model inference requires DATAPILOT_RUN_LIVE_TESTS=1 and API credentials")
    settings = Settings(llm_mode="live")
    result = await run_question(settings, "查询客户总数")
    assert result["mode"] == "live" and result["status"] == "succeeded", result["error"]
    assert result["result"].result.rows == [[240]]
