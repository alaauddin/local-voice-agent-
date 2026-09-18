import json

from django.test import TestCase, override_settings

from kiosk_agent.core.prompt_builder import build_system_prompt
from kiosk_agent.core.realtime import build_realtime_session
from kiosk_agent.core.tools import execute_tool, openai_tool_schemas
from kiosk_agent.core.voice import clean_spoken_text, split_spoken_text
from kiosk_agent.models import ChaletConfig, KioskAuditLog, StaffRequest


class AgentToolTests(TestCase):
    def setUp(self):
        self.config = ChaletConfig.load()
        self.config.chalet_number = "101"
        self.config.property_facts = {"checkout": "12:00"}
        self.config.enabled_services = ["housekeeping"]
        self.config.save()

    def test_prompt_has_fixed_identity_and_never_asks_number(self):
        prompt = build_system_prompt(self.config)
        self.assertIn("reliably known to be number\n  101", prompt)
        self.assertIn("Never ask for, infer, verify, or reconfirm the chalet number", prompt)
        self.assertIn("last golden ray over the sea", prompt)
        self.assertIn("one or two short natural sentences", prompt)
        self.assertIn("call request_property_staff in the same turn", prompt)
        self.assertNotIn("register_chalet_guest", prompt)

    @override_settings(
        REALTIME_VAD_MODE="semantic_vad",
        REALTIME_VAD_EAGERNESS="high",
        REALTIME_TRANSCRIPTION_MODEL="gpt-4o-transcribe",
    )
    def test_realtime_is_arabic_only_and_preserves_semantic_turns(self):
        session, _ = build_realtime_session()
        self.assertIn("Speak and write in Arabic only", session["instructions"])
        self.assertIn("must be entirely in Arabic", session["instructions"])
        self.assertEqual(
            session["audio"]["input"]["turn_detection"],
            {
                "type": "semantic_vad",
                "eagerness": "high",
                "create_response": True,
                "interrupt_response": True,
            },
        )
        self.assertEqual(
            session["audio"]["input"]["transcription"]["model"],
            "gpt-4o-transcribe",
        )

    def test_tool_schemas_are_strict_pydantic_schemas(self):
        schemas = openai_tool_schemas()
        self.assertTrue(all(item["function"]["strict"] for item in schemas))
        self.assertTrue(all(item["function"]["parameters"]["additionalProperties"] is False for item in schemas))
        for item in schemas:
            parameters = item["function"]["parameters"]
            self.assertEqual(set(parameters["properties"]), set(parameters["required"]))

    def test_staff_request_urgency_is_required(self):
        result = execute_tool(
            "request_property_staff",
            json.dumps({"service": "housekeeping", "details": "Fresh towels"}),
            stay_id=str(self.config.current_stay_id),
            request_id="00000000-0000-0000-0000-000000000001",
        )
        self.assertEqual(json.loads(result)["error"], "validation_error")

    def test_staff_request_is_validated_and_audited(self):
        result = execute_tool(
            "request_property_staff",
            json.dumps({"service": "housekeeping", "details": "Fresh towels", "urgency": "normal"}),
            stay_id=str(self.config.current_stay_id),
            request_id="00000000-0000-0000-0000-000000000001",
        )
        self.assertTrue(json.loads(result)["result"]["accepted"])
        self.assertEqual(KioskAuditLog.objects.filter(event="tool_called").count(), 1)
        self.assertEqual(KioskAuditLog.objects.get(event="tool_called").details["chalet_number"], "101")
        self.assertEqual(StaffRequest.objects.count(), 1)
        self.assertEqual(StaffRequest.objects.get().service, "housekeeping")

    def test_invalid_tool_input_returns_safe_error(self):
        result = execute_tool(
            "request_property_staff",
            json.dumps({"service": "unsupported", "details": "x"}),
            stay_id=str(self.config.current_stay_id),
            request_id="00000000-0000-0000-0000-000000000001",
        )
        self.assertEqual(json.loads(result)["error"], "validation_error")

    def test_voice_text_is_cleaned_and_split_for_streaming(self):
        clean = clean_spoken_text("أهلاً **بك** 🌴. كيف يمكنني خدمتك؟")
        self.assertNotIn("**", clean)
        self.assertNotIn("🌴", clean)
        self.assertEqual(split_spoken_text(clean), ["أهلاً بك .", "كيف يمكنني خدمتك؟"])
