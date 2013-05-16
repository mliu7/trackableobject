import re
import simplejson

from django.conf import settings
from django.contrib.auth.models import AnonymousUser, User
from django.contrib.contenttypes.models import ContentType
from django.db.models import get_model
from django.test.client import RequestFactory


def fake_authorized_request(*args, **kwargs):
    """ Creates a request using the login of autoupdate@leaguevine.com """
    user = User.objects.get(email="autoupdate@leaguevine.com")
    return fake_request(user, *args, **kwargs)


def fake_request(user=None, method='GET', data=None, url='/', content_type='text/html; charset=utf-8'):
    """ Returns a fake request with the user added to the request """
    factory = RequestFactory()

    # Get the method to be used for the request (i.e. get, put, post, delete)
    method = getattr(factory, method.lower())

    # If the user is passing in a json object
    if content_type == 'application/json':
        # If it's a dict, turn it into json
        if isinstance(data, dict):
            data = simplejson.dumps(data)

    # Ensure that data is being passed in as a python dict
    else:
        # Convert any json strings back to python dicts
        if isinstance(data, basestring):
            data = simplejson.loads(data)

    kwargs = {}
    if data and data != '{}':
        kwargs['data'] = data

    request = method(url, content_type=content_type, **kwargs)

    # Add the http host
    host = settings.BASE_URL
    if host.startswith('https://'):
        host = host[8:]
    elif host.startswith('http://'):
        host = host[7:]
    request.META['HTTP_HOST'] = host

    # Add the user to the request
    if user:
        request.user = user
    else:
        request.user = AnonymousUser()
    return request

def parse_id(app_object_id_string):
    """Takes an object identified by its app, class and id and returns the object

    Form of app_object_id_string:
        app-object-id
        The app is the name of the django application in lowercase
        The object is the name of the model in lowercase
        The id is the id of the model instance
        All three are separated by single hyphens

    Usage: 
        object = parse_id('team-team'284')
    """
    splitter = re.compile(r'-')
    tokens = splitter.split(app_object_id_string)
    app_string = tokens[0]
    model_string = tokens[1]
    content_id = int(tokens[2])
    content_type = ContentType.objects.get(app_label=app_string, model=model_string)
    object = content_type.model_class().objects.get(id=content_id)
    return object
