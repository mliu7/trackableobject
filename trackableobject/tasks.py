from datetime import datetime

from celery.decorators import task
from django.contrib.auth.models import User
from django.db import models

from trackable_object.utils import fake_request


@task()
def merge_objects(obj_1, obj_2, user_id, message='', force=False, do_after_saved=True, merge_event=None):
    """ Merges two trackable objects using the standard trackable_object merge method """
    user = User.objects.get(id=user_id)
    request = fake_request(user)
    return obj_1.merge(obj_2, request, message=message, force=force, do_after_saved=do_after_saved, merge_event=merge_event)


@task()
def unmerge_objects(obj, user_id, message='', force=False, do_after_saved=True, merge_event=None):
    """ Merges two trackable objects using the standard trackable_object merge method """
    user = User.objects.get(id=user_id)
    request = fake_request(user)
    return obj.unmerge(request, message=message, force=force, do_after_saved=do_after_saved, merge_event=merge_event)


@task()
def update_child_statuses(obj, status, user_id, child_status_kwargs=None, action='edit', message='', do_after_saved=True, force=False):
    user = User.objects.get(id=user_id)
    request = fake_request(user)

    print obj.__class__
    print obj.id
    print status
    print user_id
    print action

    if not child_status_kwargs:
        child_status_kwargs = {}
    children = obj._get_children(**child_status_kwargs)
    for child in children:
        if child.status == status:
            continue

        child.status = status
        if action == 'edit':
            child.edit(request, message=message, do_after_saved=False, force=force, async=False)
        if action == 'remove':
            child.remove(request, message=message, do_after_saved=False, force=force, async=False)


@task()
def update_cache_time(obj, objs_already_updated=None, exclude_models=None):
    """ DEPRECATED. 
    
        Args:
            obj 
            user_id 
            objs_already_updated
    """
    pass
