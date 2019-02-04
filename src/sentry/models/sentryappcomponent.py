from __future__ import absolute_import

import six
import uuid

from django.db import models

from sentry.db.models import EncryptedJsonField, FlexibleForeignKey, Model


def default_uuid():
    return six.binary_type(uuid.uuid4())


class SentryAppComponent(Model):
    __core__ = True

    uuid = models.CharField(max_length=64, default=default_uuid)
    sentry_app = FlexibleForeignKey('sentry.SentryApp'),
    type = models.CharField(max_length=64, null=False)
    schema = EncryptedJsonField(null=False)

    class Meta:
        app_label = 'sentry'
        db_table = 'sentry_sentryappcomponent'
