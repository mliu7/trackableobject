from django import forms
from django.contrib import admin
from django.contrib.auth.models import User


class BaseAdminForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super(BaseAdminForm, self).__init__(*args, **kwargs)
        self.fields['submitted_by'].choices = [('', 10*'-')] + list(User.objects.all().values_list('id', 'username').order_by('username'))
        self.fields['removed_by'].choices = [('', 10*'-')] + list(User.objects.all().values_list('id', 'username').order_by('username'))
        self.fields['action_by'].choices = [('', 10*'-')] + list(User.objects.all().values_list('id', 'username').order_by('username'))


class TrackableObjectAdmin(admin.ModelAdmin):
    def queryset(self, request):
        """Returns the set of all objects instead of just live objects"""
        qs = self.model.all_objects.get_query_set()
        ordering = self.ordering or ()
        if ordering:
            qs = qs.order_by(*ordering)
        return qs

    form = BaseAdminForm
