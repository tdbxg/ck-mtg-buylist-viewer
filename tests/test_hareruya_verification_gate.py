import unittest
import sys
from pathlib import Path
from unittest.mock import patch
from threading import Event
from urllib.error import HTTPError

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from verify_hareruya_versions import protected_capture


class VerificationGateTests(unittest.TestCase):
    @patch("verify_hareruya_versions.time.sleep")
    def test_purchase_access_denial_stops_queued_requests(self, sleep):
        retail, source = Event(), Event()
        denied = HTTPError("https://www.hareruyamtg.com/",403,"Forbidden",{},None)
        with patch("verify_hareruya_versions.capture_detail",side_effect=denied) as request:
            with self.assertRaises(HTTPError):
                protected_capture({},"2026-11-15T12:00:00Z",retail,source)
            self.assertIsNone(protected_capture({},"2026-11-15T12:00:00Z",retail,source))
        self.assertTrue(source.is_set())
        self.assertEqual(request.call_count,1)
        denied.close()

    @patch("verify_hareruya_versions.time.sleep")
    def test_sale_access_denial_stops_sale_requests_not_valid_buy_capture(self,sleep):
        retail, source = Event(), Event()
        with patch("verify_hareruya_versions.capture_detail",return_value={"saleCaptureError":"HTTPError: HTTP Error 403: Forbidden"}) as request:
            protected_capture({},"2026-11-15T12:00:00Z",retail,source)
            protected_capture({},"2026-11-15T12:00:00Z",retail,source)
        self.assertTrue(retail.is_set())
        self.assertFalse(source.is_set())
        self.assertFalse(request.call_args.args[2])


if __name__=="__main__":
    unittest.main()
