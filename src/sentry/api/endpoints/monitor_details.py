from __future__ import absolute_import

import logging
import six

from collections import OrderedDict
from croniter import croniter
from django.core.exceptions import ValidationError
from django.db import transaction
from rest_framework import serializers
from uuid import uuid4

from sentry.api.bases.monitor import MonitorEndpoint
from sentry.api.serializers import serialize
from sentry.tasks.deletion import generic_delete
from sentry.models import AuditLogEntryEvent, Monitor, MonitorStatus, MonitorType, ScheduleType


SCHEDULE_TYPES = OrderedDict([
    ('crontab', ScheduleType.CRONTAB),
    ('interval', ScheduleType.INTERVAL),
])

MONITOR_TYPES = OrderedDict([
    ('cron_job', MonitorType.CRON_JOB),
])

MONITOR_STATUSES = OrderedDict([
    ('active', MonitorStatus.ACTIVE),
    ('disabled', MonitorStatus.DISABLED),
])

INTERVAL_NAMES = ('year', 'month', 'week', 'day', 'hour', 'minute')

# XXX(dcramer): @reboot is not supported (as it cannot be)
NONSTANDARD_CRONTAB_SCHEDULES = {
    '@yearly': '0 0 1 1 *',
    '@annually': '0 0 1 1 *',
    '@monthly': '0 0 1 * *',
    '@weekly': '0 0 * * 0',
    '@daily': '0 0 * * *',
    '@hourly': '0 * * * *',
}

delete_logger = logging.getLogger('sentry.deletions.api')


def parse_nonstandard_crontab(value):
    ['@yearly', '0 0 1 1 *'],
    ['@annually', '0 0 1 1 *'],
    ['@monthly', '0 0 1 * *'],
    ['@weekly', '0 0 * * 0'],
    ['@daily', '0 0 * * *'],
    ['@hourly', '0 * * * *'],


class CronJobSerializer(serializers.Serializer):
    schedule_type = serializers.ChoiceField(
        choices=zip(SCHEDULE_TYPES.keys(), SCHEDULE_TYPES.keys()),
    )
    schedule = serializers.WritableField()

    def validate(self, attrs):
        if 'schedule_type' in attrs:
            schedule_type = SCHEDULE_TYPES[attrs['schedule_type']]
            attrs['schedule_type'] = schedule_type
        else:
            schedule_type = self.object['schedule_type']

        if 'schedule' in attrs:
            schedule = attrs['schedule']
            if schedule_type == ScheduleType.INTERVAL:
                if not isinstance(schedule, list):
                    raise ValidationError({
                        'schedule': ['Invalid value for schedule_type'],
                    })
                if not isinstance(schedule[0], int):
                    raise ValidationError({
                        'schedule': ['Invalid value for schedule frequency'],
                    })
                if schedule[1] not in INTERVAL_NAMES:
                    raise ValidationError({
                        'schedule': ['Invalid value for schedlue interval'],
                    })
            elif schedule_type == ScheduleType.CRONTAB:
                schedule = schedule.strip()
                if not isinstance(schedule, six.string_types):
                    raise ValidationError({
                        'schedule': ['Invalid value for schedule_type'],
                    })
                if schedule.startswith('@'):
                    try:
                        schedule = NONSTANDARD_CRONTAB_SCHEDULES[schedule]
                    except KeyError:
                        raise ValidationError({
                            'schedule': ['Schedule was not parseable'],
                        })
                if not croniter.is_valid(schedule):
                    raise ValidationError({
                        'schedule': ['Schedule was not parseable'],
                    })
                attrs['schedule'] = schedule
        return attrs


class MonitorSerializer(serializers.Serializer):
    name = serializers.CharField()
    status = serializers.ChoiceField(
        choices=zip(MONITOR_STATUSES.keys(), MONITOR_STATUSES.keys())
    )
    type = serializers.ChoiceField(
        choices=zip(MONITOR_TYPES.keys(), MONITOR_TYPES.keys())
    )

    def get_default_fields(self):
        type = self.init_data.get('type', self.object['type'])
        if type in MONITOR_TYPES:
            type = MONITOR_TYPES[type]
        if type == MonitorType.CRON_JOB:
            config = CronJobSerializer()
        else:
            raise NotImplementedError
        return {'config': config}

    def validate(self, attrs):
        if 'type' in attrs:
            attrs['type'] = MONITOR_TYPES[attrs['type']]
        if 'status' in attrs:
            attrs['status'] = MONITOR_STATUSES[attrs['status']]
        return attrs


class MonitorDetailsEndpoint(MonitorEndpoint):
    def get(self, request, project, monitor):
        """
        Retrieve a monitor
        ``````````````````

        :pparam string monitor_id: the id of the monitor.
        :auth: required
        """
        return self.respond(serialize(monitor, request.user))

    def put(self, request, project, monitor):
        """
        Update a monitor
        ````````````````

        :pparam string monitor_id: the id of the monitor.
        :auth: required
        """
        serializer = MonitorSerializer(
            data=request.DATA,
            partial=True,
            instance={
                'name': monitor.name,
                'status': monitor.status,
                'type': monitor.type,
                'config': monitor.config,
            },
            context={
                'project': project,
                'request': request,
            },
        )
        if not serializer.is_valid():
            return self.respond(serializer.errors, status=400)

        result = serializer.data

        params = {}
        if 'name' in result:
            params['name'] = result['name']
        if 'status' in result:
            if result['status'] == MonitorStatus.ACTIVE:
                if monitor.status not in (MonitorStatus.OK, MonitorStatus.ERROR):
                    params['status'] = MonitorStatus.ACTIVE
            else:
                params['status'] = result['status']
        if 'config' in result:
            params['config'] = result['config']

        if params:
            monitor.update(**params)
            self.create_audit_entry(
                request=request,
                organization=project.organization,
                target_object=monitor.id,
                event=AuditLogEntryEvent.MONITOR_EDIT,
                data=monitor.get_audit_log_data(),
            )

        return self.respond(serialize(monitor, request.user))

    def delete(self, request, project, monitor):
        """
        Delete a monitor
        ````````````````

        :pparam string monitor_id: the id of the monitor.
        :auth: required
        """
        # TODO(dcramer0:)
        with transaction.atomic():
            affected = Monitor.objects.filter(
                id=monitor.id,
            ).exclude(
                status__in=[MonitorStatus.PENDING_DELETION, MonitorStatus.DELETION_IN_PROGRESS],
            ).update(
                status=MonitorStatus.PENDING_DELETION
            )
            if not affected:
                return self.respond(status=404)

            transaction_id = uuid4().hex

            self.create_audit_entry(
                request=request,
                organization=project.organization,
                target_object=monitor.id,
                event=AuditLogEntryEvent.MONITOR_REMOVE,
                data=monitor.get_audit_log_data(),
                transaction_id=transaction_id,
            )

        generic_delete.apply_async(
            kwargs={
                'object_id': monitor.id,
                'transaction_id': transaction_id,
                'actor_id': request.user.id,
            },
        )

        delete_logger.info(
            'object.delete.queued',
            extra={
                'object_id': monitor.id,
                'transaction_id': transaction_id,
                'model': Monitor.__name__,
            }
        )
        return self.respond(status=202)
