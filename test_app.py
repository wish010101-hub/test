import os
import tempfile
os.environ['MEDIA_ROOT'] = tempfile.mkdtemp(prefix='framesave-tests-')
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import app
from security import canonical_url, public_ip
from worker import choices

@pytest.mark.parametrize('url',[
 'http://youtube.com/watch?v=BaW_jenozKc', 'https://127.0.0.1/',
 'https://youtube.com.evil.test/watch?v=BaW_jenozKc',
 'https://youtube.com@127.0.0.1/watch?v=BaW_jenozKc',
 'https://www.youtube.com:8443/watch?v=BaW_jenozKc',
 'https://instagram.com/accounts/login/', 'file:///etc/passwd',
 'https://youtube.com/watch?v=BaW_jenozKc&v=BaW_jenozKc',
 'https://youtube.com/shorts/BaW_jenozKc/../../admin',
 'https://youtube.com\\@127.0.0.1/',
])
def test_bad_url(url):
 with pytest.raises(ValueError): canonical_url(url)

@pytest.mark.parametrize('url',[
 'https://youtube.com/watch?v=BaW_jenozKc',
 'https://youtu.be/BaW_jenozKc?si=abc',
 'https://youtube.com/shorts/BaW_jenozKc',
 'https://www.instagram.com/reel/ABC123_-/'])
def test_good_url(url): assert canonical_url(url).startswith('https://www.')

@pytest.mark.parametrize('ip',['127.0.0.1','10.0.0.1','169.254.169.254','::1','::ffff:127.0.0.1','224.0.0.1','fc00::1','100.64.0.1'])
def test_private(ip): assert not public_ip(ip)

def test_formats():
 formats=choices({'formats':[{'format_id':'18','protocol':'https','ext':'mp4','height':360,'vcodec':'avc1','acodec':'aac'}, {'format_id':'bad','protocol':'m3u8_native','ext':'mp4','height':1080,'vcodec':'avc1','acodec':'aac'}, {'format_id':'drm','protocol':'https','ext':'mp4','height':720,'vcodec':'avc1','acodec':'aac','has_drm':True}]})
 assert {f['id'] for f in formats} == {'mp4-360','mp3'}

def test_api_and_cleanup():
 app.rates.clear()
 with TestClient(app.app) as c:
  assert c.get('/health').json()=={'status':'ok'}
  assert c.get('/').status_code==200
  assert c.post('/api/info',json={'url':'https://localhost','rights':True}).status_code==400
  assert c.post('/api/info',json={'url':'https://youtu.be/BaW_jenozKc','rights':False}).status_code==400
  assert c.post('/api/info',json={'url':'x'*5000,'rights':True}).status_code==413
  assert c.post('/api/info',json={'url':'x','rights':True},headers={'Origin':'https://evil.test'}).status_code==403
  assert c.get('/api/status/absent').status_code==404
  assert c.get('/api/file/absent').status_code==404
  assert c.post('/api/download',json={'ticket':'absent','index':0,'format':'mp3'}).status_code==410
  for _ in range(6): c.post('/api/info',json={'url':'bad','rights':True})
  assert c.post('/api/info',json={'url':'bad','rights':True}).status_code==429
  path=app.ROOT/'expired';path.mkdir();(path/'media.mp4').write_bytes(b'x')
  app.jobs['expired']={'status':'ready','finished':time.time()-app.TTL-1}
  app.cleanup()
  assert not path.exists() and 'expired' not in app.jobs

def test_blocked_connect(monkeypatch):
 import socket
 from security import install_network_guard
 original, original_ex = socket.socket.connect,socket.socket.connect_ex
 try:
  install_network_guard()
  with socket.socket() as s:
   with pytest.raises(OSError): s.connect(('127.0.0.1',80))
   with pytest.raises(OSError): s.connect(('169.254.169.254',80))
 finally:
  socket.socket.connect, socket.socket.connect_ex = original, original_ex
