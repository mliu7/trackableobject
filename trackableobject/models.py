import copy
from datetime import datetime, timedelta
import inspect

from django import dispatch
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes import generic
from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.db.models import get_models, Q
from django.db.models.query import QuerySet
from django.http import Http404, HttpResponseForbidden
from django.utils.html import escape as esc


# Add an attribute to the Meta class. See here: http://bit.ly/lDHjh
models.options.DEFAULT_NAMES = models.options.DEFAULT_NAMES + ('inherits_status_from',)

################################################################################
# Signals
# All of these signals are only emitted when an object that is head has one of these operations
# performed on it
# post_create is emitted whenever a head object is created, regardless of live/hidden/pending status
post_create = dispatch.Signal(providing_args=['instance', 'request', 'message'])
post_update = dispatch.Signal(providing_args=['instance', 'request', 'message'])
post_remove = dispatch.Signal(providing_args=['instance', 'request', 'message'])

# Decorators
def use_model_status(method, *args, **kwargs):
    """ This decorator is to be used on any methods that rely on status variables for a lookup.
        Without the decorator, the method would use the kwargs to look up the appropriate objects with a given status
        specified with those kwargs. If there were no kwargs, then all objects would be returned.

        With the decorator, if no kwargs are passed in, only objects with the same status as this model 
        will be considered in the lookup.
    """
    def wrapped(self, *args, **kwargs):
        if not kwargs:
            kwargs = self.get_status_kwargs()
            return method(self, *args, **kwargs)
        else:
            return method(self, *args, **kwargs)
    return wrapped

# Overriding the default Django GenericForeignKey
class TrackableObjectGenericForeignKey(generic.GenericForeignKey):
    def __get__(self, instance, instance_type=None):
        """ overrides the default get to not use ct.get_object_for_this_type but instead use the 
            trackableobject manager that fetches all objects using 'all_objects'
        """
        if instance is None:
            return self
        try:
            return getattr(instance, self.cache_attr)
        except AttributeError:
            rel_obj = None
            # Make sure to use ContentType.objects.get_for_id() to ensure that
            # lookups are cached (see ticket #5570). This takes more code than
            # the naive ``getattr(instance, self.ct_field)``, but has better
            # performance when dealing with GFKs in loops and such.
            f = self.model._meta.get_field(self.ct_field)
            ct_id = getattr(instance, f.get_attname(), None)
            if ct_id:
                ct = self.get_content_type(id=ct_id, using=instance._state.db)
                try:
                    rel_obj = ct.model_class().all_objects.get(pk=getattr(instance, self.fk_field))
                except ObjectDoesNotExist:
                    pass
            setattr(instance, self.cache_attr, rel_obj)
            return rel_obj


class TrackableObjectManager(models.Manager):
    def get_query_set(self, **kwargs): 
        """ This snippet comes from:
                http://djangosnippets.org/snippets/734/
        """
        return self.model.QuerySet(self.model).filter(is_head=True)

    def __getattr__(self, attr, *args):
        """ This allows you to define things in an object's QuerySet definition within the model, and then
            have those things be able to be chained in any order. Thus, you do not have to define them twice.

            For instance if you have a method defined on QuerySet called 'on_today()', you can do something like:
                Entry.objects.all().on_today()

            This snippet comes from:
                http://djangosnippets.org/snippets/734/
        """
        if attr.startswith("_"): # or at least "__"
            raise AttributeError
        return getattr(self.get_query_set(), attr, *args)


class LiveTrackableObjectManager(TrackableObjectManager):
    def get_query_set(self): 
        return super(LiveTrackableObjectManager, self).get_query_set().filter(status=self.model.LIVE)


class HiddenTrackableObjectManager(TrackableObjectManager):
    def get_query_set(self): 
        return super(HiddenTrackableObjectManager, self).get_query_set().filter(status=self.model.HIDDEN)


class PendingApprovalTrackableObjectManager(TrackableObjectManager):
    def get_query_set(self): 
        return super(PendingApprovalTrackableObjectManager, self).get_query_set().filter(status=self.model.PENDING_APPROVAL)


class RejectedTrackableObjectManager(TrackableObjectManager):
    def get_query_set(self): 
        return super(RejectedTrackableObjectManager, self).get_query_set().filter(status=self.model.REJECTED)


class RemovedTrackableObjectManager(TrackableObjectManager):
    def get_query_set(self): 
        return super(RemovedTrackableObjectManager, self).get_query_set().filter(status=self.model.REMOVED)


class AllTrackableObjectManager(TrackableObjectManager):
    def get_query_set(self, **kwargs): 
        return self.model.QuerySet(self.model)


class AffectedByMergeManager(models.Manager):
    def create(self, merge_event, obj):
        """ Creates a new AffectedByMerge object 

            Args:
                merge_event - An existing merge_event that has already been saved
                obj - The object that was affected by merge_event
        """
        affected_by_merge_obj = AffectedByMerge(merge_event=merge_event,
                                                content_type=obj.real_type,
                                                object_id=obj.id, 
                                                content_object=obj)
        affected_by_merge_obj.save()
        return affected_by_merge_obj


class MergeEvent(models.Model):
    id = models.AutoField(primary_key=True, db_index=True)


class AffectedByMerge(models.Model):
    merge_event = models.ForeignKey(MergeEvent)
    content_type = models.ForeignKey(ContentType)
    object_id = models.PositiveIntegerField()
    content_object = TrackableObjectGenericForeignKey('content_type', 'object_id')

    objects = AffectedByMergeManager()


