# Generated by Django 2.1.15 on 2021-10-26 04:49

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rental', '0007_more_property_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='house',
            name='min_monthly_price',
            field=models.IntegerField(null=True),
        ),
        migrations.AddField(
            model_name='housets',
            name='min_monthly_price',
            field=models.IntegerField(null=True),
        ),
    ]
