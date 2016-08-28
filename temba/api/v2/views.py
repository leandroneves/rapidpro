from __future__ import absolute_import, unicode_literals

from django import forms
from django.contrib.auth import authenticate, login
from django.db.models import Prefetch, Q
from django.db.transaction import non_atomic_requests
from django.http import HttpResponse, JsonResponse
from django.utils.translation import ugettext_lazy as _
from django.views.decorators.csrf import csrf_exempt
from rest_framework import generics, mixins, status
from rest_framework.pagination import CursorPagination
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.reverse import reverse
from smartmin.views import SmartTemplateView, SmartFormView
from temba.api.models import APIToken, Resthook, ResthookSubscriber, WebHookEvent
from temba.campaigns.models import Campaign, CampaignEvent
from temba.channels.models import Channel, ChannelEvent
from temba.contacts.models import Contact, ContactURN, ContactGroup, ContactField
from temba.flows.models import Flow, FlowRun, FlowStep, FlowStart
from temba.locations.models import AdminBoundary, BoundaryAlias
from temba.msgs.models import Broadcast, Msg, Label, SystemLabel
from temba.utils import str_to_bool, json_date_to_datetime, splitting_getlist
from .serializers import BroadcastReadSerializer, CampaignReadSerializer, CampaignEventReadSerializer
from .serializers import ChannelReadSerializer, ChannelEventReadSerializer, ContactReadSerializer
from .serializers import FlowStartReadSerializer, FlowStartWriteSerializer
from .serializers import WebHookEventReadSerializer, ResthookReadSerializer, ResthookSubscriberReadSerializer, ResthookSubscriberWriteSerializer
from .serializers import ContactFieldReadSerializer, ContactGroupReadSerializer, FlowReadSerializer
from .serializers import FlowRunReadSerializer, LabelReadSerializer, MsgReadSerializer, AdminBoundaryReadSerializer
from ..models import APIPermission, SSLPermission
from ..support import InvalidQueryError


@api_view(['GET'])
@permission_classes((SSLPermission, IsAuthenticated))
def api(request, format=None):
    """
    This is the **under-development** API v2. Everything in this version of the API is subject to change. We strongly
    recommend that most users stick with the existing [API v1](/api/v1) for now.

    The following endpoints are provided:

     * [/api/v2/boundaries](/api/v2/boundaries) - to list administrative boundaries
     * [/api/v2/broadcasts](/api/v2/broadcasts) - to list message broadcasts
     * [/api/v2/campaigns](/api/v2/campaigns) - to list campaigns
     * [/api/v2/campaign_events](/api/v2/campaign_events) - to list campaign events
     * [/api/v2/channels](/api/v2/channels) - to list channels
     * [/api/v2/channel_events](/api/v2/channel_events) - to list channel events
     * [/api/v2/contacts](/api/v2/contacts) - to list contacts
     * [/api/v2/definitions](/api/v2/definitions) - to export flow definitions, campaigns, and triggers
     * [/api/v2/fields](/api/v2/fields) - to list contact fields
     * [/api/v2/flow_starts](/api/v2/flow_starts) - to list flow starts and start contacts in flows
     * [/api/v2/flows](/api/v2/flows) - to list flows
     * [/api/v2/groups](/api/v2/groups) - to list contact groups
     * [/api/v2/labels](/api/v2/labels) - to list message labels
     * [/api/v2/messages](/api/v2/messages) - to list messages
     * [/api/v2/org](/api/v2/org) - to view your org
     * [/api/v2/runs](/api/v2/runs) - to list flow runs
     * [/api/v2/resthooks](/api/v2/resthooks) - to list resthooks
     * [/api/v2/resthook_subscribers](/api/v2/resthook_subscribers) - to list subscribers on your resthooks
     * [/api/v2/resthook_events](/api/v2/resthook_events) - to list resthook events

    You may wish to use the [API Explorer](/api/v2/explorer) to interactively experiment with the API.
    """
    return Response({
        'boundaries': reverse('api.v2.boundaries', request=request),
        'broadcasts': reverse('api.v2.broadcasts', request=request),
        'campaigns': reverse('api.v2.campaigns', request=request),
        'campaign_events': reverse('api.v2.campaign_events', request=request),
        'channels': reverse('api.v2.channels', request=request),
        'channel_events': reverse('api.v2.channel_events', request=request),
        'contacts': reverse('api.v2.contacts', request=request),
        'definitions': reverse('api.v2.definitions', request=request),
        'fields': reverse('api.v2.fields', request=request),
        'flow_starts': reverse('api.v2.flow_starts', request=request),
        'flows': reverse('api.v2.flows', request=request),
        'groups': reverse('api.v2.groups', request=request),
        'labels': reverse('api.v2.labels', request=request),
        'messages': reverse('api.v2.messages', request=request),
        'org': reverse('api.v2.org', request=request),
        'resthooks': reverse('api.v2.resthooks', request=request),
        'resthook_events': reverse('api.v2.resthook_events', request=request),
        'resthook_subscribers': reverse('api.v2.resthook_subscribers', request=request),
        'runs': reverse('api.v2.runs', request=request),
    })


class ApiExplorerView(SmartTemplateView):
    """
    Explorer view which lets users experiment with endpoints against their own data
    """
    template_name = "api/v2/api_explorer.html"

    def get_context_data(self, **kwargs):
        context = super(ApiExplorerView, self).get_context_data(**kwargs)
        context['endpoints'] = [
            BoundariesEndpoint.get_read_explorer(),
            BroadcastEndpoint.get_read_explorer(),
            CampaignsEndpoint.get_read_explorer(),
            CampaignEventsEndpoint.get_read_explorer(),
            ChannelsEndpoint.get_read_explorer(),
            ChannelEventsEndpoint.get_read_explorer(),
            ContactsEndpoint.get_read_explorer(),
            DefinitionsEndpoint.get_read_explorer(),
            FieldsEndpoint.get_read_explorer(),
            FlowsEndpoint.get_read_explorer(),
            FlowStartsEndpoint.get_read_explorer(),
            FlowStartsEndpoint.get_write_explorer(),
            GroupsEndpoint.get_read_explorer(),
            LabelsEndpoint.get_read_explorer(),
            MessagesEndpoint.get_read_explorer(),
            OrgEndpoint.get_read_explorer(),
            ResthookEndpoint.get_read_explorer(),
            ResthookEventEndpoint.get_read_explorer(),
            ResthookSubscriberEndpoint.get_read_explorer(),
            ResthookSubscriberEndpoint.get_write_explorer(),
            ResthookSubscriberEndpoint.get_delete_explorer(),
            RunsEndpoint.get_read_explorer()
        ]
        return context


class AuthenticateView(SmartFormView):
    """
    Provides a login form view for app users to generate and access their API tokens
    """
    class LoginForm(forms.Form):
        ROLE_CHOICES = (('A', _("Administrator")), ('E', _("Editor")), ('S', _("Surveyor")))

        username = forms.CharField()
        password = forms.CharField(widget=forms.PasswordInput)
        role = forms.ChoiceField(choices=ROLE_CHOICES)

    title = "API Authentication"
    form_class = LoginForm

    @csrf_exempt
    def dispatch(self, *args, **kwargs):
        return super(AuthenticateView, self).dispatch(*args, **kwargs)

    def form_valid(self, form, *args, **kwargs):
        username = form.cleaned_data.get('username')
        password = form.cleaned_data.get('password')
        role_code = form.cleaned_data.get('role')

        user = authenticate(username=username, password=password)
        if user and user.is_active:
            login(self.request, user)

            role = APIToken.get_role_from_code(role_code)
            tokens = []

            if role:
                valid_orgs = APIToken.get_orgs_for_role(user, role)
                for org in valid_orgs:
                    token = APIToken.get_or_create(org, user, role)
                    tokens.append({'org': {'id': org.pk, 'name': org.name}, 'token': token.key})
            else:
                return HttpResponse(status=404)

            return JsonResponse({'tokens': tokens})
        else:
            return HttpResponse(status=403)


class CreatedOnCursorPagination(CursorPagination):

    ordering = ('-created_on', '-id')
    offset_cutoff = 1000000


class ModifiedOnCursorPagination(CursorPagination):
    ordering = ('-modified_on', '-id')
    offset_cutoff = 1000000


class BaseAPIView(generics.GenericAPIView):
    """
    Base class of all our API endpoints
    """
    permission_classes = (SSLPermission, APIPermission)

    @non_atomic_requests
    def dispatch(self, request, *args, **kwargs):
        return super(BaseAPIView, self).dispatch(request, *args, **kwargs)

    def get_serializer_context(self):
        context = super(BaseAPIView, self).get_serializer_context()
        context['org'] = self.request.user.get_org()
        context['user'] = self.request.user
        return context


