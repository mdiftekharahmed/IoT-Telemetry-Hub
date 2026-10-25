import urllib.request
import json

login_url = "http://localhost/api/cc/auth/login"
login_data = json.dumps({"username": "admin", "password": "admin123"}).encode()
req = urllib.request.Request(login_url, data=login_data, headers={"Content-Type": "application/json"})
token = json.loads(urllib.request.urlopen(req).read().decode())["access_token"]

forecast_url = "http://localhost/api/ml/forecast/1"
req = urllib.request.Request(forecast_url, headers={"Authorization": f"Bearer {token}"})
res = json.loads(urllib.request.urlopen(req).read().decode())
print("FORECAST_RESULT:", json.dumps(res, indent=2))

health_url = "http://localhost/api/ml/health/1"
req = urllib.request.Request(health_url, headers={"Authorization": f"Bearer {token}"})
res_health = json.loads(urllib.request.urlopen(req).read().decode())
print("HEALTH_RESULT:", json.dumps(res_health, indent=2))
