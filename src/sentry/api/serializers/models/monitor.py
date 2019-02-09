from __future__ import absolute_import

import six

from sentry.api.serializers import Serializer, register
from sentry.models import Monitor, ScheduleType


SCHEDULE_TYPES = dict(ScheduleType.as_choices())


@register(Monitor)
class MonitorSerializer(Serializer):
    def serialize(self, obj, attrs, user):
        config = obj.config.copy()
        if 'schedule_type' in config:
            config['schedule_type'] = SCHEDULE_TYPES.get(config['schedule_type'], 'unknown')
        return {
            'id': six.text_type(obj.guid),
            'status': obj.get_status_display(),
            'type': obj.get_type_display(),
            'name': obj.name,
            'config': config,
            'lastCheckIn': obj.last_checkin,
            'nextCheckIn': obj.next_checkin,
            'dateCreated': obj.date_added,
        }