class TrackableObject(models.Model):
    """ This is an abstract base class and thus does not have its own table. All Leaguevine objects
        that require tracking who created/edited/removed them will inherit from this model and
        will have access to all of the fields and functions here.
    """
    id = models.AutoField(primary_key=True, db_index=True)

    # Current state of the object.
    LIVE = 1
    HIDDEN = 2
    PENDING_APPROVAL = 3
    REJECTED = 4
    REMOVED = 6
    STATUS_CHOICES = (
        (LIVE, 'Live'),
        (HIDDEN, 'Hidden'),
        (PENDING_APPROVAL, 'Pending'),
        (REJECTED, 'Rejected'),
        (REMOVED, 'Removed'),
    )
    status = models.IntegerField(choices=STATUS_CHOICES, default=LIVE)

    # User modification records.
    submitted_by = models.ForeignKey(User, null=True, blank=True, related_name="%(class)s_submitted_by")
    approved_by = models.ForeignKey(User, null=True, blank=True, related_name="%(class)s_approved_by")
    removed_by = models.ForeignKey(User, null=True, blank=True, related_name="%(class)s_removed_by")

    # Modification time records.
    # All times are stored in UTC time
    submitted_time = models.DateTimeField(db_index=True, null=True, blank=True)
    approved_time = models.DateTimeField(null=True, blank=True)
    removed_time = models.DateTimeField(null=True, blank=True)

    # Modification messages.
    submission_message = models.CharField(max_length=100, blank=True)
    removal_message = models.CharField(max_length=100, blank=True)

    # Determines whether or not a user can approve or reject this object
    # If true: a user can't approve/reject. approving and rejecting happens
    #   automatically when a related object is approved/rejected
    auto_approve = models.BooleanField(default=False)
    counts_towards_contributions = models.BooleanField(default=True)

    # Tracking changes to an object
    CREATED = 1
    EDITED = 2
    MERGED = 3
    REJECTED = 4
    REMOVED = 6 # Defined earlier as well
    UNMERGED = 7 
    APPROVED = 8
    ACTION_CHOICES = (
        (CREATED, 'Created'),
        (EDITED, 'Edited'),
        (REMOVED, 'Removed'),
        (MERGED, 'Merged'),
        (UNMERGED, 'Unmerged'),
        (APPROVED, 'Approved'),
        (REJECTED, 'Rejected'),
    )
    action_taken = models.IntegerField(choices=ACTION_CHOICES, default=CREATED)
    action_by = models.ForeignKey(User, null=True, blank=True, related_name="%(class)s_action_by")
    action_time = models.DateTimeField(null=True, blank=True, db_index=True)
    action_message = models.CharField(max_length=100, blank=True)
    
    # If True, it is the most recent revision of the object, and the only one users see
    is_head = models.BooleanField(default=True)

    # The object this object changed into. If a newer version of this object is saved, this copy remains
    # the same but a new one is created and this object will point to the new object
    points_to_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    points_to = TrackableObjectGenericForeignKey('real_type', 'points_to_id')

    # Tracking merges
    # The primary_merge_from_field tracks the primary of the two objects that was merged.
    # The primary object retains it's data over the secondary object that is merged into it.
    # The secondary object's data is only merged into the primary object for fields that are
    # currently blank on the primary object.
    primary_merge_from_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    primary_merge_from = TrackableObjectGenericForeignKey('real_type', 'primary_merge_from_id')
    secondary_merge_from_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    secondary_merge_from = TrackableObjectGenericForeignKey('real_type', 'secondary_merge_from_id')
    # This is only set to True for the object that had another object merged into it, and 
    # any other objects that had to be recursively merged for this original merge to be valid
    # Objects that were modified (i.e. had modified foreign keys), are tracked by creating an
    # AffectedByMerge object that contains the affected object and this merge_event
    merge_event = models.ForeignKey(MergeEvent, null=True, blank=True)

    # Cache
    # Stores the time this object was last cached
    cache_time = models.DateTimeField(null=True, blank=True) 

    # Subclass information.
    # This is useful if a model uses concrete inheritance to inherit from a model that uses
    # TrackableObject as it's abstract base class. The cast() function will return the child object.
    real_type = models.ForeignKey(ContentType, editable=False, null=True, related_name="%(class)s_real_type")

    # Managers
    objects = TrackableObjectManager()
    live = LiveTrackableObjectManager()
    hidden = HiddenTrackableObjectManager()
    pending_approval = PendingApprovalTrackableObjectManager()
    rejected = RejectedTrackableObjectManager()
    removed = RemovedTrackableObjectManager()
    all_objects = AllTrackableObjectManager() # Even shows all objects that are not the head (i.e. old revisions)

    update_cache_after_save = True

    @property
    def cache_key(self):
        if self.cache_time:
            time = self.cache_time
        elif self.action_time:
            time = self.action_time
        else:
            #if no submitted_time, some error in the backend when creating the object, so use Leaguevine's birthdate (8/3/2010) as submitted_time
            time = self.submitted_time if self.submitted_time else datetime(2010, 8, 3)

        delta = time - datetime(2008, 9, 1)
        timestamp = delta.total_seconds()
        cache_key = "{0}{1}{2}{3}{4:f}".format(settings.KEY_PREFIX, settings.VERSION, self.class_name(), self.id, timestamp)
        return cache_key

    @property
    def leaguevine_url(self):
        return self.get_absolute_url()

    class Meta:
        abstract = True
        permissions = (
            ('can_approve', 'Can approve content'),
            ('can_add_without_approval', 'Can add content without needing approval'),
        )

    # Public Methods
    def assert_constraints(self):
        """ Perform any checks on values before saving to the database. 
        
            This should be thought of as a last line of defense and ensure no invalid data can
            be entered. If it fails, it should raise an exception, and thus users will see a 500 error
        """
        pass
        
    def cast(self):
        real_type = self.real_type
        if real_type and real_type.model_class() != self.__class__:
            return self.real_type.model_class().all_objects.get(pk=self.pk)
        else:
            return self

    def class_name(self):
        return self.__class__.__name__

    def get_status_kwargs(self):
        """ Returns a dict of kwargs the correspond to an object's current status. 
            For instance, if the object is live, this will return: {'live': True}
        """
        return self.__class__.objects.get_status_kwargs([self.status])

    def get_status_name(self):
        for id, name in self.STATUS_CHOICES:
            if self.status == id:
                return name
        return ''

    def is_hidden(self):
        return (self.status == self.HIDDEN)

    def is_live(self):
        return (self.status == self.LIVE)

    def is_new(self):
        """ If this object did not have an ID assigned to it when it was instantiated, return True.
            Otherwise, return False. 

            This is useful for checking whether an existing object was looked up, or if this object
            was recently created and saved.
        """
        if self._original_id:
            return False 
        return True
    
    def is_pending_approval(self):
        return (self.status == self.PENDING_APPROVAL)

    def is_rejected(self):
        return (self.status == self.REJECTED)

    def is_removed(self):
        return (self.status == self.REMOVED)

    def safe_getattr(self, *args, **kwargs):
        """ Returns the first attribute that exists in the list of args that are passed in.
            If no attributes exist, then it returns the fallback value which defaults to None

            args:
                list of attributes to try on the object

            kwargs:
                fallback (optional) - a value to return if there are no attributes matching the args.
                                      defaults to None
        """
        fallback = kwargs.get('fallback', None)
        for arg in args:
            try:
                return self.__getattribute__(arg)
            except:
                pass
        return fallback

    def save(self, *args, **kwargs):
        if self.is_head:
            self.assert_constraints()
        self.set_real_type()
        self.refresh_cache()
        super(TrackableObject, self).save(*args, **kwargs)

    def set_real_type(self):
        if not self.real_type_id:
            self.real_type = self._get_real_type()

    # Permissions & things to be overridden
    def approve(self, request, message='', do_after_saved=True, **kwargs):
        if self.has_approve_perm(request.user):
            self.approve_related(request, message)
            self.status = self._get_parent().status
            self.approved_by = request.user
            self.approved_time = datetime.now()
            self._perform_action(request, self.APPROVED)
            if do_after_saved:
                self.do_after_saved(request, message, **kwargs.pop('do_after_saved_kwargs', {}))
            if self.is_live():
                self.do_if_live(request, message)
            if self.is_head:
                post_update.send(sender=self.cast().__class__, instance=self.cast(), request=request, message=message)
        return self

    def approve_related(self, request, message=''):
        pass

    def can_merge(self, obj):
        """ Returns True if this object can be merged with obj and False otherwise. Also
            returns a second argument - a string describing the error

            This does not take into account permissions. It only states whether or not this is a
            safe action that won't potentially place the merged object and children of that object
            in an unpredictable state.

            Args:
                obj - the object to be merged into this object
        """
        return self.is_head and obj.is_head

    def can_unmerge(self, merge_event=None):
        """ Returns True iff the objects are allowed to be merged, regardless of permissions """
        if not merge_event:
            merge_event = self._get_most_recent_merge_event() 
        if merge_event and self.is_head:
            return True
        else:
            return False

    def copy_perms_from_obj(self, trackable_object):
        """ Copies trackable_object's important fields to itself """
        self.status = trackable_object.status
        self.submitted_by = trackable_object.submitted_by
        self.submitted_time = trackable_object.submitted_time
        return self

    def do_if_live(self, request, message=''):
        """ Gets called immediately after the object is marked as live and saved
        
            This gets called only one time. Either:
                - When the object is created and is live immediately
                - When the object starts out in another state and then is approved 
        """
        pass

    def do_if_hidden(self, request, message=''):
        """ Gets called immediately after an object is created and marked as hidden """
        pass

    def do_if_removed(self, request, message=''):
        """Gets called immediately after the object is marked as removed/rejected and saved"""
        pass

    def do_after_saved(self, request, message='', refresh_foreign_key_cache_async=False):
        """ Gets called every time a live, hidden, or pending approval object is 
            created or editted as a result of user input 

            This method does not get called during ordinary .save() calls.

            Args:
                request
                message
                refresh_foreign_key_cache_async - True if you want to refresh the caches for the 
                                        foreign keys for this object asynchronously. False if you 
                                        want to refresh these foreign keys immediately
        """
        self.refresh_cache(foreign_key_async=refresh_foreign_key_cache_async)

    def edit(self, request, message='', force=False, do_after_saved=True, async=True, **kwargs):
        """ Edits the object and records a full history of the action 

            Args:
                request
                message - an optional message describing why the edit occurred
                force - If True, this edit occurs regardless of whether or not the
                        user would typically have permission to edit the object
                do_after_saved - If True, do_after_saved is called after the edit
                async - If True, the routine for updating child statuses is done asynchronously
                        in the background
        """
        if force or \
           (self.has_edit_perm(request.user) and (self._is_hidden_to_live() or (self._original_status == self.status))):

            child_status_kwargs = self.__class__.objects.get_status_kwargs([self._original_status]) 

            self._perform_action(request, self.EDITED)

            # If the object is changing from hidden to live, change all its children to live
            if self._is_changed_to_live():

                # Do not call do_after_saved if object is just being marked as live because
                # do_after_saved was already called when the object was previously created/edited
                # so doing it again when just changing to live would be redundant
                self._update_child_statuses(request=request, status=self.LIVE, child_status_kwargs=child_status_kwargs, action='edit', message=message, do_after_saved=do_after_saved, force=force, async=async)

            if self._is_hidden_to_live():
                self.do_if_live(request, message)

            if do_after_saved:
                self.do_after_saved(request, message, **kwargs.pop('do_after_saved_kwargs', {}))
            if self.is_head:
                post_update.send(sender=self.cast().__class__, instance=self.cast(), request=request, message=message)

            return self
        return None

    def get_conflicts(self):
        """ Returns a list of objects that conflict with this object.
        
            A conflict is defined by having two head objects in the a state where the two should
            not both be able to exist. For instance, if two foreign key fields are supposed to be
            unique together, and two objects have the same values for those foreign key fields,
            those two objects conflict with one another.

            This method is necessary because with our TrackableObject backend, these constraints
            are not enforced at the database layer since each head object potentially has an
            infinite number of previous objects representing earlier revisions of itself. These would
            break the database checks, so we need to create our own checks.

            The method is meant to be overridden by subclasses of TrackableObjects that require
            unique or unique_together constraints.
        """
        return []

    def has_add_perm(self, user):
        return self.has_perm(user, 'trackable_object.add_trackableobject') or \
               self.has_add_without_approval_perm(user) or \
               self.has_approve_perm(user) or \
               self.has_edit_perm(user) or \
               self.has_remove_perm(user)

    def has_add_without_approval_perm(self, user):
        return self.has_perm(user, 'trackable_object.can_add_without_approval') or \
               self.has_approve_perm(user) or \
               self.has_edit_perm(user) or \
               self.has_remove_perm(user)

    def has_approve_perm(self, user):
        return ((user != self.submitted_by) and self.has_perm(user, 'trackable_object.can_approve')) or \
               self.has_edit_perm(user) or \
               self.has_remove_perm(user)
    
    def has_edit_perm(self, user):
        return self.has_perm(user, 'trackable_object.change_trackableobject')

    def has_merge_perm(self, user, obj):
        """ Checks that the user has permissions to merge two objects

            It does not check whether or not the objects are allowed to be merged

            By default, only global admins can do this

            Args:
                user - the User asking for the merge to be performed
                obj - the object to be merged into this object
        """
        return user.has_perm('trackable_object.change_trackableobject')

    def has_perm(self, user, perm):
        """ Order of permissions checks:
            1) If the user was the creator, they can do anything
            2) If the user has a special permission for that perm
            3) If the user has a special restriction, they cannot do anything
            4) The user's default permission level (regular user/admin/etc)
        """
        try:
            if perm == 'can_view': 
                if (self.status == self.LIVE) or \
                   ((self.status == self.HIDDEN) and (self.submitted_by == user)):
                    return True
                elif self.status == self.REMOVED:
                    return False
            else: # For all other permission types (i.e. edit, remove, approve, reject)
                if user == self.submitted_by:
                    return True
        except:
            pass
        
        if self.has_special_restriction(user, perm):
            return self.has_special_perm(user, perm)
        else:
            return user.has_perm(perm) or self.has_special_perm(user, perm)

    def has_remove_perm(self, user):
        return self.has_perm(user, 'trackable_object.delete_trackableobject')

    def has_special_perm(self, user, perm):
        """Used to identify a user's overriding permissions on an object.
        If a user has special_perm, then he/she can do any action add/approve/reject/remove
        on an object regardless of his/her other permission status.

        Example: Tournament objects like pools, brackets, etc. will override this method
                 so that tournament admins who are not superusers can edit these things.
        """
        return False

    def has_special_restriction(self, user, perm):
        """ If true, a user does not have permission to carry out this action.
            has_special_perm overrides this method.
        """
        return False

    def has_unmerge_perm(self, user):
        """ Checks that the user has permissions to unmerge an object """
        return self.has_perm(user, 'trackable_object.change_trackableobject')

    def has_view_perm(self, user):
        """ Users can view LIVE objects or HIDDEN objects that they own """
        return self.has_perm(user, 'can_view')

    def make_live(self, request, message='', **kwargs):
        """ Marks the object as live and calls do_if_live """
        if self.has_edit_perm(request.user):
            self.status = self.LIVE
            return self.edit(request, message, **kwargs)
        return self

    def merge(self, obj, request=None, message='', force=False, do_after_saved=True, merge_event=None, **kwargs):
        """ Merges this object with a second object and returns the merged object

            Any fields that are already defined on this object will be kept as they are,
            but any fields that are empty on this object but have been defined on the
            second object will be updated with the value that is on the second object.

            Each of the two original objects will be marked as not the head and thus will 
            no longer be accessible to users.

            Important: When calling merge, be sure that you are sending in the real type of the objects.
                       If you send in anything but the real types, merge will fail intentionally

                       Also, only objects that are head can be merged

            Args:
                obj - the object to be merged into this one
                request
                message - an optional message describing why the merge occurred
                force - If True, this edit occurs regardless of whether or not the
                        user would typically have permission to edit the object
                do_after_saved - If True, do_after_saved is called after the edit
        """
        assert self.__class__ == obj.__class__
        assert self == self.cast()
        assert obj == obj.cast()
        assert self.is_head == True
        assert obj.is_head == True

        # prefetch the objects pointing to obj before we do any manipulation
        objs_pointing_to_obj = list(obj._get_objs_pointing_to_self())

        if (force or (request and request.user and self.has_merge_perm(request.user, obj))) and \
           self.can_merge(obj):

            # copy the primary object (self) to be merged
            old_self = self._copy_obj(self)

            # loop over every field on the object, setting the field to the second one iff
            # the second object has a value defined on the field and the first doesn't
            field_dict = self.__dict__
            for field in field_dict:
                if not field.startswith('_') and \
                   (not self.__getattribute__(field) and obj.__getattribute__(field)):
                    self.__setattr__(field, obj.__getattribute__(field))

            # create a copy of the secondary object, and make the head object point to 
            # the primary object (self)
            obj.is_head = False
            obj.points_to_id = self.id
            obj.edit(request=request, message=message, force=True, do_after_saved=True)

            # Create a new merge event
            if not merge_event:
                merge_event = MergeEvent()
                merge_event.save()

            # save this object along with relevant merge data
            self.merge_event = merge_event
            self.points_to_id = None
            self.is_head = True
            self.action_taken = self.MERGED
            self.action_time = datetime.now()
            if request and request.user:
                self.action_by = request.user 
            self.primary_merge_from_id = old_self.id
            self.secondary_merge_from_id = obj.id
            self = self.merge_fields(request, obj, old_self)
            self.save()

            # find all models referencing this object's class via foreign key and update them
            for pointing_obj in objs_pointing_to_obj:

                # Find any foreign keys pointing to the object
                for field in pointing_obj._meta.fields:
                    if isinstance(field, models.ForeignKey) and \
                       getattr(pointing_obj, field.name + '_id') == obj.id and \
                       issubclass(self.__class__, getattr(pointing_obj, field.name).__class__):

                        # Change the foreign key to point to the new object
                        pointing_obj.__setattr__(field.name + '_id', self.id)

                        # Notice that pointing_obj.merge_event is not set. We leave it as None
                        # because only objects that are the result of an object being merged into
                        # it have the merge_event field set to anything besides None

                conflicting_objects = pointing_obj.get_conflicts()
                
                if conflicting_objects:
                    # Re-fetch the pointing object to the point where the fields are not conflicting
                    pointing_obj = pointing_obj.__class__.objects.get(id=pointing_obj.id)

                    # If the newly saved object conflicts with others, get rid of this object
                    # by merging it into the first conflicting object
                    conflicting_obj = conflicting_objects[0]
                    conflicting_obj.merge(pointing_obj, force=True, merge_event=merge_event,
                                          request=request, message=message,
                                          do_after_saved=do_after_saved)

                    # Mark this conflicting object as affected by the merge so it will be unmerged
                    # automatically if this object is unmerged later
                    AffectedByMerge.objects.create(merge_event, conflicting_obj)

                else:
                    # Save any changes made
                    pointing_obj.edit(request=request, message=message, force=True,
                                      do_after_saved=False)

                    AffectedByMerge.objects.create(merge_event, pointing_obj)

            if do_after_saved:
                self.do_after_saved(request, message, **kwargs.pop('do_after_saved_kwargs', {}))
        return self

    def merge_fields(self, request, obj, old_self):
        """ A hook for defining any additional field manipulation when merging an object.

            This is called after the data on obj has already been added to self.
            This gets called right before this object (self) is merged.

            Args:
                request
                obj - The object being merged into self. all this data has already been copied onto
                      self for the fields on self that were None
                old_self - A copy of self before obj was merged into it, just for reference
        """
        return self

    def reject(self, request, message='', **kwargs):
        if self.has_approve_perm(request.user):
            self.reject_related(request, message)
            self.status = self.REJECTED
            self.removed_by = request.user
            self.removed_time = datetime.now()
            self._perform_action(request, self.REJECTED)
            self.do_if_removed(request, message)
            self.do_after_saved(request, message, **kwargs.pop('do_after_saved_kwargs', {}))
            if self.is_head:
                post_remove.send(sender=self.cast().__class__, instance=self.cast(), request=request, message=message)
        return self

    def submit(self, request, message='', live=False, hidden=False, force=False, check_for_duplicate=True, **kwargs):
        """ Saves an object and marks it as either hidden, live, or pending approval depending
            on the permissions the user has and the kwargs specified

            Args:
                request
                message
                live - If this is true, the object is marked as live immediately, as long as the user 
                       has permissions to add an object
                       Note that an object can still be marked as live even if the live variable is false, 
                       if the user has sufficient permissions
                       Defaults to False
                hidden - If this is true, the object is marked as hidden, as long as the user has permissions
                         to add an object
                         Defaults to False
                force - If this is True, submit will succeed regardless of the user's perms
                check_for_duplicate - If True, this method checks for a duplicate before it saves
                                      If False, it skips this check

            Note: This will not overwrite any data that already exists in the fields 'submitted_by', 
                  'submitted_time', or 'submission_message'
        """
        if force or self.has_add_perm(request.user): 
            if check_for_duplicate:
                identical_object = self._get_identical_object(request)
                if identical_object:
                    return identical_object

            if (hidden or self._parent_is_hidden()) and \
               (force or self.has_add_without_approval_perm(request.user)): 
                self.status = self.HIDDEN
                self._set_submit_params(request, message)
                self._perform_action(request, self.CREATED)
                self.do_if_hidden(request, message)
            elif live or self.has_add_without_approval_perm(request.user):
                self.status = self.LIVE
                self._set_submit_params(request, message)
                self._perform_action(request, self.CREATED)
                self.do_if_live(request, message)
            else:
                self.status = self.PENDING_APPROVAL
                self._set_submit_params(request, message)
                self._perform_action(request, self.CREATED)
                message = ("Thank you for contributing to Leaguevine. Your submission is currently "
                           "pending moderator approval. ")
                messages.success(request, message)
            self.do_after_saved(request, message, **kwargs.pop('do_after_saved_kwargs', {}))
            if self.is_head:
                post_create.send(sender=self.cast().__class__, instance=self.cast(), request=request, message=message)
        return self

    def submit_hidden(self, request, message='', force=False, **kwargs):
        return self.submit(request, message, hidden=True, force=force, **kwargs)

    def submit_live(self, request, message='', force=False, **kwargs):
        return self.submit(request, message, live=True, force=force, **kwargs)

    def refresh_cache(self, async=True, foreign_key_async=False, save=False):
        """ Refresh the cache for this object and related objects

            Args:
                async - DEPRECATED.
                foreign_key_async - DEPRECATED. 
                save - Whether or not you want to save after refreshing this object's cache
        """
        self.cache_time = datetime.now()
        if save:
            self.save()

    def reject_related(self, request, message=''):
        pass

    def remove(self, request, message='', do_after_saved=True, force=False, async=True, **kwargs):
        if force or self.has_remove_perm(request.user):
            child_status_kwargs = self.get_status_kwargs()
            self.remove_related(request, message)
            self.status = self.REMOVED
            self.removed_by = request.user
            self.removed_time = datetime.now()
            self.removal_message = message
            self._perform_action(request, self.REMOVED)
            self._update_child_statuses(request, child_status_kwargs=child_status_kwargs, status=self.REMOVED, action="remove", force=force, async=async) 
            self.do_if_removed(request, message)
            if do_after_saved:
                self.do_after_saved(request, message, **kwargs.pop('do_after_saved_kwargs', {}))
            if self.is_head:
                post_remove.send(sender=self.cast().__class__, instance=self.cast(), request=request, message=message)
        return self

    def remove_related(self, request, message=''):
        pass

    def unmerge(self, request=None, message='', merge_event=None, force=False, do_after_saved=True, **kwargs):
        """ Unmerges the merge specified by merge_event. If not specified, it unmerges the most 
            recent merge

            Important: When calling unmerge, be sure that you are sending in the real type of the objects.
                       If you send in anything but the real types, unmerge will fail intentionally

                       Also, only the head object can be unmerged

            Args:
                merge_event - The merge event that this unmerge is referring to
                request
                message - an optional message describing why the unmerge occurred
                force - If True, this unmerge occurs regardless of whether or not the
                        user would typically have permission to unmerge the object
                do_after_saved - If True, do_after_saved is called after the unmerge 
        """
        assert self == self.cast()
        assert self.is_head == True

        if not merge_event:
            merge_event = self._get_most_recent_merge_event()

        # If merge_event is not specified and this object has not been involved in a merge,
        # throw an error
        if not merge_event:
            raise HttpResponseForbidden('This object cannot be unmerged because it was never merged.')

        if self.merge_event == merge_event:
            obj_to_unmerge = self
            obj_to_unmerge_is_self = True
        else:
            # Find the object that is to be unmerged if it is not the head
            obj_to_unmerge = self._get_prev_from_merge_event(merge_event)
            obj_to_unmerge_is_self = False
            assert obj_to_unmerge != None

        if (force or (request and request.user and obj_to_unmerge.has_unmerge_perm(request.user))) and \
           self.can_unmerge(merge_event):

            # loop over every field on the object, resetting the field on the first object
            # to how it was if it had been set by the second object originally
            for field in obj_to_unmerge._meta.fields:
                old_obj_1_field = getattr(obj_to_unmerge.primary_merge_from, field.name)
                obj_1_field = getattr(self, field.name) # Get self's field because it may have changed
                                                        # since the merge happened and we want to 
                                                        # compare the most recent value
                obj_2_field = getattr(obj_to_unmerge.secondary_merge_from, field.name)
                if not field.name.startswith('_') and \
                   (old_obj_1_field == None or old_obj_1_field == '' or old_obj_1_field == 0) and \
                   obj_2_field and \
                   obj_2_field == obj_1_field:
                    setattr(obj_to_unmerge, field.name, old_obj_1_field)
                    obj_to_unmerge.save()

                    obj_to_unmerge._set_all_next_objs(field_name=field.name,
                                                      value=old_obj_1_field,
                                                      expected_value=obj_1_field)

            # Primary_merge_from and secondary_merge_from are left as is, so we know which two objects
            # the unmerge came from
            obj_to_unmerge.merge_event = None
            obj_to_unmerge.action_taken = self.UNMERGED
            # obj_to_unmerge is NOT marked as head because it is not necessarily the head object that is being 
            # unmerged. There are cases when an object that has later been edited and merged
            # needs to be unmerged from a previous state to reproduce the secondary object as it existed back then
            obj_to_unmerge.save()

            # Restore the secondary_merge_from to exactly how it was before the original merge happened
            obj_to_unmerge.secondary_merge_from.is_head = True
            obj_to_unmerge.secondary_merge_from.points_to_id = None
            obj_to_unmerge.secondary_merge_from.save()

            # Restore all other objects that were affected by this merge
            objs_affected_by_merge = [obj.content_object for obj in AffectedByMerge.objects.filter(merge_event=merge_event).order_by('id')]
            for affected_obj in objs_affected_by_merge:

                # Unmerge any objects that had been merged recursively
                if affected_obj.merge_event == merge_event:
                    affected_obj._get_head().unmerge(merge_event=merge_event, request=request, 
                                                     message=message, force=True,
                                                     do_after_saved=False)

                # Fix any objects that modified one of their foreign keys due to the merge
                else:
                    obj_to_unmerge_head_before_merge = obj_to_unmerge._get_head_before_merge()
                    affected_obj_head = affected_obj._get_head()
                    for previous_affected_obj in affected_obj._get_prev():
                        for field in affected_obj._meta.fields:
                            # If this affected object points to this unmerged object and it's
                            # previous object used to point to obj_2 instead of obj_1, then
                            # reset this pointer to obj_2
                            field_name = field.name + '_id'
                            if isinstance(field, models.ForeignKey) and \
                               hasattr(affected_obj, field_name) and \
                               issubclass(self.__class__, getattr(affected_obj, field.name).__class__) and \
                               getattr(affected_obj_head, field_name) == self.id and \
                               getattr(affected_obj, field_name) == obj_to_unmerge_head_before_merge.id and \
                               getattr(previous_affected_obj, field_name) == obj_to_unmerge.secondary_merge_from.id:
                                setattr(affected_obj, field.name, obj_to_unmerge.secondary_merge_from)
                                affected_obj.save()

                                # Also set all objects this object points to to the secondary object as well
                                affected_obj._set_all_next_objs(field_name=field.name + '_id', 
                                                                value=obj_to_unmerge.secondary_merge_from,
                                                                expected_value=self.id,
                                                                force=True)
                                # end if
                            # end for field
                        # End for previous obj
                    affected_obj._remove_affected_by_merge(merge_event=merge_event)
                    affected_obj.save()
                    # end else

        if do_after_saved:
            self.do_after_saved(request, message, **kwargs.pop('do_after_saved_kwargs', {}))

        if obj_to_unmerge_is_self:
            self = obj_to_unmerge
        return self

    # Private Methods
    def __init__(self, *args, **kwargs):
        """ Save the original id value when this object is created so we can check if it changed """
        super(TrackableObject, self).__init__(*args, **kwargs)
        self._original_id = self.id
        self._original_status = self.status

    def _copy_obj(self, obj):
        """ Takes an obj, creates a copy of it that then will point to obj, saves it, and returns it

            It fixes the pointer to the object specified by points_to. Whatever object had
            pointed to obj will point to this new object which will then point to obj.

            The object copy will not be the "head" object and thus will not be visible to users
        """
        # Evaluate this query now before we save another object pointing to obj
        previous_objects = list(obj._get_prev())

        old_obj = copy.copy(obj)

        # Both id and pk need to be set as noted here: http://bit.ly/y4vmB2
        old_obj.id = None
        old_obj.pk = None
        old_obj.points_to_id = obj.id
        old_obj.is_head = False
        old_obj.save()

        # Move any AffectedByMerge objects to the old_obj
        affected_by_merge_queryset = AffectedByMerge.objects.filter(content_type=obj.real_type,
                                                                    object_id=obj.id)
        for affected_by_merge in affected_by_merge_queryset:
            affected_by_merge.object_id = old_obj.id
            affected_by_merge.save()

        # Set the points_to field for each object that had pointed obj to the newly created object.
        # This is to maintain the linked list of objects
        for previous_object in previous_objects:
            previous_object.points_to_id = old_obj.id
            previous_object.save()

        return old_obj

    def _get_affected_by_merge(self, merge_event=None):
        if not merge_event:
            merge_event = self._get_most_recent_merge_event()
        if merge_event:
            affected_by_merge_queryset = AffectedByMerge.objects.filter(merge_event=merge_event, content_type=self.real_type, object_id=self.id)
            if affected_by_merge_queryset:
                return affected_by_merge_queryset[0]
        return None

    def _get_children(self, **kwargs):
        """ Returns a list of all objects that inherit their status from this object.

            kwargs:
                The user may specify kwargs that specify the statuses that you want to filter on when finding
                children. If no kwargs are specified, the current status of this parent object will be used.
                example: self._get_children(live=True, hidden=True)

            Pseudocode:
                For every model in the code base:
                    parent_model = get the model that it inherits status from
                    base_classes = get all of the base classes for this object, along with the object's class itself
                    if parent_model is in base_classes:
                        find any objects that point to this object
        """
        children = []
        self_class = self.__class__
        if kwargs:
            status_kwargs = kwargs
        else:
            status_kwargs = self.get_status_kwargs()
        for model in get_models():
            try:
                parent_model_strings = model._meta.inherits_status_from
                if not isinstance(parent_model_strings, list):
                    parent_model_strings = [parent_model_strings]
                for parent_model_string in parent_model_strings:
                    parent_model = model.__getattribute__(model, parent_model_string).field.related.parent_model
                    omitted_classes = [TrackableObject, models.Model, object]
                    base_classes = [item for item in list(inspect.getmro(self_class)) if item not in omitted_classes]
                    if parent_model in base_classes:
                        kwargs = {"{0}".format(parent_model_string): self}
                        children += list(model.objects.status(**status_kwargs).filter(**kwargs))
            except:
                pass
        return children

    def _get_foreign_keys(self):
        """ Returns a set of all the objects that this object has foreign keys to """
        foreign_key_set = set()

        for field in self._meta.fields:
            if isinstance(field, models.ForeignKey) and issubclass(field.rel.to, TrackableObject):
                obj = self.__getattribute__(field.name)
                if obj:
                    foreign_key_set.add(obj)

        return foreign_key_set

    def _get_recursive_foreign_keys(self):
        """ Returns a set of all the objects that this object has foreign keys to, and recursively includes
            any objects that those foreign keys are pointing to
        """
        foreign_keys = self._get_foreign_keys()
        recursive_foreign_keys_set = set([self]).union(foreign_keys)

        for foreign_key in foreign_keys:
            recursive_foreign_keys_set = recursive_foreign_keys_set.union(foreign_key._get_recursive_foreign_keys())

        return recursive_foreign_keys_set

    def _get_head(self):
        """ Returns this object's head object by following the 'points_to' attribute.

            If this object is already head, it returns itself.
        """
        if self.is_head:
            return self
        else:
            return self.points_to._get_head()

    def _get_head_before_merge(self):
        """ Returns this object's head object by following the 'points_to' attribute but stops
            if it encounters that this object was merged into another object.
        """
        points_to = self.points_to
        if self.is_head or points_to.secondary_merge_from == self:
            return self
        else:
            return points_to._get_head_before_merge()

    def _get_identical_object(self, request):
        """ Searches the database to see if there is another object of this same type that
            has all of the same parameters for submission.

            If an identical object exists, it returns this object. Otherwise it returns None
        """
        filters = {}
        for field in self._meta.fields:
            if not field.name.startswith('_') and \
               not field.name.endswith('_ptr'):
                # Add this key, value pair to a dict of lookup values
                filters[field.name] = getattr(self, field.name)

        # Add the user to the filter perms
        filters['submitted_by'] = request.user

        # Only look at items that were submitted in the last two minutes
        filters.pop('submitted_time')
        filters['submitted_time__gte'] = datetime.now() - timedelta(minutes=2)

        # If an identical object already exists in the database, return the first existing one
        identical_objects = self.__class__.objects.status(live=True).filter(**filters)

        if len(identical_objects):
            return identical_objects[0]
        return None

    def _get_models_pointing_to_self(self):
        """ Returns a list of models that have foreign keys that point to this object's model

            Inspired by:
                http://stackoverflow.com/questions/7539278/django-how-can-i-find-which-of-my-models-refer-to-a-model
        """
        all_models = models.get_models()
        referers = []
        for model in all_models:
            for field in model._meta.fields:

                # Grab any models that have foreign key fields that point to this object's model
                if isinstance(field, models.ForeignKey) and issubclass(self.__class__, field.rel.to):
                    referers.append(model)
                    break
        # return a uniquified list
        return list(set(referers))

    def _get_most_recent_merge_event(self):
        if self.merge_event:
            return self.merge_event
        else:
            all_prev = self._get_prev()
            for prev in all_prev:
                merge_event = prev._get_most_recent_merge_event()
                if merge_event:
                    return merge_event
        return None

    def _get_objs_pointing_to_self(self, exclude_models=None):
        """ Returns a list of all objects that have foreign keys that point to this object 
        
            Args:
                exclude_models - a comma separated list of model names to exclude from the search
        """
        if not exclude_models:
            exclude_models = []

        referring_models = self._get_models_pointing_to_self()
        referers = []
        for model in referring_models:

            # Check if this model should be skipped
            if model.__name__ in exclude_models:
                continue

            # Query on the field that points to the object
            for field in model._meta.fields:
                if isinstance(field, models.ForeignKey) and issubclass(self.__class__, field.rel.to):
                    kwargs = {}
                    kwargs[field.name] = self
                    referers += list(model.objects.filter(**kwargs))

        # return a uniquified list without any instances of the object itself in it
        return list(set(referers) - set([self]))

    def _get_parent(self):
        if hasattr(self._meta, 'inherits_status_from'):
            inherits_status_from = self._meta.inherits_status_from
            if isinstance(inherits_status_from, list):
                inherits_status_from = inherits_status_from[0]
            return self.__getattribute__(inherits_status_from)
        return None

    def _get_prev_from_merge_event(self, merge_event):
        """ Gets self's previous object that has a specific merge_event on it """
        objs = self.__class__.all_objects.filter(merge_event=merge_event)

        if objs:
            # Ensure there is only one of these
            assert len(objs) == 1
            return objs[0]
        return None

    def _get_prev(self):
        """ Gets a queryset of previous objects in the linked list of TrackableObjects linked by points_to """
        return self.__class__.all_objects.filter(points_to_id=self.id)

    def _get_real_type(self):
        return ContentType.objects.get_for_model(type(self))

    def _is_changed_to_live(self):
        """ Returns True iff the object has been changed from some other status to live since it was instantiated """
        return (self._original_status and self._original_status != self.LIVE and self.status == self.LIVE)

    def _is_hidden_to_live(self):
        """ Returns True iff the object has been changed from hidden to live since it was instantiated """
        return (self._original_status == self.HIDDEN and self.status == self.LIVE)

    def _parent_is_hidden(self):
        """ If the object has a parent and it is hidden, this returns True. Otherwise it returns False """
        parent = self._get_parent()
        if parent:
            return parent.is_hidden()
        return False

    def _perform_action(self, request, action):
        """ Called to perform a create/edit/remove action.

            This method creates a copy of the object and saves the appropriate data to the model.

            Merge/unmerge implement their own methods for this as they are slightly different.

            Args:
                request
                action - the ID of the action. e.g. self.CREATED, self.EDITED, self.REMOVED
        """
        # If the object exists (i.e. if it is not just being created now)
        if self.id:
            # Make a full copy of this object as it existed before the changes were made
            obj = self.__class__.all_objects.get(id=self.id)
            self._copy_obj(obj)

        self._reset_merge_fields(save=False)
        now = datetime.now()
        self.action_by = request.user
        self.action_time = now
        self.action_taken = action
        self.cache_time = now
        self.save()

    def _remove_affected_by_merge(self, merge_event):
        affected_by_merge = self._get_affected_by_merge(merge_event=merge_event)
        if affected_by_merge:
            affected_by_merge.delete()

    def _reset_merge_fields(self, save=True):
        """ Resets all fields dealing with merges to None. If save is True, it saves the object as well """
        self.merge_event = None
        self.primary_merge_from_id = None
        self.secondary_merge_from_id = None
        if save:
            self.save()

    def _set_all_next_objs(self, field_name, value, expected_value, force=False):
        """ Sets the field specified by field_name to value for all next objects.

            Important: It stops setting next objects if it finds an object 
                       that doesn't have expected_value set for that field

            Args:
                field_name - the name of the field that is being looked at
                value - the value to set field_name to on all next objects
                expected_value - only set 'field_name' to 'value' if the current value for 
                                 'field_name' is 'expected_value'
                force - if True, it ignores expected_value and executes the updates for 
                        all next objects no matter what

        """
        prev = self 
        next = self.points_to
        while True:
            valid_value = False
            # It is valid as long as the expected value is found
            if force or (next and getattr(next, field_name) == expected_value):
                valid_value = True
            if next is None or not valid_value:
                break
            setattr(next, field_name, value)
            next.save()
            prev = next
            next = next.points_to

    def _set_submit_params(self, request, message=''):
        """ If the default submit parameters are not yet set, it sets these based off of the request and submission message.
            This method does not save the object.
        """
        if not self.submitted_by:
            self.submitted_by = request.user
        if not self.submitted_time:
            self.submitted_time = datetime.now()
        if not self.submission_message:
            self.submission_message = message
        return self

    def _update_cache_time(self, async=True):
        self.cache_time = datetime.now()

    def _update_child_statuses(self, request, status, child_status_kwargs=None, action='edit', message='', do_after_saved=True, force=False, async=True):
        """ Updates the statuses of any child objects that were pointing to this object """
        from trackable_object.tasks import update_child_statuses
        kwargs = {'status': status,
                  'user_id': request.user.id,
                  'child_status_kwargs': child_status_kwargs,
                  'action': action,
                  'message': message,
                  'do_after_saved': do_after_saved,
                  'force': force}
        if async:
            update_child_statuses.delay(self, **kwargs)
        else:
            update_child_statuses(self, **kwargs)

    def _update_foreign_key_cache_time(self):
        """ DEPRECATED Updates the cache times for all the foreign keys for this object recursively """
        pass

    # Printing.
    def print_added(self):
        return ''

    def print_approved(self):
        return ''

    def print_moderation_extra_text(self):
        return ''

    def print_moderation_text(self):
        return esc(str(self))

    def print_removed(self):
        return ''

    # Extra queryset methods.
    class QuerySet(QuerySet):
        def filter_edit_perms(self, user, object=None):
            return self.filter_perms(user, 'trackable_object.change_trackableobject', object)

        def filter_perms(self, user, perm, object=None):
            """
            The object parameter is an object that a user may have special permissions on.
            If a user has special permissions on this object, then the original queryset will be returned.
            """
            if user.has_perm(perm):
                return self
            elif object and object.has_perm(user, perm):
                return self
            else:
                if perm == "can_view":
                    return self.filter(Q(status=self.model.LIVE) | \
                                       Q(status=self.model.HIDDEN, submitted_by=user.id))
                else:
                    if not user.is_anonymous():
                        return self.filter(submitted_by=user.id)
                    else:
                        return self.filter(pk=0) # Return an empty queryset

        def filter_remove_perms(self, user, object=None):
            return self.filter_perms(user, 'trackable_object.delete_trackableobject', object)

        def filter_view_perms(self, user, object=None):
            """ Returns only the objects a user is allowed to view. 

                Users can view ALL live objects, and any hidden objects they created.
            """
            return self.exclude(status=self.model.REMOVED).filter_perms(user, 'can_view', object)

        def get_from_id(self, id, select_related='', safe=False):
            """ Looks up an object by its id and returns that object

                Args:
                    id - the id of the object
                    select_related (optional) - a list of parameters to select related on
                    safe (optional) - if True, a failed lookup returns None
                                      if False, a failed lookup throws a 404 or 410 error
                                      defaults to False
            """
            try:
                if isinstance(select_related, list):
                    self = self.select_related(*select_related)
                elif select_related:
                    self = self.select_related(select_related)
                return self.get(id=int(id))
            except:
                if safe:
                    return None
                else:
                    try:
                        obj = self.model.objects.get(id=int(id)) # If an object exists but has been removed 
                    except:
                        raise Http404('This object cannot be found') # The object does not exist at all
                    if obj.is_removed():
                        raise Http404('This object has been removed.') # The object has been removed
                    raise Http404('This object cannot be found')

        def get_status_kwargs(self, list):
            """ Reads the list of statuses, and returns a dict of kwargs.
                This method has the exact opposite inputs and outputs as get_status_list
            """
            kwargs = {}
            if self.model.LIVE in list:
                kwargs['live'] = True
            if self.model.HIDDEN in list:
                kwargs['hidden'] = True
            if self.model.PENDING_APPROVAL in list:
                kwargs['pending'] = True
            if self.model.REJECTED in list:
                kwargs['rejected'] = True
            if self.model.REMOVED in list:
                kwargs['removed'] = True
            return kwargs

        def get_status_list(self, **kwargs):
            """ Reads the kwargs and returns a list of acceptable status IDs """
            live = kwargs.pop('live', False)
            hidden = kwargs.pop('hidden', False)
            pending = kwargs.pop('pending', False)
            rejected = kwargs.pop('rejected', False)
            removed = kwargs.pop('removed', False)
            all = kwargs.pop('all', False)
            status_list = []
            if live or all:
                status_list.append(self.model.LIVE)
            if hidden or all:
                status_list.append(self.model.HIDDEN)
            if pending or all:
                status_list.append(self.model.PENDING_APPROVAL)
            if rejected or all:
                status_list.append(self.model.REJECTED)
            if removed or all:
                status_list.append(self.model.REMOVED)
            return status_list

        def has_approve_perm(self, user, object=None):
            return self.has_perm(user, 'trackable_object.can_approve', object)

        def has_edit_perm(self, user, object=None):
            return self.has_perm(user, 'trackable_object.change_trackableobject', object)

        def has_perm(self, user, perm, object=None):
            if user.has_perm(perm):
                return True
            elif object and object.has_perm(user, perm):
                return True
            elif user.is_authenticated() and 0 < self.filter_perms(user, perm).count():
                return True
            else:
                return False

        def has_remove_perm(self, user, object=None):
            """Returns True or False in accordance to whether or not 'user' has permission to remove
                any of the objects in the queryset. 

                Optional parameter 'object': If 'objects' is passed, and the user has permissions on that
                object, then the function will return True. Otherwise, it will return what it would have
                returned if 'object' were left blank.
            """
            return self.has_perm(user, 'trackable_object.delete_trackableobject', object)

        def status(self, **kwargs):
            """ Filters the queryset based on the status of the object

                kwargs:
                    live -  defaults to False
                            if True, includes live objects in the set
                            if False, it does not include live objects
                    hidden - defaults to False
                    pending - defaults to False
                    rejected - defaults to False
                    removed - defaults to False

                If no kwargs are given, the original queryset is returned
            """
            status_list = self.get_status_list(**kwargs)
            if not status_list:
                return self
            else:
                return self.filter(status__in=status_list)

        # shortcuts
        def first_or_none(self):
            """ Returns the first object in the queryset if it exists, otherwise None 
            
                Taken from here:
                    http://stackoverflow.com/questions/5123839/fastest-way-to-get-the-first-object-from-a-queryset-in-django
            """
            first = list(self[:1])
            if first:
                return first[0]
            return None