class ListAPIMixin(mixins.ListModelMixin):
    """
    Mixin for any endpoint which returns a list of objects from a GET request
    """
    throttle_scope = 'v2'
    model = None
    model_manager = 'objects'
    exclusive_params = ()
    required_params = ()

    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)

    def list(self, request, *args, **kwargs):
        self.check_query(self.request.query_params)

        if not kwargs.get('format', None):
            # if this is just a request to browse the endpoint docs, don't make a query
            return Response([])
        else:
            return super(ListAPIMixin, self).list(request, *args, **kwargs)

    def check_query(self, params):
        # check user hasn't provided values for more than one of any exclusive params
        if sum([(1 if params.get(p) else 0) for p in self.exclusive_params]) > 1:
            raise InvalidQueryError("You may only specify one of the %s parameters" % ", ".join(self.exclusive_params))

        # check that any required params are included
        if self.required_params:
            if sum([(1 if params.get(p) else 0) for p in self.required_params]) != 1:
                raise InvalidQueryError("You must specify one of the %s parameters" % ", ".join(self.required_params))

    def get_queryset(self):
        org = self.request.user.get_org()
        return getattr(self.model, self.model_manager).filter(org=org)

    def filter_before_after(self, queryset, field):
        """
        Filters the queryset by the before/after params if are provided
        """
        before = self.request.query_params.get('before')
        if before:
            try:
                before = json_date_to_datetime(before)
                queryset = queryset.filter(**{field + '__lte': before})
            except Exception:
                queryset = queryset.filter(pk=-1)

        after = self.request.query_params.get('after')
        if after:
            try:
                after = json_date_to_datetime(after)
                queryset = queryset.filter(**{field + '__gte': after})
            except Exception:
                queryset = queryset.filter(pk=-1)

        return queryset

    def paginate_queryset(self, queryset):
        page = super(ListAPIMixin, self).paginate_queryset(queryset)

        # give views a chance to prepare objects for serialization
        self.prepare_for_serialization(page)

        return page

    def prepare_for_serialization(self, page):
        """
        Views can override this to do things like bulk cache initialization of result objects
        """
        pass


class CreateAPIMixin(object):
    """
    Mixin for any endpoint which can create or update objects with a write serializer. Our list and create approach
    differs slightly a bit from ListCreateAPIView in the REST framework as we use separate read and write serializers...
    and sometimes we use another serializer again for write output
    """
    write_serializer_class = None

    def post_save(self, instance):
        """
        Can be overridden to add custom handling after object creation
        """
        pass

    def post(self, request, *args, **kwargs):
        context = self.get_serializer_context()
        serializer = self.write_serializer_class(data=request.data, context=context)

        if serializer.is_valid():
            output = serializer.save()
            self.post_save(output)
            return self.render_write_response(output, context)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def render_write_response(self, write_output, context):
        response_serializer = self.serializer_class(instance=write_output, context=context)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class DeleteAPIMixin(object):
    """
    Mixin for any endpoint that can delete objects with a DELETE request
    """
    def delete(self, request, *args, **kwargs):
        return self.destroy(request, *args, **kwargs)


# ============================================================
# Endpoints (A-Z)
# ============================================================


class BoundariesEndpoint(ListAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list the administrative boundaries for the country associated with your organization
    along with the simplified GPS geometry for those boundaries in GEOJSON format.

    ## Listing Boundaries

    Returns the boundaries for your organization with the following fields. To include geometry,
    specify `geometry=true`.

      * **osm_id** - the OSM ID for this boundary prefixed with the element type (string)
      * **name** - the name of the administrative boundary (string)
      * **parent** - the id of the containing parent of this boundary or null if this boundary is a country (string)
      * **level** - the level: 0 for country, 1 for state, 2 for district (int)
      * **geometry** - the geometry for this boundary, which will usually be a MultiPolygon (GEOJSON)

    **Note that including geometry may produce a very large result so it is recommended to cache the results on the
    client side.**

    Example:

        GET /api/v2/boundaries.json?geometry=true

    Response is a list of the boundaries on your account

        {
            "next": null,
            "previous": null,
            "results": [
            {
                "osm_id": "1708283",
                "name": "Kigali City",
                "parent": {"osm_id": "171496", "name": "Rwanda"},
                "level": 1,
                "aliases": ["Kigari"],
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [
                            [
                                [7.5251021, 5.0504713],
                                [7.5330272, 5.0423498]
                            ]
                        ]
                    ]
                }
            },
            ...
        }

    """
    class Pagination(CursorPagination):
        ordering = ('osm_id',)

    permission = 'locations.adminboundary_api'
    model = AdminBoundary
    serializer_class = AdminBoundaryReadSerializer
    pagination_class = Pagination

    def get_queryset(self):
        org = self.request.user.get_org()
        if not org.country:
            return AdminBoundary.objects.none()

        queryset = org.country.get_descendants(include_self=True)

        queryset = queryset.prefetch_related(
            Prefetch('aliases', queryset=BoundaryAlias.objects.filter(org=org).order_by('name')),
        )

        return queryset.select_related('parent')

    def get_serializer_context(self):
        context = super(BoundariesEndpoint, self).get_serializer_context()
        context['include_geometry'] = str_to_bool(self.request.query_params.get('geometry', 'false'))
        return context

    @classmethod
    def get_read_explorer(cls):
        return {
            'method': "GET",
            'title': "List Administrative Boundaries",
            'url': reverse('api.v2.boundaries'),
            'slug': 'boundary-list',
            'request': "",
            'fields': []
        }


class BroadcastEndpoint(ListAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list message broadcasts on your account using the ```GET``` method.

    ## Listing Broadcasts

    Returns the message activity for your organization, listing the most recent messages first.

     * **id** - the id of the broadcast (int), filterable as `id`.
     * **urns** - the URNs that received the broadcast (array of strings)
     * **contacts** - the contacts that received the broadcast (array of objects)
     * **groups** - the groups that received the broadcast (array of objects)
     * **text** - the message text (string)
     * **created_on** - when this broadcast was either created (datetime) (filterable as `before` and `after`).

    Example:

        GET /api/v2/broadcasts.json

    Response is a list of recent broadcasts:

        {
            "next": null,
            "previous": null,
            "results": [
                {
                    "id": 123456,
                    "urns": ["tel:+250788123123", "tel:+250788123124"],
                    "contacts": [{"uuid": "09d23a05-47fe-11e4-bfe9-b8f6b119e9ab", "name": "Joe"}]
                    "groups": [],
                    "text": "hello world",
                    "created_on": "2013-03-02T17:28:12.123Z"
                },
                ...
    """
    permission = 'msgs.broadcast_api'
    model = Broadcast
    serializer_class = BroadcastReadSerializer
    pagination_class = CreatedOnCursorPagination

    def filter_queryset(self, queryset):
        params = self.request.query_params
        org = self.request.user.get_org()

        queryset = queryset.filter(is_active=True)

        # filter by id (optional)
        msg_id = params.get('id')
        if msg_id:
            queryset = queryset.filter(id=msg_id)

        queryset = queryset.prefetch_related(
            Prefetch('contacts', queryset=Contact.objects.only('uuid', 'name')),
            Prefetch('groups', queryset=ContactGroup.user_groups.only('uuid', 'name')),
        )

        if not org.is_anon:
            queryset = queryset.prefetch_related(Prefetch('urns', queryset=ContactURN.objects.only('urn')))

        return self.filter_before_after(queryset, 'created_on')

    @classmethod
    def get_read_explorer(cls):
        return {
            'method': "GET",
            'title': "List Broadcasts",
            'url': reverse('api.v2.broadcasts'),
            'slug': 'broadcast-list',
            'request': "",
            'fields': [
                {'name': 'id', 'required': False, 'help': "A broadcast ID to filter by, ex: 123456"},
                {'name': 'before', 'required': False, 'help': "Only return broadcasts created before this date, ex: 2015-01-28T18:00:00.000"},
                {'name': 'after', 'required': False, 'help': "Only return broadcasts created after this date, ex: 2015-01-28T18:00:00.000"}
            ]
        }


class CampaignsEndpoint(ListAPIMixin, BaseAPIView):
    """
    ## Listing Campaigns

    You can retrieve the campaigns for your organization by sending a ```GET``` to this endpoint, listing the
    most recently created campaigns first.

     * **uuid** - the UUID of the campaign (string), filterable as `uuid`.
     * **name** - the name of the campaign (string).
     * **group** - the group this campaign operates on (object).
     * **created_on** - when the campaign was created (datetime), filterable as `before` and `after`.

    Example:

        GET /api/v2/campaigns.json

    Response is a list of the campaigns on your account

        {
            "next": null,
            "previous": null,
            "results": [
            {
                "uuid": "f14e4ff0-724d-43fe-a953-1d16aefd1c00",
                "name": "Reminders",
                "group": {"uuid": "7ae473e8-f1b5-4998-bd9c-eb8e28c92fa9", "name": "Reporters"},
                "created_on": "2013-08-19T19:11:21.088Z"
            },
            ...
        }

    """
    permission = 'campaigns.campaign_api'
    model = Campaign
    serializer_class = CampaignReadSerializer
    pagination_class = CreatedOnCursorPagination

    def filter_queryset(self, queryset):
        params = self.request.query_params
        queryset = queryset.filter(is_active=True)

        # filter by UUID (optional)
        uuid = params.get('uuid')
        if uuid:
            queryset = queryset.filter(uuid=uuid)

        queryset = queryset.prefetch_related(
            Prefetch('group', queryset=ContactGroup.user_groups.only('uuid', 'name')),
        )

        return queryset

    @classmethod
    def get_read_explorer(cls):
        return {
            'method': "GET",
            'title': "List Campaigns",
            'url': reverse('api.v2.campaigns'),
            'slug': 'campaign-list',
            'request': "",
            'fields': [
                {'name': "uuid", 'required': False, 'help': "A campaign UUID to filter by. ex: 09d23a05-47fe-11e4-bfe9-b8f6b119e9ab"},
            ]
        }


