from pathlib import Path
import sys

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from remote.noconfig import app as noconfig_app
from remote.noconfig.user_store import user_store


def setup_function():
    user_store.clear()
    noconfig_app.configure(
        {
            "api_token": "test-token",
            "admin_username": "admin",
            "admin_password": "Aa123456",
            "port": 8002,
        }
    )


def teardown_function():
    user_store.clear()


def test_admin_requires_login():
    client = TestClient(noconfig_app.app)

    response = client.get("/admin")

    assert response.status_code == 200
    assert "后台登录" in response.text
    assert "多用户管理" not in response.text


def test_admin_login_success_and_remember_cookie():
    client = TestClient(noconfig_app.app)

    login_response = client.post(
        "/admin/login",
        json={"username": "admin", "password": "Aa123456", "remember": True},
    )

    assert login_response.status_code == 200
    assert login_response.json()["status"] == "ok"
    assert "mj_admin_auth=" in login_response.headers.get("set-cookie", "")
    assert "Max-Age=" in login_response.headers.get("set-cookie", "")

    page_response = client.get("/admin")

    assert page_response.status_code == 200
    assert "多用户管理" in page_response.text
    assert "已登录账号" in page_response.text
    assert "token-input" not in page_response.text


def test_admin_login_rejects_invalid_password():
    client = TestClient(noconfig_app.app)

    response = client.post(
        "/admin/login",
        json={"username": "admin", "password": "wrong-password", "remember": False},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid username or password"


def test_admin_logout_clears_cookie():
    client = TestClient(noconfig_app.app)
    client.post(
        "/admin/login",
        json={"username": "admin", "password": "Aa123456", "remember": False},
    )

    logout_response = client.get("/admin/logout", follow_redirects=False)

    assert logout_response.status_code == 303
    assert logout_response.headers["location"] == "/admin"
    assert "mj_admin_auth=" in logout_response.headers.get("set-cookie", "")
