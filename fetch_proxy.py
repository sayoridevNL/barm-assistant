import urllib.request, json
data = json.loads(urllib.request.urlopen("https://proxylist.geonode.com/api/proxy-list?limit=10&page=1&sort_by=lastChecked&sort_type=desc&protocols=http%2Chttps").read())
for p in data['data']:
    print(f"http://{p['ip']}:{p['port']}")
