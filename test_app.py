import unittest
import time
import random
from pathlib import Path
from tempfile import TemporaryDirectory

from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.main import create_app
from app.safety import filter_output


PASSWORD = "synthetic-test-passphrase"


class HearthAuthenticatedApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        app = create_app(
            password_hash=PasswordHasher().hash(PASSWORD),
            cookie_secure=False,
            db_path=Path(self.temp.name) / "hearth.sqlite3",
            dev_tools=True,
            voice_engine=None,
        )
        self.client = TestClient(app, base_url="http://localhost")
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def login(self):
        response = self.client.post("/api/auth/login", json={"password": PASSWORD})
        self.assertEqual(response.status_code, 200)
        return response.json()["csrf_token"]

    def test_workshop_requires_authentication(self):
        response = self.client.get("/api/workshop")
        self.assertEqual(response.status_code, 401)

    def test_login_uses_http_only_same_site_cookie(self):
        response = self.client.post("/api/auth/login", json={"password": PASSWORD})
        cookie = response.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=strict", cookie)
        self.assertNotIn(PASSWORD, response.text)

    def test_authenticated_workshop_is_synthetic(self):
        self.login()
        data = self.client.get("/api/workshop").json()
        self.assertTrue(data["synthetic"])
        self.assertEqual(len(data["memories"]), 8)

    def test_state_change_requires_csrf(self):
        self.login()
        response = self.client.patch("/api/settings", json={"notice_patterns": False})
        self.assertEqual(response.status_code, 403)

    def test_tone_rule_is_server_enforced(self):
        csrf = self.login()
        tone = {
            "warmth": 0.7, "humor": 0.3, "depth": 0.55, "questions": 0.5,
            "directness": 0.2, "challenge": 0.8, "pace": 0.5,
        }
        response = self.client.patch("/api/settings", json={"tone": tone}, headers={"X-CSRF-Token": csrf})
        self.assertEqual(response.status_code, 200)
        self.assertAlmostEqual(response.json()["tone"]["challenge"], 0.4)

    def test_tone_invariant_holds_for_random_direct_api_updates(self):
        csrf = self.login()
        rng = random.Random(4815)
        for _ in range(80):
            tone = {key: rng.random() for key in ("warmth", "humor", "depth", "questions", "directness", "challenge", "pace")}
            response = self.client.patch("/api/settings", json={"tone": tone}, headers={"X-CSRF-Token": csrf})
            self.assertEqual(response.status_code, 200)
            saved = response.json()["tone"]
            self.assertLessEqual(saved["challenge"], saved["directness"] + 0.2000001)

    def test_memory_delete_requires_csrf_and_changes_server_state(self):
        csrf = self.login()
        forbidden = self.client.delete("/api/memories/7")
        self.assertEqual(forbidden.status_code, 403)
        removed = self.client.delete("/api/memories/7", headers={"X-CSRF-Token": csrf})
        self.assertEqual(removed.status_code, 204)
        ids = [item["id"] for item in self.client.get("/api/workshop").json()["memories"]]
        self.assertNotIn(7, ids)
        log = self.client.get("/api/deletion-log").json()["entries"]
        self.assertEqual(log[-1]["entity_type"], "memory")
        self.assertEqual(log[-1]["entity_id"], "7")

    def test_reauthentication_window(self):
        csrf = self.login()
        response = self.client.post(
            "/api/auth/reauthenticate",
            json={"password": PASSWORD, "purpose": "shelf"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["reauthenticated"])

    def test_synthetic_melt_schedule_and_cancel(self):
        csrf = self.login()
        self.client.post(
            "/api/auth/reauthenticate",
            json={"password": PASSWORD, "purpose": "melt"},
            headers={"X-CSRF-Token": csrf},
        )
        scheduled = self.client.post("/api/melt/schedule", headers={"X-CSRF-Token": csrf})
        self.assertEqual(scheduled.status_code, 200)
        self.assertTrue(scheduled.json()["synthetic"])
        self.assertEqual(self.client.get("/api/melt").json()["state"], "scheduled")
        cancelled = self.client.delete("/api/melt/schedule", headers={"X-CSRF-Token": csrf})
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["state"], "none")

    def test_due_synthetic_melt_executes_and_leaves_proof(self):
        csrf = self.login()
        sentinel = "SYNTHETIC_SENTINEL_7b8926c5"
        self.client.post(
            "/api/notes",
            json={"text": sentinel, "author": "E"},
            headers={"X-CSRF-Token": csrf},
        )
        self.client.post(
            "/api/conversation/turn",
            json={"fixture_id": "synthetic-melt-sentinel", "text": sentinel},
            headers={"X-CSRF-Token": csrf},
        )
        self.client.app.state.runtime.store.schedule_melt(time.time() - 1)
        time.sleep(1.2)
        workshop = self.client.get("/api/workshop").json()
        self.assertEqual(workshop["memories"], [])
        self.assertEqual(workshop["lanterns"], [])
        self.assertEqual(workshop["notes"], [])
        self.assertEqual(workshop["settings"], self.client.app.state.runtime.store._default_settings)
        self.assertEqual(self.client.get("/api/conversation/ledger").json()["turns"], [])
        state = self.client.get("/api/melt").json()
        self.assertEqual(state["state"], "completed")
        self.assertIsNotNone(state["completed_at"])
        entries = self.client.get("/api/deletion-log").json()["entries"]
        self.assertTrue(any(entry["reason"] == "scheduled_melt" for entry in entries))
        db_path = self.client.app.state.runtime.store.path
        for candidate in db_path.parent.rglob("*"):
            if candidate.is_file():
                self.assertNotIn(sentinel.encode("utf-8"), candidate.read_bytes(), str(candidate))

    def test_note_crud_is_server_owned(self):
        csrf = self.login()
        created = self.client.post(
            "/api/notes",
            json={"text": "Synthetic note", "author": "E"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(created.status_code, 201)
        note_id = created.json()["id"]
        updated = self.client.patch(
            "/api/notes/{}".format(note_id),
            json={"text": "Synthetic note, edited"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(updated.json()["text"], "Synthetic note, edited")
        deleted = self.client.delete(
            "/api/notes/{}".format(note_id), headers={"X-CSRF-Token": csrf}
        )
        self.assertEqual(deleted.status_code, 204)

    def test_lantern_create_and_update(self):
        csrf = self.login()
        created = self.client.post(
            "/api/lanterns", json={"name": "Synthetic lantern"}, headers={"X-CSRF-Token": csrf}
        )
        self.assertEqual(created.status_code, 201)
        lantern_id = created.json()["id"]
        updated = self.client.patch(
            "/api/lanterns/{}".format(lantern_id),
            json={"mode": "watch", "level": 0.2},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["mode"], "watch")
        deleted = self.client.delete(
            "/api/lanterns/{}".format(lantern_id), headers={"X-CSRF-Token": csrf}
        )
        self.assertEqual(deleted.status_code, 204)

    def test_voice_setting_is_validated_and_persisted(self):
        csrf = self.login()
        accepted = self.client.patch(
            "/api/settings",
            json={"voice": {"id": "moss", "pitch": 0.22}},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()["voice"]["id"], "moss")
        rejected = self.client.patch(
            "/api/settings",
            json={"voice": {"id": "remote-cloud-voice", "pitch": 0.5}},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(rejected.status_code, 422)

    def test_login_rate_limit(self):
        for _ in range(5):
            response = self.client.post("/api/auth/login", json={"password": "wrong"})
            self.assertEqual(response.status_code, 401)
        response = self.client.post("/api/auth/login", json={"password": "wrong"})
        self.assertEqual(response.status_code, 429)

    def test_sqlite_state_survives_app_restart(self):
        db_path = Path(self.temp.name) / "restart.sqlite3"
        password_hash = PasswordHasher().hash(PASSWORD)
        with TestClient(create_app(password_hash=password_hash, cookie_secure=False, db_path=db_path, dev_tools=True, voice_engine=None), base_url="http://localhost") as first:
            csrf = first.post("/api/auth/login", json={"password": PASSWORD}).json()["csrf_token"]
            self.assertEqual(first.delete("/api/memories/8", headers={"X-CSRF-Token": csrf}).status_code, 204)
        with TestClient(create_app(password_hash=password_hash, cookie_secure=False, db_path=db_path, dev_tools=True, voice_engine=None), base_url="http://localhost") as second:
            second.post("/api/auth/login", json={"password": PASSWORD})
            ids = [item["id"] for item in second.get("/api/workshop").json()["memories"]]
            self.assertNotIn(8, ids)

    def test_schema_migration_is_recorded(self):
        rows = self.client.app.state.runtime.store._conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        self.assertEqual([row[0] for row in rows], [1, 2, 3, 4])

    def test_reauthentication_is_throttled(self):
        csrf = self.login()
        for _ in range(5):
            response = self.client.post(
                "/api/auth/reauthenticate",
                json={"password": "wrong", "purpose": "shelf"},
                headers={"X-CSRF-Token": csrf},
            )
            self.assertEqual(response.status_code, 401)
        blocked = self.client.post(
            "/api/auth/reauthenticate",
            json={"password": PASSWORD, "purpose": "shelf"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(blocked.status_code, 429)

    def test_locked_shelf_redacts_memory_text_and_ledger(self):
        self.login()
        for session in self.client.app.state.runtime.sessions.values():
            session.shelf_unlocked_until = 0
        workshop = self.client.get("/api/workshop")
        self.assertEqual(workshop.status_code, 200)
        self.assertFalse(workshop.json()["shelf_unlocked"])
        self.assertTrue(all("text" not in item for item in workshop.json()["memories"]))
        self.assertEqual(self.client.get("/api/conversation/ledger").status_code, 403)

    def test_explicit_shelf_lock_revokes_text_access(self):
        csrf = self.login()
        locked = self.client.post("/api/shelf/lock", headers={"X-CSRF-Token": csrf})
        self.assertEqual(locked.status_code, 200)
        workshop = self.client.get("/api/workshop").json()
        self.assertFalse(workshop["shelf_unlocked"])
        self.assertTrue(all("text" not in item for item in workshop["memories"]))

    def test_keep_and_delete_are_refused_while_shelf_is_locked(self):
        csrf = self.login()
        self.assertEqual(self.client.post("/api/shelf/lock", headers={"X-CSRF-Token": csrf}).status_code, 200)
        kept = self.client.post("/api/memories/1/keep", headers={"X-CSRF-Token": csrf})
        removed = self.client.delete("/api/memories/2", headers={"X-CSRF-Token": csrf})
        self.assertEqual((kept.status_code, kept.json()["detail"]), (403, "shelf_locked"))
        self.assertEqual((removed.status_code, removed.json()["detail"]), (403, "shelf_locked"))

    def test_confirmed_memory_cannot_be_demoted(self):
        csrf = self.login()
        first = self.client.post("/api/memories/1/keep", headers={"X-CSRF-Token": csrf})
        second = self.client.post("/api/memories/1/keep", headers={"X-CSRF-Token": csrf})
        self.assertEqual(first.json()["status"], "confirmed")
        self.assertEqual(second.json()["status"], "confirmed")

    def test_memory_correction_requires_unlock_and_persists(self):
        csrf = self.login()
        corrected = self.client.patch(
            "/api/memories/1", json={"text": "Synthetic corrected wording"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(corrected.status_code, 200)
        self.assertEqual(corrected.json()["status"], "corrected")
        self.client.post("/api/shelf/lock", headers={"X-CSRF-Token": csrf})
        denied = self.client.patch(
            "/api/memories/1", json={"text": "Must stay hidden"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(denied.status_code, 403)

    def test_tone_preview_is_side_effect_free(self):
        self.login()
        before = self.client.app.state.runtime.store.path.read_bytes()
        tone = {
            "warmth": 0.7, "humor": 0.3, "depth": 0.55, "questions": 0.5,
            "directness": 0.2, "challenge": 0.8, "pace": 0.5,
        }
        response = self.client.post("/api/tone/preview", json={"tone": tone})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["side_effect_free"])
        self.assertEqual(before, self.client.app.state.runtime.store.path.read_bytes())

    def test_privacy_and_voice_capabilities_do_not_make_fake_claims(self):
        self.login()
        privacy = self.client.get("/api/privacy").json()
        self.assertIsNone(privacy["egress_bytes"])
        self.assertIsNone(privacy["last_backup_at"])
        voices = self.client.get("/api/voices").json()
        self.assertEqual([v["id"] for v in voices["voices"]], ["willow", "moss"])
        self.assertFalse(voices["preview_supported"])

    def test_melt_requires_fresh_one_time_password_and_cannot_be_extended(self):
        csrf = self.login()
        denied = self.client.post("/api/melt/schedule", headers={"X-CSRF-Token": csrf})
        self.assertEqual(denied.status_code, 403)
        authorized = self.client.post(
            "/api/auth/reauthenticate",
            json={"password": PASSWORD, "purpose": "melt"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(authorized.status_code, 200)
        first = self.client.post("/api/melt/schedule", headers={"X-CSRF-Token": csrf})
        self.assertEqual(first.status_code, 200)
        self.client.post(
            "/api/auth/reauthenticate",
            json={"password": PASSWORD, "purpose": "melt"},
            headers={"X-CSRF-Token": csrf},
        )
        second = self.client.post("/api/melt/schedule", headers={"X-CSRF-Token": csrf})
        self.assertEqual(second.status_code, 409)

    def test_due_melt_cannot_be_cancelled(self):
        csrf = self.login()
        self.client.app.state.runtime.store.schedule_melt(time.time() - 1)
        response = self.client.delete("/api/melt/schedule", headers={"X-CSRF-Token": csrf})
        self.assertEqual(response.status_code, 409)

    def test_database_permissions_are_private(self):
        mode = self.client.app.state.runtime.store.path.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_invalid_host_is_rejected(self):
        response = self.client.get("/healthz", headers={"Host": "evil.example"})
        self.assertEqual(response.status_code, 400)

    def test_dev_routes_are_absent_when_dev_tools_are_disabled(self):
        db_path = Path(self.temp.name) / "production-shape.sqlite3"
        with TestClient(create_app(
            password_hash=PasswordHasher().hash(PASSWORD), cookie_secure=False,
            db_path=db_path, dev_tools=False, voice_engine=None,
        ), base_url="http://localhost") as production:
            login = production.post("/api/auth/login", json={"password": PASSWORD})
            csrf = login.json()["csrf_token"]
            conversation = production.post(
                "/api/conversation/turn",
                json={"fixture_id": "synthetic-disabled", "text": "synthetic"},
                headers={"X-CSRF-Token": csrf},
            )
            self.assertEqual(conversation.status_code, 404)
            self.assertEqual(production.get("/dev/orb").status_code, 404)

    def test_ordinary_violent_vent_is_not_misclassified_as_crisis(self):
        csrf = self.login()
        response = self.client.post(
            "/api/conversation/turn",
            json={"fixture_id": "synthetic-ordinary-vent", "text": "I want to punch my boss for doing that again."},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["risk_level"], "ordinary")
        self.assertEqual(data["assistant_delivered_text"], "Jesus. What happened?")
        self.assertFalse(data["outside_contact_attempted"])
        self.assertEqual(data["resource_actions"], [])

    def test_explicit_self_harm_statement_asks_direct_question_without_contact_claim(self):
        csrf = self.login()
        response = self.client.post(
            "/api/conversation/turn",
            json={"fixture_id": "synthetic-explicit-risk", "text": "I am going to kill myself."},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["risk_level"], "high")
        self.assertTrue(data["asks_clarifying_question"])
        self.assertIn("I have not contacted anyone", data["assistant_delivered_text"])
        self.assertFalse(data["outside_contact_attempted"])

    def test_uncertain_recall_floor_asks_for_clarification(self):
        csrf = self.login()
        response = self.client.post(
            "/api/conversation/turn",
            json={"fixture_id": "synthetic-uncertain-risk", "text": "Sometimes I think about suicide."},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["risk_level"], "uncertain")
        self.assertTrue(response.json()["asks_clarifying_question"])

    def test_conversation_endpoint_rejects_non_synthetic_fixture(self):
        csrf = self.login()
        response = self.client.post(
            "/api/conversation/turn",
            json={"fixture_id": "personal-data", "text": "This must not be accepted."},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 422)

    def test_delivered_text_is_ledgered_exactly(self):
        csrf = self.login()
        response = self.client.post(
            "/api/conversation/turn",
            json={"fixture_id": "synthetic-ledger-check", "text": "I had a difficult day."},
            headers={"X-CSRF-Token": csrf},
        )
        delivered = response.json()["assistant_delivered_text"]
        ledger = self.client.get("/api/conversation/ledger").json()["turns"]
        self.assertEqual(ledger[-1]["assistant_delivered_text"], delivered)
        self.assertEqual(ledger[-1]["assistant_generation_full"], delivered)
        self.assertEqual(ledger[-1]["interrupted"], 0)

    def test_output_filter_blocks_false_outside_contact_claims(self):
        for unsafe in ("I contacted 911.", "Help is on the way.", "I am monitoring your location."):
            filtered = filter_output(unsafe)
            self.assertNotEqual(filtered, unsafe)
            self.assertIn("cannot contact anyone", filtered)

    # ---- 1.1.0-rc1 hardening -------------------------------------------------

    def _runtime_bytes(self, needle: str):
        hits = []
        for candidate in Path(self.temp.name).rglob("*"):
            if candidate.is_file() and needle.encode("utf-8") in candidate.read_bytes():
                hits.append(candidate.name)
        return hits

    def test_deleted_and_corrected_memory_text_leaves_no_wal_residue(self):
        csrf = self.login()
        headers = {"X-CSRF-Token": csrf}
        self.assertEqual(
            self.client.patch("/api/memories/1", json={"text": "replacement wording"}, headers=headers).status_code, 200
        )
        self.assertEqual(self.client.delete("/api/memories/2", headers=headers).status_code, 204)
        self.assertEqual(self.client.delete("/api/memories/3", headers=headers).status_code, 204)
        self.assertEqual(self._runtime_bytes("Dana, a coworker"), [])
        self.assertEqual(self._runtime_bytes("Holds back when she is interrupted"), [])
        self.assertEqual(self._runtime_bytes("Speak up earlier in meetings"), [])

    def test_deleted_note_and_renamed_lantern_leave_no_residue(self):
        csrf = self.login()
        headers = {"X-CSRF-Token": csrf}
        self.assertEqual(self.client.delete("/api/notes/1", headers=headers).status_code, 204)
        self.assertEqual(
            self.client.patch("/api/lanterns/1", json={"name": "renamed"}, headers=headers).status_code, 200
        )
        self.assertEqual(self.client.delete("/api/lanterns/2", headers=headers).status_code, 204)
        self.assertEqual(self._runtime_bytes("less fixing, more listening"), [])
        self.assertEqual(self._runtime_bytes("Meetings that leave you drained"), [])
        self.assertEqual(self._runtime_bytes("Holding back when you"), [])

    def test_locked_shelf_blocks_memory_keep_and_delete(self):
        csrf = self.login()
        headers = {"X-CSRF-Token": csrf}
        self.assertEqual(self.client.post("/api/shelf/lock", headers=headers).status_code, 200)
        self.assertEqual(self.client.post("/api/memories/7/keep", headers=headers).status_code, 403)
        self.assertEqual(self.client.delete("/api/memories/7", headers=headers).status_code, 403)
        self.client.post("/api/auth/reauthenticate", json={"password": PASSWORD, "purpose": "shelf"}, headers=headers)
        self.assertEqual(self.client.post("/api/memories/7/keep", headers=headers).status_code, 200)
        self.assertEqual(self.client.delete("/api/memories/7", headers=headers).status_code, 204)

    def test_stranger_failures_do_not_lock_out_the_owner(self):
        app = self.client.app
        stranger = TestClient(app, base_url="http://localhost", client=("10.0.0.99", 50000))
        owner = TestClient(app, base_url="http://localhost", client=("10.0.0.5", 50001))
        for _ in range(5):
            self.assertEqual(stranger.post("/api/auth/login", json={"password": "wrong"}).status_code, 401)
        self.assertEqual(stranger.post("/api/auth/login", json={"password": "wrong"}).status_code, 429)
        self.assertEqual(stranger.post("/api/auth/login", json={"password": PASSWORD}).status_code, 429)
        self.assertEqual(owner.post("/api/auth/login", json={"password": PASSWORD}).status_code, 200)

    def test_ipv6_loopback_host_is_accepted_and_bad_host_still_gets_headers(self):
        self.assertEqual(self.client.get("/healthz", headers={"host": "[::1]:4173"}).status_code, 200)
        rejected = self.client.get("/healthz", headers={"host": "evil.example"})
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("default-src 'self'", rejected.headers["content-security-policy"])
        self.assertEqual(rejected.headers["x-content-type-options"], "nosniff")


if __name__ == "__main__":
    unittest.main()

