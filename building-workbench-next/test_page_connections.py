"""A cold pair of tabs must not overflow the HTTP connection accept backlog."""
import socket,unittest
from http.server import BaseHTTPRequestHandler
from server import WorkbenchHTTPServer

class PageConnectionsTests(unittest.TestCase):
    def test_parallel_assets_can_wait_until_handler_accepts(self):
        server=WorkbenchHTTPServer(('127.0.0.1',0),BaseHTTPRequestHandler)
        clients=[]
        try:
            # Do not serve yet: connections must fit in the actual listening
            # queue rather than relying on fast handlers during this test.
            for _ in range(16):clients.append(socket.create_connection(server.server_address,timeout=1))
            self.assertEqual(len(clients),16)
        finally:
            for client in clients:client.close()
            server.server_close()

if __name__=='__main__':unittest.main()
