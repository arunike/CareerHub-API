from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('availability', '0013_publicbooking'),
    ]

    operations = [
        migrations.AddField(
            model_name='sharelink',
            name='booking_block_minutes',
            field=models.IntegerField(default=30),
        ),
    ]
