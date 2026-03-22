import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()

from career.models import Experience
from career.serializers import ExperienceSerializer

# Create a test experience
exp = Experience.objects.create(
    title="Test Role",
    company="Test Company",
    description="I am testing the ML algorithm for NLP.",
    skills=["ML", "NLP", "Test"]
)
print(f"Created Exp ID: {exp.id}, Skills: {exp.skills}")

# Simulate frontend sending a PATCH request with skills removed
data = {
    'skills': ["ML", "NLP"]  # User removed "Test"
}

serializer = ExperienceSerializer(exp, data=data, partial=True)
if serializer.is_valid():
    updated_exp = serializer.save()
    print(f"Updated Exp Skills: {updated_exp.skills}")
else:
    print(f"Errors: {serializer.errors}")

# Clean up
exp.delete()
