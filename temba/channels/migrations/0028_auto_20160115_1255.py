# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('channels', '0027_auto_20151103_1014'),
    ]

    operations = [
        migrations.AlterField(
            model_name='channel',
            name='channel_type',
            field=models.CharField(default='A', help_text='Type of this channel, whether Android, Twilio or SMSC', max_length=3, verbose_name='Channel Type', choices=[('A', 'Android'), ('T', 'Twilio'), ('AT', "Africa's Talking"), ('ZV', 'Zenvia'), ('NX', 'Nexmo'), ('IB', 'Infobip'), ('VB', 'Verboice'), ('H9', 'Hub9'), ('VM', 'Vumi'), ('KN', 'Kannel'), ('EX', 'External'), ('TT', 'Twitter'), ('CT', 'Clickatell'), ('PL', 'Plivo'), ('SQ', 'Shaqodoon'), ('HX', 'High Connection'), ('BM', 'Blackmyna'), ('SC', 'SMSCentral'), ('YO', 'Yo!'), ('M3', 'M3 Tech'), ('WA', 'WhatsApp')]),
        ),
    ]