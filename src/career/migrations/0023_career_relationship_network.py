from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_career_relationship_network(apps, schema_editor):
    Application = apps.get_model('career', 'Application')
    ApplicationContact = apps.get_model('career', 'ApplicationContact')
    CareerRecord = apps.get_model('career', 'CareerRecord')
    Contact = apps.get_model('career', 'Contact')
    ContactContext = apps.get_model('career', 'ContactContext')
    ContactRelationship = apps.get_model('career', 'ContactRelationship')
    Experience = apps.get_model('career', 'Experience')

    record_by_application = {}
    for application in Application.objects.exclude(user_id=None).iterator():
        record = CareerRecord.objects.create(
            user_id=application.user_id,
            application_id=application.id,
        )
        record_by_application[application.id] = record

    record_by_experience = {}
    experiences = Experience.objects.select_related('offer').exclude(user_id=None)
    for experience in experiences.iterator():
        application_id = getattr(experience.offer, 'application_id', None)
        record = record_by_application.get(application_id)
        if record is None:
            record = CareerRecord.objects.create(user_id=experience.user_id)
        Experience.objects.filter(id=experience.id).update(career_record_id=record.id)
        record_by_experience[experience.id] = record
        if application_id:
            Application.objects.filter(id=application_id).exclude(status='ACCEPTED').update(
                status='ACCEPTED'
            )

    contacts_by_email = {}
    for legacy in ApplicationContact.objects.order_by('id').iterator():
        normalized_email = (legacy.email or '').strip().lower()
        key = (legacy.user_id, normalized_email) if normalized_email else None
        contact = contacts_by_email.get(key) if key else None

        if contact is None:
            contact = Contact.objects.create(
                user_id=legacy.user_id,
                name=(legacy.name or '').strip(),
                email=normalized_email,
                notes=legacy.notes or '',
                is_locked=legacy.is_locked,
            )
            if key:
                contacts_by_email[key] = contact
        else:
            updates = []
            if legacy.is_locked and not contact.is_locked:
                contact.is_locked = True
                updates.append('is_locked')
            note = (legacy.notes or '').strip()
            if note and note not in contact.notes:
                contact.notes = f'{contact.notes.strip()}\n\n{note}'.strip()
                updates.append('notes')
            if updates:
                contact.save(update_fields=updates)

        relationship_record = None
        if legacy.application_id:
            record = record_by_application.get(legacy.application_id)
            if record:
                context_filter = {
                    'contact_id': contact.id,
                    'application_id': legacy.application_id,
                    'experience_id': None,
                }
                if not ContactContext.objects.filter(**context_filter).exists():
                    ContactContext.objects.create(
                        **context_filter,
                        career_record_id=record.id,
                        source='APPLICATION',
                        notes=legacy.notes or '',
                    )
                relationship_record = relationship_record or record

        if legacy.experience_id:
            record = record_by_experience.get(legacy.experience_id)
            if record:
                context_filter = {
                    'contact_id': contact.id,
                    'application_id': None,
                    'experience_id': legacy.experience_id,
                }
                if not ContactContext.objects.filter(**context_filter).exists():
                    ContactContext.objects.create(
                        **context_filter,
                        career_record_id=record.id,
                        source='EXPERIENCE',
                        notes=legacy.notes or '',
                    )
                relationship_record = relationship_record or record

        relationship_filter = {
            'user_id': legacy.user_id,
            'source_contact_id': None,
            'target_contact_id': contact.id,
            'kind': 'CONTACT',
            'custom_label': '',
        }
        if not ContactRelationship.objects.filter(**relationship_filter).exists():
            ContactRelationship.objects.create(
                **relationship_filter,
                career_record_id=relationship_record.id if relationship_record else None,
            )


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('career', '0022_application_submitted_documents_interviewdebrief'),
    ]

    operations = [
        migrations.CreateModel(
            name='CareerRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('application', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='career_record', to='career.application')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='career_records', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-updated_at', '-id']},
        ),
        migrations.CreateModel(
            name='Contact',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('email', models.EmailField(blank=True, max_length=254)),
                ('phone', models.CharField(blank=True, max_length=50)),
                ('linkedin_url', models.URLField(blank=True, max_length=2048)),
                ('job_title', models.CharField(blank=True, max_length=255)),
                ('company', models.CharField(blank=True, max_length=255)),
                ('notes', models.TextField(blank=True)),
                ('is_locked', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='career_contacts', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['name', 'id'],
                'indexes': [
                    models.Index(fields=['user', 'name'], name='career_person_name_idx'),
                    models.Index(fields=['user', 'email'], name='career_person_email_idx'),
                ],
            },
        ),
        migrations.AddField(
            model_name='experience',
            name='career_record',
            field=models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='experiences', to='career.careerrecord'),
        ),
        migrations.CreateModel(
            name='ContactContext',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source', models.CharField(choices=[('APPLICATION', 'Application'), ('EXPERIENCE', 'Experience'), ('MANUAL', 'Manual')], max_length=20)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('application', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='contact_contexts', to='career.application')),
                ('career_record', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='contact_contexts', to='career.careerrecord')),
                ('contact', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='contexts', to='career.contact')),
                ('experience', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='contact_contexts', to='career.experience')),
            ],
            options={
                'ordering': ['created_at', 'id'],
                'indexes': [
                    models.Index(fields=['career_record', 'contact'], name='career_context_record_idx'),
                    models.Index(fields=['application', 'contact'], name='career_context_app_idx'),
                    models.Index(fields=['experience', 'contact'], name='career_context_exp_idx'),
                ],
                'constraints': [
                    models.CheckConstraint(
                        check=models.Q(application__isnull=False) | models.Q(experience__isnull=False),
                        name='contact_context_has_owner',
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name='ContactRelationship',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('CONTACT', 'Contact'), ('RECRUITER', 'Recruiter'), ('INTERVIEWER', 'Interviewer'), ('HIRING_MANAGER', 'Hiring Manager'), ('MANAGER', 'Manager'), ('DIRECT_TEAMMATE', 'Direct Teammate'), ('COWORKER', 'Coworker'), ('DIRECT_REPORT', 'Direct Report'), ('REFERRAL', 'Referral'), ('MENTOR', 'Mentor'), ('WORKS_WITH', 'Works With'), ('CUSTOM', 'Custom')], default='CONTACT', max_length=30)),
                ('custom_label', models.CharField(blank=True, max_length=80)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('career_record', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='contact_relationships', to='career.careerrecord')),
                ('source_contact', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='outgoing_relationships', to='career.contact')),
                ('target_contact', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='incoming_relationships', to='career.contact')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='contact_relationships', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['created_at', 'id'],
                'indexes': [
                    models.Index(fields=['user', 'source_contact'], name='career_rel_source_idx'),
                    models.Index(fields=['user', 'target_contact'], name='career_rel_target_idx'),
                ],
            },
        ),
        migrations.RunPython(backfill_career_relationship_network, migrations.RunPython.noop),
    ]
