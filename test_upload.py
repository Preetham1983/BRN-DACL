import requests

url = "http://localhost:8000/api/upload"
files = {
    'file': ('dacl_test_rules.txt', open(r'c:\Users\BandiPreethamReddy\Desktop\BRN\dacl_agent\temp\dacl_test_rules.txt', 'rb'), 'text/plain')
}
data = {
    'company': 'test',
    'domain': 'test_domain',
    'description': '',
    'force': 'true',
    'strict_verify': 'false',
    'changed_by': 'admin',
    'change_note': ''
}
try:
    response = requests.post(url, files=files, data=data)
    print("STATUS:", response.status_code)
    print("BODY:", response.text)
except Exception as e:
    print("REQ ERROR:", e)
