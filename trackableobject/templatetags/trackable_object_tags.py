from django import template
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.urlresolvers import reverse
from django.db.models import get_model, Q
from django.utils.html import escape as esc

from annoying.decorators import render_to

from trackable_object.models import TrackableObject

register = template.Library()

@register.simple_tag
def moderate(moderated_objects):
    t = template.loader.get_template('moderate_objects.html')
    return t.render(template.Context({'objects': moderated_objects}))

class CanApproveNode(template.Node):
    def __init__(self, object, user, varname):
        self.object = template.Variable(object)
        self.user = template.Variable(user)
        self.varname = varname
    def render(self, context):
        user = self.user.resolve(context)
        object = self.object.resolve(context)
        context[self.varname] = object.has_approve_perm(user)
        return ''

def do_can_approve(parser, token):
    """Returns a boolean variable that is true iff a user has the 
    permissions necessary to approve an object
    
   Usage:
       {% load trackable_object_tags %}
       {% can_approve object user as can_approve_var %}
    """

    bits = token.split_contents()
    if len(bits) != 5:
        raise template.TemplateSyntaxError("'can_approve' tag requires exactly 4 arguments")
    object = bits[1]
    user = bits[2]
    varname = bits[4]
    return CanApproveNode(object, user, varname)
register.tag('can_approve', do_can_approve)

@register.simple_tag
def make_object_id(object):
    """Returns an id for a div that consists of an objects content type and id
    
    Reason for usage: The purpose of this is to provide an id for moderated objects
        that can be used in conjunction with the approve_or_reject template tag
    
    Usage:
    {% load trackable_object_tags %}       
    <div id={% make_object_id team %} class="moderate">...</div>
    """
    app = object._meta.app_label
    object_type = ContentType.objects.get_for_model(object).model
    return '%s-%s-%s' % (app, object_type, object.id)

@register.simple_tag
def make_approve_or_reject_buttons(moderated_object):
    """Renders information and buttons for approve/reject moderation

    Usage:
    {% load trackable_object_tags %}
    {% for team in teams %}
        <div id={% approve_or_reject_id team %} class="moderate">
            <a href="{% get_team_url team season %}" class="object">{{ team.name }}</a>
            {% make_approve_or_reject_buttons team %}
        </div>
    {% endfor %}
    """
    t = template.loader.get_template('approve_or_reject_buttons.html')
    return t.render(template.Context({'object': moderated_object}))

@register.simple_tag
def make_remove_button(object):
    t = template.loader.get_template('remove_button.html')
    return t.render(template.Context({'object': object}))

@register.simple_tag
def get_pending_approval_count():
    """ As of 8/23, TrackableObjects cannot be queried and thus this currently returns 0 until a different implementation
        is needed.
    """
    return 0

@register.simple_tag
def trackable_object_js_import():
    """Returns the html for fetching the trackable_object javascript

    Usage:
    {% block extra-head %}{{ block.super }}
        {% load trackable_object_tags %}
        {% trackable_object_js_import %}
    {% endblock %}
    """
    return '<script src="{0}js/trackable_object.js" type="text/javascript" charset="utf-80"></script>'.format(settings.STATIC_URL)

class CastNode(template.Node):
    def __init__(self, object, varname):
        self.object_variable = template.Variable(object)
        self.varname = varname

    def render(self, context):
        object = self.object_variable.resolve(context)
        
        context[self.varname] = object.cast()
        return ''

def do_cast(parser, token):
    """
    Usage:
        {% load trackable_object_tags %}
        {% cast object as obj %}
    """
    bits = token.split_contents()
    if len(bits) != 4:
        raise template.TemplateSyntaxError("'cast' tag requires exactly 3 arguments")
    object = bits[1]
    varname = bits[3]
    return CastNode(object, varname)

register.tag('cast', do_cast)
