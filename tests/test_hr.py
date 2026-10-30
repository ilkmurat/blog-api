from app.config import get_settings
from app.hr import chunk_pages
from tests.conftest import login
from tests.pdf import make_pdf
from tests.test_auth_likes import MEMBER, member_client
from tests.test_mcp import call

LEAVE = make_pdf([
    ["Annual leave policy", "Employees get 14 working days of annual leave per year.",
     "Unused annual leave can be carried over to the next year."],
    ["Sick leave", "Sick leave requires a doctor report after 2 days."],
])
REMOTE = make_pdf([["Remote work", "Employees may work remotely two days per week with manager approval."]])


def upload(client, data=LEAVE, filename="leave.pdf", **form):
    return client.post("/api/v1/hr/documents", files={"file": (filename, data, "application/pdf")}, data=form)


def test_chunking_respects_size_overlap_and_pages():
    text = " ".join(f"Sentence number {i} about leave rules." for i in range(120))
    chunks = chunk_pages([text, "", "Short page."], size=300, overlap=60)
    assert all(len(c.text) <= 300 for c in chunks)
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert chunks[-1].page == 3 and chunks[-1].text == "Short page."
    first, second = chunks[0].text, chunks[1].text
    assert second.split(" ")[0] in first[-60:]  # tail overlap carried over


def test_upload_processes_pdf(client):
    r = upload(client, title="İzin Politikası", topic="İzin")
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "processing" and r.json()["uploaded_by"] == "murat"
    doc = client.get(f"/api/v1/hr/documents/{r.json()['id']}").json()  # background task already ran
    assert doc["status"] == "ready" and doc["pages"] == 2 and doc["chunk_count"] >= 2
    assert doc["title"] == "İzin Politikası" and doc["topic"] == "İzin"


def test_defaults_title_and_topic(client):
    doc = upload(client, filename="Uzaktan Calisma.pdf").json()
    assert doc["title"] == "Uzaktan Calisma" and doc["topic"] == "Genel"


def test_rejects_non_pdf_and_large_files(client):
    assert upload(client, data=b"hello", filename="x.txt").status_code == 415
    settings = get_settings()
    old, settings.hr_max_upload_mb = settings.hr_max_upload_mb, 0
    try:
        assert upload(client).status_code == 413
    finally:
        settings.hr_max_upload_mb = old


def test_pdf_without_text_fails_cleanly(client):
    doc_id = upload(client, data=make_pdf([[]]), filename="scan.pdf").json()["id"]
    doc = client.get(f"/api/v1/hr/documents/{doc_id}").json()
    assert doc["status"] == "failed" and "No extractable text" in doc["error"]


def test_hr_endpoints_are_admin_only(anon):
    member = member_client(anon)
    for c, code in ((anon, 401), (member, 403)):
        assert upload(c).status_code == code
        assert c.get("/api/v1/hr/documents").status_code == code
        assert c.delete("/api/v1/hr/documents/1").status_code == code


def test_hr_search_requires_login(client, anon):
    upload(client)
    err, msg = call(anon, "hr_search", {"query": "annual leave"})
    assert err and "logged-in" in msg
    err, msg = call(anon, "hr_list_documents")
    assert err

    anon.post("/api/v1/auth/register", json=MEMBER)
    member = login(anon, "ayse", "x")
    err, body = call(anon, "hr_search", {"query": "annual leave days"}, member)
    assert not err
    top = body["passages"][0]
    assert top["document"] == "leave" and top["page"] == 1 and "14 working days" in top["text"]
    err, body = call(anon, "hr_list_documents", {}, member)
    assert body == {"documents": [{"title": "leave", "topic": "Genel", "pages": 2}]}


def test_topic_filter_and_delete(client, anon):
    upload(client, topic="İzin")
    remote_id = upload(client, data=REMOTE, filename="remote.pdf", topic="Uzaktan Çalışma").json()["id"]
    admin = login(anon)
    _, body = call(anon, "hr_search", {"query": "remote work days", "topic": "İzin"}, admin)
    assert {p["topic"] for p in body["passages"]} == {"İzin"}
    _, body = call(anon, "hr_search", {"query": "remote work days"}, admin)
    assert body["passages"][0]["document"] == "remote"

    assert client.delete(f"/api/v1/hr/documents/{remote_id}").status_code == 204
    assert client.get(f"/api/v1/hr/documents/{remote_id}").status_code == 404
    _, body = call(anon, "hr_search", {"query": "remote work days", "limit": 10}, admin)
    assert all(p["document"] != "remote" for p in body["passages"])
    assert [d["topic"] for d in client.get("/api/v1/hr/documents").json()] == ["İzin"]


def test_search_with_no_documents(anon):
    anon.post("/api/v1/auth/register", json=MEMBER)
    _, body = call(anon, "hr_search", {"query": "izin"}, login(anon, "ayse", "x"))
    assert body["passages"] == [] and "No HR documents" in body["note"]
