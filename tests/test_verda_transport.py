import json
import math
import os
from pathlib import Path
import stat
import tempfile
import unittest
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone
from unittest import mock

from tools.verda_model_experiment import transport

CLIENT_ID = "client-id-fixture"
CLIENT_SECRET = "client-secret-fixture"
INFERENCE_KEY = "inference-key-fixture"
CREDENTIAL_VALUES = {
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "inference_api_key": INFERENCE_KEY,
}
CREDENTIALS = transport.Credentials(
    CLIENT_ID, CLIENT_SECRET, INFERENCE_KEY)
TOKEN_BODY = b'{"access_token":"oauth-token-fixture"}'


class FakeResponse:
    def __init__(self, body=b"", status=200, read_error=None,
                 close_error=None):
        self.body = body
        self.status = status
        self.read_error = read_error
        self.close_error = close_error
        self.read_sizes = []
        self.closed = False

    def read(self, size):
        self.read_sizes.append(size)
        if self.read_error is not None:
            raise self.read_error
        return self.body[:size]

    def close(self):
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


class FakeSender:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def __call__(self, method, url, headers, payload, timeout, cap):
        self.calls.append({
            "method": method,
            "url": url,
            "headers": dict(headers),
            "payload": payload,
            "timeout": timeout,
            "cap": cap,
        })
        if not self.results:
            raise AssertionError("unexpected transport call")
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def parse_query(url):
    parts = urllib.parse.urlsplit(url)
    params = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
    return parts, params


def parse_wire_time(value):
    return datetime.fromisoformat(value[:-1] + "+00:00")


