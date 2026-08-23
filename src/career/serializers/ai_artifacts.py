
from rest_framework import serializers

from ..models import AIArtifact, AIArtifactGenerationJob, Application, Offer, Experience


class AIArtifactSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIArtifact
        fields = [
            'id',
            'artifact_type',
            'client_id',
            'title',
            'summary',
            'payload',
            'source_application',
            'source_offer',
            'source_experience',
            'is_locked',
            'saved_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        if request and getattr(request, 'user', None) and request.user.is_authenticated:
            fields['source_application'].queryset = Application.objects.filter(user=request.user)
            fields['source_offer'].queryset = Offer.objects.filter(application__user=request.user)
            fields['source_experience'].queryset = Experience.objects.filter(user=request.user)
        else:
            fields['source_application'].queryset = Application.objects.none()
            fields['source_offer'].queryset = Offer.objects.none()
            fields['source_experience'].queryset = Experience.objects.none()
        return fields

    def validate_payload(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Artifact payload must be an object.')
        return value

    def create(self, validated_data):
        request = self.context.get('request')
        artifact, _ = AIArtifact.objects.update_or_create(
            user=request.user,
            client_id=validated_data['client_id'],
            defaults=validated_data,
        )
        return artifact


class AIArtifactGenerationJobSerializer(serializers.ModelSerializer):
    artifact_client_id = serializers.CharField(source='artifact.client_id', read_only=True)

    class Meta:
        model = AIArtifactGenerationJob
        fields = [
            'id',
            'kind',
            'status',
            'input_payload',
            'result_payload',
            'error_message',
            'artifact',
            'artifact_client_id',
            'started_at',
            'completed_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'status',
            'result_payload',
            'error_message',
            'artifact',
            'artifact_client_id',
            'started_at',
            'completed_at',
            'created_at',
            'updated_at',
        ]

    def validate_input_payload(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Job input payload must be an object.')
        messages = value.get('messages')
        if not isinstance(messages, list) or not messages:
            raise serializers.ValidationError('Job input payload must include messages.')
        artifact = value.get('artifact')
        if not isinstance(artifact, dict):
            raise serializers.ValidationError('Job input payload must include artifact metadata.')
        return value

    def create(self, validated_data):
        request = self.context.get('request')
        return AIArtifactGenerationJob.objects.create(user=request.user, **validated_data)
