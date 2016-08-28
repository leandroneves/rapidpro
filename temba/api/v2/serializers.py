from __future__ import absolute_import, unicode_literals

import json
from django.forms import ValidationError

from rest_framework import serializers
from temba.api.models import Resthook, ResthookSubscriber, WebHookEvent
from temba.campaigns.models import Campaign, CampaignEvent
from temba.channels.models import Channel, ChannelEvent, ANDROID

from temba.contacts.models import Contact, ContactField, ContactGroup, URN
from temba.flows.models import Flow, FlowRun, FlowStep, FlowStart
from temba.locations.models import AdminBoundary
from temba.msgs.models import Broadcast, Msg, Label, STATUS_CONFIG, INCOMING, OUTGOING, INBOX, FLOW, IVR, PENDING
from temba.msgs.models import QUEUED
from temba.utils import datetime_to_json_date
from temba.values.models import Value


def format_datetime(value):
    """
    Datetime fields are formatted with microsecond accuracy for v2
    """
    return datetime_to_json_date(value, micros=True) if value else None


class ReadSerializer(serializers.ModelSerializer):
    """
    We deviate slightly from regular REST framework usage with distinct serializers for reading and writing
    """
    @staticmethod
    def extract_constants(config):
        return {t[0]: t[2] for t in config}

    def save(self, **kwargs):  # pragma: no cover
        raise ValueError("Can't call save on a read serializer")


class WriteSerializer(serializers.Serializer):
    """
    The normal REST framework way is to have the view decide if it's an update on existing instance or a create for a
    new instance. Since our logic for that gets relatively complex, we have the serializer make that call.
    """

    def __init__(self, *args, **kwargs):
        super(WriteSerializer, self).__init__(*args, **kwargs)
        self.instance = None

    def run_validation(self, data=serializers.empty):
        if not isinstance(data, dict):
            raise serializers.ValidationError(detail={'non_field_errors': ["Request body should be a single JSON object"]})

        return super(WriteSerializer, self).run_validation(data)


class UUIDListField(serializers.ListField):
    child = serializers.UUIDField()


class URNField(serializers.CharField):
    def to_representation(self, obj):
        return unicode(obj)

    def to_internal_value(self, data):
        if not URN.validate(data):
            raise ValidationError("Invalid URN: %s" % data)

        return URN.normalize(data)


class URNListField(serializers.ListField):
    child = URNField()


# ============================================================
# Serializers (A-Z)
# ============================================================

class AdminBoundaryReadSerializer(ReadSerializer):
    parent = serializers.SerializerMethodField()
    aliases = serializers.SerializerMethodField()
    geometry = serializers.SerializerMethodField()

    def get_parent(self, obj):
        return {'osm_id': obj.parent.osm_id, 'name': obj.parent.name} if obj.parent else None

    def get_aliases(self, obj):
        return [alias.name for alias in obj.aliases.all()]

    def get_geometry(self, obj):
        if self.context['include_geometry'] and obj.simplified_geometry:
            return json.loads(obj.simplified_geometry.geojson)
        else:
            return None

    class Meta:
        model = AdminBoundary
        fields = ('osm_id', 'name', 'parent', 'level', 'aliases', 'geometry')


class BroadcastReadSerializer(ReadSerializer):
    urns = serializers.SerializerMethodField()
    contacts = serializers.SerializerMethodField()
    groups = serializers.SerializerMethodField()

    def get_urns(self, obj):
        if self.context['org'].is_anon:
            return None
        else:
            return [urn.urn for urn in obj.urns.all()]

    def get_contacts(self, obj):
        return [{'uuid': c.uuid, 'name': c.name} for c in obj.contacts.all()]

    def get_groups(self, obj):
        return [{'uuid': g.uuid, 'name': g.name} for g in obj.groups.all()]

    class Meta:
        model = Broadcast
        fields = ('id', 'urns', 'contacts', 'groups', 'text', 'created_on')