class CredentialTests(unittest.TestCase):
    def write_credentials(self, root, values=None, mode=0o600,
                          name="verda.json"):
        path = root / name
        path.write_text(json.dumps(values or CREDENTIAL_VALUES),
                        encoding="utf-8")
        path.chmod(mode)
        return path

    def test_private_regular_file_is_read_and_redacted(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_credentials(Path(temporary))
            credentials = transport.Credentials.from_file(str(path))
        self.assertEqual(credentials.client_id, CLIENT_ID)
        self.assertEqual(credentials.client_secret, CLIENT_SECRET)
        self.assertEqual(credentials.inference_api_key, INFERENCE_KEY)
        self.assertEqual(repr(credentials), "Credentials(<redacted>)")
        for value in (CLIENT_ID, CLIENT_SECRET, INFERENCE_KEY):
            self.assertNotIn(value, repr(credentials))
            self.assertNotIn(value, str(credentials))

    def test_reader_rejects_symlink_wrong_mode_owner_and_type(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = self.write_credentials(root)
            link = root / "linked.json"
            link.symlink_to(target)
            with self.assertRaisesRegex(
                    transport.TransportError, "credential_file_invalid"):
                transport.Credentials.from_file(str(link))

            wrong_mode = self.write_credentials(root, name="mode.json",
                                                mode=0o644)
            with self.assertRaisesRegex(
                    transport.TransportError, "credential_file_invalid"):
                transport.Credentials.from_file(str(wrong_mode))

            wrong_owner = self.write_credentials(root, name="owner.json")
            with mock.patch.object(transport.os, "getuid",
                                   return_value=os.getuid() + 1):
                with self.assertRaisesRegex(
                        transport.TransportError, "credential_file_invalid"):
                    transport.Credentials.from_file(str(wrong_owner))

            directory = root / "directory.json"
            directory.mkdir()
            with self.assertRaisesRegex(
                    transport.TransportError, "credential_file_invalid"):
                transport.Credentials.from_file(str(directory))

            fifo = root / "fifo.json"
            os.mkfifo(fifo)
            fifo.chmod(0o600)
            with self.assertRaisesRegex(
                    transport.TransportError, "credential_file_invalid"):
                transport.Credentials.from_file(str(fifo))

    def test_reader_rejects_missing_unreadable_and_oversized_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(
                    transport.TransportError, "credential_file_invalid"):
                transport.Credentials.from_file(str(root / "missing.json"))

            unreadable = self.write_credentials(
                root, name="unreadable.json", mode=0o000)
            with self.assertRaisesRegex(
                    transport.TransportError, "credential_file_invalid"):
                transport.Credentials.from_file(str(unreadable))

            oversized = self.write_credentials(root, name="oversized.json")
            with mock.patch.object(transport, "CREDENTIAL_FILE_MAX_BYTES", 20):
                with self.assertRaisesRegex(
                        transport.TransportError, "credential_file_invalid"):
                    transport.Credentials.from_file(str(oversized))

            with self.assertRaisesRegex(
                    transport.TransportError, "credential_file_invalid"):
                transport.Credentials.from_file(None)

    def test_reader_bounds_growth_after_the_stat_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_credentials(Path(temporary))
            info = mock.Mock(
                st_mode=stat.S_IFREG | 0o600,
                st_uid=os.getuid(),
                st_size=1,
            )
            cap = transport.CREDENTIAL_FILE_MAX_BYTES
            with mock.patch.object(transport.os, "fstat", return_value=info), \
                    mock.patch.object(
                        transport.os, "read",
                        side_effect=[b"x" * (cap + 1)]):
                with self.assertRaisesRegex(
                        transport.TransportError, "credential_file_invalid"):
                    transport.Credentials.from_file(str(path))

    def test_reader_sanitizes_stat_read_and_close_failures(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_credentials(Path(temporary))
            with mock.patch.object(
                    transport.os, "fstat",
                    side_effect=OSError("raw credential path")), \
                    mock.patch.object(
                        transport.os, "read",
                        side_effect=OSError("raw credential path")):
                with self.assertRaises(
                        transport.TransportError) as raised:
                    transport.Credentials.from_file(str(path))
                self.assertEqual(
                    raised.exception.reason, "credential_file_invalid")
                self.assertNotIn("raw credential", str(raised.exception))
                self.assertNotIn(str(path), str(raised.exception))
            real_close = os.close

            def failing_close(descriptor):
                real_close(descriptor)
                raise OSError("raw credential path")

            with mock.patch.object(
                    transport.os, "close", side_effect=failing_close):
                credentials = transport.Credentials.from_file(str(path))
            self.assertEqual(credentials.client_id, CLIENT_ID)

            unreadable = self.write_credentials(
                root=Path(temporary), name="read-error.json")
            with mock.patch.object(
                    transport.os, "read",
                    side_effect=OSError("raw credential path")):
                with self.assertRaises(
                        transport.TransportError) as raised:
                    transport.Credentials.from_file(str(unreadable))
                self.assertEqual(
                    raised.exception.reason, "credential_file_invalid")
                self.assertNotIn("raw credential", str(raised.exception))

    def test_reader_rejects_invalid_json_shapes_and_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw.json"
            raw.write_bytes(b"not json")
            raw.chmod(0o600)
            utf8 = root / "utf8.json"
            utf8.write_bytes(b"\xff")
            utf8.chmod(0o600)
            missing = self.write_credentials(
                root, name="missing-field.json",
                values={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET})
            extra = self.write_credentials(
                root, name="extra-field.json",
                values={**CREDENTIAL_VALUES, "other": "value"})
            empty = self.write_credentials(
                root, name="empty.json",
                values={**CREDENTIAL_VALUES, "client_id": ""})
            non_string = self.write_credentials(
                root, name="number.json",
                values={**CREDENTIAL_VALUES, "inference_api_key": 7})
            list_payload = root / "list.json"
            list_payload.write_text("[]", encoding="utf-8")
            list_payload.chmod(0o600)
            paths = (raw, utf8, missing, extra, empty, non_string,
                     list_payload)
            for path in paths:
                with self.subTest(path=path.name), self.assertRaisesRegex(
                        transport.TransportError, "credential_file_invalid"):
                    transport.Credentials.from_file(str(path))


class UrllibAdapterTests(unittest.TestCase):
    def test_secure_request_is_bounded_returns_status_and_closes(self):
        response = FakeResponse(body=bytearray(b"payload"), status=200)
        url = "https://api.verda.com/v1/example"
        with mock.patch.object(transport._OPENER, "open",
                               return_value=response) as opener:
            status, body = transport._urllib_send(
                "GET", url, {"Accept": "application/json"}, None, 5.5, 16)
        self.assertEqual((status, body), (200, b"payload"))
        self.assertEqual(response.read_sizes, [17])
        self.assertTrue(response.closed)
        request = opener.call_args.args[0]
        self.assertEqual(opener.call_args.kwargs, {"timeout": 5.5})
        self.assertEqual(request.full_url, url)
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.headers["Accept"], "application/json")

    def test_plain_http_and_credential_urls_are_rejected(self):
        invalid = (
            "http://api.verda.com/v1/example",
            "https:///missing-host",
            "https://[bad/v1/example",
            "https://user:password@api.verda.com/v1/example",
            None,
        )
        with mock.patch.object(transport._OPENER, "open") as opener:
            for url in invalid:
                with self.subTest(url=url), self.assertRaises(
                        transport.TransportError) as raised:
                    transport._urllib_send("GET", url, {}, None, 1.0, 8)
                self.assertEqual(raised.exception.reason, "transport_error")
        opener.assert_not_called()

    def test_redirects_are_not_followed(self):
        handler = transport._NoRedirect()
        self.assertIsNone(handler.redirect_request(
            None, None, 302, "Found", {}, "https://api.verda.com/v1/next"))
        response = FakeResponse(body=b"redirect", status=302)
        url = "https://api.verda.com/v1/example"
        error = urllib.error.HTTPError(url, 302, "Found", {}, response)
        with mock.patch.object(transport._OPENER, "open",
                               side_effect=error) as opener:
            status, body = transport._urllib_send(
                "GET", url, {}, None, 1.0, 16)
        self.assertEqual((status, body), (302, b"redirect"))
        self.assertEqual(opener.call_count, 1)
        self.assertTrue(response.closed)

    def test_http_error_status_body_and_closure_are_preserved(self):
        response = FakeResponse(body=b"not-found", status=404)
        url = "https://api.verda.com/v1/example"
        error = urllib.error.HTTPError(url, 404, "Not Found", {}, response)
        with mock.patch.object(transport._OPENER, "open", side_effect=error):
            status, body = transport._urllib_send(
                "GET", url, {}, None, 1.0, 32)
        self.assertEqual((status, body), (404, b"not-found"))
        self.assertTrue(response.closed)

    def test_network_errors_are_closed_and_do_not_leak_text(self):
        errors = (
            urllib.error.URLError("raw credential text"),
            OSError("raw credential text"),
            ValueError("raw credential text"),
            RuntimeError("raw credential text"),
        )
        with mock.patch.object(transport._OPENER, "open") as opener:
            for error in errors:
                opener.side_effect = error
                with self.subTest(error=type(error).__name__):
                    with self.assertRaises(
                            transport.TransportError) as raised:
                        transport._urllib_send(
                            "GET", "https://api.verda.com/v1/example",
                            {}, None, 1.0, 8)
                    failure = raised.exception
                    self.assertEqual(failure.reason, "transport_error")
                    self.assertIsNone(failure.status)
                    self.assertNotIn("raw credential text", str(failure))
                    self.assertIsNone(failure.__cause__)

    def test_invalid_status_and_read_failures_are_sanitized(self):
        cases = (
            (FakeResponse(status="invalid"), "response_read_failed"),
            (FakeResponse(read_error=RuntimeError("raw secret")),
             "response_read_failed"),
            (FakeResponse(body="text"), "response_read_failed"),
        )
        with mock.patch.object(transport._OPENER, "open") as opener:
            for response, reason in cases:
                opener.return_value = response
                with self.subTest(reason=reason, status=response.status):
                    with self.assertRaises(
                            transport.TransportError) as raised:
                        transport._urllib_send(
                            "GET", "https://api.verda.com/v1/example",
                            {}, None, 1.0, 8)
                    failure = raised.exception
                    self.assertEqual(failure.reason, reason)
                    self.assertNotIn("raw secret", str(failure))
                    self.assertIsNone(failure.__cause__)
                    self.assertTrue(response.closed)

    def test_cap_exceeded_reads_one_extra_byte_and_closes(self):
        response = FakeResponse(body=b"12345", status=200)
        with mock.patch.object(transport._OPENER, "open",
                               return_value=response):
            with self.assertRaises(transport.TransportError) as raised:
                transport._urllib_send(
                    "GET", "https://api.verda.com/v1/example",
                    {}, None, 1.0, 4)
        self.assertEqual(raised.exception.reason, "response_cap_exceeded")
        self.assertEqual(raised.exception.status, 200)
        self.assertEqual(response.read_sizes, [5])
        self.assertTrue(response.closed)

    def test_close_errors_are_suppressed(self):
        response = FakeResponse(body=b"ok", status=200,
                                close_error=OSError("close failed"))
        with mock.patch.object(transport._OPENER, "open",
                               return_value=response):
            status, body = transport._urllib_send(
                "GET", "https://api.verda.com/v1/example", {}, None, 1.0, 8)
        self.assertEqual((status, body), (200, b"ok"))
        self.assertTrue(response.closed)

    def test_invalid_http_error_code_is_sanitized_and_closed(self):
        response = FakeResponse(status=302)
        url = "https://api.verda.com/v1/example"
        error = urllib.error.HTTPError(url, 302, "Found", {}, response)
        error.code = "invalid"
        with mock.patch.object(transport._OPENER, "open", side_effect=error):
            with self.assertRaises(transport.TransportError) as raised:
                transport._urllib_send("GET", url, {}, None, 1.0, 8)
        self.assertEqual(raised.exception.reason, "transport_error")
        self.assertTrue(response.closed)

    def test_fixed_urls_are_https_and_have_one_v1_prefix(self):
        names = (
            "CLOUD_ROOT", "TOKEN_URL", "DEPLOYMENT_URL", "STATUS_URL",
            "REPLICAS_URL", "SCALING_URL", "LOGS_URL", "SYSTEM_LOGS_URL",
            "INFERENCE_URL",
        )
        for name in names:
            value = getattr(transport, name)
            with self.subTest(name=name):
                self.assertTrue(value.startswith("https://"))
                self.assertEqual(value.count("/v1"), 1)
                self.assertNotIn("/v1/v1", value)
        self.assertEqual(transport.SYSTEM_LOGS_URL,
                         transport.DEPLOYMENT_URL + "/system-logs")


class OAuthAndInferenceTests(unittest.TestCase):
    def test_oauth_posts_client_credentials_and_stores_access_token(self):
        sender = FakeSender((200, TOKEN_BODY))
        client = transport.VerdaTransport(CREDENTIALS, sender=sender)
        client.fetch_token()
        call = sender.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["url"], transport.TOKEN_URL)
        self.assertEqual(call["headers"], {"Content-Type": "application/json"})
        self.assertEqual(call["timeout"], transport.OAUTH_TIMEOUT_SECONDS)
        self.assertEqual(call["cap"], transport.MANAGEMENT_CAP_BYTES)
        self.assertEqual(json.loads(call["payload"]), {
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        })
        self.assertNotIn(INFERENCE_KEY, call["payload"].decode())
        self.assertNotIn("Authorization", call["headers"])

    def test_oauth_rejects_non_200_without_retry(self):
        for status in (201, 401, 500):
            sender = FakeSender((status, TOKEN_BODY))
            client = transport.VerdaTransport(CREDENTIALS, sender=sender)
            with self.subTest(status=status):
                with self.assertRaises(transport.TransportError) as raised:
                    client.fetch_token()
                self.assertEqual(raised.exception.reason, "oauth_failed")
                self.assertEqual(raised.exception.status, status)
                self.assertEqual(len(sender.calls), 1)

    def test_oauth_rejects_invalid_json_and_shapes(self):
        bodies = (
            b"not json",
            b"\xff",
            b"[]",
            b"{}",
            b'{"access_token":""}',
            b'{"access_token":7}',
        )
        for body in bodies:
            sender = FakeSender((200, body))
            client = transport.VerdaTransport(CREDENTIALS, sender=sender)
            with self.subTest(body=body):
                with self.assertRaises(transport.TransportError) as raised:
                    client.fetch_token()
                self.assertEqual(
                    raised.exception.reason, "oauth_response_invalid")
                self.assertEqual(len(sender.calls), 1)

    def test_management_uses_oauth_bearer_and_parses_objects(self):
        sender = FakeSender(
            (200, TOKEN_BODY),
            (200, b'{"name":"deployment"}'),
            (200, b'{"min_replica_count":0}'),
            (200, b'{"min_replica_count":1}'),
            (200, b'{"name":"deployment-updated"}'),
            (200, b'{"status":"paused"}'),
            (200, b'{"list":[]}'),
        )
        client = transport.VerdaTransport(CREDENTIALS, sender=sender)
        client.fetch_token()
        self.assertEqual(client.get_deployment(), {"name": "deployment"})
        self.assertEqual(client.get_scaling(), {"min_replica_count": 0})
        self.assertEqual(
            client.patch_scaling({"min_replica_count": 1}),
            {"min_replica_count": 1})
        self.assertEqual(
            client.patch_deployment({"containers": []}),
            {"name": "deployment-updated"})
        self.assertEqual(client.get_status(), "paused")
        self.assertEqual(client.get_replicas(), {"list": []})

        expected = (
            ("GET", transport.DEPLOYMENT_URL, None),
            ("GET", transport.SCALING_URL, None),
            ("PATCH", transport.SCALING_URL,
             b'{"min_replica_count":1}'),
            ("PATCH", transport.DEPLOYMENT_URL, b'{"containers":[]}'),
            ("GET", transport.STATUS_URL, None),
            ("GET", transport.REPLICAS_URL, None),
        )
        for call, (method, url, payload) in zip(sender.calls[1:], expected):
            self.assertEqual(call["method"], method)
            self.assertEqual(call["url"], url)
            self.assertEqual(call["payload"], payload)
            self.assertEqual(call["headers"]["Authorization"],
                             "Bearer oauth-token-fixture")
            self.assertEqual(call["headers"]["Accept"], "application/json")
            if payload is None:
                self.assertNotIn("Content-Type", call["headers"])
            else:
                self.assertEqual(call["headers"]["Content-Type"],
                                 "application/json")
            self.assertEqual(call["timeout"],
                             transport.MANAGEMENT_TIMEOUT_SECONDS)
            self.assertEqual(call["cap"], transport.MANAGEMENT_CAP_BYTES)

    def test_management_requires_token_without_sending(self):
        sender = FakeSender()
        client = transport.VerdaTransport(CREDENTIALS, sender=sender)
        with self.assertRaises(transport.TransportError) as raised:
            client.get_deployment()
        self.assertEqual(raised.exception.reason, "token_missing")
        self.assertEqual(sender.calls, [])

    def test_management_rejects_non_200_for_reads_and_patches(self):
        for operation in ("read", "patch"):
            for status in (201, 202, 500):
                sender = FakeSender((200, TOKEN_BODY), (status, b"{}"))
                client = transport.VerdaTransport(CREDENTIALS, sender=sender)
                client.fetch_token()
                with self.subTest(operation=operation, status=status):
                    with self.assertRaises(
                            transport.TransportError) as raised:
                        if operation == "read":
                            client.get_deployment()
                        else:
                            client.patch_scaling({"min_replica_count": 1})
                    self.assertEqual(
                        raised.exception.reason, "management_http")
                    self.assertEqual(raised.exception.status, status)
                    self.assertEqual(len(sender.calls), 2)

    def test_management_rejects_invalid_json_and_shapes(self):
        cases = (
            (b"not json", "management_json_invalid",
             lambda client: client.get_deployment()),
            (b"[]", "management_json_invalid",
             lambda client: client.get_scaling()),
            (b'{"status":"paused","other":1}', "status_shape_invalid",
             lambda client: client.get_status()),
            (b'{"status":1}', "status_shape_invalid",
             lambda client: client.get_status()),
            (b"{}", "replicas_shape_invalid",
             lambda client: client.get_replicas()),
            (b'{"list":{}}', "replicas_shape_invalid",
             lambda client: client.get_replicas()),
        )
        for body, reason, operation in cases:
            sender = FakeSender((200, TOKEN_BODY), (200, body))
            client = transport.VerdaTransport(CREDENTIALS, sender=sender)
            client.fetch_token()
            with self.subTest(reason=reason, body=body):
                with self.assertRaises(transport.TransportError) as raised:
                    operation(client)
                self.assertEqual(raised.exception.reason, reason)
                self.assertEqual(len(sender.calls), 2)

    def test_inference_returns_passthrough_status_and_body(self):
        sender = FakeSender((201, b"inference-result"))
        client = transport.VerdaTransport(CREDENTIALS, sender=sender)
        result = client.post_inference(b'{"text":"synthetic"}', 9.5)
        self.assertEqual(result, (201, b"inference-result"))
        call = sender.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["url"], transport.INFERENCE_URL)
        self.assertEqual(call["payload"], b'{"text":"synthetic"}')
        self.assertEqual(call["headers"]["Authorization"],
                         "Bearer " + INFERENCE_KEY)
        self.assertEqual(call["headers"]["Content-Type"],
                         "application/json")
        self.assertEqual(call["headers"]["Accept"], "application/json")
        self.assertEqual(call["timeout"], 9.5)
        self.assertEqual(call["cap"], transport.INFERENCE_CAP_BYTES)
        self.assertNotIn(CLIENT_SECRET, json.dumps(call["headers"]))
        self.assertNotIn(CLIENT_ID, json.dumps(call["headers"]))

    def test_inference_never_uses_the_oauth_token(self):
        sender = FakeSender((200, TOKEN_BODY), (200, b"ok"))
        client = transport.VerdaTransport(CREDENTIALS, sender=sender)
        client.fetch_token()
        status, body = client.post_inference(b"{}", 3.0)
        self.assertEqual((status, body), (200, b"ok"))
        call = sender.calls[1]
        self.assertEqual(call["headers"]["Authorization"],
                         "Bearer " + INFERENCE_KEY)
        self.assertNotIn("oauth-token-fixture",
                         json.dumps(call["headers"]))


