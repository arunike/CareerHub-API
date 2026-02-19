from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from availability.models import Event, EventCategory
from career.models import Application, Company
from .custom_widgets import process_query

class CustomWidgetTests(TestCase):
    def setUp(self):
        # Setup Availability Data
        self.category = EventCategory.objects.create(name='Work', color='#000000')
        now = timezone.now()
        
        Event.objects.create(
            name='Meeting 1', 
            date=now.date(), 
            start_time=(now).strftime('%H:%M'),
            end_time=(now + timedelta(hours=1)).strftime('%H:%M'),
            category=self.category
        )
        Event.objects.create(
            name='Meeting 2', 
            date=now.date(), 
            start_time=(now).strftime('%H:%M'),
            end_time=(now + timedelta(hours=1)).strftime('%H:%M'),
            category=self.category
        )
        
        # Setup Career Data
        self.company = Company.objects.create(name='Tech Corp')
        Application.objects.create(
            company=self.company,
            role_title='Dev',
            status='APPLIED',
            date_applied=now.date()
        )
        Application.objects.create(
            company=self.company,
            role_title='Senior Dev',
            status='REJECTED',
            date_applied=now.date()
        )

    def test_availability_metrics(self):
        # Total Events
        result = process_query('Total events', 'availability')
        self.assertEqual(result['type'], 'metric')
        self.assertEqual(result['value'], 2)
        
        # Total Events This Month
        result = process_query('Total events this month', 'availability')
        self.assertEqual(result['value'], 2)

    def test_availability_charts(self):
        # Events by Category
        result = process_query('Events by category', 'availability')
        self.assertEqual(result['type'], 'chart')
        self.assertEqual(len(result['data']), 1)
        self.assertEqual(result['data'][0]['name'], 'Work')
        self.assertEqual(result['data'][0]['value'], 2)

    def test_job_hunt_metrics(self):
        # Total Applications
        result = process_query('Total applications', 'job-hunt')
        self.assertEqual(result['value'], 2)
        
        # Active Applications (excludes REJECTED)
        result = process_query('Active applications', 'job-hunt')
        self.assertEqual(result['value'], 1)

    def test_job_hunt_charts(self):
        # Apps by Status
        result = process_query('Applications by status', 'job-hunt')
        self.assertEqual(result['type'], 'chart')
        # Should have data points for APPLIED and REJECTED
        statuses = [item['name'] for item in result['data']]
        self.assertIn('APPLIED', statuses)
        self.assertIn('REJECTED', statuses)
    def test_cross_context_query(self):
        """Test that a job-hunt query in availability context is handled correctly."""
        # Create an application
        Application.objects.create(
            company=self.company,
            role_title='Engineer',
            date_applied=timezone.now().date(),
            status='APPLIED'
        )
        
        response = self.client.post('/api/analytics/query/', {'query': 'Total applications', 'context': 'availability'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['type'], 'metric')
        self.assertEqual(response.data['value'], 3) # 2 from setUp + 1 new
        self.assertEqual(response.data['unit'], 'applications')

    def test_total_offers_query(self):
        """Test total offers query."""
        Application.objects.create(
            company=self.company,
            role_title='Engineer',
            date_applied=timezone.now().date(),
            status='OFFER'
        )
        
        response = self.client.post('/api/analytics/query/', {'query': 'Total offers', 'context': 'job-hunt'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['type'], 'metric')
        self.assertEqual(response.data['value'], 1)
        self.assertEqual(response.data['unit'], 'offers')

    def test_year_parsing(self):
        """Test query with specific year."""
        # Create an event in 2023
        date_2023 = (timezone.now() - timedelta(days=365*2)).date().replace(year=2023)
        Event.objects.create(
            name='2023 Event',
            date=date_2023,
            start_time='10:00',
            end_time='11:00',
            category=self.category
        )
        
        # Create an event in 2024
        date_2024 = (timezone.now() - timedelta(days=365)).date().replace(year=2024)
        Event.objects.create(
            name='2024 Event',
            date=date_2024,
            start_time='10:00',
            end_time='11:00',
            category=self.category
        )
        
        # Query for 2024
        response = self.client.post('/api/analytics/query/', {'query': 'Total events in 2024', 'context': 'availability'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['value'], 1)
