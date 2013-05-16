from django.conf.urls.defaults import *

def regex():
    return '[a-z_0-9-]+'

def num_regex():
    return '[0-9]+'

urlpatterns = patterns(
    'trackable_object.views',
    url(r'$', 'moderate_all', name='moderate_all'),
)