class DeploymentActionTests(unittest.TestCase):
    def client(self, *results):
        sender = FakeSender((200, TOKEN_BODY), *results)
        client = transport.VerdaTransport(CREDENTIALS, sender=sender)
        client.fetch_token()
        return client, sender

    def test_pause_and_resume_accept_201_without_json(self):
        client, sender = self.client((201, b""), (201, b"not json"))
        client.post_action("pause")
        client.post_action("resume")
        self.assertEqual(
            [call["url"] for call in sender.calls[1:]],
            [transport.DEPLOYMENT_URL + "/pause",
             transport.DEPLOYMENT_URL + "/resume"])
        for call in sender.calls[1:]:
            self.assertEqual(call["method"], "POST")
            self.assertIsNone(call["payload"])
            self.assertNotIn("Content-Type", call["headers"])
            self.assertEqual(call["headers"]["Authorization"],
                             "Bearer oauth-token-fixture")
            self.assertEqual(call["headers"]["Accept"], "application/json")

    def test_pause_accepts_200_and_rejects_other_status(self):
        client, sender = self.client((200, b""))
        client.post_action("pause")
        self.assertEqual(len(sender.calls), 2)
        client, sender = self.client((202, b""))
        with self.assertRaises(transport.TransportError) as raised:
            client.post_action("resume")
        self.assertEqual(raised.exception.reason, "management_http")
        self.assertEqual(raised.exception.status, 202)
        self.assertEqual(len(sender.calls), 2)

    def test_invalid_action_does_not_send(self):
        client, sender = self.client()
        with self.assertRaises(transport.TransportError) as raised:
            client.post_action("delete")
        self.assertEqual(raised.exception.reason, "action_invalid")
        self.assertEqual(len(sender.calls), 1)

    def test_action_failure_is_not_retried(self):
        client, sender = self.client((500, b""))
        with self.assertRaises(transport.TransportError) as raised:
            client.post_action("pause")
        self.assertEqual(raised.exception.reason, "management_http")
        self.assertEqual(raised.exception.status, 500)
        self.assertEqual(len(sender.calls), 2)