class CampaignEventsEndpoint(ListAPIMixin, BaseAPIView):
    """
    ## Listing Campaign Events

    You can retrieve the campaign events for your organization by sending a ```GET``` to this endpoint, listing the
    most recently created events first.

     * **uuid** - the UUID of the campaign (string), filterable as `uuid`.
     * **campaign** - the UUID and name of the campaign (object), filterable as `campaign` with UUID.
     * **relative_to** - the key and label of the date field this event is based on (object).
     * **offset** - the offset from our contact field (positive or negative integer).
     * **unit** - the unit for our offset (one of "minutes, "hours", "days", "weeks").
     * **delivery_hour** - the hour of the day to deliver the message (integer 0-24, -1 indicates send at the same hour as the contact field).
     * **message** - the message to send to the contact if this is a message event (string)
     * **flow** - the UUID and name of the flow if this is a flow event (object).
     * **created_on** - when the event was created (datetime).

    Example:

        GET /api/v2/campaign_events.json

    Response is a list of the campaign events on your account

        {
            "next": null,
            "previous": null,
            "results": [
            {
                "uuid": "f14e4ff0-724d-43fe-a953-1d16aefd1c00",
                "campaign": {"uuid": "f14e4ff0-724d-43fe-a953-1d16aefd1c00", "name": "Reminders"},
                "relative_to": {"key": "registration", "label": "Registration Date"},
                "offset": 7,
                "unit": "days",
                "delivery_hour": 9,
                "flow": {"uuid": "09d23a05-47fe-11e4-bfe9-b8f6b119e9ab", "name": "Survey"},
                "message": null,
                "created_on": "2013-08-19T19:11:21.088Z"
            },
            ...
        }

    """
    permission = 'campaigns.campaignevent_api'
    model = CampaignEvent
    serializer_class = CampaignEventReadSerializer
    pagination_class = CreatedOnCursorPagination

    def get_queryset(self):
        return self.model.objects.filter(campaign__org=self.request.user.get_org(), is_active=True)

    def filter_queryset(self, queryset):
        params = self.request.query_params
        queryset = queryset.filter(is_active=True)
        org = self.request.user.get_org()

        # filter by UUID (optional)
        uuid = params.get('uuid')
        if uuid:
            queryset = queryset.filter(uuid=uuid)

        # filter by campaign name/uuid (optional)
        campaign_ref = params.get('campaign')
        if campaign_ref:
            campaign = Campaign.objects.filter(org=org).filter(Q(uuid=campaign_ref) | Q(name=campaign_ref)).first()
            if campaign:
                queryset = queryset.filter(campaign=campaign)
            else:
                queryset = queryset.filter(pk=-1)

        queryset = queryset.prefetch_related(
            Prefetch('campaign', queryset=Campaign.objects.only('uuid', 'name')),
            Prefetch('flow', queryset=Flow.objects.only('uuid', 'name')),
            Prefetch('relative_to', queryset=ContactField.objects.only('key', 'label')),
        )

        return queryset

    @classmethod
    def get_read_explorer(cls):
        return {
            'method': "GET",
            'title': "List Campaign Events",
            'url': reverse('api.v2.campaign_events'),
            'slug': 'campaign-event-list',
            'request': "",
            'fields': [
                {'name': "uuid", 'required': False, 'help': "An event UUID to filter by. ex: 09d23a05-47fe-11e4-bfe9-b8f6b119e9ab"},
                {'name': "campaign", 'required': False, 'help': "A campaign UUID or name to filter by. ex: Reminders"},
            ]
        }


class ChannelsEndpoint(ListAPIMixin, BaseAPIView):
    """
    ## Listing Channels

    A **GET** returns the list of Android channels for your organization, in the order of last created.  Note that for
    Android devices, all status information is as of the last time it was seen and can be null before the first sync.

     * **uuid** - the UUID of the channel (string), filterable as `uuid`.
     * **name** - the name of the channel (string).
     * **address** - the address (e.g. phone number, Twitter handle) of the channel (string), filterable as `address`.
     * **country** - which country the sim card for this channel is registered for (string, two letter country code).
     * **device** - information about the device if this is an Android channel:
        * **name** - the name of the device (string).
        * **power_level** - the power level of the device (int).
        * **power_status** - the power status, either ```STATUS_DISCHARGING``` or ```STATUS_CHARGING``` (string).
        * **power_source** - the source of power as reported by Android (string).
        * **network_type** - the type of network the device is connected to as reported by Android (string).
     * **last_seen** - the datetime when this channel was last seen (datetime).
     * **created_on** - the datetime when this channel was created (datetime).

    Example:

        GET /api/v2/channels.json

    Response containing the channels for your organization:

        {
            "next": null,
            "previous": null,
            "results": [
            {
                "uuid": "09d23a05-47fe-11e4-bfe9-b8f6b119e9ab",
                "name": "Android Phone",
                "address": "+250788123123",
                "country": "RW",
                "device": {
                    "name": "Nexus 5X",
                    "power_level": 99,
                    "power_status": "STATUS_DISCHARGING",
                    "power_source": "BATTERY",
                    "network_type": "WIFI",
                },
                "last_seen": "2016-03-01T05:31:27.456",
                "created_on": "2014-06-23T09:34:12.866",
            }]
        }

    """
    permission = 'channels.channel_api'
    model = Channel
    serializer_class = ChannelReadSerializer
    pagination_class = CreatedOnCursorPagination

    def filter_queryset(self, queryset):
        params = self.request.query_params
        queryset = queryset.filter(is_active=True)

        # filter by UUID (optional)
        uuid = params.get('uuid')
        if uuid:
            queryset = queryset.filter(uuid=uuid)

        # filter by address (optional)
        address = params.get('address')
        if address:
            queryset = queryset.filter(address=address)

        return queryset

    @classmethod
    def get_read_explorer(cls):
        return {
            'method': "GET",
            'title': "List Channels",
            'url': reverse('api.v2.channels'),
            'slug': 'channel-list',
            'request': "",
            'fields': [
                {'name': "uuid", 'required': False, 'help': "A channel UUID to filter by. ex: 09d23a05-47fe-11e4-bfe9-b8f6b119e9ab"},
                {'name': "address", 'required': False, 'help': "A channel address to filter by. ex: +250783530001"},
            ]
        }


class ChannelEventsEndpoint(ListAPIMixin, BaseAPIView):
    """
    Returns the channel events for your organization, most recent first.

     * **id** - the ID of the event (int), filterable as `id`.
     * **channel** - the UUID and name of the channel that handled this call (object).
     * **type** - the type of event (one of "call-in", "call-in-missed", "call-out", "call-out-missed").
     * **contact** - the UUID and name of the contact (object), filterable as `contact` with UUID.
     * **time** - when this event happened on the channel (datetime).
     * **duration** - the duration in seconds if event is a call (int, 0 for missed calls).
     * **created_on** - when this event was created (datetime), filterable as `before` and `after`.

    Example:

        GET /api/v2/channel_events.json

    Response:

        {
            "next": null,
            "previous": null,
            "results": [
            {
                "id": 4,
                "channel": {"uuid": "9a8b001e-a913-486c-80f4-1356e23f582e", "name": "Nexmo"},
                "type": "call-in"
                "contact": {"uuid": "d33e9ad5-5c35-414c-abd4-e7451c69ff1d", "name": "Bob McFlow"},
                "time": "2013-02-27T09:06:12.123"
                "duration": 606,
                "created_on": "2013-02-27T09:06:15.456"
            },
            ...

    """
    permission = 'channels.channelevent_api'
    model = ChannelEvent
    serializer_class = ChannelEventReadSerializer
    pagination_class = CreatedOnCursorPagination

    def filter_queryset(self, queryset):
        params = self.request.query_params
        queryset = queryset.filter(is_active=True)
        org = self.request.user.get_org()

        # filter by id (optional)
        call_id = params.get('id')
        if call_id:
            queryset = queryset.filter(pk=call_id)

        # filter by contact (optional)
        contact_uuid = params.get('contact')
        if contact_uuid:
            contact = Contact.objects.filter(org=org, is_test=False, is_active=True, uuid=contact_uuid).first()
            if contact:
                queryset = queryset.filter(contact=contact)
            else:
                queryset = queryset.filter(pk=-1)

        queryset = queryset.prefetch_related(
            Prefetch('contact', queryset=Contact.objects.only('uuid', 'name')),
            Prefetch('channel', queryset=Channel.objects.only('uuid', 'name')),
        )

        return self.filter_before_after(queryset, 'created_on')

    @classmethod
    def get_read_explorer(cls):
        return {
            'method': "GET",
            'title': "List Channel Events",
            'url': reverse('api.v2.channel_events'),
            'slug': 'channel-event-list',
            'request': "",
            'fields': [
                {'name': "id", 'required': False, 'help': "An event ID to filter by. ex: 12345"},
                {'name': "contact", 'required': False, 'help': "A contact UUID to filter by. ex: 09d23a05-47fe-11e4-bfe9-b8f6b119e9ab"},
                {'name': 'before', 'required': False, 'help': "Only return events created before this date, ex: 2015-01-28T18:00:00.000"},
                {'name': 'after', 'required': False, 'help': "Only return events created after this date, ex: 2015-01-28T18:00:00.000"}
            ]
        }


