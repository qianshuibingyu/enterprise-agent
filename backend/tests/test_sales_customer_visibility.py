"""业务员可见范围：运营转交给我的客户链路必须真的能看到。

回归的是「链路负责人是我，但我的工作台是 0 条」：原来业务员范围额外要求
`inquiries.department` 非空且等于本人部门，而 `department` 只记录入库时运营账号
的部门，老数据大量为空、跨部门转交也会不匹配，于是被转交的人看不到刚转给自己的客户。
PROJECT_SPEC §3.2 的口径是「业务员仅处理分配给本人的询盘」，部门不作为可见前提。

夹具现状：链路 3 已分配给业务员 sales(id=3) 并带一条消息；链路 2 属于 other-sales；
链路 4 的来源渠道已撤权，不应出现。
"""

from app.models.business import Inquiry
from app.models.user import User
from tests.test_business_authorization import business_client, login  # noqa: F401


def test_sales_sees_assigned_inquiry_without_department_mapping(business_client):
    with business_client.testing_session() as db:
        # 老数据里链路没有部门标注（入库时运营账号没设部门时就是这样）。
        db.get(Inquiry, 3).department = "  "
        db.commit()

    login(business_client, "sales", "salespass1")

    listing = business_client.get("/api/inquiries", params={"status": "assigned"})
    assert listing.status_code == 200
    assert {row["id"] for row in listing.json()["items"]} == {3}

    detail = business_client.get("/api/inquiries/3")
    assert detail.status_code == 200
    payload = detail.json()
    # 转交后必须能看到必要原始信息：联系人/联系方式/原文/来源渠道。
    assert payload["contact_sources"]
    assert payload["messages"], "业务员应能看到被转交链路的原始消息"
    # 原文（原始内容）必须可回溯，AI 摘要不能替代。
    content = business_client.get(f"/api/messages/{payload['messages'][0]['id']}/content")
    assert content.status_code == 200, content.text


def test_sales_sees_assigned_inquiry_from_another_department(business_client):
    with business_client.testing_session() as db:
        db.get(Inquiry, 3).department = "运营部"  # 与业务员所在部门不同
        db.commit()

    login(business_client, "sales", "salespass1")
    listing = business_client.get("/api/inquiries", params={"status": "assigned"})
    assert {row["id"] for row in listing.json()["items"]} == {3}


def test_sales_cannot_see_inquiries_owned_by_someone_else(business_client):
    login(business_client, "sales", "salespass1")
    listing = business_client.get("/api/inquiries", params={"status": "assigned"})
    ids = {row["id"] for row in listing.json()["items"]}
    assert ids == {3}, "只应看到负责人是自己的链路（链路 4 来源已撤权，也不应出现）"
    assert business_client.get("/api/inquiries/2").status_code in {403, 404}


def test_sales_without_department_stays_data_dark(business_client):
    """没有部门归属的业务员仍按 deny-by-default 处理。"""
    with business_client.testing_session() as db:
        db.get(User, 3).department = "  "
        db.commit()

    login(business_client, "sales", "salespass1")
    assert business_client.get("/api/inquiries", params={"status": "assigned"}).json()["items"] == []