class LogQueryTests(unittest.TestCase):
    EXACT_POD = "envai-pii-test-6f9c8b7d5-x2abc"
    START = "2026-10-28T18:37:31Z"
    END = "2026-10-28T18:38:20.500000Z"

    def client(self, *results):
        sender = FakeSender((200, TOKEN_BODY), *results)
        client = transport.VerdaTransport(CREDENTIALS, sender=sender)
        client.fetch_token()
        return client, sender

    def last_query(self, sender):
        call = sender.calls[-1]
        parts, params = parse_query(call["url"])
        self.assertEqual(call["method"], "GET")
        self.assertEqual(call["payload"], None)
        self.assertEqual(call["headers"]["Authorization"],
                         "Bearer oauth-token-fixture")
        self.assertEqual(call["timeout"], transport.MANAGEMENT_TIMEOUT_SECONDS)
        self.assertEqual(call["cap"], transport.MANAGEMENT_CAP_BYTES)
        return parts, params

    def test_logs_send_exact_pod_iso_window_order_and_limit(self):
        entries = [{"timestamp": self.START, "message": "synthetic"}]
        client, sender = self.client((200, json.dumps(entries).encode()))
        result = client.get_logs(
            start=self.START, end=self.END, pod=self.EXACT_POD,
            order="desc", limit=1000)
        self.assertEqual(result, entries)
        parts, params = self.last_query(sender)
        self.assertEqual(parts.scheme, "https")
        self.assertEqual(
            parts.geturl().split("?")[0], transport.LOGS_URL)
        self.assertEqual(params["pod"], [self.EXACT_POD])
        self.assertEqual(params["start"], [self.START])
        self.assertEqual(params["end"], [self.END])
        self.assertEqual(params["order"], ["desc"])
        self.assertEqual(params["limit"], ["1000"])
        self.assertNotIn("container_name", params)
        self.assertNotIn("/v1/v1", parts.geturl())

    def test_logs_support_repeated_pods_and_container_name(self):
        client, sender = self.client((200, b"[]"))
        client.get_logs(
            start=self.START, end=self.END, pod=[self.EXACT_POD, "pod-two"],
            pods=("pod-three",), container_name="app")
        _, params = self.last_query(sender)
        self.assertEqual(
            params["pod"], [self.EXACT_POD, "pod-two", "pod-three"])
        self.assertEqual(params["container_name"], ["app"])

    def test_logs_accept_fractional_epoch_and_omit_end(self):
        start = 1_790_000_000.25
        client, sender = self.client((200, b"[]"))
        self.assertEqual(client.get_logs(start=start), [])
        _, params = self.last_query(sender)
        self.assertEqual(params["start"], ["2026-09-21T14:13:20.250000Z"])
        self.assertEqual(
            parse_wire_time(params["start"][0]),
            datetime.fromtimestamp(start, timezone.utc))
        self.assertNotIn("end", params)
        self.assertEqual(params["order"], ["asc"])
        self.assertEqual(params["limit"], [str(transport.LOG_LIMIT_MAX)])

    def test_logs_accept_exact_55_second_epoch_window(self):
        start = 1_790_000_000.0
        end = start + transport.MAX_LOG_WINDOW_SECONDS
        client, sender = self.client((200, b"[]"))
        client.get_logs(start=start, end=end)
        _, params = self.last_query(sender)
        self.assertEqual(
            (parse_wire_time(params["end"][0])
             - parse_wire_time(params["start"][0])).total_seconds(), 55.0)

    def test_logs_normalize_offset_zero_iso_to_utc(self):
        client, sender = self.client((200, b"[]"))
        client.get_logs(start="2026-10-28T18:37:31+00:00",
                        end="2026-10-28T18:38:00+00:00")
        _, params = self.last_query(sender)
        self.assertEqual(params["start"], ["2026-10-28T18:37:31Z"])
        self.assertEqual(params["end"], ["2026-10-28T18:38:00Z"])

    def test_logs_reject_windows_over_55_seconds_and_reversed(self):
        for start, end in (
                (self.START, "2026-10-28T18:38:26.000001Z"),
                (self.END, self.START)):
            client, sender = self.client()
            with self.subTest(start=start, end=end):
                with self.assertRaises(
                        transport.TransportError) as raised:
                    client.get_logs(start=start, end=end)
                self.assertEqual(
                    raised.exception.reason, "log_query_invalid")
                self.assertEqual(len(sender.calls), 1)

    def test_logs_reject_invalid_times_without_leaking_values(self):
        invalid = (
            None,
            True,
            math.nan,
            math.inf,
            1e30,
            b"2026-10-28T18:37:31Z",
            "2026-10-28",
            "2026-10-28T18:37:31",
            "2026-10-28T18:37:31+02:00",
            " 2026-10-28T18:37:31Z",
            "2026-13-01T00:00:00Z",
            datetime(2026, 10, 28, 18, 37, 31),
            datetime(2026, 10, 28, 18, 37, 31,
                     tzinfo=timezone(timedelta(hours=2))),
            object(),
        )
        client, sender = self.client()
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(
                        transport.TransportError) as raised:
                    client.get_logs(start=value)
                self.assertEqual(
                    raised.exception.reason, "log_query_invalid")
                self.assertNotIn(repr(value), str(raised.exception))
        self.assertEqual(len(sender.calls), 1)

    def test_logs_reject_invalid_order_and_limit(self):
        for order, limit in (
                ("ASC", 10), ("ascending", 10), ("asc", 0), ("asc", 1001),
                ("asc", True), ("asc", 1.0), ("asc", "10")):
            client, sender = self.client()
            with self.subTest(order=order, limit=limit):
                with self.assertRaises(
                        transport.TransportError) as raised:
                    client.get_logs(start=self.START, end=self.END,
                                    order=order, limit=limit)
                self.assertEqual(
                    raised.exception.reason, "log_query_invalid")
                self.assertEqual(len(sender.calls), 1)

    def test_logs_reject_invalid_pods_and_container_names(self):
        invalid_pods = (
            7,
            b"pod",
            {"pod"},
            "pod with space",
            "pod&limit=1",
            "pod\nvalue",
            "p" * (transport.MAX_LOG_POD_LENGTH + 1),
            "",
        )
        for value in invalid_pods:
            client, sender = self.client()
            with self.subTest(pod=value):
                with self.assertRaises(
                        transport.TransportError) as raised:
                    client.get_logs(start=self.START, end=self.END, pod=value)
                self.assertEqual(
                    raised.exception.reason, "log_query_invalid")
                self.assertEqual(len(sender.calls), 1)
        for pods in ("pod", None, [7]):
            client, sender = self.client()
            with self.subTest(pods=pods):
                with self.assertRaises(
                        transport.TransportError) as raised:
                    client.get_logs(start=self.START, end=self.END, pods=pods)
                self.assertEqual(
                    raised.exception.reason, "log_query_invalid")
                self.assertEqual(len(sender.calls), 1)
        client, sender = self.client()
        with self.assertRaises(transport.TransportError):
            client.get_logs(
                start=self.START, end=self.END, container_name="app" * 30)
        self.assertEqual(len(sender.calls), 1)

    def test_logs_reject_invalid_shapes_and_non_200(self):
        for body, status, reason in (
                (b"{}", 200, "logs_shape_invalid"),
                (b"not json", 200, "logs_shape_invalid"),
                (b"[]", 201, "management_http")):
            client, sender = self.client((status, body))
            with self.subTest(body=body, status=status):
                with self.assertRaises(
                        transport.TransportError) as raised:
                    client.get_logs(start=self.START, end=self.END)
                self.assertEqual(raised.exception.reason, reason)
                self.assertEqual(len(sender.calls), 2)