class ChannelEventReadSerializer(ReadSerializer):
    TYPES = ReadSerializer.extract_constants(ChannelEvent.TYPE_CONFIG)

    type = serializers.SerializerMethodField()
    contact = serializers.SerializerMethodField()
    channel = serializers.SerializerMethodField()

    def get_type(self, obj):
        return self.TYPES.get(obj.event_type)

    def get_contact(self, obj):
        return {'uuid': obj.contact.uuid, 'name': obj.contact.name}

    def get_channel(self, obj):
        return {'uuid': obj.channel.uuid, 'name': obj.channel.name}

    class Meta:
        model = ChannelEvent
        fields = ('id', 'type', 'contact', 'channel', 'time', 'duration', 'created_on')


class CampaignReadSerializer(ReadSerializer):
    group = serializers.SerializerMethodField()

    def get_group(self, obj):
        return {'uuid': obj.group.uuid, 'name': obj.group.name}

    class Meta:
        model = Campaign
        fields = ('uuid', 'name', 'group', 'created_on')


class CampaignEventReadSerializer(ReadSerializer):
    UNITS = ReadSerializer.extract_constants(CampaignEvent.UNIT_CONFIG)

    campaign = serializers.SerializerMethodField()
    flow = serializers.SerializerMethodField()
    relative_to = serializers.SerializerMethodField()
    unit = serializers.SerializerMethodField()

    def get_campaign(self, obj):
        return {'uuid': obj.campaign.uuid, 'name': obj.campaign.name}

    def get_flow(self, obj):
        if obj.event_type == CampaignEvent.TYPE_FLOW:
            return {'uuid': obj.flow.uuid, 'name': obj.flow.name}
        else:
            return None

    def get_relative_to(self, obj):
        return {'key': obj.relative_to.key, 'label': obj.relative_to.label}

    def get_unit(self, obj):
        return self.UNITS.get(obj.unit)

    class Meta:
        model = CampaignEvent
        fields = ('uuid', 'campaign', 'relative_to', 'offset', 'unit', 'delivery_hour', 'flow', 'message', 'created_on')


class ChannelReadSerializer(ReadSerializer):
    country = serializers.SerializerMethodField()
    device = serializers.SerializerMethodField()

    def get_country(self, obj):
        return unicode(obj.country) if obj.country else None

    def get_device(self, obj):
        if obj.channel_type != ANDROID:
            return None

        return {
            'name': obj.device,
            'power_level': obj.get_last_power(),
            'power_status': obj.get_last_power_status(),
            'power_source': obj.get_last_power_source(),
            'network_type': obj.get_last_network_type()
        }

    class Meta:
        model = Channel
        fields = ('uuid', 'name', 'address', 'country', 'device', 'last_seen', 'created_on')


class ContactReadSerializer(ReadSerializer):
    name = serializers.SerializerMethodField()
    language = serializers.SerializerMethodField()
    urns = serializers.SerializerMethodField()
    groups = serializers.SerializerMethodField()
    fields = serializers.SerializerMethodField('get_contact_fields')
    blocked = serializers.SerializerMethodField()
    stopped = serializers.SerializerMethodField()

    def get_name(self, obj):
        return obj.name if obj.is_active else None

    def get_language(self, obj):
        return obj.language if obj.is_active else None

    def get_urns(self, obj):
        if self.context['org'].is_anon or not obj.is_active:
            return []

        return [urn.urn for urn in obj.get_urns()]

    def get_groups(self, obj):
        if not obj.is_active:
            return []

        groups = obj.prefetched_user_groups if hasattr(obj, 'prefetched_user_groups') else obj.user_groups.all()
        return [{'uuid': g.uuid, 'name': g.name} for g in groups]

    def get_contact_fields(self, obj):
        if not obj.is_active:
            return {}

        fields = {}
        for contact_field in self.context['contact_fields']:
            value = obj.get_field(contact_field.key)
            fields[contact_field.key] = Contact.serialize_field_value(contact_field, value)
        return fields

    def get_blocked(self, obj):
        return obj.is_blocked if obj.is_active else None

    def get_stopped(self, obj):
        return obj.is_stopped if obj.is_active else None

    class Meta:
        model = Contact
        fields = ('uuid', 'name', 'language', 'urns', 'groups', 'fields', 'blocked', 'stopped',
                  'created_on', 'modified_on')