class ContactsEndpoint(ListAPIMixin, BaseAPIView):
    """
    ## Listing Contacts

    A **GET** returns the list of contacts for your organization, in the order of last activity date. You can return
    only deleted contacts by passing the "deleted=true" parameter to your call.

     * **uuid** - the UUID of the contact (string), filterable as `uuid`.
     * **name** - the name of the contact (string).
     * **language** - the preferred language of the contact (string).
     * **urns** - the URNs associated with the contact (string array), filterable as `urn`.
     * **groups** - the UUIDs of any groups the contact is part of (array of objects), filterable as `group` with group name or UUID.
     * **fields** - any contact fields on this contact (dictionary).
     * **created_on** - when this contact was created (datetime).
     * **modified_on** - when this contact was last modified (datetime), filterable as `before` and `after`.

    Example:

        GET /api/v1/contacts.json

    Response containing the contacts for your organization:

        {
            "next": null,
            "previous": null,
            "results": [
            {
                "uuid": "09d23a05-47fe-11e4-bfe9-b8f6b119e9ab",
                "name": "Ben Haggerty",
                "language": null,
                "urns": ["tel:+250788123123"],
                "groups": [{"name": "Customers", "uuid": "5a4eb79e-1b1f-4ae3-8700-09384cca385f"}],
                "fields": {
                  "nickname": "Macklemore",
                  "side_kick": "Ryan Lewis"
                }
                "created_on": "2015-11-11T13:05:57.457742Z",
                "modified_on": "2015-11-11T13:05:57.576056Z"
            }]
        }
    """
    permission = 'contacts.contact_api'
    model = Contact
    serializer_class = ContactReadSerializer
    pagination_class = ModifiedOnCursorPagination
    throttle_scope = 'v2.contacts'

    def filter_queryset(self, queryset):
        params = self.request.query_params
        org = self.request.user.get_org()

        deleted_only = str_to_bool(params.get('deleted'))
        queryset = queryset.filter(is_test=False, is_active=(not deleted_only))

        # filter by UUID (optional)
        uuid = params.get('uuid')
        if uuid:
            queryset = queryset.filter(uuid=uuid)

        # filter by URN (optional)
        urn = params.get('urn')
        if urn:
            queryset = queryset.filter(urns__urn=urn)

        # filter by group name/uuid (optional)
        group_ref = params.get('group')
        if group_ref:
            group = ContactGroup.user_groups.filter(org=org).filter(Q(uuid=group_ref) | Q(name=group_ref)).first()
            if group:
                queryset = queryset.filter(all_groups=group)
            else:
                queryset = queryset.filter(pk=-1)

        # use prefetch rather than select_related for foreign keys to avoid joins
        queryset = queryset.prefetch_related(
            Prefetch('all_groups', queryset=ContactGroup.user_groups.only('uuid', 'name'), to_attr='prefetched_user_groups')
        )

        return self.filter_before_after(queryset, 'modified_on')

    def prepare_for_serialization(self, object_list):
        # initialize caches of all contact fields and URNs
        org = self.request.user.get_org()
        Contact.bulk_cache_initialize(org, object_list)

    def get_serializer_context(self):
        """
        So that we only fetch active contact fields once for all contacts
        """
        context = super(ContactsEndpoint, self).get_serializer_context()
        context['contact_fields'] = ContactField.objects.filter(org=self.request.user.get_org(), is_active=True)
        return context

    @classmethod
    def get_read_explorer(cls):
        return {
            'method': "GET",
            'title': "List Contacts",
            'url': reverse('api.v2.contacts'),
            'slug': 'contact-list',
            'request': "urn=tel%3A%2B250788123123",
            'fields': [
                {'name': "uuid", 'required': False, 'help': "A contact UUID to filter by. ex: 09d23a05-47fe-11e4-bfe9-b8f6b119e9ab"},
                {'name': "urn", 'required': False, 'help': "A contact URN to filter by. ex: tel:+250788123123"},
                {'name': "group", 'required': False, 'help': "A group name or UUID to filter by. ex: Customers"},
                {'name': "deleted", 'required': False, 'help': "Whether to return only deleted contacts. ex: false"},
                {'name': 'before', 'required': False, 'help': "Only return contacts modified before this date, ex: 2015-01-28T18:00:00.000"},
                {'name': 'after', 'required': False, 'help': "Only return contacts modified after this date, ex: 2015-01-28T18:00:00.000"}
            ]
        }


class DefinitionsEndpoint(BaseAPIView):
    """
    ## Exporting Definitions

    A **GET** exports a set of flows and campaigns, and can automatically include dependencies for the requested items,
    such as groups, triggers and other flows.

      * **flow** - the UUIDs of flows to include (string, repeatable)
      * **campaign** - the UUIDs of campaigns to include (string, repeatable)
      * **dependencies** - whether to include dependencies (boolean, default: true)

    Example:

        GET /api/v2/definitions.json?flow=f14e4ff0-724d-43fe-a953-1d16aefd1c0b&flow=09d23a05-47fe-11e4-bfe9-b8f6b119e9ab

    Response is a collection of definitions:

        {
          version: 8,
          campaigns: [],
          triggers: [],
          flows: [{
            metadata: {
              "name": "Water Point Survey",
              "uuid": "f14e4ff0-724d-43fe-a953-1d16aefd1c0b",
              "saved_on": "2015-09-23T00:25:50.709164Z",
              "revision": 28,
              "expires": 7880,
              "id": 12712,
            },
            "version": 7,
            "flow_type": "S",
            "base_language": "eng",
            "entry": "87929095-7d13-4003-8ee7-4c668b736419",
            "action_sets": [
              {
                "y": 0,
                "x": 100,
                "destination": "32d415f8-6d31-4b82-922e-a93416d5aa0a",
                "uuid": "87929095-7d13-4003-8ee7-4c668b736419",
                "actions": [
                  {
                    "msg": {
                      "eng": "What is your name?"
                    },
                    "type": "reply"
                  }
                ]
              },
              ...
            ],
            "rule_sets": [
              {
                "uuid": "32d415f8-6d31-4b82-922e-a93416d5aa0a",
                "webhook_action": null,
                "rules": [
                  {
                    "test": {
                      "test": "true",
                      "type": "true"
                    },
                      "category": {
                      "eng": "All Responses"
                    },
                    "destination": null,
                    "uuid": "5fa6e9ae-e78e-4e38-9c66-3acf5e32fcd2",
                    "destination_type": null
                  }
                ],
                "webhook": null,
                "ruleset_type": "wait_message",
                "label": "Name",
                "operand": "@step.value",
                "finished_key": null,
                "y": 162,
                "x": 62,
                "config": {}
              },
              ...
            ]
            }
          }]
        }
    """
    permission = 'orgs.org_api'

    def get(self, request, *args, **kwargs):
        org = request.user.get_org()
        params = request.query_params

        if 'flow_uuid' in params or 'campaign_uuid' in params:  # deprecated
            flow_uuids = splitting_getlist(self.request, 'flow_uuid')
            campaign_uuids = splitting_getlist(self.request, 'campaign_uuid')
        else:
            flow_uuids = params.getlist('flow')
            campaign_uuids = params.getlist('campaign')

        depends = str_to_bool(params.get('dependencies', 'true'))

        if flow_uuids:
            flows = set(Flow.objects.filter(uuid__in=flow_uuids, org=org))
        else:
            flows = set()

        # any fetched campaigns
        campaigns = []
        if campaign_uuids:
            campaigns = Campaign.objects.filter(uuid__in=campaign_uuids, org=org)

            if depends:
                for campaign in campaigns:
                    for event in campaign.events.filter(event_type=CampaignEvent.TYPE_FLOW, is_active=True).exclude(flow=None):
                        flows.add(event.flow)

        # get any dependencies on our flows and campaigns
        dependencies = dict(flows=set(), campaigns=set(campaigns), triggers=set(), groups=set())
        for flow in flows:
            if depends:
                dependencies = flow.get_dependencies(dependencies=dependencies)

        # make sure our requested items are included flows we requested are included
        to_export = dict(flows=dependencies['flows'],
                         campaigns=dependencies['campaigns'],
                         triggers=dependencies['triggers'])

        # add in our primary requested flows
        to_export['flows'].update(flows)

        export = org.export_definitions(self.request.branding['link'], **to_export)

        return Response(export, status=status.HTTP_200_OK)

    @classmethod
    def get_read_explorer(cls):
        return {
            'method': "GET",
            'title': "Export Definitions",
            'url': reverse('api.v2.definitions'),
            'slug': 'export-definitions',
            'request': "flow=f14e4ff0-724d-43fe-a953-1d16aefd1c0b&flow=09d23a05-47fe-11e4-bfe9-b8f6b119e9ab",
            'fields': [
                {'name': "flow", 'required': False, 'help': "One or more flow UUIDs to include"},
                {'name': "campaign", 'required': False, 'help': "One or more campaign UUIDs to include"},
                {'name': "dependencies", 'required': False, 'help': "Whether to include dependencies of the requested items. ex: false"}
            ]
        }


