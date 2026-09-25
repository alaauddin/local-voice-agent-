from rest_framework import serializers

from .ac_control import serialize_ac_state
from .models import ACState, ChaletConfig, KioskMessage, RemoteButton, RemoteControl


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


class RemoteButtonPublicSerializer(serializers.ModelSerializer):
    configured = serializers.SerializerMethodField()

    class Meta:
        model = RemoteButton
        fields = (
            "id",
            "key",
            "label",
            "icon",
            "row",
            "column",
            "sort_order",
            "requires_confirmation",
            "configured",
        )

    def get_configured(self, obj):
        return obj.is_configured


class RemoteControlPublicSerializer(serializers.ModelSerializer):
    buttons = serializers.SerializerMethodField()
    brand_label = serializers.CharField(source="get_brand_display", read_only=True)
    ac_state = serializers.SerializerMethodField()

    class Meta:
        model = RemoteControl
        fields = (
            "id",
            "name",
            "slug",
            "location",
            "device_name",
            "device_type",
            "brand",
            "brand_label",
            "protocol",
            "protocol_model",
            "sort_order",
            "ac_state",
            "buttons",
        )

    def get_buttons(self, obj):
        buttons = [button for button in obj.buttons.all() if button.is_active]
        return RemoteButtonPublicSerializer(buttons, many=True).data

    def get_ac_state(self, obj):
        if obj.device_type != RemoteControl.DeviceType.AC:
            return None
        try:
            state = obj.ac_state
        except ACState.DoesNotExist:
            state, _ = ACState.objects.get_or_create(device=obj)
        return {
            "state_version": state.state_version,
            "updated_at": state.updated_at,
            **serialize_ac_state(state),
        }
