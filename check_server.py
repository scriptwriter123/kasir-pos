import urllib.request, re

response = urllib.request.urlopen('http://127.0.0.1:8001/', timeout=10)
html = response.read().decode()
print('STATUS:', response.status)
print('Chatbot widget:', 'chatbot' in html.lower())
wa = re.search(r'https://wa\.me/[^\s"]+', html)
print('WhatsApp link:', 'FOUND' if wa else 'NOT FOUND', '--', wa.group() if wa else '')