class FieldsEndpoint(ListAPIMixin, BaseAPIView):
    """
    ## Listing Fields

    A **GET** returns the list of custom contact fields for your organization, in the order of last created.

     * **key** - the unique key of this field (string), filterable as `key`
     * **label** - the display label of this field (string)
     * **value_type** - the data type of values associated with this field (string)

    Example:

        GET /api/v2/fields.json

    Response containing the fields for your organization:

         {
            "next": null,
            "previous": null,
            "results": [
                {
                    "key": "nick_name",
                    "label": "Nick name",
                    "value_type": "text"
                },
                ...
            ]
        }
    """
    permission = 'contacts.contactfield_api'
    model = ContactField
    serializer_class = ContactFieldReadSerializer
    pagination_class = CreatedOnCursorPagination

    def filter_queryset(self, queryset):
        params = self.request.query_params

        # filter by key (optional)
        key = params.get('key')
        if key:
            queryset = queryset.filter(key=key)

        return queryset.filter(is_active=True)

    @classmethod
    def get_read_explorer(cls):
        return {
            'method': "GET",
            'title': "List Fields",
            'url': reverse('api.v2.fields'),
            'slug': 'field-list',
            'request': "key=nick_name",
            'fields': [
                {'name': "key", 'required': False, 'help': "A field key to filter by. ex: nick_name"}
            ]
        }


class FlowsEndpoint(ListAPIMixin, BaseAPIView):
    """
    ## Listing Flows

    A **GET** returns the list of flows for your organization, in the order of last created.

     * **uuid** - the UUID of the flow (string), filterable as `uuid`
     * **name** - the name of the flow (string)
     * **archived** - whether this flow is archived (boolean)
     * **labels** - the labels for this flow (array of objects)
     * **expires** - the time (in minutes) when this flow's inactive contacts will expire (integer)
     * **created_on** - when this flow was created (datetime)
     * **runs** - the counts of completed, interrupted and expired runs (object)

    Example:

        GET /api/v2/flows.json

    Response containing the groups for your organization:

        {
            "next": null,
            "previous": null,
            "results": [
                {
                    "uuid": "5f05311e-8f81-4a67-a5b5-1501b6d6496a",
                    "name": "Survey",
                    "archived": false,
                    "labels": [{"name": "Important", "uuid": "5a4eb79e-1b1f-4ae3-8700-09384cca385f"}],
                    "expires": 600,
                    "created_on": "2016-01-06T15:33:00.813162Z",
                    "runs": {
                        "completed": 123,
                        "interrupted": 2,
                        "expired": 34
                    }
                },
                ...
            ]
        }
    """
    permission = 'flows.flow_api'
    model = Flow
    serializer_class = FlowReadSerializer
    pagination_class = CreatedOnCursorPagination

    def filter_queryset(self, queryset):
        params = self.request.query_params

        # filter by UUID (optional)
        uuid = params.get('uuid')
        if uuid:
            queryset = queryset.filter(uuid=uuid)

        queryset = queryset.prefetch_related('labels')

        return queryset

    @classmethod
    def get_read_explorer(cls):
        return {
            'method': "GET",
            'title': "List Flows",
            'url': reverse('api.v2.flows'),
            'slug': 'flow-list',
            'request': "",
            'fields': [
                {'name': "uuid", 'required': False, 'help': "A flow UUID filter by. ex: 5f05311e-8f81-4a67-a5b5-1501b6d6496a"}
            ]
        }


class GroupsEndpoint(ListAPIMixin, BaseAPIView):
    """
    ## Listing Groups

    A **GET** returns the list of contact groups for your organization, in the order of last created.

     * **uuid** - the UUID of the group (string), filterable as `uuid`
     * **name** - the name of the group (string)
     * **count** - the number of contacts in the group (int)

    Example:

        GET /api/v2/groups.json

    Response containing the groups for your organization:

        {
            "next": null,
            "previous": null,
            "results": [
                {
                    "uuid": "5f05311e-8f81-4a67-a5b5-1501b6d6496a",
                    "name": "Reporters",
                    "count": 315
                },
                ...
            ]
        }
    """
    permission = 'contacts.contactgroup_api'
    model = ContactGroup
    model_manager = 'user_groups'
    serializer_class = ContactGroupReadSerializer
    pagination_class = CreatedOnCursorPagination

    def filter_queryset(self, queryset):
        params = self.request.query_params

        # filter by UUID (optional)
        uuid = params.get('uuid')
        if uuid:
            queryset = queryset.filter(uuid=uuid)

        return queryset.filter(is_active=True)

    @classmethod
    def get_read_explorer(cls):
        return {
            'method': "GET",
            'title': "List Groups",
            'url': reverse('api.v2.groups'),
            'slug': 'group-list',
            'request': "",
            'fields': [
                {'name': "uuid", 'required': False, 'help': "A group UUID filter by. ex: 5f05311e-8f81-4a67-a5b5-1501b6d6496a"}
            ]
        }


class LabelsEndpoint(ListAPIMixin, BaseAPIView):
    """
    ## Listing Labels

    A **GET** returns the list of message labels for your organization, in the order of last created.

     * **uuid** - the UUID of the label (string), filterable as `uuid`
     * **name** - the name of the label (string)
     * **count** - the number of messages with this label (int)

    Example:

        GET /api/v2/labels.json

    Response containing the labels for your organization:

        {
            "next": null,
            "previous": null,
            "results": [
                {
                    "uuid": "5f05311e-8f81-4a67-a5b5-1501b6d6496a",
                    "name": "Screened",
                    "count": 315
                },
                ...
            ]
        }
    """
    permission = 'contacts.label_api'
    model = Label
    model_manager = 'label_objects'
    serializer_class = LabelReadSerializer
    pagination_class = CreatedOnCursorPagination

    def filter_queryset(self, queryset):
        params = self.request.query_params

        # filter by UUID (optional)
        uuid = params.get('uuid')
        if uuid:
            queryset = queryset.filter(uuid=uuid)

        return queryset.filter(is_active=True)

    @classmethod
    def get_read_explorer(cls):
        return {
            'method': "GET",
            'title': "List Labels",
            'url': reverse('api.v2.labels'),
            'slug': 'label-list',
            'request': "",
            'fields': [
                {'name': "uuid", 'required': False, 'help': "A label UUID to filter by. ex: 5f05311e-8f81-4a67-a5b5-1501b6d6496a"}
            ]
        }


class MediaEndpoint(BaseAPIView):
    """
    This endpoint allows you to submit media which can be embedded in flow steps

    ## Creating Media

    By making a ```POST``` request to the endpoint you can add a new media files
    """
    parser_classes = (MultiPartParser, FormParser,)
    permission = 'msgs.msg_api'

    def post(self, request, format=None, *args, **kwargs):

        org = self.request.user.get_org()
        media_file = request.data.get('media_file', None)
        extension = request.data.get('extension', None)

        if media_file and extension:
            location = org.save_media(media_file, extension)
            return Response(dict(location=location), status=status.HTTP_201_CREATED)

        return Response(dict(), status=status.HTTP_400_BAD_REQUEST)


