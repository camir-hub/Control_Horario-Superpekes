import pytest
from app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_login_page_loads(client):
    response = client.get('/login')
    assert response.status_code == 200
    assert b'login' in response.data.lower()

def test_admin_login_page_loads(client):
    response = client.get('/admin-login')
    assert response.status_code == 200
    assert b'admin' in response.data.lower()

def test_calendar_requires_login(client):
    response = client.get('/calendar', follow_redirects=True)
    assert b'login' in response.data.lower()
