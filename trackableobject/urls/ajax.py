from django.conf.urls.defaults import *

from trackable_object.views import approve_object, reject_object

def regex():
    return '[a-z_0-9-]+'

def num_regex():
    return '[0-9]+'

urlpatterns = patterns('',
    (r'(?P<app_object_id>' + regex() + r')/approve/$', approve_object),
    (r'(?P<app_object_id>' + regex() + r')/reject/$', reject_object),
)
