from django.db import models

class Company(models.Model):
    name = models.CharField(max_length=255)
    website = models.URLField(blank=True, null=True)
    industry = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Companies"

    def __str__(self):
        return self.name

class Application(models.Model):
    STATUS_CHOICES = [
        ('APPLIED', 'Applied'),
        ('OA', 'Online Assessment'),
        ('SCREEN', 'Phone Screen'),
        ('ONSITE', 'Onsite Interview'),
        ('OFFER', 'Offer Received'),
        ('REJECTED', 'Rejected'),
        ('ACCEPTED', 'Accepted'),
        ('GHOSTED', 'Ghosted'),
    ]

    RTO_CHOICES = [
        ('REMOTE', 'Remote'),
        ('HYBRID', 'Hybrid'),
        ('ONSITE', 'Onsite'),
        ('UNKNOWN', 'Unknown'),
    ]
    VALUE_FREQUENCY_CHOICES = [
        ('DAILY', 'Daily'),
        ('MONTHLY', 'Monthly'),
        ('YEARLY', 'Yearly'),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='applications')
    role_title = models.CharField(max_length=255)
    job_link = models.URLField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='APPLIED')
    
    # Details
    rto_policy = models.CharField(max_length=20, choices=RTO_CHOICES, default='UNKNOWN')
    rto_days_per_week = models.PositiveSmallIntegerField(default=0)
    commute_cost_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    commute_cost_frequency = models.CharField(max_length=10, choices=VALUE_FREQUENCY_CHOICES, default='MONTHLY')
    free_food_perk_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    free_food_perk_frequency = models.CharField(max_length=10, choices=VALUE_FREQUENCY_CHOICES, default='YEARLY')
    tax_base_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    tax_bonus_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    tax_equity_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    monthly_rent_override = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    salary_range = models.CharField(max_length=100, blank=True, help_text="e.g. $150k - $180k")
    location = models.CharField(max_length=100, blank=True)
    
    notes = models.TextField(blank=True)
    current_round = models.IntegerField(default=0, help_text="Current interview round number (0 for none)")
    is_locked = models.BooleanField(default=False, help_text="Locked applications cannot be deleted")
    
    date_applied = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.role_title} at {self.company.name}"

class Offer(models.Model):
    application = models.OneToOneField(Application, on_delete=models.CASCADE, related_name='offer')
    
    base_salary = models.DecimalField(max_digits=12, decimal_places=2, help_text="Annual Base Salary")
    bonus = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Annual Target Bonus")
    equity = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Annualized Equity Value")
    equity_total_grant = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text="Total equity grant value")
    equity_vesting_percent = models.DecimalField(max_digits=5, decimal_places=2, default=25, help_text="Annual vesting percent used for annualized equity")
    sign_on = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="One-time Sign On Bonus")
    benefits_value = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Estimated Annual Benefits Value")
    benefit_items = models.JSONField(default=list, blank=True, help_text="Benefit item breakdown used to derive annual benefits value")
    pto_days = models.IntegerField(default=15)
    holiday_days = models.IntegerField(default=11)
    is_current = models.BooleanField(default=False, help_text="Is this your current role?")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Offer for {self.application}"

class Document(models.Model):
    DOCUMENT_TYPES = [
        ('RESUME', 'Resume'),
        ('COVER_LETTER', 'Cover Letter'),
        ('PORTFOLIO', 'Portfolio'),
        ('OTHER', 'Other'),
    ]

    title = models.CharField(max_length=255)
    file = models.FileField(upload_to='documents/')
    document_type = models.CharField(max_length=20, choices=DOCUMENT_TYPES, default='RESUME')
    application = models.ForeignKey(Application, on_delete=models.SET_NULL, null=True, blank=True, related_name='documents')
    root_document = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='versions')
    version_number = models.PositiveIntegerField(default=1)
    is_current = models.BooleanField(default=True)
    is_locked = models.BooleanField(default=False, help_text="Locked documents cannot be deleted")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} (v{self.version_number})"


class Task(models.Model):
    STATUS_CHOICES = [
        ('TODO', 'To Do'),
        ('IN_PROGRESS', 'In Progress'),
        ('DONE', 'Done'),
    ]

    PRIORITY_CHOICES = [
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
    ]

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='TODO')
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='MEDIUM')
    due_date = models.DateField(null=True, blank=True)
    position = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['status', 'position', '-updated_at']

    def __str__(self):
        return self.title