class ContactFieldReadSerializer(ReadSerializer):
    VALUE_TYPES = ReadSerializer.extract_constants(Value.TYPE_CONFIG)

    value_type = serializers.SerializerMethodField()

    def get_value_type(self, obj):
        return self.VALUE_TYPES.get(obj.value_type)

    class Meta:
        model = ContactField
        fields = ('key', 'label', 'value_type')


class ContactGroupReadSerializer(ReadSerializer):
    count = serializers.SerializerMethodField()

    def get_count(self, obj):
        return obj.get_member_count()

    class Meta:
        model = ContactGroup
        fields = ('uuid', 'name', 'query', 'count')


class FlowReadSerializer(ReadSerializer):
    archived = serializers.ReadOnlyField(source='is_archived')
    labels = serializers.SerializerMethodField()
    expires = serializers.ReadOnlyField(source='expires_after_minutes')
    runs = serializers.SerializerMethodField()

    def get_labels(self, obj):
        return [{'uuid': l.uuid, 'name': l.name} for l in obj.labels.all()]

    def get_runs(self, obj):
        return {
            'completed': obj.get_completed_runs(),
            'interrupted': obj.get_interrupted_runs(),
            'expired': obj.get_expired_runs()
        }

    class Meta:
        model = Flow
        fields = ('uuid', 'name', 'archived', 'labels', 'expires', 'runs', 'created_on')


class FlowRunReadSerializer(ReadSerializer):
    NODE_TYPES = {
        FlowStep.TYPE_RULE_SET: 'ruleset',
        FlowStep.TYPE_ACTION_SET: 'actionset'
    }
    EXIT_TYPES = {
        FlowRun.EXIT_TYPE_COMPLETED: 'completed',
        FlowRun.EXIT_TYPE_INTERRUPTED: 'interrupted',
        FlowRun.EXIT_TYPE_EXPIRED: 'expired'
    }

    flow = serializers.SerializerMethodField()
    contact = serializers.SerializerMethodField()
    steps = serializers.SerializerMethodField()
    exit_type = serializers.SerializerMethodField()

    def get_flow(self, obj):
        return {'uuid': obj.flow.uuid, 'name': obj.flow.name}

    def get_contact(self, obj):
        return {'uuid': obj.contact.uuid, 'name': obj.contact.name}

    def get_steps(self, obj):
        # avoiding fetching org again
        run = obj
        run.org = self.context['org']

        steps = []
        for step in obj.steps.all():
            val = step.rule_decimal_value if step.rule_decimal_value is not None else step.rule_value
            steps.append({'type': self.NODE_TYPES.get(step.step_type),
                          'node': step.step_uuid,
                          'arrived_on': format_datetime(step.arrived_on),
                          'left_on': format_datetime(step.left_on),
                          'messages': self.get_step_messages(run, step),
                          'text': step.get_text(run=run),  # TODO remove
                          'value': val,
                          'category': step.rule_category})
        return steps

    def get_exit_type(self, obj):
        return self.EXIT_TYPES.get(obj.exit_type)

    @staticmethod
    def get_step_messages(run, step):
        messages = []
        for m in step.messages.all():
            messages.append({'id': m.id, 'broadcast': m.broadcast_id, 'text': m.text})

        for b in step.broadcasts.all():
            if b.purged:
                text = b.get_translated_text(run.contact, base_language=run.flow.base_language, org=run.org)
                messages.append({'id': None, 'broadcast': b.id, 'text': text})

        return messages

    class Meta:
        model = FlowRun
        fields = ('id', 'flow', 'contact', 'responded', 'steps',
                  'created_on', 'modified_on', 'exited_on', 'exit_type')


