# -*- coding: utf-8 -*-
# Generated by Django 1.9.10 on 2016-12-08 13:51
from __future__ import unicode_literals

from django.db import migrations
import django.db.models.manager


class Migration(migrations.Migration):

    dependencies = [
        ('msgs', '0073_auto_20161201_1639'),
    ]

    operations = [
        migrations.AlterModelManagers(
            name='label',
            managers=[
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
    ]
