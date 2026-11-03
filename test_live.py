import json, unittest
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from lcu_bridge import normalize_session
from serve import Handler

class DraftTests(unittest.TestCase):
    def test_confirmed_only_and_no_identity(self):
        session={'localPlayerCellId':0,'myTeam':[{'cellId':0,'championId':103,'assignedPosition':'middle','puuid':'private'},{'cellId':1,'championId':54,'assignedPosition':'top'}],'theirTeam':[{'cellId':5,'championId':157,'assignedPosition':'top','summonerId':123}], 'actions':[[{'type':'pick','actorCellId':0,'championId':103,'completed':False},{'type':'pick','actorCellId':1,'championId':54,'completed':True},{'type':'pick','actorCellId':5,'championId':157,'completed':True},{'type':'ban','championId':238,'completed':True},{'type':'ban','championId':99,'completed':False}]],'bans':{'myTeamBans':[238,-1],'theirTeamBans':[84]}}
        result=normalize_session(session)
        self.assertEqual(result['ownChampionId'],0)
        self.assertEqual(result['ownRole'],'middle')
        self.assertEqual(result['allies'][1]['championId'],54)
        self.assertEqual(result['enemies'],[{'championId':157,'role':None}])
        self.assertEqual(result['bans'],[84,238])
        self.assertNotIn('private',json.dumps(result))
        self.assertNotIn('summonerId',json.dumps(result))

    def test_local_api_origin_and_read_only(self):
        class FakeBridge:
            def snapshot(self):return {'status':'disconnected'}
        class TestHandler(Handler):
            bridge=FakeBridge()
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),TestHandler)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}/api/draft'
        try:
            with urlopen(base) as r:self.assertEqual(json.load(r)['status'],'disconnected')
            for headers in [{'Origin':'https://example.com'},{'Host':'example.com'}]:
                with self.assertRaises(HTTPError) as e:urlopen(Request(base,headers=headers))
                self.assertEqual(e.exception.code,403)
                e.exception.close()
            with self.assertRaises(HTTPError) as e:urlopen(Request(base,data=b'{}',method='POST'))
            self.assertEqual(e.exception.code,501)
            e.exception.close()
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