class MessagesEndpoint(ListAPIMixin, BaseAPIView):
    """
    This endpoint allows you to fetch messages.

    ## Listing Messages

    By making a ```GET``` request you can list the messages for your organization, filtering them as needed. Each
    message has the following attributes:

     * **id** - the ID of the message (int), filterable as `id`.
     * **broadcast** - the id of the broadcast (int), filterable as `broadcast`.
     * **contact** - the UUID and name of the contact (object), filterable as `contact` with UUID.
     * **urn** - the URN of the sender or receiver, depending on direction (string).
     * **channel** - the UUID and name of the channel that handled this message (object).
     * **direction** - the direction of the message (one of "incoming" or "outgoing").
     * **type** - the type of the message (one of "inbox", "flow", "ivr").
     * **status** - the status of the message (one of "initializing", "queued", "wired", "sent", "delivered", "handled", "errored", "failed", "resent").
     * **visibility** - the visibility of the message (one of "visible", "archived" or "deleted")
     * **text** - the text of the message received (string). Note this is the logical view and the message may have been received as multiple physical messages.
     * **labels** - any labels set on this message (array of objects), filterable as `label` with label name or UUID.
     * **created_on** - when this message was either received by the channel or created (datetime) (filterable as `before` and `after`).
     * **sent_on** - for outgoing messages, when the channel sent the message (null if not yet sent or an incoming message) (datetime).

    You can also filter by `folder` where folder is one of `inbox`, `flows`, `archived`, `outbox`, `incoming` or `sent`.
    Note that you cannot filter by more than one of `contact`, `folder`, `label` or `broadcast` at the same time.

    The sort order for all folders save for `incoming` is the message creation date. For the `incoming` folder (which
    includes all incoming messages, regardless of visibility or type) messages are sorted by last modified date. This
    allows clients to poll for updates to message labels and visibility changes.

    Example:

        GET /api/v2/messages.json?folder=inbox

    Response is the list of messages for that contact, most recently created first:

        {
            "next": "http://example.com/api/v2/messages.json?folder=inbox&cursor=cD0yMDE1LTExLTExKzExJTNBM40NjQlMkIwMCUzRv",
            "previous": null,
            "results": [
            {
                "id": 4105426,
                "broadcast": 2690007,
                "contact": {"uuid": "d33e9ad5-5c35-414c-abd4-e7451c69ff1d", "name": "Bob McFlow"},
                "urn": "twitter:textitin",
                "channel": {"uuid": "9a8b001e-a913-486c-80f4-1356e23f582e", "name": "Nexmo"},
                "direction": "out",
                "type": "inbox",
                "status": "wired",
                "visibility": "visible",
                "text": "How are you?",
                "labels": [{"name": "Important", "uuid": "5a4eb79e-1b1f-4ae3-8700-09384cca385f"}],
                "created_on": "2016-01-06T15:33:00.813162Z",
                "sent_on": "2016-01-06T15:35:03.675716Z",
            },
            ...
        }
    """
    class Pagination(CreatedOnCursorPagination):
        """
        Overridden paginator for Msg endpoint that switches from created_on to modified_on when looking
        at all incoming messages.
        """
        def get_ordering(self, request, queryset, view=None):

            try:
                self.page_size = int(request.query_params.get('count'))
            except:
                pass

            if request.query_params.get('folder', '').lower() == 'incoming':
                return ModifiedOnCursorPagination.ordering
            else:
                return CreatedOnCursorPagination.ordering

    permission = 'msgs.msg_api'
    model = Msg
    serializer_class = MsgReadSerializer
    pagination_class = Pagination
    exclusive_params = ('contact', 'folder', 'label', 'broadcast')
    required_params = ('contact', 'folder', 'label', 'broadcast', 'id')
    throttle_scope = 'v2.messages'

    FOLDER_FILTERS = {'inbox': SystemLabel.TYPE_INBOX,
                      'flows': SystemLabel.TYPE_FLOWS,
                      'archived': SystemLabel.TYPE_ARCHIVED,
                      'outbox': SystemLabel.TYPE_OUTBOX,
                      'sent': SystemLabel.TYPE_SENT}

    def get_queryset(self):
        org = self.request.user.get_org()
        folder = self.request.query_params.get('folder')

        if folder:
            sys_label = self.FOLDER_FILTERS.get(folder.lower())
            if sys_label:
                return SystemLabel.get_queryset(org, sys_label, exclude_test_contacts=False)
            elif folder == 'incoming':
                return self.model.all_messages.filter(org=org, direction='I')
            else:
                return self.model.all_messages.filter(pk=-1)
        else:
            return self.model.all_messages.filter(org=org).exclude(visibility=Msg.VISIBILITY_DELETED).exclude(msg_type=None)

    def filter_queryset(self, queryset):
        params = self.request.query_params
        org = self.request.user.get_org()

        # filter by id (optional)
        msg_id = params.get('id')
        if msg_id:
            queryset = queryset.filter(id=msg_id)

        # filter by broadcast (optional)
        broadcast_id = params.get('broadcast')
        if broadcast_id:
            queryset = queryset.filter(broadcast_id=broadcast_id)

        # filter by contact (optional)
        contact_uuid = params.get('contact')
        if contact_uuid:
            contact = Contact.objects.filter(org=org, is_test=False, is_active=True, uuid=contact_uuid).first()
            if contact:
                queryset = queryset.filter(contact=contact)
            else:
                queryset = queryset.filter(pk=-1)
        else:
            # otherwise filter out test contact runs
            test_contact_ids = list(Contact.objects.filter(org=org, is_test=True).values_list('pk', flat=True))
            queryset = queryset.exclude(contact__pk__in=test_contact_ids)

        # filter by label name/uuid (optional)
        label_ref = params.get('label')
        if label_ref:
            label = Label.label_objects.filter(org=org).filter(Q(name=label_ref) | Q(uuid=label_ref)).first()
            if label:
                queryset = queryset.filter(labels=label, visibility=Msg.VISIBILITY_VISIBLE)
            else:
                queryset = queryset.filter(pk=-1)

        # use prefetch rather than select_related for foreign keys to avoid joins
        queryset = queryset.prefetch_related(
            Prefetch('contact', queryset=Contact.objects.only('uuid', 'name')),
            Prefetch('contact_urn', queryset=ContactURN.objects.only('urn')),
            Prefetch('channel', queryset=Channel.objects.only('uuid', 'name')),
            Prefetch('labels', queryset=Label.label_objects.only('uuid', 'name')),
        )

        # incoming folder gets sorted by 'modified_on'
        if self.request.query_params.get('folder', '').lower() == 'incoming':
            return self.filter_before_after(queryset, 'modified_on')

        # everything else by 'created_on'
        else:
            return self.filter_before_after(queryset, 'created_on')

    @classmethod
    def get_read_explorer(cls):
        return {
            'method': "GET",
            'title': "List Messages",
            'url': reverse('api.v2.messages'),
            'slug': 'msg-list',
            'request': "folder=incoming&after=2014-01-01T00:00:00.000",
            'fields': [
                {'name': 'id', 'required': False, 'help': "A message ID to filter by, ex: 123456"},
                {'name': 'broadcast', 'required': False, 'help': "A broadcast ID to filter by, ex: 12345"},
                {'name': 'contact', 'required': False, 'help': "A contact UUID to filter by, ex: 09d23a05-47fe-11e4-bfe9-b8f6b119e9ab"},
                {'name': 'folder', 'required': False, 'help': "A folder name to filter by, one of: inbox, flows, archived, outbox, sent, incoming"},
                {'name': 'label', 'required': False, 'help': "A label name or UUID to filter by, ex: Spam"},
                {'name': 'before', 'required': False, 'help': "Only return messages created before this date, ex: 2015-01-28T18:00:00.000"},
                {'name': 'after', 'required': False, 'help': "Only return messages created after this date, ex: 2015-01-28T18:00:00.000"},
                {'name': 'count', 'required': False, 'help': "Number of items returned in the query, paging the rest."}
            ]
        }


class OrgEndpoint(BaseAPIView):
    """
    ## Viewing Current Organization

    A **GET** returns the details of your organization. There are no parameters.

    Example:

        GET /api/v2/org.json

    Response containing your organization:

        {
            "name": "Nyaruka",
            "country": "RW",
            "languages": ["eng", "fre"],
            "primary_language": "eng",
            "timezone": "Africa/Kigali",
            "date_style": "day_first",
            "anon": false
        }
    """
    permission = 'orgs.org_api'

    def get(self, request, *args, **kwargs):
        org = request.user.get_org()

        data = {
            'name': org.name,
            'country': org.get_country_code(),
            'languages': [l.iso_code for l in org.languages.order_by('iso_code')],
            'primary_language': org.primary_language.iso_code if org.primary_language else None,
            'timezone': org.timezone,
            'date_style': ('day_first' if org.get_dayfirst() else 'month_first'),
            'anon': org.is_anon
        }

        return Response(data, status=status.HTTP_200_OK)

    @classmethod
    def get_read_explorer(cls):
        return {
            'method': "GET",
            'title': "View Current Org",
            'url': reverse('api.v2.org'),
            'slug': 'org-read',
            'request': ""
        }


