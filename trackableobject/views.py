from django.contrib.auth.decorators import permission_required
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponse, HttpResponseRedirect
from django.utils import simplejson
from django.forms.models import modelformset_factory
from django.shortcuts import render_to_response, render
from django.template import RequestContext

from annoying.decorators import render_to
from endless_pagination.decorators import page_template

from game.models import GameScore
from trackable_object.forms import RemoveForm, add_edit_message, add_redirect, add_remove_message, \
        add_formset_redirect
from trackable_object.utils import parse_id


@permission_required('trackable_object.add_trackableobject')
@page_template('moderate_objects.html')
def moderate_all(request, template="moderate_all.html", extra_context=None):
    objects = GameScore.pending_approval.filter(auto_approve=False).order_by('-submitted_time')
    context = {'objects': objects}
    if extra_context is not None:
        context.update(extra_context)
    return render_to_response(template, context, context_instance=RequestContext(request))

def approve_object(request, app_object_id):
    """AJAX method.
    
    Checks if a user has correct permissions and then marks object as live"""
    object = parse_id(app_object_id)
    try:
        object.approve(request)
        message = "Approved"
    except:
        message = "Sorry. There was an unexpected problem. Please try again later."
    response_dict = {'message': message}
    return HttpResponse(simplejson.dumps(response_dict), mimetype='application/json')

def reject_object(request, app_object_id):
    """AJAX method.
    
    Checks if a user has correct permissions and then marks object as rejected"""
    object = parse_id(app_object_id)
    try:
        object.reject(request)
        message = "Rejected"
    except:
        message = "Sorry. There was an unexpected problem. Please try again later."
    response_dict = {'message': message}
    return HttpResponse(simplejson.dumps(response_dict), mimetype='application/json')

def create_object(request, form_class, redirect_on_cancel, redirect_on_continue=None,
                  redirect_on_success=None, form_params=None, message=False, no_redirect=False):
    """ Creates either a form or a request object.

        If the request is a POST:
            submits the object and lets the submit handler determine it's status
            If successful (and the object was  or user clicked 'cancel':
                returns a redirect to redirect
            If there were form errors
                returns the form with errors
        If the request is not a POST:
            Returns a form to be displayed

        Args
            form_class - The Form that is to be used to create a new object.
            redirect_on_cancel - The url to redirect to if the user clicks cancel
            redirect_on_continue (optional) - The url to redirect to if the user clicks "save and add another"
            redirect_on_success (optional) - defaults to the new object's get_absolute_url().
                    A second way to redirect on success is by specifying an attribute on
                    your bound form named 'redirect_on_success'
            form_params (optional) - A dictionary of kwargs to initialize the form class with
            message (optional) - defaults to False
                                 If True, a message field is added to the form to prompt an explanation

        Note:
            This method can be used for any general form submissions and is not restricted to only object
            creations. The form_class specified must implement a save() method that submits any objects
            and checks any necessary parameters before actually saving.
    """
    if not form_params:
        form_params = {}

    response = None
    
    # Stores this redirect in a hidden field that will be accessed upon a successful save
    form_class = add_redirect(form_class, redirect_on_success, redirect_on_cancel)

    if request.method == 'POST':
        form = form_class(request.POST, request.FILES, **form_params)
        redirect_on_cancel = form.data.get('redirect_on_cancel', redirect_on_cancel)
        if 'cancel' in request.POST:
            response = HttpResponseRedirect(redirect_on_cancel)
        elif form.is_valid():
            object = form.save()
            if (no_redirect or 'no_redirect' in request.POST) and redirect_on_continue:
                response = HttpResponseRedirect(redirect_on_continue)
            else:
                if object.is_live() or object.is_hidden():
                    redirect_on_success = form.cleaned_data.get('redirect', redirect_on_success)
                    if not redirect_on_success:
                        if hasattr(form, 'redirect_on_success'):
                            # Check to see if the form saved an attribute called redirect_on_success
                            redirect_on_success = form.redirect_on_success
                        else:
                            try:
                                redirect_on_success = object.get_absolute_url()
                            except:
                                redirect_on_success = redirect_on_cancel
                    response = HttpResponseRedirect(redirect_on_success)
                else:
                    response = HttpResponseRedirect(redirect_on_cancel)
    else:
        form = form_class(**form_params)

    return {'form': form,
            'response': response}

