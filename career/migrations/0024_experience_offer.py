from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('career', '0023_offer_raise_history'),
    ]

    operations = [
        migrations.AddField(
            model_name='experience',
            name='offer',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='experiences',
                to='career.offer',
                help_text='Linked offer for raise history tracking',
            ),
        ),
    ]
