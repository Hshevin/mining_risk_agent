from fastapi.testclient import TestClient

from mining_risk_serve.api.main import create_app


def test_knowledge_system_overview_read_only_shape():
    client = TestClient(create_app())

    resp = client.get("/api/v1/knowledge/system/overview")

    assert resp.status_code == 200
    body = resp.json()
    assert body["overview"]["audit_status"] == "PASS_WITH_WARNINGS"
    assert body["overview"]["kb_file_count"] == 6
    assert body["overview"]["rag_chunks"] == 639
    assert len(body["knowledge_bases"]) == 6
    assert body["agentfs"]["sync_script_name"] == "scripts/sync_kb_to_agentfs.py"
    assert body["agentfs"]["fs_agentfs_match"] is True
    assert body["rag_index"]["collection_name"] == "knowledge_base"


def test_knowledge_rag_search_read_only_shape():
    client = TestClient(create_app())

    resp = client.get("/api/v1/knowledge/rag/search", params={"q": "粉尘涉爆除尘系统异常"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "粉尘涉爆除尘系统异常"
    assert body["embedding_backend"] == "fallback"
    assert isinstance(body["results"], list)
    assert body["results"]
    first = body["results"][0]
    for key in ("source_file", "section_title", "doc_type", "matched_text"):
        assert key in first