def edit_object(request, object, form_class, redirect=None, form_params=None, message=False, can_edit=False):
    """Creates either a form or a request object.

        If the request is a POST:
            Checks that the user has permissions to edit
            Saves the object along with updating the edit log
            If successful or user doesn't have permissions or user clicked 'cancel':
                Returns a redirect
            If there were form errors:
                Returns the form with errors
        If it is not a POST
            Returns a form to be displayed

        Args
            object - The object to be editted
            form_class - The ModelForm that will be used to edit the object
            redirect (optional) - Defaults to object.get_absolute_url()
                                  If included, it will redirect to this url on success or cancel.
            message (optional)
                If Message is true, then a "Message field is added to the form prompting the user to explain the edit"
                If Message is false, no message field is added.
            can_edit (optional) - Defaults to False
                                  If True, this indicates the user has the permissions to edit this object
    """
    if not (can_edit or object.has_edit_perm(request.user)):
        return {'form': None,
                'response': redirect_to_login(request.path)}

    if not redirect:
        redirect = object.get_absolute_url()

    if not form_params:
        form_params = {}

    form_class = add_redirect(form_class, redirect)

    if message:
        form_class = add_edit_message(form_class)

    if request.method == 'POST':
        form = form_class(request.POST, request.FILES, instance=object, **form_params)
        redirect = form.data.get('redirect', redirect)
        if 'cancel' in request.POST:
            return {'form': None,
                    'response': HttpResponseRedirect(redirect)}
        elif form.is_valid():
            message = form.cleaned_data.get('message', '')
            object = form.instance.edit(request, message) 
            if object:
                form.save()
            return {'form': None,
                    'response': HttpResponseRedirect(redirect)}
    else:
        form = form_class(instance=object, **form_params)
    return {'form': form,
            'response': None}

def edit_objects(request, queryset, formset_class, redirect, form_params=None, message=False, can_edit=False):
    """ Creates either a model formset or a request object.

        If the request is a POST:
            Checks that the user has permissions to edit
            Checks that the formset is valid
            Saves each form along with updating the edit log
            If successful or user doesn't have permissions or user clicked 'cancel':
                returns a redirect
            If there were form errors:
                Returns the formset with errors
        If it is not a post:
            Returns the formset to be displayed

        Args:
            request
            queryset - The set of objects to be editted
            formset_class - The formset class returned by modelformset_factory
            redirect - The URL of where to go after you are done with the form
            form_params (optional) - A dict of kwargs that will be passed into every form in the formset
            message (optional) - If True, a message field is added to the formset at the end
            can_edit (optional) - If True, this indicates the user has permissions to edit these objects
    """
    if not (can_edit or queryset.filter_edit_perms(request.user)):
        return {'formset': None,
                'response': redirect_to_login(request.path)}

    if not form_params:
        form_params = {}

    formset_class = add_formset_redirect(formset_class, redirect)

    #TODO: Figure out a way to add a message field on a formset

    if request.method == 'POST':
        formset = formset_class(request.POST, request.FILES, queryset=queryset, **form_params)
        redirect = formset[0].data.get('redirect', redirect)
        if 'cancel' in request.POST:
            return {'formset': None,
                    'response': HttpResponseRedirect(redirect)}
        elif formset.is_valid():
            for form in formset:
                if form.is_valid() and form.changed_data:
                    message = form.cleaned_data.get('message', '')
                    object = form.instance.edit(request, message)
                    if object:
                        form.save()
            return {'formset': None,
                    'response': HttpResponseRedirect(redirect)}
    else:
        formset = formset_class(queryset=queryset, **form_params)
    return {'formset': formset,
            'response': None}

def remove_object(request, object, redirect, redirect_on_cancel=None, form_class=None):
    """Creates either a form or a request object.

    If the request is a POST:
        Checks that the user has permission to remove the object
        Removes the object and saves the meta information
        If successful or user doesn't have permissions:
            Returns the appropriate redirect
    If it is not a POST:
        Returns a form to be displayed

        Args
            object - the object to be removed
            redirect - the redirect to be used after it is removed
            redirect_on_cancel (optional) - the redirect to be used if the remove is cancelled
                                            Defaults to object's absolute url
    """
    if not form_class:
        form_class = RemoveForm

    if not object.has_remove_perm(request.user):
        return {'form': None,
                'response': redirect_to_login(request.path)}

    if not redirect_on_cancel:
        redirect_on_cancel = object.get_absolute_url()

    RemoveFormWithRedirect = add_redirect(form_class, redirect_url=redirect, 
                                          redirect_on_cancel_url = redirect_on_cancel)

    RemoveFormWithRedirect = add_remove_message(RemoveFormWithRedirect)

    if request.method == 'POST':
        form = RemoveFormWithRedirect(request.POST, request.FILES, request=request, object=object)
        if 'cancel' in request.POST:
            return {'form': None,
                    'response': HttpResponseRedirect(form.data.get('redirect_on_cancel', redirect_on_cancel))}
        elif form.is_valid():
            message = form.cleaned_data['message']
            object.remove(request, message) 
            return {'form': None,
                    'response': HttpResponseRedirect(form.data.get('redirect', redirect))}
    else:
        form = RemoveFormWithRedirect()

    return {'form': form,
            'response': None}

