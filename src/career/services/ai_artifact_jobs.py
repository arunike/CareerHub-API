import json
import threading

from django.db import transaction
from django.utils import timezone

from availability.ai_provider import (
    AIProviderConfigurationError,
    AIProviderRequestError,
    relay_ai_provider_chat_completion,
)
from availability.models import UserSettings

from ..cache import invalidate_ai_artifacts_cache
from ..models import AIArtifact, AIArtifactGenerationJob


def _strip_code_fences(value: str) -> str:
    text = value.strip()
    if text.startswith('```'):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
        return '\n'.join(lines).strip()
    return text


def _completion_content(payload: dict) -> str:
    choices = payload.get('choices') if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices:
        raise AIProviderRequestError('Provider returned an empty completion.')
    message = choices[0].get('message') if isinstance(choices[0], dict) else None
    content = message.get('content') if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise AIProviderRequestError('Provider returned an empty completion.')
    return _strip_code_fences(content)


def _fail_job(job: AIArtifactGenerationJob, message: str):
    job.status = AIArtifactGenerationJob.STATUS_FAILED
    job.error_message = message
    job.completed_at = timezone.now()
    job.save(update_fields=['status', 'error_message', 'completed_at', 'updated_at'])


def process_ai_artifact_generation_job(job_id: int) -> AIArtifactGenerationJob:
    with transaction.atomic():
        job = AIArtifactGenerationJob.objects.select_for_update().get(id=job_id)
        if job.status not in [
            AIArtifactGenerationJob.STATUS_QUEUED,
            AIArtifactGenerationJob.STATUS_RUNNING,
        ]:
            return job
        job.status = AIArtifactGenerationJob.STATUS_RUNNING
        job.started_at = job.started_at or timezone.now()
        job.error_message = ''
        job.save(update_fields=['status', 'started_at', 'error_message', 'updated_at'])

    try:
        input_payload = job.input_payload or {}
        messages = input_payload.get('messages') or []
        artifact_payload = input_payload.get('artifact') or {}
        temperature = input_payload.get('temperature', 0.25)
        max_tokens = input_payload.get('max_tokens')

        user_settings, _ = UserSettings.objects.get_or_create(user=job.user)
        provider_payload = relay_ai_provider_chat_completion(
            user_settings=user_settings,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        review = json.loads(_completion_content(provider_payload))
        saved_at = timezone.now().isoformat()
        client_id = artifact_payload.get('client_id') or f'promotion-review-{job.id}'
        stored_review = {
            'id': client_id,
            'title': artifact_payload.get('title') or 'Promotion Review',
            'companyName': artifact_payload.get('companyName') or '',
            'roleTitle': artifact_payload.get('roleTitle') or '',
            'sourceExperienceId': artifact_payload.get('sourceExperienceId'),
            'inputContext': artifact_payload.get('inputContext') or {},
            'review': review,
            'savedAt': saved_at,
        }

        artifact, _ = AIArtifact.objects.update_or_create(
            user=job.user,
            client_id=client_id,
            defaults={
                'artifact_type': AIArtifact.TYPE_PROMOTION_REVIEW,
                'title': stored_review['title'],
                'summary': review.get('readiness_verdict', {}).get('summary', ''),
                'payload': stored_review,
                'source_experience_id': artifact_payload.get('sourceExperienceId'),
                'saved_at': timezone.now(),
            },
        )
        invalidate_ai_artifacts_cache(job.user_id)

        job.status = AIArtifactGenerationJob.STATUS_SUCCEEDED
        job.result_payload = {
            'review': review,
            'artifact_client_id': artifact.client_id,
            'artifact_id': artifact.id,
        }
        job.artifact = artifact
        job.completed_at = timezone.now()
        job.save(
            update_fields=[
                'status',
                'result_payload',
                'artifact',
                'completed_at',
                'updated_at',
            ]
        )
    except json.JSONDecodeError:
        _fail_job(
            job,
            'AI provider returned incomplete JSON. Try again, or switch to a faster model for this review.',
        )
    except (AIProviderConfigurationError, AIProviderRequestError) as exc:
        _fail_job(job, str(exc))
    except Exception as exc:
        _fail_job(job, 'Promotion review generation failed.')
        raise exc

    return job


def process_next_ai_artifact_generation_job() -> AIArtifactGenerationJob | None:
    job = (
        AIArtifactGenerationJob.objects.filter(status=AIArtifactGenerationJob.STATUS_QUEUED)
        .order_by('created_at')
        .first()
    )
    if not job:
        return None
    return process_ai_artifact_generation_job(job.id)


def start_ai_artifact_generation_thread(job_id: int):
    thread = threading.Thread(
        target=process_ai_artifact_generation_job,
        args=(job_id,),
        daemon=True,
    )
    thread.start()
    return thread
