from rest_framework import serializers

from .models import ChaletConfig, KioskMessage


class ChatRequestSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=4000, trim_whitespace=True)


class RealtimeMessageSerializer(serializers.Serializer):
    stay_id = serializers.UUIDField()
    session_id = serializers.UUIDField()
    request_id = serializers.UUIDField()
    role = serializers.ChoiceField(choices=("user", "assistant"))
    content = serializers.CharField(max_length=4000, trim_whitespace=True)
    event_id = serializers.CharField(max_length=200, required=False, allow_blank=True)
    input_mode = serializers.ChoiceField(
        choices=("voice", "text", "realtime"), default="realtime"
    )


class RealtimeToolSerializer(serializers.Serializer):
    stay_id = serializers.UUIDField()
    session_id = serializers.UUIDField()
    request_id = serializers.UUIDField()
    call_id = serializers.CharField(min_length=1, max_length=200)
    name = serializers.CharField(min_length=1, max_length=100)
    arguments = serializers.JSONField()


class RealtimeSessionIdentitySerializer(serializers.Serializer):
    stay_id = serializers.UUIDField()
    session_id = serializers.UUIDField()


class KioskMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = KioskMessage
        fields = (
            "id",
            "request_id",
            "role",
            "content",
            "status",
            "tool_name",
            "sequence",
            "metadata",
            "created_at",
        )


class ChaletPublicSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChaletConfig
        fields = ("chalet_name", "persona_name", "welcome_message", "enabled_services")