class FlowStartReadSerializer(ReadSerializer):
    STATUSES = {
        FlowStart.STATUS_PENDING: 'pending',
        FlowStart.STATUS_STARTING: 'starting',
        FlowStart.STATUS_COMPLETE: 'complete',
        FlowStart.STATUS_FAILED: 'failed'
    }

    flow = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    groups = serializers.SerializerMethodField()
    contacts = serializers.SerializerMethodField()

    def get_contacts(self, obj):
        contacts = []
        for contact in obj.contacts.all():
            contacts.append(dict(uuid=contact.uuid, name=contact.name))
        return contacts

    def get_groups(self, obj):
        groups = []
        for group in obj.groups.all():
            groups.append(dict(uuid=group.uuid, name=group.name))
        return groups

    def get_flow(self, obj):
        return dict(uuid=obj.flow.uuid, name=obj.flow.name)

    def get_status(self, obj):
        return FlowStartReadSerializer.STATUSES.get(obj.status)

    class Meta:
        model = FlowStart
        fields = ('id', 'flow', 'status', 'groups', 'contacts', 'restart_participants', 'created_on', 'modified_on')


class FlowStartWriteSerializer(WriteSerializer):
    flow = serializers.UUIDField()
    contacts = UUIDListField(required=False)
    groups = UUIDListField(required=False)
    urns = URNListField(required=False)

    def validate_flow(self, value):
        flow = Flow.objects.filter(org=self.context['org'], is_active=True, uuid=value).first()
        if not flow:
            raise ValidationError("No flow found with UUID: %s" % value)
        return flow

    def validate_contacts(self, value):
        contacts = []
        for contact_uuid in value:
            contact = Contact.objects.filter(org=self.context['org'], is_active=True, uuid=contact_uuid).first()
            if not contact:
                raise ValidationError("No contact found with UUID: %s" % value)
            contacts.append(contact)

        return contacts

    def validate_groups(self, value):
        groups = []
        for group_uuid in value:
            group = ContactGroup.user_groups.filter(org=self.context['org'], is_active=True, uuid=group_uuid).first()
            if not group:
                raise ValidationError("No group found with UUID: %s" % value)
            groups.append(group)

        return groups

    def validate_urns(self, value):
        urn_contacts = []
        for urn in value:
            contact = Contact.get_or_create(self.context['org'], self.context['user'], urns=[urn])
            urn_contacts.append(contact)

        return urn_contacts

    def validate(self, data):
        # need at least one of urns, groups or contacts
        args = data.get('groups', []) + data.get('contacts', []) + data.get('urns', [])
        if not args:
            raise ValidationError("Must specify at least one group, contact or URN")

        return data

    def save(self):
        # ok, let's go create our flow start, the actual starting will happen in our view
        start = FlowStart.create(self.validated_data['flow'], self.context['user'],
                                 restart_participants=self.validated_data.get('restart_participants', True),
                                 contacts=self.validated_data.get('contacts', []) + self.validated_data.get('urns', []),
                                 groups=self.validated_data.get('groups', []))

        return start

    class Meta:
        model = FlowStart
        fields = ('resthook', 'target_url')


class LabelReadSerializer(ReadSerializer):
    count = serializers.SerializerMethodField()

    def get_count(self, obj):
        return obj.get_visible_count()

    class Meta:
        model = Label
        fields = ('uuid', 'name', 'count')


