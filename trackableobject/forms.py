import datetime

from django import forms
from django.forms.fields import SplitDateTimeField, MultiValueField
from django.forms.widgets import SplitDateTimeWidget
from django.utils.translation import ugettext_lazy as _


class RemoveForm(forms.Form):
    def __init__(self, *args, **kwargs):
        self.object = kwargs.pop('object', None)
        self.request = kwargs.pop('request', None)
        super(RemoveForm, self).__init__(*args, **kwargs)

    def save(self, *args, **kwargs):
        message = self.cleaned_data.get('message', '')
        return self.object.remove(self.request, message)

def add_edit_message(form):
    class MessageForm(form):
        message = forms.CharField(max_length=100, required=False, label="Reason for Edit (optional)")
    return MessageForm

def add_remove_message(form):
    class RemoveForm(form):
        message = forms.CharField(max_length=100, required=False, label="Reason for removal (optional)")
    return RemoveForm

def add_redirect(form, redirect_url, redirect_on_cancel_url=None):
    if not redirect_on_cancel_url:
        redirect_on_cancel_url = ''
    class RedirectForm(form):
        redirect = forms.CharField(max_length=200, initial=redirect_url, \
                                   widget=forms.HiddenInput(), required=False) 
        redirect_on_cancel = forms.CharField(max_length=200, initial=redirect_on_cancel_url, \
                                             widget=forms.HiddenInput(), required=False) 
    return RedirectForm

def add_formset_redirect(formset, redirect_url):
    class RedirectFormSet(formset):
        def add_fields(self, form, index):
            super(RedirectFormSet, self).add_fields(form, index)
            form.fields['redirect'] = forms.CharField(max_length=200, initial=redirect_url, \
                                                      widget=forms.HiddenInput(), required=False)
    return RedirectFormSet


class CustomDateTimeField(SplitDateTimeField):
    def __init__(self, *args, **kwargs):
        """ An initial date is required """
        initial = kwargs.pop('initial', None) # The initial date
        required = kwargs.pop('required', True)

        default_kwargs = {
            'input_date_formats': ['%Y-%m-%d'],
            'input_time_formats': ['%H:%M'], 
            'widget': SplitDateTimeWidget(date_format='%Y-%m-%d',
                                          time_format='%H:%M'),
        }
        if initial:
            default_kwargs.update({'initial': lambda: initial})
        if kwargs:
            kwargs.update(default_kwargs)
        else:
            kwargs = default_kwargs
        super(CustomDateTimeField, self).__init__(*args, **kwargs)

        self.fields[0].required = required
        self.fields[1].required = required

        self.fields[0].help_text = "yyyy-mm-dd"
        self.fields[1].help_text = "hh:mm"

        # Set the widget class attributes so the javascript knows about it
        self.widget.widgets[0].attrs = {'class':'datepicker'}
        self.widget.widgets[1].attrs = {'class':'timepicker'}

    def compress(self, data_list):
        # Call the super method to check for any errors, but don't return this result because it
        # manipulates the timezone which we don't want
        super(CustomDateTimeField, self).compress(data_list)
        return datetime.datetime.combine(data_list[0], data_list[1])