class ResthookEndpoint(ListAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list the resthooks on your account.

    ## Listing Resthooks

    By making a ```GET``` request you can list all the resthooks on your organization.  Each
    resthook has the following attributes:

     * **resthook** - the slug for the resthook (string)
     * **created_on** - the datetime when this resthook was created (datetime)
     * **modified_on** - the datetime when this resthook was last modified (datetime)

    Example:

        GET /api/v2/resthooks.json

    Response is the list of resthooks on your organization, most recently modified first:

        {
            "next": "http://example.com/api/v2/resthooks.json?cursor=cD0yMDE1LTExLTExKzExJTNBM40NjQlMkIwMCUzRv",
            "previous": null,
            "results": [
            {
                "resthook": "new-report",
                "created_on": "2015-11-11T13:05:57.457742Z",
                "modified_on": "2015-11-11T13:05:57.457742Z",
            },
            ...
        }
    """
    permission = 'api.resthook_api'
    model = Resthook
    serializer_class = ResthookReadSerializer
    pagination_class = ModifiedOnCursorPagination
    throttle_scope = 'v2.api'

    def filter_queryset(self, queryset):
        org = self.request.user.get_org()
        return Resthook.objects.filter(org=org, is_active=True).order_by('-modified_on')

    @classmethod
    def get_read_explorer(cls):
        return {
            'method': "GET",
            'title': "List Resthooks",
            'url': reverse('api.v2.resthooks'),
            'slug': 'resthook-list',
            'request': "?",
            'fields': []
        }


class ResthookSubscriberEndpoint(ListAPIMixin, CreateAPIMixin, DeleteAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list, add or remove subscribers to resthooks.

    ## Listing Resthook Subscribers

    By making a ```GET``` request you can list all the subscribers on your organization.  Each
    resthook subscriber has the following attributes:

     * **id** - the id of the subscriber (integer)
     * **resthook** - the resthook they are subscribed to (string, filterable)
     * **target_url** - the url that will be notified when this event occurs
     * **created_on** - when this subscriber was added

    Example:

        GET /api/v2/resthook_subscribers.json

    Response is the list of resthook subscribers on your organization, most recently created first:

        {
            "next": "http://example.com/api/v2/resthook_subscribers.json?cursor=cD0yMDE1LTExLTExKzExJTNBM40NjQlMkIwMCUzRv",
            "previous": null,
            "results": [
            {
                "id": "10404016"
                "resthook": "mother-registration",
                "target_url": "https://zapier.com/receive/505019595",
                "created_on": "2013-08-19T19:11:21.082Z"
            },
            {
                "id": "10404055",
                "resthook": "new-birth",
                "target_url": "https://zapier.com/receive/605010501",
                "created_on": "2013-08-19T19:11:21.082Z"
            },
            ...
        }

    ## Subscribing to a Resthook

    By making a ```POST``` request with the event you want to subscribe to and the target URL, you can subscribe to be notified
    whenever your resthook event is triggered.

     * **resthook** - the slug of the resthook to subscribe to
     * **target_url** - the URL you want called (will be called with a POST)

    Example:

        POST /api/v2/resthook_subscribers.json
        {
            "resthook": "new-report",
            "target_url": "https://zapier.com/receive/505019595"
        }

    Response is the created subscription:

        {
            "id": "10404016",
            "resthook": "new-report",
            "target_url": "https://zapier.com/receive/505019595",
            "created_on": "2013-08-19T19:11:21.082Z"
        }

    ## Deleting a Subscription

    By making a ```DELETE``` request with the id of the subscription, you can remove it.

     * **id** - the id of the resthook subscription you want to remove, on success you will receive a 204 and empty body

    Example:

        POST /api/v2/resthook_subscribers.json?id=10404016

    Response is status code 204 and an empty response

        status code: 204

    """
    permission = 'api.resthooksubscriber_api'
    model = ResthookSubscriber
    serializer_class = ResthookSubscriberReadSerializer
    write_serializer_class = ResthookSubscriberWriteSerializer
    pagination_class = CreatedOnCursorPagination
    throttle_scope = 'v2.api'

    def get_queryset(self):
        org = self.request.user.get_org()
        return ResthookSubscriber.objects.filter(resthook__org=org, is_active=True).order_by('-created_on')

    @classmethod
    def get_read_explorer(cls):
        return {
            'method': "GET",
            'title': "List Resthook Subscribers",
            'url': reverse('api.v2.resthook_subscribers'),
            'slug': 'resthooksubscriber-list',
            'request': "?",
            'fields': []
        }

    @classmethod
    def get_write_explorer(cls):
        spec = dict(method="POST",
                    title="Add a subscriber for a resthook",
                    url=reverse('api.v2.resthook_subscribers'),
                    slug='resthooksubscriber-create',
                    request='{ "resthook": "new-report", "target_url": "https://zapier.com/handle/1515155" }')

        spec['fields'] = [dict(name='resthook', required=True,
                               help="The slug for the resthook you width to subscribe to"),
                          dict(name='target_url', required=True,
                               help="The URL that will be called when the resthook is triggered.")]

        return spec

    @classmethod
    def get_delete_explorer(cls):
        spec = dict(method="DELETE",
                    title="Delete resthook subscriber",
                    url=reverse('api.v2.resthook_subscribers'),
                    slug='resthooksubscriber-delete',
                    request="id=10404055")
        spec['fields'] = [dict(name='id', required=True,
                               help="The id of the subscriber you want to remove")]

        return spec

    def destroy(self, request, *args, **kwargs):
        subscriber_id = request.query_params.get('id')
        if not subscriber_id:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        subscriber = ResthookSubscriber.objects.filter(resthook__org=request.user.get_org(), id=subscriber_id).first()
        if not subscriber:
            return Response(status=status.HTTP_404_NOT_FOUND)

        subscriber.release(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ResthookEventEndpoint(ListAPIMixin, BaseAPIView):
    """
    This endpoint lists recent events for the passed in Resthook.

    ## Listing Resthook Events

    By making a ```GET``` request you can list all the recent resthook events on your organization.
    Each event has the following attributes:

     * **resthook** - the slug for the resthook (filterable)
     * **data** - the data for the resthook
     * **created_on** - the datetime when this resthook was created (datetime)

    Example:

        GET /api/v2/resthook_events.json

    Response is the list of recent resthook events on your organization, most recently created first:

        {
            "next": "http://example.com/api/v2/resthook_events.json?cursor=cD0yMDE1LTExLTExKzExJTNBM40NjQlMkIwMCUzRv",
            "previous": null,
            "results": [
            {
                "resthook": "new-report",
                "data": {
                    channel=105,
                    flow=50505,
                    "flow_base_language": "eng",
                    run=50040405,
                    text="Incoming text",
                    step="d33e9ad5-5c35-414c-abd4-e7451c69ff1d",
                    contact=d33e9ad5-5c35-414c-abd4-e7451casdf",
                    urn="tel:+12067781234",
                    values=[{
                        "category": {
                            "eng": "All Responses"
                        },
                        "node": "c33724d7-1064-4dd6-9aa3-efd29252cb88",
                        "text": "Ryan Lewis",
                        "rule_value": "Ryan Lewis",
                        "value": "Ryan Lewis",
                        "label": "Name",
                        "time": "2016-08-10T21:18:51.186826Z"
                    }],
                    steps=[{
                        "node": "2d4f8c9a-cf12-4f6c-ad55-a6cc633954f6",
                        "left_on": "2016-08-10T21:18:45.391114Z",
                        "text": "What is your name?",
                        "value": null,
                        "arrived_on": "2016-08-10T21:18:45.378598Z",
                        "type": "A"
                    },
                    {
                        "node": "c33724d7-1064-4dd6-9aa3-efd29252cb88",
                        "left_on": "2016-08-10T21:18:51.186826Z",
                        "text": "Eric Newcomer",
                        "value": "Eric Newcomer",
                        "arrived_on": "2016-08-10T21:18:45.391114Z",
                        "type": "R"
                    }],
                },
                "created_on": "2015-11-11T13:05:57.457742Z",
            },
            ...
        }
    """
    permission = 'api.webhookevent_api'
    model = WebHookEvent
    serializer_class = WebHookEventReadSerializer
    pagination_class = CreatedOnCursorPagination
    throttle_scope = 'v2.api'

    def filter_queryset(self, queryset):
        params = self.request.query_params
        org = self.request.user.get_org()
        queryset = queryset.filter(org=org).exclude(resthook=None)

        resthook = params.get('resthook')
        if resthook:
            queryset = queryset.filter(resthook__slug=resthook)

        return queryset.order_by('-created_on')

    @classmethod
    def get_read_explorer(cls):
        return {
            'method': "GET",
            'title': "List Resthook Events",
            'url': reverse('api.v2.resthook_events'),
            'slug': 'resthook-event-list',
            'request': "?",
            'fields': []
        }


class RunsEndpoint(ListAPIMixin, BaseAPIView):
    """
    This endpoint allows you to fetch flow runs. A run represents a single contact's path through a flow and is created
    each time a contact is started in a flow.

    ## Listing Flow Runs

    By making a ```GET``` request you can list all the flow runs for your organization, filtering them as needed.  Each
    run has the following attributes:

     * **id** - the ID of the run (int), filterable as `id`.
     * **flow** - the UUID and name of the flow (object), filterable as `flow` with UUID.
     * **contact** - the UUID and name of the contact (object), filterable as `contact` with UUID.
     * **responded** - whether the contact responded (boolean), filterable as `responded`.
     * **steps** - steps visited by the contact on the flow (array of objects).
     * **created_on** - the datetime when this run was started (datetime).
     * **modified_on** - when this run was last modified (datetime), filterable as `before` and `after`.
     * **exited_on** - the datetime when this run exited or null if it is still active (datetime).
     * **exit_type** - how the run ended (one of "interrupted", "completed", "expired").

    Note that you cannot filter by `flow` and `contact` at the same time.

    Example:

        GET /api/v2/runs.json?flow=f5901b62-ba76-4003-9c62-72fdacc1b7b7

    Response is the list of runs on the flow, most recently modified first:

        {
            "next": "http://example.com/api/v2/runs.json?cursor=cD0yMDE1LTExLTExKzExJTNBM40NjQlMkIwMCUzRv",
            "previous": null,
            "results": [
            {
                "id": 12345678,
                "flow": {"uuid": "f5901b62-ba76-4003-9c62-72fdacc1b7b7", "name": "Specials"},
                "contact": {"uuid": "d33e9ad5-5c35-414c-abd4-e7451c69ff1d", "name": "Bob McFlow"},
                "responded": true,
                "steps": [
                    {
                        "node": "22bd934e-953b-460d-aaf5-42a84ec8f8af",
                        "category": null,
                        "left_on": "2013-08-19T19:11:21.082Z",
                        "text": "Hi from the Thrift Shop! We are having specials this week. What are you interested in?",
                        "value": null,
                        "arrived_on": "2013-08-19T19:11:21.044Z",
                        "type": "actionset"
                    },
                    {
                        "node": "9a31495d-1c4c-41d5-9018-06f93baa5b98",
                        "category": "Foxes",
                        "left_on": null,
                        "text": "I want to buy a fox skin",
                        "value": "fox skin",
                        "arrived_on": "2013-08-19T19:11:21.088Z",
                        "type": "ruleset"
                    }
                ],
                "created_on": "2015-11-11T13:05:57.457742Z",
                "modified_on": "2015-11-11T13:05:57.576056Z",
                "exited_on": "2015-11-11T13:05:57.576056Z",
                "exit_type": "completed"
            },
            ...
        }
    """
    permission = 'flows.flow_api'
    model = FlowRun
    serializer_class = FlowRunReadSerializer
    pagination_class = ModifiedOnCursorPagination
    exclusive_params = ('contact', 'flow')
    throttle_scope = 'v2.runs'

    def filter_queryset(self, queryset):
        params = self.request.query_params
        org = self.request.user.get_org()

        # filter by flow (optional)
        flow_uuid = params.get('flow')
        if flow_uuid:
            flow = Flow.objects.filter(org=org, uuid=flow_uuid, is_active=True).first()
            if flow:
                queryset = queryset.filter(flow=flow)
            else:
                queryset = queryset.filter(pk=-1)

        # filter by id (optional)
        run_id = params.get('id')
        if run_id:
            queryset = queryset.filter(id=run_id)

        # filter by contact (optional)
        contact_uuid = params.get('contact')
        if contact_uuid:
            contact = Contact.objects.filter(org=org, is_test=False, is_active=True, uuid=contact_uuid).first()
            if contact:
                queryset = queryset.filter(contact=contact)
            else:
                queryset = queryset.filter(pk=-1)
        else:
            # otherwise filter out test contact runs
            test_contact_ids = list(Contact.objects.filter(org=org, is_test=True).values_list('pk', flat=True))
            queryset = queryset.exclude(contact__pk__in=test_contact_ids)

        # limit to responded runs (optional)
        if str_to_bool(params.get('responded')):
            queryset = queryset.filter(responded=True)

        # use prefetch rather than select_related for foreign keys to avoid joins
        queryset = queryset.prefetch_related(
            Prefetch('flow', queryset=Flow.objects.only('uuid', 'name', 'base_language')),
            Prefetch('contact', queryset=Contact.objects.only('uuid', 'name', 'language')),
            Prefetch('steps', queryset=FlowStep.objects.order_by('arrived_on')),
            Prefetch('steps__messages', queryset=Msg.all_messages.only('broadcast', 'text')),
            Prefetch('steps__broadcasts', queryset=Broadcast.objects.all()),
        )

        return self.filter_before_after(queryset, 'modified_on')

    @classmethod
    def get_read_explorer(cls):
        return {
            'method': "GET",
            'title': "List Flow Runs",
            'url': reverse('api.v2.runs'),
            'slug': 'run-list',
            'request': "after=2014-01-01T00:00:00.000",
            'fields': [
                {'name': 'id', 'required': False, 'help': "A run ID to filter by, ex: 123456"},
                {'name': 'flow', 'required': False, 'help': "A flow UUID to filter by, ex: f5901b62-ba76-4003-9c62-72fdacc1b7b7"},
                {'name': 'contact', 'required': False, 'help': "A contact UUID to filter by, ex: 09d23a05-47fe-11e4-bfe9-b8f6b119e9ab"},
                {'name': 'responded', 'required': False, 'help': "Whether to only return runs with contact responses"},
                {'name': 'before', 'required': False, 'help': "Only return runs modified before this date, ex: 2015-01-28T18:00:00.000"},
                {'name': 'after', 'required': False, 'help': "Only return runs modified after this date, ex: 2015-01-28T18:00:00.000"}
            ]
        }


class FlowStartsEndpoint(ListAPIMixin, CreateAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list manual flow starts on your account and add or start contacts in a flow.

    ## Listing Flow Starts

    By making a ```GET``` request you can list all the manual flow starts on your organization.  Each
    flow start has the following attributes:

     * **id** - the id of this flow start (integer)
     * **flow** - the flow which was started (object)
     * **contacts** - the list of contacts that were started in the flow (objects)
     * **groups** - the list of groups that were started in the flow (objects)
     * **restart_particpants** - whether the contacts were restarted in this flow (boolean)
     * **status** - the status of this flow start
     * **created_on** - the datetime when this flow start was created (datetime)

    Example:

        GET /api/v2/flow_starts.json

    Response is the list of flow starts on your organization, most recently modified first:

        {
            "next": "http://example.com/api/v2/flow_starts.json?cursor=cD0yMDE1LTExLTExKzExJTNBM40NjQlMkIwMCUzRv",
            "previous": null,
            "results": [
            {
                "id": 150051,
                "flow": {
                    name: "Thrift Shop",
                    uuid: "f5901b62-ba76-4003-9c62-72fdacc1b7b7"
                },
                "groups": [
                     {
                          "name": "Ryan & Macklemore",
                          "uuid": "f5901b62-ba76-4003-9c62-72fdacc1b7b7"
                     }
                ],
                "contacts": [
                     {
                         "name": "Wanz",
                         "uuid": "f5901b62-ba76-4003-9c62-fjjajdsi15553"

                     }
                ],
                "restart_participants": true,
                "status": "complete",
                "created_on": "2013-08-19T19:11:21.082Z"
            },
            ...
            ]
        }

    ## Starting contacts down a flow

    By making a ```POST``` request with the contacts, groups and URNs you want to start down a flow you can trigger a flow
    start. Note that that contacts will be added to the flow asynchronously, you can use the runs endpoint to monitor the
    runs created by this start.

     * **flow** - the UUID of the flow to start contacts in (required)
     * **groups** - a list of the UUIDs of the groups you want to start in this flow (optional)
     * **contacts** - a list of the UUIDs of the contacts you want to start in this flow (optional)
     * **urns** - a list of URNs you want to start in this flow (optional)
     * **restart_participants** - whether to restart participants already in this flow (optional, defaults to true)

    Example:

        POST /api/v2/flow_starts.json
        {
            "flow": "f5901b62-ba76-4003-9c62-72fdacc1b7b7",
            "groups": ["f5901b62-ba76-4003-9c62-72fdacc15515"],
            "contacts": ["f5901b62-ba76-4003-9c62-fjjajdsi15553"]
            "urns": ["twitter:sirmixalot", "tel:+12065551212"]
        }

    Response is the created flow start:

        {
            "flow": {
                name: "Thrift Shop",
                uuid: "f5901b62-ba76-4003-9c62-72fdacc1b7b7"
            },
            "groups": [
                 {
                      "name": "Ryan & Macklemore",
                      "uuid": "f5901b62-ba76-4003-9c62-72fdacc1b7b7"
                 }
            ],
            "contacts": [
                 {
                     "name": "Wanz",
                     "uuid": "f5901b62-ba76-4003-9c62-fjjajdsi15553"
                 },
                 {
                     "name": "Sir Mixa Lot",
                     "uuid": "f5901b62-ba76-4003-9c62-72fftww881256"
                 }
            ],
            "restart_participants": true,
            "status": "pending",
            "created_on": "2013-08-19T19:11:21.082Z"
        }

    """
    permission = 'api.flowstart_api'
    model = FlowStart
    serializer_class = FlowStartReadSerializer
    write_serializer_class = FlowStartWriteSerializer
    pagination_class = CreatedOnCursorPagination
    throttle_scope = 'v2.api'

    def get_queryset(self):
        org = self.request.user.get_org()
        return FlowStart.objects.filter(flow__org=org, is_active=True).order_by('-modified_on', '-id')

    def filter_queryset(self, queryset):
        params = self.request.query_params

        # filter by id (optional)
        start_id = params.get('id')
        if start_id:
            queryset = queryset.filter(id=start_id)

        # use prefetch rather than select_related for foreign keys to avoid joins
        queryset = queryset.prefetch_related(
            Prefetch('contacts', queryset=Contact.objects.only('uuid', 'name')),
            Prefetch('groups', queryset=ContactGroup.user_groups.only('uuid', 'name')),
        )

        return self.filter_before_after(queryset, 'modified_on')

    def post_save(self, instance):
        # actually start our flow
        instance.async_start()

    @classmethod
    def get_read_explorer(cls):
        return {
            'method': "GET",
            'title': "List Flow Starts",
            'url': reverse('api.v2.flow_starts'),
            'slug': 'flow_start-list',
            'request': "?after=2014-01-01T00:00:00.000",
            'fields': [dict(name='id', required=False,
                            help="Only return the flow start with this id"),
                       dict(name='after', required=False,
                            help="Only return flow starts modified after this date"),
                       dict(name='before', required=False,
                            help="Only return flow starts modified before this date")]
        }

    @classmethod
    def get_write_explorer(cls):
        spec = dict(method="POST",
                    title="Start contacts in a flow",
                    url=reverse('api.v2.flow_starts'),
                    slug='flow_start-create',
                    request='{ "flow": "f5901b62-ba76-4003-9c62-72fdacc1b7b7", "urns": ["twitter:sirmixalot"] }')

        spec['fields'] = [dict(name='flow', required=True,
                               help="The UUID of the flow to start"),
                          dict(name='groups', required=False,
                               help="The UUIDs of any contact groups you want to start"),
                          dict(name='contacts', required=False,
                               help="The UUIDs of any contacts you want to start"),
                          dict(name='urns', required=False,
                               help="The URNS of any contacts you want to start"),
                          dict(name='restart_participants', required=False,
                               help="Whether to restart any participants already in the flow")
                          ]

        return spec