class MsgReadSerializer(ReadSerializer):
    STATUSES = ReadSerializer.extract_constants(STATUS_CONFIG)
    VISIBILITIES = ReadSerializer.extract_constants(Msg.VISIBILITY_CONFIG)
    DIRECTIONS = {
        INCOMING: 'in',
        OUTGOING: 'out'
    }
    MSG_TYPES = {
        INBOX: 'inbox',
        FLOW: 'flow',
        IVR: 'ivr'
    }

    broadcast = serializers.SerializerMethodField()
    contact = serializers.SerializerMethodField()
    urn = serializers.SerializerMethodField()
    channel = serializers.SerializerMethodField()
    direction = serializers.SerializerMethodField()
    type = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    archived = serializers.SerializerMethodField()
    visibility = serializers.SerializerMethodField()
    labels = serializers.SerializerMethodField()
    ruleset = serializers.SerializerMethodField()

    def get_ruleset(self, obj):
        try:
            step = obj.get_flow_step()
            destination = step.get_step().destination
            return RuleSet.objects.filter(uuid=destination).first().as_json()
        except:
            return None

    def get_broadcast(self, obj):
        return obj.broadcast_id

    def get_contact(self, obj):
        return {'uuid': obj.contact.uuid, 'name': obj.contact.name}

    def get_urn(self, obj):
        if self.context['org'].is_anon:
            return None
        elif obj.contact_urn_id:
            return obj.contact_urn.urn
        else:
            return None

    def get_channel(self, obj):
        return {'uuid': obj.channel.uuid, 'name': obj.channel.name} if obj.channel_id else None

    def get_direction(self, obj):
        return self.DIRECTIONS.get(obj.direction)

    def get_type(self, obj):
        return self.MSG_TYPES.get(obj.msg_type)

    def get_status(self, obj):
        # PENDING and QUEUED are same as far as users are concerned
        return self.STATUSES.get(QUEUED if obj.status == PENDING else obj.status)

    def get_archived(self, obj):
        return obj.visibility == Msg.VISIBILITY_ARCHIVED

    def get_visibility(self, obj):
        return self.VISIBILITIES.get(obj.visibility)

    def get_labels(self, obj):
        return [{'uuid': l.uuid, 'name': l.name} for l in obj.labels.all()]

    class Meta:
        model = Msg
        fields = ('id', 'broadcast', 'contact', 'urn', 'channel',
                  'direction', 'type', 'status', 'archived', 'visibility', 'text', 'labels',
                  'created_on', 'sent_on', 'modified_on', 'ruleset')


class ResthookReadSerializer(ReadSerializer):
    resthook = serializers.SerializerMethodField()

    def get_resthook(self, obj):
        return obj.slug

    class Meta:
        model = Resthook
        fields = ('resthook', 'modified_on', 'created_on')


class ResthookSubscriberReadSerializer(ReadSerializer):
    resthook = serializers.SlugField()

    def get_resthook(self, obj):
        return obj.resthook.slug

    class Meta:
        model = ResthookSubscriber
        fields = ('id', 'resthook', 'target_url', 'created_on')


class ResthookSubscriberWriteSerializer(WriteSerializer):
    resthook = serializers.SlugField()
    target_url = serializers.URLField()

    def get_resthook(self, slug):
        return Resthook.objects.filter(is_active=True, org=self.context['org'], slug=slug).first()

    def validate_resthook(self, value):
        if value:
            resthook = self.get_resthook(value)
            if not resthook:
                raise serializers.ValidationError("No resthook with slug: %s" % value)
        return value

    def validate(self, data):
        resthook = self.get_resthook(data.get('resthook'))
        target_url = data.get('target_url')

        # make sure this combination doesn't already exist
        if ResthookSubscriber.objects.filter(resthook=resthook, target_url=target_url, is_active=True):
            raise serializers.ValidationError("URL is already subscribed to this event.")

        return data

    def save(self):
        resthook = self.get_resthook(self.validated_data['resthook'])
        target_url = self.validated_data['target_url']
        return resthook.add_subscriber(target_url, self.context['user'])

    class Meta:
        model = ResthookSubscriber
        fields = ('resthook', 'target_url')


class WebHookEventReadSerializer(ReadSerializer):
    resthook = serializers.SerializerMethodField()
    data = serializers.SerializerMethodField()

    def get_resthook(self, obj):
        return obj.resthook.slug

    def get_data(self, obj):
        decoded = json.loads(obj.data)

        # also decode values and steps
        decoded['values'] = json.loads(decoded['values'])
        decoded['steps'] = json.loads(decoded['steps'])
        return decoded

    class Meta:
        model = WebHookEvent
        fields = ('resthook', 'data', 'created_on')