class SystemLogTests(unittest.TestCase):
    START = "2026-10-28T18:37:31Z"
    END = "2026-10-28T18:38:20Z"

    def client(self, *results):
        sender = FakeSender((200, TOKEN_BODY), *results)
        client = transport.VerdaTransport(CREDENTIALS, sender=sender)
        client.fetch_token()
        return client, sender

    def test_system_logs_return_metadata_only(self):
        entries = [
            {
                "timestamp": "2026-10-28T18:38:00Z",
                "first_timestamp": "2026-10-28T18:37:59Z",
                "last_timestamp": "2026-10-28T18:38:01Z",
                "level": "info",
                "reason": "ScaledToZero",
                "involved_object": "envai-pii-test",
                "count": 1,
                "message": "synthetic credential text",
                "payload": {"secret": "value"},
                "raw": b"bytes",
            },
            "not a mapping",
            {"message": "metadata-free"},
        ]
        client, sender = self.client(
            (200, json.dumps(entries, default=lambda value: "bytes")
             .encode()))
        result = client.get_system_logs(
            start=self.START, end=self.END, order="desc", limit=50)
        self.assertEqual(result, [{
            "timestamp": "2026-10-28T18:38:00Z",
            "first_timestamp": "2026-10-28T18:37:59Z",
            "last_timestamp": "2026-10-28T18:38:01Z",
            "level": "info",
            "reason": "ScaledToZero",
            "involved_object": "envai-pii-test",
            "count": 1,
        }])
        call = sender.calls[-1]
        parts, params = parse_query(call["url"])
        self.assertEqual(parts.geturl().split("?")[0],
                         transport.SYSTEM_LOGS_URL)
        self.assertEqual(params["start"], [self.START])
        self.assertEqual(params["end"], [self.END])
        self.assertEqual(params["order"], ["desc"])
        self.assertEqual(params["limit"], ["50"])
        self.assertNotIn("pod", params)
        self.assertNotIn("container_name", params)
        self.assertEqual(call["method"], "GET")
        self.assertEqual(call["headers"]["Authorization"],
                         "Bearer oauth-token-fixture")
        self.assertNotIn("synthetic credential text", json.dumps(result))

    def test_system_logs_reject_invalid_shape_and_window(self):
        client, sender = self.client((200, b"{}"))
        with self.assertRaises(transport.TransportError) as raised:
            client.get_system_logs(start=self.START, end=self.END)
        self.assertEqual(raised.exception.reason,
                         "system_logs_shape_invalid")
        self.assertEqual(len(sender.calls), 2)
        client, sender = self.client()
        with self.assertRaises(transport.TransportError) as raised:
            client.get_system_logs(
                start=self.START, end="2026-10-28T18:38:27Z")
        self.assertEqual(raised.exception.reason, "log_query_invalid")
        self.assertEqual(len(sender.calls), 1)

    def test_system_logs_reject_non_200(self):
        client, sender = self.client((201, b"[]"))
        with self.assertRaises(transport.TransportError) as raised:
            client.get_system_logs(start=self.START)
        self.assertEqual(raised.exception.reason, "management_http")
        self.assertEqual(raised.exception.status, 201)
        self.assertEqual(len(sender.calls), 2)


if __name__ == "__main__":
    unittest.main()