def remove_objects(request, model, queryset, redirect):
    """Returns either a formset or a redirect for removing objects from a queryset

    Sample usage:
    dict = remove_objects(request, TournamentTeam, tournament_teams, \
                          reverse('tournament_teams', kwargs=tournament.get_url_kwargs()))
    if dict['response']:
        return dict['response']
    formset = dict['formset'] 

    """
    FormSet = modelformset_factory(model, fields=("removed_by",), extra=0, can_delete=True)

    if request.method == 'POST':
        formset = FormSet(request.POST, request.FILES)
        if 'cancel' in request.POST:
            return {'form': None,
                    'response': HttpResponseRedirect(redirect)}
        elif formset.is_valid():
            for form in formset.forms:
                if form.is_valid():
                    if form.cleaned_data['DELETE']:
                        object = form.instance
                        object.remove(request)
        return {'form': None,
                'response': HttpResponseRedirect(redirect)}
    else:
        formset = FormSet(queryset=queryset)

    return {'formset': formset,
            'response': None}

def render_form_view(fn, request, template, context, *args, **kwargs):
    """ A wrapper around any trackable_object form view that renders a single form or formset.

        Args
            fn - the function that will be called to do the rendering
            template - the name of the template to be rendered
            context - any context to be rendered to the page
            *args - the args that the form view takes (i.e. object, objects, etc)
            **kwargs - the kwargs that the form view takes 
    """
    dict = fn(request, *args, **kwargs)
    if dict['response']:
        return dict['response']
    context.update({'form': dict.get('form', None),
                    'formset': dict.get('formset', None)})
    return render(request, template, context)

def render_create_object(*args, **kwargs):
    return render_form_view(create_object, *args, **kwargs)

def render_edit_object(*args, **kwargs):
    return render_form_view(edit_object, *args, **kwargs)

def render_edit_objects(*args, **kwargs):
    return render_form_view(edit_objects, *args, **kwargs)

def render_remove_object(*args, **kwargs):
    return render_form_view(remove_object, *args, **kwargs)

def render_remove_objects(*args, **kwargs):
    return render_form_view(remove_objects, *args, **kwargs)

def ajax_form_response(request, form_class, form_params=None, extra_context=None, template=None):
    """ Processes an ajax form submission and returns an Http Response with json data 
    
        Args:
            form_class - the class of the form to be processed
            form_params (optional) - any parameters that need to be passed into the form
            extra_context (optional) - any context that should be returned with the Http Response
            template (optional) - If None, only post requests are allowed. 
                                  If not None, get requests result in the form being rendered to the template
                                  Defaults to None
    """
    if not form_params:
        form_params = {}
    if not extra_context:
        extra_context = {}
    error_message = ''

    if request.method == 'POST' and request.is_ajax():
        form = form_class(data=request.POST, **form_params)
        if form.is_valid():
            object = form.save()
        else:
            for error in form.errors.values():
                error_message += ' ' + error[0]
        context = {'error_message': error_message,
                   'valid': not error_message}
        if extra_context:
            context.update(extra_context)
        try:
            # Try to add the object's info to the context
            context.update({'object': object.get_info()})
            context.update({'render_object_url': object.get_absolute_render_url()})
        except:
            pass
        return HttpResponse(simplejson.dumps(context), mimetype='application/json')
    else:
        form = form_class(**form_params)
        if template:
            context = {'form': form}
            if extra_context:
                context.update(extra_context)
            return render(request, template, context)
        else:
            error_message = "The request must be of type POST and be an ajax request. You may be getting this error because javascript is turned off in your browser. Please enable javascript and try again."
            return HttpResponse(simplejson.dumps({'error_message': error_message, 'valid': False}),
                                                  mimetype='application/json')
